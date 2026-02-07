# Monitor - Treemap Dashboard for Pubsub

## Architecture
- Python client library (`lib/monitor.py`) publishes status blobs to pubsub under `/monitor/...`
- Browser UI (`ui/`) polls pubsub, renders squarified treemap with zoom/pan
- Pubsub server at port 19103 is the central hub (CORS enabled)

## Status Blob Format
```json
{"weight": 5, "status": "good", "name": "Root Disk", "value": "45%", "details": "...", "timestamp": 1706300000}
```
- `status`: "good" | "warn" | "bad"
- `weight`: relative size among siblings (> 0)
- Stale if no update in 5 minutes (overrides status color)

## Agent
- `agent/agent.py` runs collectors in threads, publishes to pubsub
- Collectors: disks, processes, system, websites (in `agent/collectors/`)
- Config: machine name from hostname mapping or `MONITOR_MACHINE` env var
- `processes.py` uses `_find_auto()` to locate `~/bin/auto` (not in PATH under daemons)
- Category weights published at startup (services=3, others=1)
- Mac-mini deployment: rsync agent+lib, registered with `auto` via `run-agent.sh` wrapper for env vars

## UI Key Patterns
- Root node skipped in render - children laid out directly at viewport level
- Branch nodes always green (`status-good`); leaf weight from published blob
- Branch node weight: explicit from value blob if present, else 1
- Dead subtree pruning: `isDead()` removes null-valued branches during `mergeUpdate()`
- Leaf title/value use absolute positioning to prevent overlap
- `fitText()` binary search for largest font fitting container
- `wrappableHTML()` wraps tokens in nowrap spans with zero-width-space break opportunities
- Token: URL query param > localStorage > prompt

## Testing
- Python tests: `./run test` (11 tests, real integration against pubsub)
- Tests use `/testing` prefix (not `/monitor`) to keep production data clean
- Pubsub must be running for tests
- Token read from `~/src/pubsub/data/token`

## Deployment
- Local: registered with `auto` as `monitor-agent`
- Mac-mini (10.0.0.46): `~/src/monitor/run-agent.sh` registered with `auto`
- Sync: `rsync -az agent/ darrenoakey@10.0.0.46:src/monitor/agent/`

## Commands
- `./run serve` - serve UI on port 8090
- `./run test` - run Python tests
- `./run agent` - run monitoring agent
