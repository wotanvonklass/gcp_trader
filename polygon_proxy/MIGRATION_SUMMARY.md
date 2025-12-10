# Migration to Two-Tier Architecture - Summary

## What Changed

The original `polygon_proxy` has been reorganized into a **two-tier architecture** with separate **firehose** and **filtered** proxies.

## Before (Single Proxy)

```
polygon_proxy/
├── src/
│   ├── main.rs
│   ├── config.rs
│   ├── upstream.rs (connected directly to Polygon)
│   └── ...
├── Cargo.toml
└── .env
```

**Behavior:**
- Connected directly to Polygon
- Aggregated client subscriptions
- Sent subscriptions upstream to Polygon

## After (Two-Tier Architecture)

```
polygon_proxy/
├── firehose-proxy/              # Tier 1: Connects to Polygon
│   ├── src/
│   │   ├── main.rs
│   │   ├── upstream.rs (→ Polygon)
│   │   └── ...
│   ├── Cargo.toml
│   └── .env
│
├── filtered-proxy/              # Tier 2: Filters per-client
│   ├── src/
│   │   ├── main.rs
│   │   ├── upstream.rs (→ Firehose)
│   │   └── ...
│   ├── Cargo.toml
│   └── .env
│
├── README.md
└── PLAN.md
```

## Architecture Flow

### Firehose Proxy (Port 8767)
```
Polygon ← (aggregated subs) ← Firehose Proxy ← (*) ← Filtered Proxy
```

**Responsibilities:**
- Maintains ONE connection to Polygon
- Aggregates subscriptions from filtered proxies
- Broadcasts all received data to connected filtered proxies

### Filtered Proxy (Port 8765)
```
Filtered Proxy ← (specific subs) ← Clients
```

**Responsibilities:**
- Subscribes to wildcard (`*`) from firehose
- Receives ALL data from firehose
- Filters messages per-client based on their subscriptions
- Only sends relevant data to each client

## Key Changes Made

### 1. Created `firehose-proxy/` Directory
- **Purpose:** Connect to Polygon directly
- **Port:** 8767 (configurable via `FIREHOSE_PORT`)
- **Subscription behavior:** Aggregates client subscriptions and sends to Polygon

### 2. Created `filtered-proxy/` Directory
- **Purpose:** Filter data per-client
- **Port:** 8765 (configurable via `FILTERED_PROXY_PORT`)
- **Subscription behavior:** Subscribes to `*` from firehose, filters locally

### 3. Modified `filtered-proxy/src/config.rs`
**Added:**
```rust
pub firehose_url: String,  // URL of firehose proxy to connect to
```

**Changed:**
```rust
// Before: PROXY_STOCKS_PORT
// After: FILTERED_PROXY_PORT
```

### 4. Modified `filtered-proxy/src/upstream.rs`
**Changed connection target:**
```rust
// Before: Connect to wss://socket.polygon.io/stocks
let url = format!("{}?apiKey={}", self.cluster.url(), self.api_key);

// After: Connect to firehose proxy
let url = self.firehose_url.clone();
```

**Added wildcard subscription:**
```rust
// After auth success, subscribe to wildcard
let subscribe_msg = serde_json::json!({
    "action": "subscribe",
    "params": "*"
});
```

**Changed subscription forwarding:**
```rust
// Before: Forward client subscriptions to Polygon
write.send(Message::Text(cmd)).await?;

// After: Don't forward (already subscribed to *)
// Client subscriptions handled locally by router
debug!("Received client subscription (not forwarding to firehose)");
```

### 5. Modified `filtered-proxy/src/types.rs`
**Changed `url()` method:**
```rust
// Before
pub fn url(&self) -> &str {
    match self {
        Self::Stocks => "wss://socket.polygon.io/stocks",
    }
}

// After
pub fn url(&self, config: &crate::config::Config) -> String {
    match self {
        Self::Stocks => config.firehose_url.clone(),
    }
}
```

### 6. Modified `filtered-proxy/src/main.rs`
**Changed startup message:**
```rust
// Before
info!("Starting Polygon WebSocket proxy for stocks");

// After
info!("Starting Polygon Filtered WebSocket Proxy");
info!("Firehose URL: {}", config.firehose_url);
```

**Updated UpstreamConnection initialization:**
```rust
// Added firehose_url parameter
let upstream = UpstreamConnection::new(
    cluster,
    config.firehose_url.clone(),  // NEW
    config.polygon_api_key.clone(),
    upstream_tx,
    upstream_cmd_rx,
);
```

