# Fake Data Generator Implementation Plan for Polygon Proxy

## Overview
Implement a fake data generator for the Polygon WebSocket proxy, based on the successful implementation in the Alpaca WS proxy. This will enable testing and development without consuming live Polygon API resources.

## Reference Implementation
The Alpaca WS proxy (`/home/ubuntu/code/alpaca_proxy`) has a working fake data generator with these key features:
- Generates realistic trade data for a special symbol (FAKETICKER)
- Only generates data when there are active subscribers (resource-efficient)
- Integrates seamlessly with existing routing infrastructure
- Uses oscillating price patterns for realistic testing
- Can be started/stopped dynamically

## Architecture Analysis

### Alpaca Proxy Architecture (Reference)
```
┌─────────────────────────────────────────────────────────────┐
│ Main (websocket.rs)                                         │
│  ├─ UpstreamConnection (real data) ──┐                      │
│  ├─ FakeDataGenerator (test data) ───┼─→ mpsc::channel ─→   │
│  └─ Router ←─────────────────────────┘                      │
│     └─ Routes to Clients based on subscriptions             │
└─────────────────────────────────────────────────────────────┘
```

**Key Components:**
1. **FakeDataGenerator** - Generates fake trade messages
2. **Router callback** - Checks if symbol has subscribers
3. **Shared message channel** - Fake & real data use same channel
4. **Timer-based generation** - 100ms interval for continuous data

### Polygon Proxy Current Architecture
```
┌─────────────────────────────────────────────────────────────┐
│ Main (main.rs)                                              │
│  ├─ UpstreamConnection ──┐                                  │
│  │   └─ Receives from upstream_tx channel                   │
│  └─ Router ←─────────────┘                                  │
│     ├─ Uses SubscriptionManager                             │
│     └─ Routes to Clients                                    │
└─────────────────────────────────────────────────────────────┘
```

**Current Flow:**
1. UpstreamConnection sends messages via `upstream_tx` channel
2. Main loop receives from `upstream_rx` channel
3. Router routes messages to subscribed clients
4. SubscriptionManager tracks who's subscribed to what

## Implementation Plan

### Phase 1: Core Fake Data Generator Module

#### File: `src/fake_data_generator.rs`

**Purpose:** Generate realistic Polygon-format trade/quote/aggregate data for testing

**Features:**
- Generate data for special symbol(s): `FAKETICKER`, `TESTSTOCK`, etc.
- Support multiple Polygon message types:
  - **T** - Trades (most important for initial implementation)
  - **Q** - Quotes (NBBO)
  - **A** - Per-second aggregates
  - **AM** - Per-minute aggregates
- Only generate when subscribers exist (efficiency)
- Start/stop capability
- Configurable generation rate

**Key Struct:**
```rust
pub struct FakeDataGenerator {
    tx: mpsc::Sender<String>,  // Send to upstream_rx (same as real data)
    running: Arc<AtomicBool>,
    trade_counter: Arc<AtomicU64>,
    check_subscribers: Arc<dyn Fn(&str) -> bool + Send + Sync>,
    config: FakeDataConfig,
}
```

**Configuration:**
```rust
pub struct FakeDataConfig {
    pub symbols: Vec<String>,           // Which symbols to generate
    pub enabled_types: Vec<MessageType>, // T, Q, A, AM
    pub interval_ms: u64,                // Generation interval (default: 100ms)
    pub base_price: f64,                 // Starting price (default: 100.0)
    pub price_amplitude: f64,            // Price oscillation (default: 5.0)
    pub price_period_secs: f64,          // Sine wave period (default: 10.0)
}
```

**Message Generation Examples:**

1. **Trade Message (T):**
```json
{
  "ev": "T",
  "sym": "FAKETICKER",
  "x": 4,           // Exchange ID (random)
  "p": 102.45,      // Price (oscillating)
  "s": 250,         // Size (random 100-500)
  "t": 1704067200000,  // Timestamp (nanoseconds)
  "c": [14, 37]     // Conditions (random)
}
```

2. **Quote Message (Q):**
```json
{
  "ev": "Q",
  "sym": "FAKETICKER",
  "bx": 4,          // Bid exchange
  "bp": 102.40,     // Bid price
  "bs": 100,        // Bid size
  "ax": 7,          // Ask exchange
  "ap": 102.50,     // Ask price
  "as": 150,        // Ask size
  "t": 1704067200000
}
```

