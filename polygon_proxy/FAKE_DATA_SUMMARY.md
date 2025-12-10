# Fake Data Generator - Quick Summary

## What is it?
A test data generator that creates realistic Polygon-format market data without consuming API resources. Based on the proven implementation in the Alpaca WS proxy.

## How the Alpaca Proxy Does It

### Key Architecture
```
Upstream Connection  ─┐
                      ├──→ mpsc::channel ──→ Router ──→ Clients
Fake Data Generator ──┘
```

**Both real and fake data flow through the same channel!**

### Core Components

1. **FakeDataGenerator** (`alpaca_proxy/src/websocket/fake_data_generator.rs`)
   - Generates data for "FAKETICKER" symbol
   - Only when there are subscribers (efficient)
   - 100ms interval with 1-2 trades per tick
   - Oscillating prices using sine wave: `base_price + amplitude * sin(time / period)`
   - Random volumes: 100-500 shares

2. **Integration** (`alpaca_proxy/src/bin/websocket.rs`)
   ```rust
   // Create channel (line 27)
   let (tx, mut rx) = mpsc::channel::<(FeedType, RawMessage)>(1000);

   // Start fake generator (line 88)
   let fake_generator = Arc::new(FakeDataGenerator::new(
       tx.clone(),  // Same channel!
       check_subscribers
   ));
   fake_gen.start().await;

   // Router receives both real and fake (line 106)
   while let Some((feed, message)) = rx.recv().await {
       message_router.route_message(feed, message).await;
   }
   ```

3. **Subscriber Check** (line 84-86)
   ```rust
   let check_subscribers = Arc::new(move |symbol: &str| -> bool {
       router_for_fake.has_subscribers(symbol)
   });
   ```

## How to Implement in Polygon Proxy

### Step 1: Create Fake Data Generator
**New file:** `src/fake_data_generator.rs`

```rust
pub struct FakeDataGenerator {
    tx: mpsc::Sender<String>,  // Send JSON strings (Polygon format)
    running: Arc<AtomicBool>,
    check_subscribers: Arc<dyn Fn(&str) -> bool + Send + Sync>,
}

impl FakeDataGenerator {
    pub async fn start(&self) {
        let mut ticker = interval(Duration::from_millis(100));
        while self.running.load(Ordering::Relaxed) {
            ticker.tick().await;

            if !self.check_subscribers("FAKETICKER") {
                continue;  // Skip if no subscribers
            }

            // Generate Polygon-format trade
            let trade = json!({
                "ev": "T",
                "sym": "FAKETICKER",
                "p": self.generate_price(),
                "s": self.generate_volume(),
                "t": Utc::now().timestamp_nanos(),
                "x": 4,
                "c": [14, 37]
            });

            let _ = self.tx.send(trade.to_string()).await;
        }
    }
}
```

### Step 2: Integrate in Main
**Modify:** `src/main.rs`

```rust
async fn start_cluster_proxy(cluster: Cluster, config: Config) -> Result<()> {
    // ... existing setup ...

    let (upstream_tx, mut upstream_rx) = mpsc::channel(100);

    // NEW: Create fake data generator
    if config.enable_fake_data {
        let subs_clone = subscriptions.clone();
        let check_subscribers = Arc::new(move |symbol: &str| -> bool {
            subs_clone.blocking_lock().has_symbol_subscribers(symbol)
        });

        let fake_gen = FakeDataGenerator::new(
            upstream_tx.clone(),  // Same channel as real data!
            check_subscribers,
        );

        tokio::spawn(async move {
            fake_gen.start().await;
        });
    }

    // Router receives both real and fake data
    while let Some(message) = upstream_rx.recv().await {
        router.route_message(message).await;
    }

    Ok(())
}
```

### Step 3: Add Configuration
**Modify:** `src/config.rs`

```rust
pub struct Config {
    // ... existing ...
    pub enable_fake_data: bool,
    pub fake_data_symbols: Vec<String>,
}

// In from_env():
let enable_fake_data = env::var("ENABLE_FAKE_DATA")
    .unwrap_or("false".to_string())
    .parse()
    .unwrap_or(false);
```

**Add to `.env`:**
```bash
ENABLE_FAKE_DATA=true
FAKE_DATA_SYMBOLS=FAKETICKER,TESTSTOCK
```

### Step 4: Add Subscriber Check
**Modify:** `src/subscription_manager.rs`

```rust
impl SubscriptionManager {
    pub fn has_symbol_subscribers(&self, symbol: &str) -> bool {
        // Check wildcard
        if !self.wildcard_clients.is_empty() {
            return true;
        }
        // Check specific symbol
        self.symbol_to_clients
            .get(symbol)
            .map(|clients| !clients.is_empty())
            .unwrap_or(false)
    }
}
```

