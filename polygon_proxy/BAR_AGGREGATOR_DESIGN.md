# Millisecond Bar Aggregator Proxy - Design Document

## Overview

A specialized proxy that generates **millisecond-interval OHLCV bars** (1ms - 60000ms) from trade data in real-time. This fills the gap below Polygon's 1-second aggregates for high-frequency trading and algorithmic applications.

## Scope (Simplified from Alpaca Version)

| What We Do | What We Forward | What We Reject |
|------------|----------------|----------------|
| **1ms - 60000ms** | **A.*** (1-second) | **> 60000ms** |
| Generate from trades | **AM.*** (1-minute) | Use Polygon AM.* |
| 100Ms, 250Ms, 500Ms... | Forward Polygon native | (auto-forward option) |

**Key Principle**: Only generate what Polygon doesn't provide (sub-60-second bars)

## Background: Alpaca Proxy Feature

The Alpaca proxy had a successful implementation of local bar generation that we'll adapt for millisecond intervals only.

### Key Features (Adapted):
- **WebSocket Subscriptions**: `{"action": "subscribe", "bars": ["100Ms.AAPL", "250Ms.SPY"]}`
- **Wildcard Support**: `{"action": "subscribe", "bars": ["500Ms.*"]}` (all symbols)
- **Real-time Aggregation**: Trades → OHLCV bars with configurable delay (20ms default)
- **REST API**: Historical ms-bar generation from trade history
- **Memory efficient**: Stream processing

### Implementation:
- ~300 lines of Rust code (simplified from Alpaca version)
- Trade → Bar aggregation with OHLCV, volume, trade count, VWAP
- Timer-based emission (10ms check interval for ms precision)
- Memory efficient (stream processing)

## Polygon Context

### What Polygon Already Provides (Forward These):
- **A.*** - 1-second aggregates (OHLCV) ✅ Forward directly
- **AM.*** - 1-minute aggregates (OHLCV) ✅ Forward directly

### What We Add (Millisecond Bars Only):
- **100Ms.*** - 100-millisecond bars
- **250Ms.*** - 250-millisecond bars
- **500Ms.*** - 500-millisecond bars
- **1000Ms.*** to **60000Ms.*** - 1 second to 60 seconds (in ms precision)
- **Custom ms intervals**: Any millisecond interval from 1ms to 60000ms

### What We DON'T Do (Use Polygon Native):
- ❌ Intervals > 60 seconds → Use Polygon AM.* (minute bars)
- ❌ Standard second intervals → Use Polygon A.* (1-second bars)
- ❌ Custom multi-minute intervals → Use Polygon AM.* (1-minute bars)

### Interval Ranges:
- **1ms - 999ms**: Sub-second bars (generated)
- **1000ms - 59999ms**: Multi-second bars (generated, up to 59.999 seconds)
- **60000ms+**: Use Polygon's AM.* native minute bars (forwarded)

## Architecture Options

### Option 1: Integrated with Filtered Proxy ❌
```
Polygon → Firehose (8767) → Filtered Proxy (8765) → Clients
                                ↓
                           [Bar Aggregator Module]
```

**Pros:**
- Single component for clients
- Simpler deployment

**Cons:**
- ❌ Violates single responsibility principle
- ❌ Adds complexity to filtered proxy
- ❌ Couples filtering with aggregation
- ❌ Harder to scale independently

### Option 2: Separate Aggregator Proxy (Connected to Firehose) ✅ **RECOMMENDED**
```
Polygon → Firehose (8767) → Filtered Proxy (8765) → Clients
              ↓
          Aggregator Proxy (8768) → Clients (custom bars)
```

**Pros:**
- ✅ Clean separation of concerns
- ✅ Optional component (only deploy if needed)
- ✅ Can scale independently
- ✅ Gets all trade data from firehose
- ✅ Simple architecture

**Cons:**
- Subscribes to all trades (wildcard) from firehose
- May receive more data than needed

### Option 3: Separate Aggregator Proxy (Connected to Filtered) 🤔
```
Polygon → Firehose (8767) → Filtered Proxy (8765) → Clients
                                      ↓
                              Aggregator Proxy (8768) → Clients
```

**Pros:**
- Can filter which symbols to aggregate
- More efficient for specific symbols

**Cons:**
- ⚠️ Extra hop in the chain
- ⚠️ Filtered proxy becomes a hub
- More complex dependency chain

## Recommended Architecture: Option 2