3. **Aggregate Message (A - per second):**
```json
{
  "ev": "A",
  "sym": "FAKETICKER",
  "v": 5200,        // Volume
  "av": 125000,     // Accumulated volume
  "op": 102.00,     // Official opening price
  "vw": 102.35,     // VWAP
  "o": 102.30,      // Open
  "c": 102.45,      // Close
  "h": 102.50,      // High
  "l": 102.25,      // Low
  "a": 102.37,      // Average
  "z": 104,         // Average trade size
  "s": 1704067200000,  // Start timestamp
  "e": 1704067201000   // End timestamp
}
```

### Phase 2: Integration with Main Application

#### Changes to `src/main.rs`

**Add after upstream connection setup:**
```rust
// Create fake data generator (if enabled)
if config.enable_fake_data {
    let subscriptions_for_fake = subscriptions.clone();
    let check_subscribers = Arc::new(move |symbol: &str| -> bool {
        // Check if anyone is subscribed to this symbol
        let subs = subscriptions_for_fake.blocking_lock();
        subs.has_symbol_subscribers(symbol)
    });

    let fake_config = FakeDataConfig {
        symbols: config.fake_data_symbols.clone(),
        enabled_types: vec![MessageType::Trade, MessageType::Quote, MessageType::Aggregate],
        interval_ms: 100,
        base_price: 100.0,
        price_amplitude: 5.0,
        price_period_secs: 10.0,
    };

    let fake_generator = FakeDataGenerator::new(
        upstream_tx.clone(),  // Same channel as real data!
        check_subscribers,
        fake_config,
    );

    tokio::spawn(async move {
        fake_generator.start().await;
    });

    info!("Fake data generator started for symbols: {:?}", config.fake_data_symbols);
}
```

### Phase 3: Configuration Updates

#### Changes to `src/config.rs`

**Add fields:**
```rust
pub struct Config {
    // ... existing fields ...

    // Fake data configuration
    pub enable_fake_data: bool,
    pub fake_data_symbols: Vec<String>,
    pub fake_data_interval_ms: u64,
}
```

**Add to `from_env()`:**
```rust
let enable_fake_data = env::var("ENABLE_FAKE_DATA")
    .unwrap_or_else(|_| "false".to_string())
    .parse()
    .unwrap_or(false);

let fake_data_symbols = env::var("FAKE_DATA_SYMBOLS")
    .unwrap_or_else(|_| "FAKETICKER,TESTSTOCK".to_string())
    .split(',')
    .map(|s| s.trim().to_string())
    .collect();

let fake_data_interval_ms = env::var("FAKE_DATA_INTERVAL_MS")
    .unwrap_or_else(|_| "100".to_string())
    .parse()
    .unwrap_or(100);
```

#### Update `.env.example`

Add:
```bash
# Fake Data Generator (for testing/development)
ENABLE_FAKE_DATA=false              # Enable fake data generation
FAKE_DATA_SYMBOLS=FAKETICKER,TESTSTOCK  # Symbols to generate data for
FAKE_DATA_INTERVAL_MS=100           # Generation interval in milliseconds
```

### Phase 4: Subscription Manager Enhancement

#### Changes to `src/subscription_manager.rs`

**Add method to check if symbol has subscribers:**
```rust
impl SubscriptionManager {
    // ... existing methods ...

    /// Check if any clients are subscribed to a specific symbol
    pub fn has_symbol_subscribers(&self, symbol: &str) -> bool {
        // Check wildcard subscribers
        if !self.wildcard_clients.is_empty() {
            return true;
        }

        // Check specific symbol subscribers
        self.symbol_to_clients
            .get(symbol)
            .map(|clients| !clients.is_empty())
            .unwrap_or(false)
    }
}
```

### Phase 5: Message Type Definitions

#### Update `src/types.rs`

**Add message type enum:**
```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageType {
    Trade,      // T
    Quote,      // Q
    Aggregate,  // A (per second)
    AggregateMin, // AM (per minute)
    Status,     // status messages
}

impl MessageType {
    pub fn code(&self) -> &str {
        match self {
            Self::Trade => "T",
            Self::Quote => "Q",
            Self::Aggregate => "A",
            Self::AggregateMin => "AM",
            Self::Status => "status",
        }
    }
}
```

## Implementation Details

### Data Generation Patterns

#### 1. **Price Generation (Sine Wave with Noise)**
```rust
fn generate_price(&self, seconds_elapsed: f64) -> f64 {
    let base_oscillation = self.config.price_amplitude
        * (seconds_elapsed / self.config.price_period_secs).sin();

    let noise = fastrand::f64() * 0.5 - 0.25; // ±0.25

    self.config.base_price + base_oscillation + noise
}
```

#### 2. **Volume Generation (Random with Distribution)**
```rust
fn generate_volume(&self) -> u64 {
    // Most trades are small, occasional large ones
    let r = fastrand::f64();
    if r < 0.8 {
        100 + fastrand::u64(..400)  // 100-500 shares (80% of trades)
    } else if r < 0.95 {
        500 + fastrand::u64(..2000) // 500-2500 shares (15% of trades)
    } else {
        2500 + fastrand::u64(..10000) // Large trades (5% of trades)
    }
}
```

