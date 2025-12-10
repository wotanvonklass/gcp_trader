# Polygon WebSocket Proxy

## Overview

Three-tier WebSocket proxy system for Polygon.io market data with **millisecond bar support**. Get real-time ticks, quotes, AND sub-second bars through a single connection.

## Architecture

```
┌─────────────────────────────────────────────┐
│              POLYGON.IO                     │
└────────────────┬────────────────────────────┘
                 │ (1 connection)
                 ▼
┌─────────────────────────────────────────────┐
│       Firehose Proxy (8767)                 │
│       - Single Polygon connection           │
└────────┬────────────────────────┬───────────┘
         │                        │
         ▼                        ▼
┌──────────────────┐    ┌──────────────────────┐
│ Ms-Aggregator    │    │ Filtered Proxy       │
│ (8768)           │───>│ (8765)               │
│ - Generates      │    │ - Per-client filter  │
│   100ms bars     │    │ - Smart routing      │
│ - Forwards       │    │ - Unified stream     │
│   A.*, AM.*      │    └──────────┬───────────┘
└──────────────────┘               │
                                   ▼
                            ┌──────────────┐
                            │   CLIENTS    │
                            │ Port 8765    │
                            └──────────────┘
```

**For Clients:** Connect to port **8765** and get everything (ticks, quotes, bars, millisecond bars)

## Components

| Component | Port | Purpose |
|-----------|------|---------|
| **Firehose Proxy** | 8767 | Single connection to Polygon |
| **Ms-Aggregator** | 8768 | Generates millisecond bars (100Ms, 250Ms, etc.) + forwards A.*, AM.* |
| **Filtered Proxy** | 8765 | **Client connection point** - Smart routing + per-client filtering |

**Clients connect to port 8765** - everything else is internal infrastructure.

## Quick Start

### 1. Start All Services

```bash
# Terminal 1: Firehose Proxy
cd firehose-proxy && cargo run --release

# Terminal 2: Ms-Aggregator
cd ms-aggregator && cargo run --release

# Terminal 3: Filtered Proxy
cd filtered-proxy && cargo run --release
```

### 2. Connect Your Client (Port 8765)

```python
import asyncio
import websockets
import json

async def client():
    async with websockets.connect("ws://localhost:8765") as ws:
        # Authenticate
        await ws.send(json.dumps({
            "action": "auth",
            "params": "YOUR_API_KEY"
        }))
        print(await ws.recv())

        # Subscribe to ticks, 1-second bars, AND 100ms bars!
        await ws.send(json.dumps({
            "action": "subscribe",
            "params": "T.AAPL,A.AAPL,100Ms.AAPL"
        }))

        # Receive unified stream of all data types
        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            for item in data:
                if item.get("ev") == "T":
                    print(f"Trade: {item['sym']} @ ${item['p']}")
                elif item.get("ev") == "A":
                    print(f"1-sec bar: {item['sym']} OHLCV")
                elif item.get("ev") == "MB":  # Millisecond bar format
                    print(f"{item['interval']}ms bar: {item['sym']} OHLCV")

asyncio.run(client())
```

## Subscription Format

**Message Types:**
- `T.*` - Trades (individual executions)
- `Q.*` - Quotes (NBBO - best bid/ask)
- `A.*` - 1-second bars from Polygon
- `AM.*` - 1-minute bars from Polygon
- `100Ms.*` - **100ms bars** (generated)
- `250Ms.*` - **250ms bars** (generated)
- `500Ms.*` - **500ms bars** (generated)
- `*Ms.*` - Any millisecond interval (1ms - 60000ms)

### Quick Examples

```python
# Trades only
{"action": "subscribe", "params": "T.AAPL"}

# 1-second bars (Polygon native)
{"action": "subscribe", "params": "A.AAPL"}

# 100ms bars (generated from trades)
{"action": "subscribe", "params": "100Ms.AAPL"}

# Everything for AAPL: ticks + 1-sec bars + 100ms bars
{"action": "subscribe", "params": "T.AAPL,A.AAPL,100Ms.AAPL"}

# Multiple symbols with ms bars
{"action": "subscribe", "params": "250Ms.AAPL,250Ms.SPY,250Ms.QQQ"}

# Wildcard (gets T.*, Q.*, A.*, AM.* but NOT millisecond bars)
{"action": "subscribe", "params": "*"}
```

