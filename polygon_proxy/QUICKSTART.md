# Quick Start Guide - Two-Tier Polygon Proxy

## TL;DR

```bash
# Terminal 1: Start firehose proxy (connects to Polygon)
cd firehose-proxy
cargo run --release

# Terminal 2: Start filtered proxy (filters per-client)
cd filtered-proxy
cargo run --release

# Terminal 3: Connect your client
python test_polygon_proxy.py
```

Clients connect to: `ws://localhost:8765`

## Architecture at a Glance

```
Polygon.io (wss://socket.polygon.io/stocks)
    ↑
    │ (1 connection, aggregated subscriptions)
    │
Firehose Proxy (localhost:8767)
    ↑
    │ (wildcard subscription: *)
    │
Filtered Proxy (localhost:8765)
    ↑
    │ (client-specific filtering)
    │
Clients (connect here!)
```

## What Each Component Does

### Firehose Proxy (Port 8767)
- ✅ Connects to Polygon directly
- ✅ Maintains ONE upstream connection
- ✅ Receives data for all subscribed symbols
- ✅ Broadcasts to all filtered proxies
- ❌ Does NOT filter per-client

### Filtered Proxy (Port 8765)
- ✅ Connects to firehose proxy
- ✅ Subscribes to `*` (gets everything)
- ✅ Filters messages per-client
- ✅ Clients connect here
- ❌ Does NOT connect to Polygon directly

## Configuration

### Firehose Proxy: `firehose-proxy/.env`
```bash
POLYGON_API_KEY=your_polygon_api_key_here
FIREHOSE_PORT=8767
LOG_LEVEL=info
```

### Filtered Proxy: `filtered-proxy/.env`
```bash
FIREHOSE_URL=ws://localhost:8767
POLYGON_API_KEY=your_polygon_api_key_here
FILTERED_PROXY_PORT=8765
LOG_LEVEL=info
```

## Example Client Code

```python
import asyncio
import websockets
import json

async def polygon_client():
    # Connect to FILTERED PROXY (not firehose!)
    async with websockets.connect("ws://localhost:8765") as ws:

        # 1. Authenticate
        await ws.send(json.dumps({
            "action": "auth",
            "params": "YOUR_API_KEY"
        }))
        response = await ws.recv()
        print(f"Auth: {response}")

        # 2. Subscribe to specific symbols
        await ws.send(json.dumps({
            "action": "subscribe",
            "params": "T.AAPL,Q.AAPL"  # Trades and quotes for AAPL
        }))

        # 3. Receive filtered data (only AAPL!)
        while True:
            message = await ws.recv()
            data = json.loads(message)
            print(f"Received: {data}")

asyncio.run(polygon_client())
```

## Data Flow Example

**Client subscribes to T.AAPL:**

```
1. Client → Filtered Proxy: {"action":"subscribe","params":"T.AAPL"}
   └─ Filtered proxy records: Client wants T.AAPL
   └─ Does NOT forward to firehose (already has *)

2. Firehose Proxy → Filtered Proxy: (all data)
   [{"ev":"T","sym":"AAPL",...}]  ← AAPL trade
   [{"ev":"T","sym":"GOOGL",...}] ← GOOGL trade
   [{"ev":"Q","sym":"MSFT",...}]  ← MSFT quote

3. Filtered Proxy → Client: (filtered)
   [{"ev":"T","sym":"AAPL",...}]  ← Only AAPL sent to client!
```

## Common Operations

### Check if everything is running

```bash
# Check firehose proxy
curl http://localhost:8767/health  # (if health endpoint exists)
# OR check logs for "Authenticated successfully"

# Check filtered proxy
curl http://localhost:8765/health  # (if health endpoint exists)
# OR check logs for "Subscribed to wildcard (*)"
```

### View logs

```bash
# Firehose proxy logs
cd firehose-proxy
LOG_LEVEL=debug cargo run

# Filtered proxy logs
cd filtered-proxy
LOG_LEVEL=debug cargo run
```

### Test with multiple clients

```bash
# Client 1 - only AAPL
python test_client.py --symbols "T.AAPL"

# Client 2 - only GOOGL
python test_client.py --symbols "T.GOOGL"

# Client 3 - everything
python test_client.py --symbols "*"
```

## Subscription Format

Polygon format: `TYPE.SYMBOL`

**Examples:**
- `T.AAPL` - AAPL trades only
- `Q.AAPL` - AAPL quotes only
- `T.AAPL,Q.AAPL` - AAPL trades AND quotes
- `T.*` - All trades (all symbols)
- `*` - Everything (all types, all symbols)

**Message Types:**
- `T` - Trades
- `Q` - Quotes (NBBO)
- `A` - Aggregates (per second)
- `AM` - Aggregates (per minute)
- `LULD` - Limit Up Limit Down
- `FMV` - Fair Market Value

## Troubleshooting

### "Connection refused to localhost:8767"
**Problem:** Filtered proxy can't connect to firehose
**Solution:** Start firehose-proxy first!

```bash
cd firehose-proxy
cargo run --release
```

### "Connection refused to localhost:8765"
**Problem:** Client can't connect to filtered proxy
**Solution:** Start filtered-proxy!

```bash
cd filtered-proxy
cargo run --release
```

### "Not receiving any data"
**Problem:** No messages coming through
**Solution:**
1. Check firehose proxy logs - is it connected to Polygon?
2. Check filtered proxy logs - is it subscribed to `*`?
3. Check client subscription format - is it correct?

### "Receiving wrong symbols"
**Problem:** Getting data you didn't subscribe to
**Solution:** Check subscription message format. Should be `T.AAPL` not just `AAPL`

## Advanced: Scaling

### Run multiple filtered proxies

```bash
# Filtered proxy 1 (port 8765)
cd filtered-proxy
FILTERED_PROXY_PORT=8765 cargo run --release

# Filtered proxy 2 (port 8775)
cd filtered-proxy
FILTERED_PROXY_PORT=8775 cargo run --release

# Both connect to same firehose (8767)
# Each handles different clients
```

### Load balance clients

Use nginx or HAProxy to distribute clients across filtered proxies:

```nginx
upstream polygon_filtered {
    server localhost:8765;
    server localhost:8775;
    server localhost:8785;
}
```

## Performance Tips

### For filtered proxy:
- Increase channel buffer size in `main.rs` if handling high volume
- Use release builds (`cargo build --release`)
- Monitor memory usage with many clients

### For firehose proxy:
- Ensure stable connection to Polygon
- Monitor subscription aggregation
- Watch for connection drops

## Security

### Production checklist:
- [ ] Use WSS (not WS) for production
- [ ] Validate API keys before forwarding
- [ ] Rate limit client connections
- [ ] Monitor for abuse
- [ ] Use firewall rules to restrict access
- [ ] Enable authentication on filtered proxy

## Monitoring

### Key metrics to track:

**Firehose Proxy:**
- Upstream connection status
- Messages per second received
- Active filtered proxy connections

**Filtered Proxy:**
- Active client connections
- Messages filtered per second
- Memory usage

## Getting Help

- [README.md](README.md) - Full architecture docs
- [MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md) - What changed
- [filtered-proxy/README.md](filtered-proxy/README.md) - Filtered proxy details
- [PLAN.md](PLAN.md) - Original implementation plan

## Summary

```
┌─────────────────────────────────────────────────────┐
│  START HERE                                         │
│  1. cd firehose-proxy && cargo run                  │
│  2. cd filtered-proxy && cargo run                  │
│  3. Connect client to ws://localhost:8765           │
│                                                     │
│  Your client gets filtered data automatically! ✨   │
└─────────────────────────────────────────────────────┘
```
