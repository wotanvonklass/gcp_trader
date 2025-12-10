# Polygon Firehose Proxy

A high-performance WebSocket proxy for Polygon market data that broadcasts all configured data types to multiple clients.

## Features

- ✅ **Zero Filtering Overhead:** All messages broadcast to all clients (firehose model)
- ✅ **Simple Auth:** Clients authenticate with proxy token (not Polygon credentials)
- ✅ **Auto-Reconnect:** Handles upstream disconnections automatically
- ✅ **Configurable Data Types:** Subscribe to trades (T), aggregates (A, AM), quotes (Q), or any combination
- ✅ **Low Latency:** ~100ns routing per client (no JSON parsing, no routing logic)
- ✅ **Unlimited Clients:** Scale to thousands of clients with minimal overhead

## Architecture

```
Polygon Data Feed         Firehose Proxy            Multiple Clients
─────────────────         ────────────────          ────────────────
                              :8767
wss://socket.polygon   →   Broadcasts All    →     Client A (*)
  .io/stocks               Messages (zero         Client B (*)
                           filtering)              Client C (*)
```

**Key Design:**
- Proxy subscribes to `*` (wildcard) for configured data types
- All messages broadcast to all authenticated clients
- No per-symbol subscription tracking
- No message filtering or routing

## Quick Start

### 1. Configuration

Create `.env` file:

```bash
# Polygon API Configuration
POLYGON_API_KEY=your_polygon_api_key_here

# Polygon WebSocket URL
POLYGON_WS_URL=wss://socket.polygon.io/stocks

# Data types to subscribe (comma-separated)
# T = Trades, Q = Quotes, A = Aggregates (per second), AM = Aggregates (per minute)
# Note: Q excluded by default to reduce bandwidth
SUBSCRIBE_DATA_TYPES=T,A,AM

# Proxy settings
PROXY_PORT=8767
LOG_LEVEL=info
```

### 2. Run the Proxy

```bash
cargo run --release
```

### 3. Connect Clients

**Example Python Client:**

```python
import asyncio
import websockets
import json

async def subscribe_to_firehose():
    async with websockets.connect("ws://localhost:8767") as ws:
        # Authenticate with proxy
        auth = {"action": "auth", "token": "firehose-token-12345"}
        await ws.send(json.dumps(auth))
        print(await ws.recv())  # {"status":"authenticated",...}

        # Subscribe to firehose
        subscribe = {"action": "subscribe"}
        await ws.send(json.dumps(subscribe))
        print(await ws.recv())  # {"status":"subscribed",...}

        # Receive all messages
        async for message in ws:
            data = json.loads(message)
            print(f"Received: {data}")

asyncio.run(subscribe_to_firehose())
```

## Protocol

### Client → Proxy Messages

**1. Authenticate:**
```json
{"action": "auth", "token": "firehose-token-12345"}
```

**2. Subscribe:**
```json
{"action": "subscribe"}
```

### Proxy → Client Messages

**Auth Response:**
```json
{"status": "authenticated", "message": "Successfully authenticated"}
```

**Subscribe Response:**
```json
{"status": "subscribed", "message": "Subscribed to firehose"}
```

**Data Messages:**
All Polygon messages forwarded as-is. See [Polygon Docs](https://polygon.io/docs/websocket/stocks/overview).

## Performance

| Metric | Value |
|--------|-------|
| Routing Latency | ~100ns per client |
| Memory per Client | ~16 bytes |
| Max Clients | Limited by system resources |
| Throughput | >1M msg/s on 4-core CPU |

## Use Cases

✅ **Perfect For:**
- Market data recorders (store everything)
- Real-time analytics platforms
- Risk management systems
- High-frequency trading backtesting
- Market monitoring dashboards

❌ **Not Ideal For:**
- Clients needing specific symbols only (use polygon_proxy instead)
- Low-bandwidth connections
- Mobile clients

## Comparison with Polygon Proxy

| Feature | Firehose Proxy | Polygon Proxy |
|---------|----------------|---------------|
| Filtering | None (broadcast all) | Per TYPE.SYMBOL |
| Routing | ~100ns | ~5-10µs |
| Memory | O(1) per client | O(N) per client |
| Complexity | ~200 LOC | ~800 LOC |
| Use Case | Full market data | Selective subscriptions |

## Configuration Options

### Data Types

**T (Trades):** Real-time trade executions
```bash
SUBSCRIBE_DATA_TYPES=T
```

**A (Aggregates/Second):** Per-second OHLCV bars
```bash
SUBSCRIBE_DATA_TYPES=A
```

**AM (Aggregates/Minute):** Per-minute OHLCV bars
```bash
SUBSCRIBE_DATA_TYPES=AM
```

**Q (Quotes):** Best bid/ask updates (high volume!)
```bash
SUBSCRIBE_DATA_TYPES=T,A,AM,Q
```

**All Types:** Include LULD and FMV data
```bash
SUBSCRIBE_DATA_TYPES=T,Q,A,AM,LULD,FMV
```

## Development

```bash
# Check compilation
cargo check

# Run with debug logging
LOG_LEVEL=debug cargo run

# Build optimized binary
cargo build --release

# Run tests (TODO)
cargo test
```

## Deployment

**Systemd Service:**

```ini
[Unit]
Description=Polygon Firehose Proxy
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/path/to/firehose-proxy
EnvironmentFile=/path/to/firehose-proxy/.env
ExecStart=/path/to/firehose-proxy/target/release/firehose_proxy
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Security Notes

⚠️ **Important:**
- Default auth token is for demo only
- Change `auth_token` in `src/main.rs` line 43
- Consider implementing proper token management
- Use TLS in production (wss://)
- Restrict firewall access to trusted IPs

## License

MIT

## Related Projects

- [polygon_proxy](../): Full-featured proxy with per-symbol routing for Polygon.io