## Key Insights from Alpaca Implementation

### ✅ What Works Well

1. **Same Channel Pattern**
   - Real and fake data use the same `mpsc::channel`
   - Router doesn't know/care if data is real or fake
   - No special routing logic needed

2. **Subscriber-Based Generation**
   - Only generates when `check_subscribers()` returns true
   - Saves CPU when no one is listening
   - Simple callback pattern

3. **Separate Async Task**
   - Runs in own `tokio::spawn()`
   - Doesn't block other operations
   - Uses `tokio::time::interval()` for timing

4. **Arc for Sharing**
   - Uses `Arc<AtomicBool>` for running state
   - Uses `Arc<dyn Fn>` for subscriber check
   - Cheap to clone, thread-safe

### 🎯 Critical Design Decisions

1. **Message Format**
   - Alpaca: `{"T":"t", "S":"FAKETICKER", "p":102.45, ...}`
   - Polygon: `{"ev":"T", "sym":"FAKETICKER", "p":102.45, ...}`
   - Just change the field names!

2. **Channel Integration**
   ```rust
   // Alpaca uses typed channel
   mpsc::Sender<(FeedType, RawMessage)>

   // Polygon uses string channel
   mpsc::Sender<String>

   // Solution: Send JSON string directly!
   tx.send(json!({...}).to_string()).await
   ```

3. **Subscriber Callback**
   ```rust
   // Alpaca: Router method
   router.has_subscribers(symbol)

   // Polygon: SubscriptionManager method (to add)
   subscription_manager.has_symbol_subscribers(symbol)
   ```

## Message Format Comparison

### Alpaca Trade Message
```json
{
  "T": "t",
  "S": "FAKETICKER",
  "p": "102.45",
  "s": 250,
  "t": "2024-01-01T12:00:00.123456789Z",
  "i": 12345,
  "x": "FAKE",
  "z": "A",
  "c": null
}
```

### Polygon Trade Message (to generate)
```json
{
  "ev": "T",
  "sym": "FAKETICKER",
  "p": 102.45,
  "s": 250,
  "t": 1704110400123456789,
  "x": 4,
  "c": [14, 37]
}
```

## Testing Strategy

### 1. Unit Test (Generator)
```rust
#[tokio::test]
async fn test_generates_valid_polygon_format() {
    let (tx, mut rx) = mpsc::channel(10);
    let check = Arc::new(|_: &str| true);
    let gen = FakeDataGenerator::new(tx, check);

    gen.start().await;

    let msg = rx.recv().await.unwrap();
    let data: serde_json::Value = serde_json::from_str(&msg).unwrap();

    assert_eq!(data["ev"], "T");
    assert_eq!(data["sym"], "FAKETICKER");
    assert!(data["p"].is_number());
}
```

### 2. Integration Test (End-to-End)
```python
import asyncio
import websockets
import json

async def test():
    ws = await websockets.connect("ws://localhost:8765")

    # Auth
    await ws.send(json.dumps({"action": "auth", "params": "test"}))
    print(await ws.recv())

    # Subscribe to fake ticker
    await ws.send(json.dumps({"action": "subscribe", "params": "T.FAKETICKER"}))

    # Should receive fake trades
    for i in range(5):
        msg = json.loads(await ws.recv())
        print(f"Trade {i}: {msg}")
        assert msg[0]['sym'] == 'FAKETICKER'

asyncio.run(test())
```

## File Checklist

- [ ] `src/fake_data_generator.rs` - NEW
- [ ] `src/main.rs` - MODIFY (add fake generator)
- [ ] `src/config.rs` - MODIFY (add enable_fake_data)
- [ ] `src/subscription_manager.rs` - MODIFY (add has_symbol_subscribers)
- [ ] `.env.example` - MODIFY (add ENABLE_FAKE_DATA)
- [ ] `tests/fake_data_test.rs` - NEW
- [ ] `Cargo.toml` - MODIFY (add fastrand for randomness)

## Estimated Effort
- **Core Implementation:** 4-6 hours
- **Testing:** 2-3 hours
- **Documentation:** 1-2 hours
- **Total:** ~1 day

## Next Steps

1. Review this plan
2. Start with `fake_data_generator.rs` (use Alpaca version as template)
3. Add config support
4. Integrate in main.rs
5. Test with Python client
6. Document usage

## Reference Files
- Alpaca fake generator: `/home/ubuntu/code/alpaca_proxy/src/websocket/fake_data_generator.rs`
- Alpaca integration: `/home/ubuntu/code/alpaca_proxy/src/bin/websocket.rs`
- Polygon proxy main: `/home/ubuntu/code/polygon_proxy/src/main.rs`
