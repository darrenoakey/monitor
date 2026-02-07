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

## Testing
- Python tests: `./run test` (11 tests, real integration against pubsub)
- Pubsub must be running for tests
- Token read from `~/src/pubsub/data/token`

## Commands
- `./run serve` - serve UI on port 8090
- `./run test` - run Python tests
- `./run demo` - run demo data publisher