```
┌────────────────────────────────────────────────────────────┐
│                      POLYGON.IO                            │
│              wss://socket.polygon.io/stocks                │
└───────────────────────────┬────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                  Firehose Proxy (8767)                    │
│  - Subscribes to T.*, A.*, AM.*                           │
│  - Broadcasts all data                                    │
└────────────┬────────────────────────┬─────────────────────┘
             │                        │
             ▼                        ▼
┌────────────────────────┐  ┌──────────────────────────────────┐
│ Filtered Proxy (8765)  │  │ Millisecond Aggregator (8768)    │
│ - Filters per-client   │  │ - Subscribes to T.* (trades)     │
│ - Standard data        │  │ - Subscribes to A.* (forwards)   │
│ - T, Q, A, AM, LULD... │  │ - Subscribes to AM.* (forwards)  │
└────────────────────────┘  │ - Generates ms bars (100Ms, etc) │
                            │ - Per-client bar routing         │
                            └──────────────────────────────────┘
```

### Data Flow Examples:

**Example 1: Client wants 250ms AAPL bars (Generated)**

1. Client connects to Ms-Aggregator Proxy (8768)
2. Client subscribes: `{"action": "subscribe", "bars": ["250Ms.AAPL"]}`
3. Aggregator subscribes to `T.AAPL` from Firehose
4. Aggregator receives trades: `[{"ev":"T","sym":"AAPL","p":150.25,...}]`
5. Aggregator builds 250ms bars in memory
6. Every 250ms, aggregator emits: `[{"T":"b","S":"AAPL","o":150.20,"h":150.30,"l":150.15,"c":150.25,"v":1250,...}]`
7. Client receives 250-millisecond bars

**Example 2: Client wants 1-second AAPL bars (Forwarded from Polygon)**

1. Client connects to Ms-Aggregator Proxy (8768)
2. Client subscribes: `{"action": "subscribe", "bars": ["A.AAPL"]}` (or second-level API)
3. Aggregator subscribes to `A.AAPL` from Firehose
4. Aggregator receives Polygon's native 1-sec bars: `[{"ev":"A","sym":"AAPL",...}]`
5. Aggregator forwards directly to client (no aggregation needed)
6. Client receives Polygon's native 1-second bars

**Example 3: Client wants both millisecond and native bars**

1. Client subscribes: `{"action": "subscribe", "bars": ["100Ms.AAPL", "A.AAPL", "AM.AAPL"]}`
2. Aggregator:
   - Subscribes to `T.AAPL` → generates 100ms bars
   - Subscribes to `A.AAPL` → forwards Polygon's 1-sec bars
   - Subscribes to `AM.AAPL` → forwards Polygon's 1-min bars
3. Client receives all three streams efficiently

## Feature Comparison

| Feature | Polygon Native | Ms-Aggregator Proxy |
|---------|---------------|---------------------|
| 1-second bars | ✅ A.* | ✅ A.* (forwarded) |
| 1-minute bars | ✅ AM.* | ✅ AM.* (forwarded) |
| 100ms bars | ❌ | ✅ 100Ms.* (generated) |
| 250ms bars | ❌ | ✅ 250Ms.* (generated) |
| 500ms bars | ❌ | ✅ 500Ms.* (generated) |
| Custom ms intervals | ❌ | ✅ (any ms interval) |
| Wildcard support | ✅ | ✅ |
| Historical data | ✅ REST API | ✅ REST API + cache |

**Key Decision**: Only generate what Polygon doesn't provide (millisecond bars). Forward everything else.

## Implementation Plan

### Phase 1: Core Bar Aggregator
- [ ] Create `aggregator-proxy/` directory
- [ ] Implement `CandleBuilder` module (OHLCV aggregation)
- [ ] Implement `BarSubscriptionManager` (subscription handling)
- [ ] WebSocket connection to Firehose Proxy
- [ ] Real-time bar emission with configurable delay

### Phase 2: WebSocket Subscriptions
- [ ] Parse bar subscription format (`"5Sec.AAPL"`, `"15Min.*"`)
- [ ] Subscribe to required trades from Firehose
- [ ] Route bars to subscribed clients
- [ ] Handle wildcard subscriptions

### Phase 3: REST API (Historical Bars)
- [ ] Endpoint: `/v2/stocks/{symbol}/bars`
- [ ] Fetch historical trades from Polygon REST API
- [ ] Build bars from trade history
- [ ] File-based cache with gzip compression
- [ ] Cache key: symbol + timeframe + date range

### Phase 4: Production Features
- [ ] Adjustment factors (splits/dividends)
- [ ] Multiple feed support (SIP, IEX)
- [ ] Metrics and monitoring
- [ ] Cache cleanup (30-day retention)