#### 3. **Quote Spread Generation**
```rust
fn generate_quote(&self, mid_price: f64) -> (f64, f64) {
    // Typical spread: 1-5 cents
    let spread = 0.01 + fastrand::f64() * 0.04;
    let bid = mid_price - spread / 2.0;
    let ask = mid_price + spread / 2.0;
    (bid, ask)
}
```

### Performance Considerations

1. **Resource Efficiency:**
   - Only generate when subscribers exist
   - Configurable generation rate
   - Use Arc for shared state (cheap cloning)

2. **Message Format:**
   - Generate JSON once and reuse
   - Use serde_json for serialization
   - Match exact Polygon format

3. **Timing:**
   - Use `tokio::time::interval` for consistent intervals
   - Don't block other tasks
   - Spawn as separate async task

### Testing Strategy

#### Unit Tests (`src/fake_data_generator.rs`)
```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_generates_valid_trade_json() {
        // Test that generated trade messages are valid JSON
        // and contain all required Polygon fields
    }

    #[tokio::test]
    async fn test_price_oscillation() {
        // Test that prices oscillate within expected range
    }

    #[tokio::test]
    async fn test_stops_when_no_subscribers() {
        // Test that generation pauses when no subscribers
    }

    #[tokio::test]
    async fn test_multiple_symbols() {
        // Test generating data for multiple symbols
    }
}
```

#### Integration Tests (`tests/fake_data_integration.rs`)
```rust
#[tokio::test]
async fn test_fake_data_routing() {
    // Connect client to proxy
    // Subscribe to FAKETICKER
    // Verify messages are received
    // Verify message format matches Polygon
}

#[tokio::test]
async fn test_fake_and_real_data_mix() {
    // Subscribe to both real and fake symbols
    // Verify both types of data are received
    // Verify no cross-contamination
}
```

## Advanced Features (Future Enhancements)

### 1. **Scenario-Based Generation**
```rust
pub enum Scenario {
    Normal,           // Standard trading patterns
    HighVolatility,   // Large price swings
    LowLiquidity,     // Infrequent trades
    GapUp,           // Price jumps up
    GapDown,         // Price jumps down
    TradingHalt,     // No trades for period
}
```

### 2. **Market Hours Simulation**
```rust
fn should_generate(&self) -> bool {
    let now = Utc::now();
    let hour = now.hour();

    // Only generate during market hours (9:30 AM - 4:00 PM ET)
    if self.config.respect_market_hours {
        hour >= 9 && hour < 16
    } else {
        true
    }
}
```

### 3. **Correlation Between Message Types**
- Trades should influence quotes
- Aggregates should reflect trade data
- Consistent price movement across message types

### 4. **Multiple Symbol Support with Different Behaviors**
```rust
pub struct SymbolBehavior {
    pub symbol: String,
    pub base_price: f64,
    pub volatility: f64,    // Higher = more price movement
    pub liquidity: f64,     // Higher = more trades
    pub correlation: Option<String>, // Correlate with another symbol
}
```

## File Structure

After implementation:
```
polygon_proxy/
├── src/
│   ├── main.rs                    # Modified: integrate fake generator
│   ├── config.rs                  # Modified: add fake data config
│   ├── types.rs                   # Modified: add MessageType enum
│   ├── subscription_manager.rs    # Modified: add has_symbol_subscribers()
│   ├── fake_data_generator.rs     # NEW: core generator logic
│   └── test/                      # NEW: test utilities
│       ├── mod.rs
│       ├── scenarios.rs           # Test scenarios
│       └── symbol_behavior.rs     # Symbol behavior configs
├── tests/
│   └── fake_data_integration.rs   # NEW: integration tests
└── .env.example                   # Modified: add fake data vars
```

## Implementation Checklist

### Phase 1: Core Generator (Week 1)
- [ ] Create `src/fake_data_generator.rs`
- [ ] Implement `FakeDataGenerator` struct
- [ ] Implement trade message generation
- [ ] Implement quote message generation
- [ ] Implement aggregate message generation
- [ ] Add subscriber checking logic
- [ ] Add start/stop functionality
- [ ] Write unit tests

### Phase 2: Integration (Week 1-2)
- [ ] Update `src/config.rs` with fake data settings
- [ ] Update `src/main.rs` to initialize generator
- [ ] Update `src/subscription_manager.rs` with helper method
- [ ] Update `src/types.rs` with MessageType enum
- [ ] Update `.env.example` with configuration examples
- [ ] Test integration with existing proxy

