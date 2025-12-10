# Polygon Filtered WebSocket Proxy

## Overview

The **Filtered Proxy** is a client-specific WebSocket proxy that connects to a **Firehose Proxy** and performs per-client filtering. This two-tier architecture provides:

- **Efficient Resource Usage**: One firehose connection handles all data
- **Client-Specific Filtering**: Each client only receives their subscribed symbols
- **Scalability**: Can support many clients without multiple Polygon connections

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         Polygon                                │
└────────────────┬───────────────────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────────┐
│                    Firehose Proxy (8767)                       │
└────────┬──────────────────────────────────┬────────────────────┘
         │                                  │
         ▼                                  ▼
┌─────────────────────┐          ┌────────────────────────────────┐
│  Filtered Proxy     │          │  Ms-Aggregator (8768)          │
│  (8765)             │◄─────────│  - Generates ms bars           │
│                     │  bars    │  - Forwards A.*, AM.*          │
│  Two Upstreams:     │          └────────────────────────────────┘
│  1. Firehose        │
│     (T.*, Q.*, ...) │
│  2. Ms-Aggregator   │
│     (A.*, AM.*, Ms) │
└─────────────────────┘
         ▲
         │
    ┌────┴────┐
    │ Clients │
    └─────────┘
```

**Key Design:**
- **Firehose Proxy**: Single connection to Polygon
- **Ms-Aggregator**: Specialized bar data service
  - Generates millisecond bars (100Ms.*, 250Ms.*, etc.)
  - Forwards native bars (A.*, AM.*)
- **Filtered Proxy**: Smart router for clients
  - Routes bar requests → Ms-Aggregator
  - Routes tick/quote requests → Firehose
  - **Clients only connect to Filtered Proxy (8765)**

## How It Works

### Filtered Proxy Behavior:

1. **Connects to TWO Upstreams**
   - **Firehose Proxy** (`ws://localhost:8767`): For trades, quotes, LULD, etc.
   - **Ms-Aggregator** (`ws://localhost:8768`): For ALL bar data

2. **Client Connections**
   - Clients connect to **Filtered Proxy only** (`ws://localhost:8765`)
   - Each client subscribes to any symbols: `T.AAPL`, `Q.GOOGL`, `A.AAPL`, `100Ms.SPY`
   - **Smart Routing**:
     - Bar subscriptions (`A.*`, `AM.*`, `*Ms.*`) → forwarded to Ms-Aggregator
     - Non-bar subscriptions (`T.*`, `Q.*`, etc.) → forwarded to Firehose

3. **Per-Client Filtering**
   - Router receives data from BOTH upstreams
   - For each message, checks which clients are subscribed
   - Only forwards message to clients that want it
   - **Seamless unified data stream to clients**

### Example Flow:

```
Client subscribes to: "T.AAPL,A.AAPL,100Ms.AAPL"

Filtered Proxy:
  ├─ T.AAPL → subscribes to Firehose
  ├─ A.AAPL → subscribes to Ms-Aggregator
  └─ 100Ms.AAPL → subscribes to Ms-Aggregator

Data Flow:
  ├─ Firehose sends: {"ev":"T","sym":"AAPL","p":150.25,...}
  │  └─ Routed to client
  │
  ├─ Ms-Aggregator sends: {"ev":"A","sym":"AAPL","o":150.20,"h":150.30,...}
  │  └─ Routed to client (native 1-second bar)
  │
  └─ Ms-Aggregator sends: {"T":"b","S":"AAPL","o":150.20,"h":150.25,...}
     └─ Routed to client (generated 100ms bar)

Result: Client receives unified stream of all three!
```

## Configuration

### Environment Variables

Create a `.env` file:

```bash
# Firehose Proxy URL (for trades, quotes, LULD, FMV)
FIREHOSE_URL=ws://localhost:8767

# Ms-Aggregator URL (for bar data: A.*, AM.*, *Ms.*)
MS_AGGREGATOR_URL=ws://localhost:8768

# Polygon API Key
POLYGON_API_KEY=your_polygon_api_key_here

# Filtered Proxy Port (clients connect here)
FILTERED_PROXY_PORT=8765

# Log Level
LOG_LEVEL=info
```

**Note**: Both Firehose Proxy and Ms-Aggregator must be running before starting Filtered Proxy.

## Building and Running

### Prerequisites
Make sure these are running first:
1. **Firehose Proxy** (port 8767)
2. **Ms-Aggregator** (port 8768)

### Build
```bash
cd filtered-proxy
cargo build --release
```

### Run
```bash
cargo run --release
```

You should see:
```
INFO Starting Polygon Filtered WebSocket Proxy
INFO Firehose URL: ws://localhost:8767
INFO Ms-Aggregator URL: ws://localhost:8768
INFO Starting stocks proxy on port 8765
```

## Key Differences

| Feature | Firehose Proxy | Ms-Aggregator | Filtered Proxy |
|---------|----------------|---------------|----------------|
| **Connects to** | Polygon directly | Firehose | Firehose + Ms-Aggregator |
| **Purpose** | Multiplex Polygon | Generate/forward bars | Route & filter per client |
| **Client filtering** | No | No | Yes (per-client) |
| **Data types** | All | Bars only | All (unified) |
| **Client connects to** | 8767 | 8768 | **8765 (recommended)** |