## Configuration

### aggregator-proxy/.env
```bash
# Firehose connection
FIREHOSE_URL=ws://localhost:8767
POLYGON_API_KEY=your_api_key_here

# Aggregator settings
AGGREGATOR_PORT=8768
BAR_DELAY_MS=20  # Delay before emitting completed bars
CHECK_INTERVAL_MS=10  # How often to check for completed bars (10ms for ms precision)

# Interval limits
MIN_INTERVAL_MS=1      # Minimum: 1ms
MAX_INTERVAL_MS=60000  # Maximum: 60000ms (60 seconds)
# Above MAX_INTERVAL_MS: Forward to Polygon AM.* (minute bars)

# Cache settings
CACHE_DIR=./cache/bars
CACHE_RETENTION_DAYS=30
MAX_CACHE_SIZE_GB=10

# Limits
MAX_HISTORICAL_HOURS=1  # For millisecond bars
REQUEST_TIMEOUT_SEC=60

# Logging
LOG_LEVEL=info
```

## Client Usage Examples

### WebSocket - Millisecond bars (Generated)
```python
import asyncio
import websockets
import json

async def subscribe_ms_bars():
    async with websockets.connect("ws://localhost:8768") as ws:
        # Authenticate
        await ws.send(json.dumps({
            "action": "auth",
            "params": "YOUR_API_KEY"
        }))
        print(await ws.recv())

        # Subscribe to 100ms and 250ms bars for AAPL
        await ws.send(json.dumps({
            "action": "subscribe",
            "bars": ["100Ms.AAPL", "250Ms.SPY"]
        }))

        # Receive millisecond bars
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print(f"Received bar: {data}")
```

### WebSocket - Mixed millisecond + native bars
```python
# Subscribe to millisecond bars (generated) + native bars (forwarded)
await ws.send(json.dumps({
    "action": "subscribe",
    "bars": ["100Ms.AAPL", "A.AAPL", "AM.AAPL"]
}))

# Receives:
# - 100Ms.AAPL: Generated by aggregator (10 bars/sec)
# - A.AAPL: Forwarded from Polygon (1 bar/sec)
# - AM.AAPL: Forwarded from Polygon (1 bar/min)
```

### WebSocket - Wildcard millisecond bars
```python
# Subscribe to 500ms bars for ALL symbols
await ws.send(json.dumps({
    "action": "subscribe",
    "bars": ["500Ms.*"]
}))

# Receives 500ms bars for every symbol with trades
```

### REST API - Historical 250ms bars
```bash
# Get 250ms bars for AAPL from 9:30 AM to 9:31 AM (1 minute of data)
GET http://localhost:8768/v2/stocks/AAPL/bars?timeframe=250Ms&start=2025-01-10T09:30:00Z&end=2025-01-10T09:31:00Z

# Response (Polygon-compatible format)
{
  "bars": [
    {
      "T": "b",
      "S": "AAPL",
      "o": 150.20,
      "h": 150.25,
      "l": 150.18,
      "c": 150.22,
      "v": 850,
      "t": "2025-01-10T09:30:00.000Z",
      "n": 12,
      "vw": 150.21
    },
    {
      "T": "b",
      "S": "AAPL",
      "o": 150.22,
      "h": 150.28,
      "l": 150.22,
      "c": 150.27,
      "v": 920,
      "t": "2025-01-10T09:30:00.250Z",
      "n": 15,
      "vw": 150.25
    },
    ...
    // 240 bars total (4 per second × 60 seconds)
  ]
}
```

### REST API - Native bars (forwarded to Polygon)
```bash
# Get 1-second bars - forwarded to Polygon's native API
GET http://localhost:8768/v2/stocks/AAPL/bars?timeframe=1Sec&start=2025-01-10T09:30:00Z&end=2025-01-10T10:30:00Z

# Proxy detects "1Sec" is not milliseconds, forwards to Polygon A.* API
# Returns Polygon's native 1-second aggregates
```

### Invalid intervals (rejected)
```bash
# Requesting > 60000ms should be rejected
GET http://localhost:8768/v2/stocks/AAPL/bars?timeframe=120000Ms&...

# Response: 400 Bad Request
{
  "error": "Invalid timeframe",
  "message": "Millisecond intervals must be between 1ms and 60000ms. For longer intervals, use Polygon's native A.* or AM.* bars."
}

# Alternative: Proxy could auto-forward to AM.* for convenience
```

## Performance Characteristics

