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


def run_collector(mon, machine, collector_name, collect_fn, interval):
    """Run a collector in a loop on its own interval."""
    while True:
        try:
            items = collect_fn()
            for path, name, status, value, weight, details in items:
                full_path = f"{machine}/{path}"
                mon.publish(full_path, name, status, value, weight=weight, details=details)
            if items:
                print(f"  [{collector_name}] published {len(items)} metrics")
        except Exception as e:
            print(f"  [{collector_name}] error: {e}")
        time.sleep(interval)


def main():
    machine = machine_name()
    token = pubsub_token()
    host = pubsub_host()
    port = pubsub_port()

    if not token:
        print("Error: no pubsub token. Set MONITOR_PUBSUB_TOKEN or ensure ~/src/pubsub/data/token exists.")
        sys.exit(1)

    mon = Monitor(host=host, port=port, token=token)
    print(f"Monitor agent starting: machine={machine}, pubsub={host}:{port}")

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
        threads.append(t)
        print(f"  Started {name} collector (every {interval}s)")

    print(f"All collectors running. Publishing to /monitor/{machine}/...")

    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
