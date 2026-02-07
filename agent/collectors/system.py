"""System metrics collector. CPU load, memory usage, uptime."""

import os
import subprocess


def _memory_pressure():
    """Get memory usage on macOS using vm_stat."""
    try:
        result = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.splitlines()
        stats = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            val = val.strip().rstrip(".")
            try:
                stats[key.strip()] = int(val)
            except ValueError:
                continue

        page_size = 16384  # Apple Silicon
        free = stats.get("Pages free", 0)
        active = stats.get("Pages active", 0)
        inactive = stats.get("Pages inactive", 0)
        speculative = stats.get("Pages speculative", 0)
        wired = stats.get("Pages wired down", 0)
        compressed = stats.get("Pages occupied by compressor", 0)

        total_pages = free + active + inactive + speculative + wired + compressed
        if total_pages == 0:
            return None, None

        used_pages = active + wired + compressed
        total_gb = (total_pages * page_size) / (1024 ** 3)
        used_gb = (used_pages * page_size) / (1024 ** 3)
        pct = (used_pages / total_pages) * 100
        return pct, f"{used_gb:.1f}GB / {total_gb:.0f}GB"
    except Exception:
        return None, None


def collect():
    """Return list of (path, name, status, value, weight, details) tuples."""
    results = []

    # CPU load average (1 min)
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        load_pct = (load1 / cpu_count) * 100

        if load_pct > 90:
            status = "bad"
        elif load_pct > 70:
            status = "warn"
        else:
            status = "good"

        results.append((
            "system/load",
            "CPU Load",
            status,
            f"{load_pct:.0f}%",
            4,
            f"1m: {load1:.1f}, 5m: {load5:.1f}, 15m: {load15:.1f} ({cpu_count} cores)",
        ))
    except OSError:
        pass

    # Memory
    mem_pct, mem_details = _memory_pressure()
    if mem_pct is not None:
        if mem_pct > 90:
            status = "bad"
        elif mem_pct > 75:
            status = "warn"
        else:
            status = "good"

        results.append((
            "system/memory",
            "Memory",
            status,
            f"{mem_pct:.0f}%",
            5,
            mem_details,
        ))

    return results
