#!/usr/bin/env python3
"""Monitoring agent. Runs collectors on independent intervals and publishes to pubsub."""

import os
import sys
import time
import threading

# Unbuffered output for auto log visibility
sys.stdout.reconfigure(line_buffering=True)

# Add lib/ to path for monitor.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from monitor import Monitor
from config import machine_name, pubsub_host, pubsub_port, pubsub_token
from collectors import disks, processes, system, websites

# Category weights: services most important (3), others equal (1).
CATEGORY_WEIGHTS = {"services": 3, "disk": 1, "system": 1, "websites": 1}

# Re-publish category weights this often (seconds). Also serves as the
# recovery interval after pubsub comes back from an outage.
WEIGHT_INTERVAL = 300

# If a collector hasn't completed a cycle in this many multiples of its
# interval, consider it stuck and exit so auto restarts us.
STUCK_MULTIPLIER = 5

# Shared last-activity timestamps per collector, updated after each cycle.
_last_activity = {}  # name -> timestamp
_activity_lock = threading.Lock()


def run_collector(mon, machine, collector_name, collect_fn, interval):
    """Run a collector in a loop on its own interval. Never exits."""
    with _activity_lock:
        _last_activity[collector_name] = time.time()
    while True:
        try:
            items = collect_fn()
            published = 0
            for path, name, status, value, weight, details in items:
                full_path = f"{machine}/{path}"
                try:
                    mon.publish(full_path, name, status, value, weight=weight, details=details)
                    published += 1
                except Exception:
                    pass  # publish errors are logged inside Monitor
            if items:
                if published == len(items):
                    print(f"  [{collector_name}] published {len(items)} metrics")
                else:
                    print(f"  [{collector_name}] published {published}/{len(items)} metrics")
            else:
                print(f"  [{collector_name}] no items collected")
        except Exception as e:
            print(f"  [{collector_name}] error: {e}")
        with _activity_lock:
            _last_activity[collector_name] = time.time()
        time.sleep(interval)


def publish_weights(mon, machine):
    """Publish category weights. Returns True on success."""
    try:
        for cat, w in CATEGORY_WEIGHTS.items():
            mon.publish(f"{machine}/{cat}", cat, "good", "", weight=w)
        return True
    except Exception:
        return False


def main():
    machine = machine_name()
    host = pubsub_host()
    port = pubsub_port()

    # Retry token acquisition - volume may not be mounted yet at boot.
    token = ""
    for attempt in range(30):
        token = pubsub_token()
        if token:
            break
        wait = min(10, 2 * (attempt + 1))
        print(f"No pubsub token (attempt {attempt + 1}/30), retrying in {wait}s...")
        time.sleep(wait)
    if not token:
        print("Error: no pubsub token after 30 attempts. Exiting.")
        sys.exit(1)

    mon = Monitor(host=host, port=port, token=token)
    print(f"Monitor agent starting: machine={machine}, pubsub={host}:{port}")

    # Try initial category weight publish, but don't block startup.
    if publish_weights(mon, machine):
        print(f"  Published category weights: {CATEGORY_WEIGHTS}")
    else:
        print(f"  Could not publish category weights (pubsub down?), will retry")

    # Each collector runs in its own thread with its own interval
    collectors = [
        ("disks", disks.collect, 60),
        ("system", system.collect, 60),
        ("processes", processes.collect, 30),
        ("websites", websites.collect, 60),
    ]

    threads = []
    for name, fn, interval in collectors:
        t = threading.Thread(
            target=run_collector,
            args=(mon, machine, name, fn, interval),
            daemon=True,
        )
        t.start()
        threads.append((name, t))
        print(f"  Started {name} collector (every {interval}s)")

    print(f"All collectors running. Publishing to /monitor/{machine}/...")

    # Main loop: periodically re-publish category weights and monitor threads.
    last_weight_publish = time.time()
    while True:
        try:
            time.sleep(30)

            # Re-publish category weights periodically.
            if time.time() - last_weight_publish > WEIGHT_INTERVAL:
                if publish_weights(mon, machine):
                    last_weight_publish = time.time()

            now = time.time()
            for i, (name, t) in enumerate(threads):
                interval = collectors[i][2]

                # Dead thread: restart it.
                if not t.is_alive():
                    print(f"  WARNING: {name} collector thread died, restarting")
                    coll = collectors[i]
                    new_t = threading.Thread(
                        target=run_collector,
                        args=(mon, machine, coll[0], coll[1], coll[2]),
                        daemon=True,
                    )
                    new_t.start()
                    threads[i] = (name, new_t)
                    continue

                # Stuck thread: can't kill it, so exit and let auto restart us.
                with _activity_lock:
                    last = _last_activity.get(name, now)
                stale = now - last
                if stale > interval * STUCK_MULTIPLIER:
                    print(f"  FATAL: {name} collector stuck for {stale:.0f}s "
                          f"(limit {interval * STUCK_MULTIPLIER}s). Exiting.")
                    sys.exit(1)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"  Main loop error (continuing): {e}")


if __name__ == "__main__":
    main()
