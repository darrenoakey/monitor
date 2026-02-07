#!/usr/bin/env python3
"""Demo script that publishes fake monitoring data to pubsub.

Creates ~50 nodes across 3 machines with disk, cpu, memory, and process metrics.
Runs in a loop, updating values every 2 seconds with some randomization.
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from monitor import Monitor

TOKEN_PATH = os.path.expanduser('~/src/pubsub/data/token')


def read_token():
    with open(TOKEN_PATH) as f:
        return f.read().strip()


MACHINES = {
    'mac-mini': {
        'disk/root': {'name': 'Root Disk', 'base': 45, 'unit': '%', 'weight': 5},
        'disk/data': {'name': 'Data Disk', 'base': 72, 'unit': '%', 'weight': 8},
        'cpu/load': {'name': 'CPU Load', 'base': 25, 'unit': '%', 'weight': 4},
        'cpu/temp': {'name': 'CPU Temp', 'base': 55, 'unit': 'C', 'weight': 3},
        'memory/used': {'name': 'Memory', 'base': 60, 'unit': '%', 'weight': 5},
        'memory/swap': {'name': 'Swap', 'base': 5, 'unit': '%', 'weight': 2},
        'procs/pubsub': {'name': 'Pubsub', 'base': 12, 'unit': 'MB', 'weight': 2},
        'procs/nginx': {'name': 'Nginx', 'base': 8, 'unit': 'MB', 'weight': 2},
        'procs/postgres': {'name': 'Postgres', 'base': 250, 'unit': 'MB', 'weight': 3},
        'procs/redis': {'name': 'Redis', 'base': 30, 'unit': 'MB', 'weight': 2},
        'network/in': {'name': 'Net In', 'base': 15, 'unit': 'Mbps', 'weight': 2},
        'network/out': {'name': 'Net Out', 'base': 8, 'unit': 'Mbps', 'weight': 2},
    },
    'nas': {
        'disk/vol1': {'name': 'Volume 1', 'base': 85, 'unit': '%', 'weight': 10},
        'disk/vol2': {'name': 'Volume 2', 'base': 40, 'unit': '%', 'weight': 10},
        'disk/cache': {'name': 'SSD Cache', 'base': 30, 'unit': '%', 'weight': 3},
        'cpu/load': {'name': 'CPU Load', 'base': 15, 'unit': '%', 'weight': 3},
        'memory/used': {'name': 'Memory', 'base': 45, 'unit': '%', 'weight': 4},
        'raid/status': {'name': 'RAID', 'base': 0, 'unit': '', 'weight': 5},
        'procs/smb': {'name': 'Samba', 'base': 20, 'unit': 'MB', 'weight': 2},
        'procs/plex': {'name': 'Plex', 'base': 350, 'unit': 'MB', 'weight': 3},
        'procs/backup': {'name': 'Backup', 'base': 100, 'unit': 'MB', 'weight': 2},
        'network/in': {'name': 'Net In', 'base': 50, 'unit': 'Mbps', 'weight': 3},
        'network/out': {'name': 'Net Out', 'base': 45, 'unit': 'Mbps', 'weight': 3},
        'temp/drives': {'name': 'Drive Temp', 'base': 38, 'unit': 'C', 'weight': 3},
    },
    'workstation': {
        'disk/system': {'name': 'System SSD', 'base': 55, 'unit': '%', 'weight': 5},
        'disk/projects': {'name': 'Projects', 'base': 68, 'unit': '%', 'weight': 5},
        'cpu/load': {'name': 'CPU Load', 'base': 35, 'unit': '%', 'weight': 4},
        'cpu/temp': {'name': 'CPU Temp', 'base': 62, 'unit': 'C', 'weight': 3},
        'gpu/load': {'name': 'GPU Load', 'base': 20, 'unit': '%', 'weight': 4},
        'gpu/temp': {'name': 'GPU Temp', 'base': 50, 'unit': 'C', 'weight': 3},
        'gpu/vram': {'name': 'VRAM', 'base': 40, 'unit': '%', 'weight': 3},
        'memory/used': {'name': 'Memory', 'base': 50, 'unit': '%', 'weight': 5},
        'procs/chrome': {'name': 'Chrome', 'base': 1200, 'unit': 'MB', 'weight': 3},
        'procs/vscode': {'name': 'VS Code', 'base': 450, 'unit': 'MB', 'weight': 2},
        'procs/docker': {'name': 'Docker', 'base': 800, 'unit': 'MB', 'weight': 3},
        'procs/node': {'name': 'Node.js', 'base': 200, 'unit': 'MB', 'weight': 2},
        'network/in': {'name': 'Net In', 'base': 25, 'unit': 'Mbps', 'weight': 2},
        'network/out': {'name': 'Net Out', 'base': 12, 'unit': 'Mbps', 'weight': 2},
    },
}


def get_status(path, val):
    """Determine status based on metric type and value."""
    if 'temp' in path:
        if val > 80:
            return 'bad'
        if val > 65:
            return 'warn'
        return 'good'
    if 'disk' in path or 'memory' in path or 'vram' in path or 'swap' in path:
        if val > 90:
            return 'bad'
        if val > 75:
            return 'warn'
        return 'good'
    if 'cpu' in path or 'gpu/load' in path:
        if val > 90:
            return 'bad'
        if val > 70:
            return 'warn'
        return 'good'
    if 'raid' in path:
        return 'good'
    return 'good'


def get_details(path, val, spec):
    """Generate details string."""
    if 'disk' in path:
        total = int(val * 2)
        return f"Used: {val}{spec['unit']} of {total}GB"
    if 'memory' in path or 'swap' in path:
        return f"Utilization: {val}{spec['unit']}"
    if 'temp' in path:
        return f"Current: {val}{spec['unit']} (max 95C)"
    if 'procs' in path:
        return f"RSS: {val}{spec['unit']}"
    if 'network' in path:
        return f"Throughput: {val}{spec['unit']}"
    if 'raid' in path:
        return 'All drives healthy, RAID5 nominal'
    return f"{val}{spec['unit']}"


def main():
    token = read_token()
    mon = Monitor(token=token)
    iteration = 0

    print(f'Publishing demo data to pubsub (token: {token[:8]}...)')
    print(f'Machines: {", ".join(MACHINES.keys())}')
    print(f'Total metrics: {sum(len(m) for m in MACHINES.values())}')
    print('Press Ctrl+C to stop.\n')

    while True:
        iteration += 1
        for machine, metrics in MACHINES.items():
            for path, spec in metrics.items():
                # Add some random variation
                drift = random.uniform(-5, 5)
                val = max(0, spec['base'] + drift)

                # Occasionally spike a random metric
                if random.random() < 0.02:
                    val = spec['base'] + random.uniform(20, 40)

                if 'raid' in path:
                    display_val = 'Healthy'
                else:
                    val = round(val, 1)
                    display_val = f'{val}{spec["unit"]}'

                status = get_status(path, val)
                details = get_details(path, val, spec)
                full_path = f'{machine}/{path}'

                mon.publish(
                    full_path,
                    name=spec['name'],
                    status=status,
                    value=display_val,
                    weight=spec['weight'],
                    details=details,
                )

        print(f'[{iteration}] Published {sum(len(m) for m in MACHINES.values())} metrics')
        time.sleep(2)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