**Recommended**: Clients should connect to **Filtered Proxy (8765)** for:
- Single connection point
- Per-client filtering
- Access to both ticks/quotes AND bars (including millisecond bars)

## Client Usage

Clients connect to **Filtered Proxy** for a unified stream of ticks, quotes, AND bars:

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

        # Subscribe to ANY combination of ticks, quotes, and bars!
        await ws.send(json.dumps({
            "action": "subscribe",
            "params": "T.AAPL,Q.AAPL,A.AAPL,100Ms.AAPL"
            # T.AAPL → trades from Firehose
            # Q.AAPL → quotes from Firehose
            # A.AAPL → 1-second bars from Ms-Aggregator
            # 100Ms.AAPL → 100ms bars from Ms-Aggregator
        }))

        # Receive unified stream
        while True:
            msg = await ws.recv()
            print(f"Received: {msg}")

asyncio.run(client())
```

**Key Advantage**: One connection, all data types!

## Subscription Management

### Smart Routing

The `SubscriptionManager` intelligently routes subscriptions to the right upstream:

```rust
Client subscribes: "T.AAPL,A.AAPL,100Ms.SPY"

SubscriptionManager:
  ├─ T.AAPL → Firehose (non-bar)
  ├─ A.AAPL → Ms-Aggregator (bar)
  └─ 100Ms.SPY → Ms-Aggregator (bar)

Then filters incoming messages per-client:
  - AAPL trade from Firehose → Client A (subscribed to T.AAPL)
  - AAPL 1-sec bar from Ms-Agg → Client A (subscribed to A.AAPL)
  - SPY 100ms bar from Ms-Agg → Client A (subscribed to 100Ms.SPY)
```

### Wildcard Support

Clients can subscribe to wildcard:

```json
{"action": "subscribe", "params": "*"}
```

This gets ALL messages from BOTH upstreams:
- Firehose: `T.*,Q.*,LULD.*,FMV.*`
- Ms-Aggregator: `A.*,AM.*`

**Important:** Wildcard does **NOT** include millisecond bars (`100Ms.*`, `250Ms.*`, `500Ms.*`, etc.).

To receive millisecond bars, explicitly subscribe:
```json
{"action": "subscribe", "params": "500Ms.TSLA,1000Ms.SPY"}
```

**Rationale:** Millisecond bars are high-volume data. Explicit subscriptions give clients control over bandwidth and data usage.

## Performance Characteristics

### Advantages:
- ✅ **Single connection for clients**: Unified access to ticks, quotes, AND bars
- ✅ **Smart routing**: Automatically delegates bar requests to Ms-Aggregator
- ✅ **Low latency**: Local WebSocket connections to upstreams
- ✅ **Scalable**: Can support many clients efficiently
- ✅ **Per-client filtering**: Reduces bandwidth to clients
- ✅ **Millisecond bars**: Access to sub-second aggregates (100Ms, 250Ms, etc.)

### Considerations:
- ⚠️ **Requires two upstreams**: Firehose Proxy and Ms-Aggregator must be running
- ⚠️ **Memory usage**: Stores all client subscriptions
- ⚠️ **CPU for filtering**: Router must check subscriptions for each message

## Monitoring

The proxy logs important events:

```
INFO Starting Polygon Filtered WebSocket Proxy
INFO Firehose URL: ws://localhost:8767
INFO Ms-Aggregator URL: ws://localhost:8768
INFO Starting stocks proxy on port 8765
INFO Connecting to firehose at ws://localhost:8767
INFO Connecting to ms-aggregator at ws://localhost:8768
INFO stocks connected to firehose proxy
INFO stocks connected to ms-aggregator proxy
```

## Troubleshooting

### "Failed to connect to firehose"
- Ensure **Firehose Proxy** is running on port 8767
- Check `FIREHOSE_URL` in `.env`

### "Failed to connect to ms-aggregator"
- Ensure **Ms-Aggregator** is running on port 8768
- Check `MS_AGGREGATOR_URL` in `.env`

### "No bar data received"
- Verify Ms-Aggregator is connected and running
- Check client subscription includes bar symbols (A.*, AM.*, *Ms.*)
- Verify Firehose Proxy is sending trade data (T.*) to Ms-Aggregator

### "No tick/quote data received"
- Verify Firehose Proxy is connected to Polygon
- Check client subscription includes tick/quote symbols (T.*, Q.*)
- Verify API key is valid

## Source Code Structure

```
filtered-proxy/
├── src/
│   ├── main.rs                  # Entry point
│   ├── config.rs                # Config (connects to firehose)
│   ├── upstream.rs              # Connects to firehose, subscribes to *
│   ├── client_handler.rs        # Handles client connections
│   ├── router.rs                # Routes messages per-client
│   ├── subscription_manager.rs  # Tracks client subscriptions
│   └── types.rs                 # Type definitions
├── Cargo.toml
├── .env
└── README.md
```

## Development

### Testing

Test with multiple clients:

```python
# Client 1 - Subscribe to AAPL
python test_client.py --symbols "T.AAPL"

# Client 2 - Subscribe to GOOGL
python test_client.py --symbols "T.GOOGL"

# Client 3 - Subscribe to all
python test_client.py --symbols "*"
```

### Debug Logging

Enable debug logs:

```bash
LOG_LEVEL=debug cargo run
```

## License

MIT