**Important:** Wildcard subscriptions (`*`) do **NOT** include millisecond bars. You must explicitly subscribe to millisecond intervals (e.g., `500Ms.TSLA`).

**High-Frequency Trading (100ms bars):**
```python
# Sub-second precision for HFT strategies
{"action": "subscribe", "params": "100Ms.SPY,100Ms.QQQ,100Ms.IWM"}
```

**Scalping (250ms bars + trades):**
```python
# Ultra-fast entries with 250ms OHLCV patterns
{"action": "subscribe", "params": "T.AAPL,250Ms.AAPL"}
```

**Day Trading (500ms + 1-second bars):**
```python
# Multiple timeframes for confluence
{"action": "subscribe", "params": "500Ms.SPY,A.SPY,T.SPY"}
```

**Charting Application:**
```python
# 1-second and 1-minute bars for live charts
{"action": "subscribe", "params": "A.AAPL,AM.AAPL"}
```

## Why Use This?

✅ **Single Polygon Connection** - Share one connection across unlimited clients
✅ **Millisecond Bars** - Get 100ms, 250ms, 500ms bars (Polygon doesn't provide these)
✅ **Per-Client Filtering** - Each client only receives their subscribed symbols
✅ **Unified Stream** - Ticks, quotes, AND bars through one WebSocket
✅ **Cost Effective** - Minimize Polygon connection fees
✅ **Scalable** - Add more filtered proxies as needed

## Configuration

Create `.env` files in each component directory:

```bash
# Required: Your Polygon API key
POLYGON_API_KEY=your_polygon_api_key_here

# Optional: Ports (defaults shown)
FIREHOSE_PORT=8767
MS_AGGREGATOR_PORT=8768
FILTERED_PROXY_PORT=8765

# Optional: Logging
LOG_LEVEL=info
```

## Unsubscribe

```python
# Unsubscribe from specific symbols
await ws.send(json.dumps({
    "action": "unsubscribe",
    "params": "T.AAPL,100Ms.AAPL"
}))
```

## Message Formats

### Trades (from Polygon)
```json
{"ev": "T", "sym": "AAPL", "p": 150.25, "s": 100, "t": 1633024800000}
```

### Quotes (from Polygon)
```json
{"ev": "Q", "sym": "AAPL", "bp": 150.20, "ap": 150.25, "t": 1633024800000}
```

### Native Bars (A.*, AM.* from Polygon)
```json
{"ev": "A", "sym": "AAPL", "o": 150.20, "h": 150.30, "l": 150.15, "c": 150.25, "v": 1000}
```

### Millisecond Bars (100Ms.*, 250Ms.*, 500Ms.* - generated)
```json
{
  "ev": "MB",
  "sym": "AAPL",
  "interval": 500,
  "o": 150.20,
  "h": 150.30,
  "l": 150.15,
  "c": 150.25,
  "v": 1000,
  "s": 1633024800000,
  "e": 1633024800500,
  "n": 42
}
```
**Fields:**
- `ev`: "MB" (millisecond bar event type)
- `sym`: Symbol
- `interval`: Bar interval in milliseconds
- `o`, `h`, `l`, `c`: Open, High, Low, Close prices
- `v`: Volume (total shares traded)
- `s`, `e`: Start and end timestamps (Unix milliseconds)
- `n`: Number of trades in the bar

## Troubleshooting

**Can't connect to port 8765?**
- Ensure all three services are running (firehose, ms-aggregator, filtered-proxy)
- Check logs for errors

**No millisecond bars received?**
- Verify ms-aggregator is running on port 8768
- Check you're explicitly subscribing (e.g., `500Ms.TSLA`, not `*`)
- During off-hours, there may be no trades to aggregate
- If connecting directly to ms-aggregator (port 8768) for testing, you must authenticate first with `{"action": "auth", "params": "your_key"}`

**Getting all symbols instead of just subscribed?**
- Ensure you didn't subscribe to wildcard `*`
- Each client has independent subscriptions

**Connection drops frequently?**
- Check your Polygon API key is valid
- Verify network stability

## Development

```bash
# Build all components
cd firehose-proxy && cargo build --release
cd ../ms-aggregator && cargo build --release
cd ../filtered-proxy && cargo build --release

# Run tests
cd filtered-proxy && cargo test
pytest filtered-proxy/tests/test_filtered_proxy.py -v
```

## License

MIT