### Phase 3: Testing (Week 2)
- [ ] Write integration tests
- [ ] Test with Python client script
- [ ] Test subscription/unsubscription behavior
- [ ] Test multiple concurrent clients
- [ ] Verify message format compatibility
- [ ] Performance testing (memory, CPU)

### Phase 4: Documentation (Week 2)
- [ ] Update README with fake data usage
- [ ] Add examples of using fake data
- [ ] Document configuration options
- [ ] Create troubleshooting guide

## Success Criteria

1. **Functional:**
   - ✅ Generates valid Polygon-format messages
   - ✅ Only generates when subscribers exist
   - ✅ Can be enabled/disabled via config
   - ✅ Works seamlessly with real data
   - ✅ Multiple clients can subscribe independently

2. **Performance:**
   - ✅ Minimal CPU usage when no subscribers
   - ✅ Handles 100+ concurrent fake symbol subscriptions
   - ✅ No impact on real data routing performance

3. **Quality:**
   - ✅ Realistic price movements
   - ✅ Consistent timestamps
   - ✅ Proper JSON formatting
   - ✅ All unit tests passing
   - ✅ Integration tests passing

## Example Usage

### Enable Fake Data
```bash
# In .env file
ENABLE_FAKE_DATA=true
FAKE_DATA_SYMBOLS=FAKETICKER,TESTSTOCK,DEMOTICKER
FAKE_DATA_INTERVAL_MS=100
```

### Connect and Subscribe
```python
import asyncio
import websockets
import json

async def test_fake_data():
    async with websockets.connect("ws://localhost:8765") as ws:
        # Auth
        await ws.send(json.dumps({"action": "auth", "params": "YOUR_API_KEY"}))
        print(await ws.recv())

        # Subscribe to fake ticker
        await ws.send(json.dumps({
            "action": "subscribe",
            "params": "T.FAKETICKER,Q.FAKETICKER,A.FAKETICKER"
        }))

        # Receive data
        for _ in range(10):
            msg = await ws.recv()
            data = json.loads(msg)
            print(f"Received: {data}")

asyncio.run(test_fake_data())
```

Expected output:
```json
[{"ev":"T","sym":"FAKETICKER","x":4,"p":102.45,"s":250,"t":1704067200000,"c":[14,37]}]
[{"ev":"Q","sym":"FAKETICKER","bx":4,"bp":102.40,"bs":100,"ax":7,"ap":102.50,"as":150,"t":1704067200050}]
[{"ev":"A","sym":"FAKETICKER","v":5200,"av":125000,"op":102.00,"vw":102.35,"o":102.30,"c":102.45,"h":102.50,"l":102.25,"a":102.37,"z":104,"s":1704067200000,"e":1704067201000}]
```

## Comparison: Alpaca vs Polygon Implementation

| Aspect | Alpaca Proxy | Polygon Proxy (Planned) |
|--------|--------------|-------------------------|
| **Symbol** | FAKETICKER | FAKETICKER, TESTSTOCK, etc. |
| **Message Types** | Trade only | Trade, Quote, Aggregate |
| **Message Format** | `{"T":"t","S":"..."}` | `{"ev":"T","sym":"..."}` |
| **Channel** | `(FeedType, RawMessage)` | `String` (raw JSON) |
| **Subscriber Check** | Via Router callback | Via SubscriptionManager |
| **Configuration** | Hardcoded | Environment variables |
| **Generation Rate** | 100ms (1-2 messages) | Configurable (default 100ms) |

## Key Differences from Alpaca Implementation

1. **Message Format:**
   - Alpaca: Uses `T` and `S` fields, wraps in array
   - Polygon: Uses `ev` and `sym` fields, different structure

2. **Channel Type:**
   - Alpaca: Typed channel with `(FeedType, RawMessage)`
   - Polygon: String channel with raw JSON

3. **Routing:**
   - Alpaca: Router has sophisticated feed-based routing
   - Polygon: Simpler symbol-based routing

4. **Subscription Checking:**
   - Alpaca: Router's `has_subscribers()` method
   - Polygon: SubscriptionManager's method (to be added)

## References

- Alpaca Proxy: `/home/ubuntu/code/alpaca_proxy/src/websocket/fake_data_generator.rs`
- Polygon WebSocket API: https://polygon.io/docs/stocks/ws_getting-started
- Current Polygon Proxy: `/home/ubuntu/code/polygon_proxy/`

## Notes

- The fake data generator will run in its own async task
- It uses the same message channel as the upstream connection
- The router doesn't need to know whether data is real or fake
- All existing subscription logic works without modification
- Can be enabled/disabled without code changes via environment variables