### Real-time Bars
- **Latency**: ~20-100ms after bar close
- **Memory**: O(symbols × timeframes) - typically < 100MB
- **CPU**: Low (event-driven aggregation)
- **Throughput**: 10,000+ bars/sec

### Historical Bars (REST API)
- **Cache Hit**: ~1ms
- **Cache Miss**:
  - Light trading: 100-500ms
  - Heavy trading: 1-10 seconds
- **Memory**: Bounded by request limits (1 hour max)

## Advantages of Ms-Aggregator Proxy

### Fills the Gap
- **Sub-second precision**: 100ms, 250ms, 500ms bars for HFT/algorithmic trading
- **Polygon doesn't provide**: Nothing below 1-second (A.*)
- **Critical use case**: High-frequency strategies need sub-second bars

### Best of Both Worlds
- **Millisecond bars**: Generated locally (100ms, 250ms, 500ms, etc.)
- **Second/minute bars**: Forwarded from Polygon (A.*, AM.*)
- **Single connection**: Client gets everything from one proxy

### Cost Efficiency
- **Single trade feed**: Reuse T.* data for multiple ms intervals
- **No redundancy**: Forward Polygon's native A.*/AM.* instead of re-aggregating
- **Caching**: Reduce Polygon REST API calls for historical ms-bars

### Features
- **Wildcard support**: `500Ms.*` gets bars for all symbols
- **Real-time WebSocket**: Polygon's A.*/AM.* are only via REST API
- **Combined streams**: Mix ms-bars with native bars in one subscription

## Comparison to Alternatives

### vs. Using only Polygon A.* (1-second)
- ❌ Not enough precision for HFT (need < 1 second)
- ✅ Native support, no aggregation
- ❌ Can't get 100ms or 250ms bars

### vs. Aggregating in client application
- ❌ Each client must implement complex aggregation logic
- ❌ Each client receives full T.* stream (wasteful bandwidth)
- ❌ Duplicated work across multiple clients
- ✅ No additional infrastructure needed

### vs. Ms-Aggregator Proxy ✅
- ✅ Centralized aggregation (write once, use everywhere)
- ✅ Efficient (clients only get bars they subscribe to)
- ✅ Sub-second bars (100ms, 250ms, 500ms, etc.)
- ✅ Historical data with caching
- ✅ Forwards native A.*/AM.* (doesn't duplicate Polygon's work)

## Roadmap

### MVP (Week 1-2)
- [x] Research Alpaca proxy implementation
- [ ] Core bar aggregation logic
- [ ] WebSocket subscriptions
- [ ] Connect to Firehose Proxy
- [ ] Basic testing

### v1.0 (Week 3-4)
- [ ] REST API for historical bars
- [ ] File-based caching
- [ ] Wildcard subscriptions
- [ ] Documentation

### v2.0 (Future)
- [ ] Adjustment factors (splits/dividends)
- [ ] Redis cache for distributed deployment
- [ ] Pre-calculation for popular symbols
- [ ] Compression for bandwidth optimization

## Related Work

- **Alpaca Proxy**: `/home/ubuntu/code/alpaca_proxy/SUB_MINUTE_BARS_DESIGN.md`
- **Alpaca Implementation**: `/home/ubuntu/code/alpaca_proxy/src/websocket/bar_subscription_manager.rs`
- **Polygon Proxy**: Current firehose + filtered architecture

## Conclusion

**Recommendation: Build as separate Millisecond Bar Aggregator Proxy**

This approach provides:
- ✅ **Clean architecture**: Separate component, independent of filtered proxy
- ✅ **Optional deployment**: Only needed for sub-60-second bar intervals
- ✅ **Focused scope**: Only ms bars (1ms - 60000ms), forward everything else
- ✅ **No redundancy**: Uses Polygon's native A.* and AM.* instead of duplicating
- ✅ **Proven design**: Adapts successful Alpaca proxy implementation
- ✅ **High-value feature**: Fills critical gap for HFT/algorithmic trading

### Implementation Scope:
- **Core aggregation**: ~200-300 lines (simplified from Alpaca version)
- **WebSocket integration**: Reuse existing patterns
- **Timeline**: 1 week for MVP (WebSocket only)

### Key Design Decisions:
1. **Only generate millisecond bars** (1ms - 60000ms)
2. **Forward Polygon native bars** for seconds (A.*) and minutes (AM.*)
3. **10ms timer precision** for accurate millisecond bar emission
4. **20ms delay** before emitting completed bars (catch late trades)
5. **Separate component** connected to Firehose (not integrated into filtered proxy)

This focused approach provides maximum value with minimal complexity.
