# Alpaca Trading Updates Proxy

A minimal, lightweight WebSocket proxy that multiplexes Alpaca's trading updates stream to unlimited clients.

## Features

- ✅ **Paper & Live Trading** - Separate endpoints for paper and live accounts
- ✅ **Multi-client Support** - Unlimited concurrent connections
- ✅ **Auto-reconnection** - Exponential backoff reconnection to Alpaca
- ✅ **Zero Configuration** - No subscriptions needed, automatically streams all trading events
- ✅ **Lightweight** - Single binary, ~300 lines of code, minimal dependencies

## Quick Start

### 1. Configure

Copy `.env.example` to `.env` and add your Alpaca credentials:

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Build

```bash
cargo build --release
```

### 3. Run

```bash
cargo run --release
```

Or run the binary directly:

```bash
./target/release/trade-updates-proxy
```

## Usage

### Connect to Paper Trading

```python
import asyncio
import json
import websockets

async def stream_trading_updates():
    url = "ws://localhost:8099/trade-updates-paper"

    async with websockets.connect(url) as ws:
        # Authenticate (proxy accepts any credentials)
        await ws.send(json.dumps({"action": "auth", "key": "any", "secret": "any"}))
        auth_response = await ws.recv()
        print(f"Auth: {auth_response}")

        # Receive trading updates
        while True:
            message = await ws.recv()
            data = json.loads(message)
            print(f"Update: {data}")

asyncio.run(stream_trading_updates())
```

### Connect to Live Trading

```python
url = "ws://localhost:8099/trade-updates-live"  # Requires live credentials in .env
```

## Endpoints

| Endpoint | Description | Requirements |
|----------|-------------|--------------|
| `ws://localhost:8099/trade-updates-paper` | Paper trading updates | ALPACA_API_KEY, ALPACA_SECRET_KEY |
| `ws://localhost:8099/trade-updates-live` | Live trading updates | ALPACA_LIVE_API_KEY, ALPACA_LIVE_SECRET_KEY |

## Trading Update Events

The proxy streams all trading events automatically after authentication:

- **Order Placed** - New order created
- **Order Filled** - Order executed (partial or complete)
- **Order Cancelled** - Order cancelled
- **Order Expired** - Order expired
- **Order Rejected** - Order rejected by exchange

### Example Message

```json
{
  "stream": "trade_updates",
  "data": {
    "event": "fill",
    "order": {
      "id": "...",
      "symbol": "AAPL",
      "side": "buy",
      "qty": "10",
      "filled_qty": "10",
      "filled_avg_price": "150.25",
      "status": "filled",
      ...
    }
  }
}
```

## Configuration

Environment variables:

- `ALPACA_API_KEY` - Your Alpaca API key (paper)
- `ALPACA_SECRET_KEY` - Your Alpaca secret key (paper)
- `ALPACA_LIVE_API_KEY` - Optional: Live trading API key
- `ALPACA_LIVE_SECRET_KEY` - Optional: Live trading secret key
- `PROXY_PORT` - WebSocket port (default: 8099)

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌────────────┐
│   Client 1  │────────▶│              │         │            │
├─────────────┤         │   Minimal    │◀───────▶│  Alpaca    │
│   Client 2  │────────▶│    Proxy     │         │  Trading   │
├─────────────┤         │              │         │   API      │
│   Client N  │────────▶│              │         │            │
└─────────────┘         └──────────────┘         └────────────┘
```

**Key differences from full alpaca_proxy:**
- No subscription management (trading updates stream everything)
- No bar generation or candle building
- No symbol-based routing
- No REST API
- No feed multiplexing (only trading updates)

## Why This Proxy?

Alpaca allows only **one WebSocket connection per account** for trading updates. This proxy:

1. Maintains a single upstream connection to Alpaca
2. Accepts unlimited client connections
3. Broadcasts all trading events to all connected clients
4. Handles reconnection automatically

Perfect for:
- Multi-strategy trading systems
- Monitoring multiple algorithms
- Development/testing environments
- Dashboard + trading bot simultaneously

## Comparison

| Feature | Full Proxy | Minimal Proxy |
|---------|------------|---------------|
| Market Data | ✅ | ❌ |
| Bar Generation | ✅ | ❌ |
| Trading Updates | ✅ | ✅ |
| REST API | ✅ | ❌ |
| Binary Size | ~15 MB | ~5 MB |
| Lines of Code | ~3000 | ~300 |
| Memory Usage | ~50 MB | ~10 MB |

## License

MIT