### 7. Created Documentation
- `README.md` - Overall architecture explanation
- `filtered-proxy/README.md` - Filtered proxy details
- `firehose-proxy/README.md` - Firehose proxy details (if exists)
- `filtered-proxy/.env.example` - Configuration template

## Configuration Changes

### Firehose Proxy `.env`
```bash
# Connects to Polygon
POLYGON_API_KEY=your_api_key
FIREHOSE_PORT=8767
LOG_LEVEL=info
```

### Filtered Proxy `.env`
```bash
# Connects to firehose
FIREHOSE_URL=ws://localhost:8767
POLYGON_API_KEY=your_api_key
FILTERED_PROXY_PORT=8765
LOG_LEVEL=info
```

## Behavioral Changes

### Subscription Flow

**Before (Single Proxy):**
```
Client A: subscribe T.AAPL
Client B: subscribe T.GOOGL
        ↓
Proxy aggregates: T.AAPL,T.GOOGL
        ↓
Sent to Polygon: T.AAPL,T.GOOGL
        ↓
Receives: AAPL trades, GOOGL trades
        ↓
Routes to clients based on subscriptions
```

**After (Two-Tier):**
```
Client A: subscribe T.AAPL → Filtered Proxy
Client B: subscribe T.GOOGL → Filtered Proxy
        ↓
Filtered Proxy: subscribes to * from firehose
        ↓
Firehose Proxy: subscribes to T.AAPL,T.GOOGL from Polygon
        ↓
Firehose: receives all data, sends to filtered proxy
        ↓
Filtered Proxy: receives all, filters per-client
        ↓
Client A: receives only AAPL
Client B: receives only GOOGL
```

## Benefits of New Architecture

### ✅ Scalability
- Can run multiple filtered proxies
- Each filtered proxy can handle many clients
- Only one Polygon connection needed

### ✅ Efficiency
- Firehose handles upstream complexity
- Filtered proxy focuses on client filtering
- Reduced Polygon API usage

### ✅ Flexibility
- Easy to add more filtered proxies
- Can implement different filtering strategies
- Clean separation of concerns

## Migration Checklist

If you were using the old single proxy:

- [ ] Start firehose-proxy on port 8767
- [ ] Configure firehose-proxy with your Polygon API key
- [ ] Update client connections to point to filtered-proxy (port 8765)
- [ ] Configure filtered-proxy to connect to firehose (ws://localhost:8767)
- [ ] Test client subscriptions work correctly
- [ ] Monitor logs for both proxies

## Testing the Setup

### 1. Start Firehose Proxy
```bash
cd firehose-proxy
cargo run --release
```

Expected output:
```
INFO Starting Polygon Firehose Proxy
INFO Connecting to Polygon at wss://socket.polygon.io/stocks
INFO Authenticated successfully
```

### 2. Start Filtered Proxy
```bash
cd filtered-proxy
cargo run --release
```

Expected output:
```
INFO Starting Polygon Filtered WebSocket Proxy
INFO Firehose URL: ws://localhost:8767
INFO Connected to firehose proxy
INFO Subscribed to wildcard (*) from firehose
```

### 3. Connect Client
```python
import asyncio
import websockets
import json

async def test():
    ws = await websockets.connect("ws://localhost:8765")

    # Auth
    await ws.send(json.dumps({"action": "auth", "params": "YOUR_API_KEY"}))
    print(await ws.recv())

    # Subscribe
    await ws.send(json.dumps({"action": "subscribe", "params": "T.AAPL"}))

    # Receive data
    while True:
        print(await ws.recv())

asyncio.run(test())
```

## Troubleshooting

### Filtered proxy can't connect to firehose
- **Issue:** `Connection refused`
- **Solution:** Ensure firehose-proxy is running on port 8767

### No data received at client
- **Issue:** Messages not being filtered correctly
- **Solution:** Check filtered-proxy logs, verify subscription format

### Too much data at client
- **Issue:** Client receiving all symbols
- **Solution:** Verify client subscription message format

## Rollback Plan

If you need to go back to single-proxy architecture:

1. Stop both proxies
2. Copy `filtered-proxy/src/` to root `src/`
3. Restore original `upstream.rs` that connects to Polygon
4. Update `config.rs` to remove `firehose_url`
5. Rebuild and run

## Next Steps

- [ ] Add health check endpoints
- [ ] Implement metrics collection
- [ ] Add Docker deployment
- [ ] Create monitoring dashboards
- [ ] Document scaling strategy

## Questions?

See:
- [README.md](README.md) - Architecture overview
- [filtered-proxy/README.md](filtered-proxy/README.md) - Filtered proxy docs
- [PLAN.md](PLAN.md) - Original implementation plan
