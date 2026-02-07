"""Disk usage collector. Auto-discovers real storage volumes."""

import os
import shutil
import subprocess


# Mount paths to ignore (virtual, system, dev simulators)
IGNORE_PREFIXES = (
    "/System/Volumes/Preboot",
    "/System/Volumes/VM",
    "/System/Volumes/Update",
    "/System/Volumes/xarts",
    "/System/Volumes/iSCPreboot",
    "/System/Volumes/Hardware",
    "/Library/Developer",
    "/private",
)

# Filesystem types to ignore
IGNORE_FS = {"devfs", "autofs", "nullfs", "fdesc"}

# Minimum size to report (1 GB)
MIN_SIZE_BYTES = 1024 ** 3


def _discover_volumes():
    """Discover real storage volumes from mount output."""
    volumes = []
    try:
        result = subprocess.run(
            ["mount"], capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return volumes

    seen_devices = set()
    for line in result.stdout.splitlines():
        # Format: /dev/disk1s2 on /path (type, options)
        parts = line.split(" on ", 1)
        if len(parts) != 2:
            continue
        device = parts[0].strip()
        rest = parts[1]
        paren = rest.rfind(" (")
        if paren < 0:
            continue
        mount = rest[:paren].strip()
        type_info = rest[paren + 2:].rstrip(")")

        # Extract filesystem type
        fs_type = type_info.split(",")[0].strip()
        if fs_type in IGNORE_FS:
            continue

        if any(mount.startswith(p) for p in IGNORE_PREFIXES):
            continue

        # Skip duplicate devices (e.g. snapshot mounts)
        if mount == "/System/Volumes/Data":
            # This is the main data volume - always include as "system"
            volumes.append(("system", mount, "System"))
            seen_devices.add(device)
            continue
        if mount == "/":
            # Root snapshot - skip, we use /System/Volumes/Data instead
            continue

        # /Volumes/* are external/extra drives
        if mount.startswith("/Volumes/"):
            name = os.path.basename(mount)
            key = name.lower().replace(" ", "-").replace("'", "").replace("\u2019", "")
            # Skip TimeMachine volumes
            if ".timemachine" in mount.lower() or "timemachine" in name.lower():
                continue
            if device not in seen_devices:
                volumes.append((key, mount, name))
                seen_devices.add(device)

    return volumes


def collect():
    """Return list of (path, name, status, value, weight, details) tuples."""
    results = []
    for key, mount, name in _discover_volumes():
        try:
            usage = shutil.disk_usage(mount)
        except (FileNotFoundError, PermissionError, OSError):
            continue

        if usage.total < MIN_SIZE_BYTES:
            continue

        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        pct = max(0, (usage.used / usage.total) * 100)

        if pct > 95:
            status = "bad"
        elif pct > 80:
            status = "warn"
        else:
            status = "good"

        results.append((
            f"disk/{key}",
            name,
            status,
            f"{pct:.0f}%",
            max(1, int(total_gb / 100)),
            f"{used_gb:.0f}GB / {total_gb:.0f}GB",
        ))
    return results
