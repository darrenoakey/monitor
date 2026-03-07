"""Auto process collector. Reports status of all registered services."""

import os
import re
import subprocess


def _find_auto():
    """Find the auto binary, checking ~/bin first."""
    home_bin = os.path.expanduser("~/bin/auto")
    if os.path.isfile(home_bin) and os.access(home_bin, os.X_OK):
        return home_bin
    return "auto"


def collect():
    """Return list of (path, name, status, value, weight, details) tuples."""
    try:
        result = subprocess.run(
            [_find_auto(), "-q", "ps"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []

    results = []
    for line in result.stdout.splitlines():
        # Parse: NAME  PID  PORT
        # Skip header line
        line = line.strip()
        if not line or line.startswith("NAME"):
            continue

        parts = re.split(r'\s{2,}', line)
        if len(parts) < 2:
            continue

        name = parts[0]
        pid_str = parts[1] if len(parts) > 1 else ""
        port_str = parts[2] if len(parts) > 2 else "-"

        # Skip monitoring ourselves
        if name in ("monitor", "monitor-agent"):
            continue

        if pid_str == "dead":
            status = "bad"
            value = "dead"
        elif pid_str == "stopped":
            status = "warn"
            value = "stopped"
        else:
            status = "good"
            value = f"pid {pid_str}"

        port_info = f"port {port_str}" if port_str != "-" else "no port"
        details = f"{name}: {value}, {port_info}"

        results.append((
            f"services/{name}",
            name,
            status,
            value,
            1,
            details,
        ))
    return results
