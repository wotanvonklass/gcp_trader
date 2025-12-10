# Polygon WebSocket Proxy Implementation Plan

## Overview
Create a transparent WebSocket proxy server for Polygon.io stocks real-time data feed that:
1. Overcomes connection limitations by multiplexing a single upstream connection to multiple clients
2. Provides complete WebSocket API compatibility as a drop-in replacement
3. Enables test data injection for development/testing

## Architecture

### Key Design Principle
A single proxy endpoint that multiplexes connections to the Polygon stocks feed.

```
Client Applications          Proxy Server              Polygon.io
─────────────────           ─────────────            ───────────

Multiple Stock Clients  →   :8765 (stocks)    →     wss://socket.polygon.io/stocks
```

The proxy endpoint:
- Maintains ONE upstream connection to Polygon stocks endpoint
- Accepts MULTIPLE client connections
- Routes messages to subscribed clients

## Architecture Comparison

### Polygon vs Alpaca WebSocket Differences

| Feature | Alpaca | Polygon |
|---------|---------|---------|
| WebSocket Endpoints | Multiple endpoints (IEX, SIP, etc.) | Single endpoint with clusters |
| Authentication | API Key + Secret in message | API Key in URL query param or message |
| Message Format | JSON only | JSON |
| Subscription Model | Per-feed subscriptions | Single connection, multi-cluster |
| Connection Limit | 1 per feed type | Varies by plan (typically 1-4) |
| Clusters | N/A | stocks, options, forex, crypto |

### Polygon WebSocket Architecture

**Polygon WebSocket URL:**
```
wss://socket.polygon.io/stocks    # Stocks feed
```

**Authentication:**
```json
{"action": "auth", "params": "YOUR_API_KEY"}
```

**Subscription Format:**
```json
{
  "action": "subscribe",
  "params": "T.AAPL,Q.AAPL,A.AAPL"  // Format: TYPE.SYMBOL
}
```

**Message Types:**
- `T.*` - Trades (tick-level trade data with price, size, exchange, conditions)
- `Q.*` - Quotes (NBBO - National Best Bid and Offer)
- `A.*` - Aggregates (Per Second - second-by-second OHLC and volume)
- `AM.*` - Aggregates (Per Minute - minute-by-minute OHLC and volume)
- `LULD.*` - Limit Up Limit Down (volatility safeguards and price bands)
- `FMV.*` - Fair Market Value (proprietary real-time metric, Business plan only)
- `status` - Connection/auth status messages

## Implementation Plan

### Phase 1: Project Setup & Structure

#### Directory Structure
```
polygon_proxy/
├── Cargo.toml
├── README.md
├── PLAN.md (this file)
├── CLAUDE.md
├── .env.example
├── .gitignore
├── src/
│   ├── main.rs
│   ├── config.rs           # Configuration management
│   ├── types.rs            # Polygon message types
│   ├── upstream.rs         # Polygon connection manager
│   ├── client.rs           # Client connection handler
│   ├── router.rs           # Message routing
│   └── test/
│       ├── mod.rs
│       ├── scenarios.rs    # Test scenarios
│       └── generator.rs    # Mock data generator
├── tests/
│   └── integration_test.rs
├── scripts/
│   ├── setup.sh
│   ├── test_connection.py
│   ├── test_multi_client.py
│   ├── test_performance.py
│   └── monitor.sh
└── docs/
    ├── websocket_api.md
    └── deployment.md
```

### Phase 2: Core WebSocket Proxy

#### TODO List - WebSocket Implementation

- [ ] **Project Setup**
  - [ ] Create Cargo.toml with dependencies:
    - [ ] `tokio` (async runtime)
    - [ ] `tokio-tungstenite` (WebSocket implementation)
    - [ ] `tungstenite` (WebSocket protocol)
    - [ ] `serde` + `serde_json` (JSON handling)
    - [ ] `tracing` + `tracing-subscriber` (structured logging)
    - [ ] `anyhow` (error handling)
    - [ ] `thiserror` (custom errors)
    - [ ] `futures-util` (stream utilities)
  - [ ] Set up logging with tracing/env_logger
  - [ ] Create .env.example with required variables
  - [ ] Write initial README.md

- [ ] **Configuration Module** (`src/config.rs`)
  - [ ] Parse environment variables
  - [ ] Polygon API key
  - [ ] Connection parameters (timeouts, retries)
  - [ ] Test mode configuration
  - [ ] WebSocket port configuration (default: 8765)

- [ ] **Type Definitions** (`src/types.rs`)
  - [ ] Define Polygon message structures
  - [ ] Trade message type
  - [ ] Quote message type
  - [ ] Aggregate message type
  - [ ] Status/error message types
  - [ ] Subscription request/response types
  - [ ] Client control messages

- [ ] **Upstream Connection** (`src/upstream.rs`)
  - [ ] Connect to Polygon WebSocket with API key in URL
  - [ ] Auto-reconnect on disconnect (5 second delay)
  - [ ] Send ping every 30 seconds to keep alive
  - [ ] Forward all messages to router
  - [ ] Single connection to stocks feed

- [ ] **Client Handler** (`src/client.rs`)
  - [ ] Accept WebSocket connections
  - [ ] Forward client messages to router
  - [ ] Send messages from router to client
  - [ ] Clean up on disconnect

- [ ] **Message Router** (`src/router.rs`)
  - [ ] Track client subscriptions (which symbols each client wants)
  - [ ] Handle wildcard (*) subscriptions mixed with specific symbols
  - [ ] Forward messages to subscribed clients only
  - [ ] Combine all client subscriptions for upstream
  - [ ] Simple JSON parsing to get symbol from message
  - [ ] Proper unsubscribe with delayed upstream cleanup

- [ ] **Main Application** (`src/main.rs`)
  - [ ] Initialize all components
  - [ ] Start WebSocket server for stocks
  - [ ] Coordinate upstream connection
  - [ ] Graceful shutdown handling
  - [ ] Signal handling (SIGTERM, SIGINT)

### Phase 3: Test Data Injection

#### TODO List - Test System

- [ ] **Test Mode Configuration**
  - [ ] Enable/disable test mode via env var
  - [ ] Scenario selection mechanism
  - [ ] Mix real/test data option
  - [ ] Test mode indicators in responses

- [ ] **Mock Data Generator** (`src/test/generator.rs`)
  - [ ] Generate realistic stock prices
  - [ ] Generate trade sequences with realistic volumes
  - [ ] Generate quote data with proper bid/ask spread
  - [ ] Generate aggregate/bar data
  - [ ] Maintain price continuity
  - [ ] Simulate market hours/after-hours patterns
  - [ ] Simulate trading halts and circuit breakers

- [ ] **Test Scenarios** (`src/test/scenarios.rs`)
  - [ ] Normal trading day scenario
  - [ ] High volatility scenario
  - [ ] Low liquidity scenario
  - [ ] Gap up/down scenario
  - [ ] Halted trading scenario
  - [ ] News-driven movement scenario

### Phase 4: Monitoring & Operations

#### TODO List - Operations

- [ ] **Health Endpoints**
  - [ ] `/health` - Overall system health (HTTP endpoint)
  - [ ] `/health/upstream` - Upstream connection status
  - [ ] `/health/clients` - Connected clients info
  - [ ] `/metrics` - Prometheus metrics

- [ ] **Logging & Monitoring**
  - [ ] Structured logging with tracing
  - [ ] Log rotation configuration
  - [ ] Metrics collection (messages/sec, latency)
  - [ ] Alert conditions (disconnections, high latency)
  - [ ] Performance monitoring

- [ ] **Admin WebSocket Commands**
  - [ ] Get connection status
  - [ ] List active subscriptions
  - [ ] Enable/disable test mode
  - [ ] Load test scenario
  - [ ] Force reconnect upstream

- [ ] **Deployment**
  - [ ] Systemd service file
  - [ ] Docker container option
  - [ ] Environment configuration
  - [ ] Graceful restart procedures
  - [ ] Connection draining

### Phase 5: Testing & Validation

#### Multi-Client Test Suite

##### Test Script 1: Basic Multi-Client Connection (`scripts/test_multi_client.py`)
```python
#!/usr/bin/env python3
"""
Test multiple clients connecting to Polygon proxy simultaneously.
Uses existing POLYGON_API_KEY from environment or breaking_news project.
"""
import asyncio
import websockets
import json
import os
from datetime import datetime
from typing import Dict, List

# Get API key from environment or breaking_news config
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha")
PROXY_URL = "ws://localhost:8765/stocks"  # Proxy endpoint
DIRECT_URL = "wss://socket.polygon.io/stocks"  # Direct Polygon (for comparison)

class PolygonClient:
    def __init__(self, client_id: str, symbols: List[str], use_proxy: bool = True):
        self.client_id = client_id
        self.symbols = symbols
        self.url = PROXY_URL if use_proxy else DIRECT_URL
        self.messages_received = 0
        self.connected = False
        
    async def connect_and_subscribe(self):
        async with websockets.connect(self.url) as ws:
            # Authenticate
            auth_msg = {"action": "auth", "params": POLYGON_API_KEY}
            await ws.send(json.dumps(auth_msg))
            
            # Wait for auth response
            response = await ws.recv()
            auth_data = json.loads(response)
            print(f"[{self.client_id}] Auth response: {auth_data}")
            
            # Subscribe to symbols (all available data types)
            subscriptions = [f"T.{s},Q.{s},A.{s},AM.{s},LULD.{s},FMV.{s}" for s in self.symbols]
            sub_msg = {
                "action": "subscribe",
                "params": ",".join(subscriptions)
            }
            await ws.send(json.dumps(sub_msg))
            
            # Receive messages for 30 seconds
            start_time = datetime.now()
            while (datetime.now() - start_time).seconds < 30:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    self.messages_received += 1
                    if self.messages_received % 100 == 0:
                        print(f"[{self.client_id}] Received {self.messages_received} messages")
                except asyncio.TimeoutError:
                    continue
                    
        return self.messages_received

async def test_multiple_clients():
    # Test scenarios
    test_cases = [
        # 10 clients with same symbols (test deduplication)
        {"count": 10, "symbols": ["AAPL", "GOOGL", "MSFT"], "description": "Same symbols"},
        # 10 clients with different symbols (test routing)
        {"count": 10, "symbols_per_client": lambda i: [f"TEST{i}", f"DEMO{i}"], "description": "Different symbols"},
        # 50 clients mixed (stress test)
        {"count": 50, "symbols": ["SPY", "QQQ", "IWM"], "description": "High load"}
    ]
    
    for test in test_cases:
        print(f"\n=== Test: {test['description']} ===")
        tasks = []
        for i in range(test["count"]):
            if "symbols_per_client" in test:
                symbols = test["symbols_per_client"](i)
            else:
                symbols = test["symbols"]
            client = PolygonClient(f"client_{i}", symbols)
            tasks.append(client.connect_and_subscribe())
        
        results = await asyncio.gather(*tasks)
        print(f"Total messages received: {sum(results)}")
        print(f"Average per client: {sum(results) / len(results):.0f}")

if __name__ == "__main__":
    asyncio.run(test_multiple_clients())
```

##### Test Script 2: Subscription Management Test (`scripts/test_subscription_mgmt.py`)
```python
#!/usr/bin/env python3
"""
Test subscription management with clients joining/leaving dynamically.
"""
import asyncio
import websockets
import json
import random
import os
from typing import List

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha")
PROXY_URL = "ws://localhost:8765/stocks"

async def client_lifecycle(client_id: str, duration: int, symbols: List[str]):
    """Client that connects, subscribes, then disconnects after duration"""
    try:
        async with websockets.connect(PROXY_URL) as ws:
            # Auth
            await ws.send(json.dumps({"action": "auth", "params": POLYGON_API_KEY}))
            await ws.recv()  # Auth response
            
            # Subscribe
            sub_params = ",".join([f"T.{s}" for s in symbols])
            await ws.send(json.dumps({"action": "subscribe", "params": sub_params}))
            
            print(f"[{client_id}] Connected and subscribed to {symbols}")
            
            # Stay connected for duration
            await asyncio.sleep(duration)
            
            # Unsubscribe
            await ws.send(json.dumps({"action": "unsubscribe", "params": sub_params}))
            
            print(f"[{client_id}] Disconnecting after {duration}s")
    except Exception as e:
        print(f"[{client_id}] Error: {e}")

async def test_dynamic_clients():
    """Test clients joining and leaving at different times"""
    symbols_pool = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA"]
    
    tasks = []
    for i in range(20):
        # Random duration between 5-30 seconds
        duration = random.randint(5, 30)
        # Random symbols
        symbols = random.sample(symbols_pool, k=random.randint(1, 3))
        # Random start delay
        delay = random.randint(0, 10)
        
        async def delayed_start(client_id, delay, duration, symbols):
            await asyncio.sleep(delay)
            await client_lifecycle(client_id, duration, symbols)
        
        tasks.append(delayed_start(f"dynamic_{i}", delay, duration, symbols))
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(test_dynamic_clients())
```

##### Test Script 3: Performance & Load Test (`scripts/test_performance.py`)
```python
#!/usr/bin/env python3
"""
Performance test with metrics collection.
Measures latency, throughput, and resource usage.
"""
import asyncio
import websockets
import json
import time
import statistics
import os
from collections import defaultdict
from datetime import datetime

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha")
PROXY_URL = "ws://localhost:8765/stocks"

class PerformanceMonitor:
    def __init__(self):
        self.latencies = []
        self.message_counts = defaultdict(int)
        self.start_time = None
        self.end_time = None
        
    def record_latency(self, latency_ms):
        self.latencies.append(latency_ms)
        
    def record_message(self, client_id):
        self.message_counts[client_id] += 1
        
    def get_stats(self):
        if not self.latencies:
            return {}
            
        duration = (self.end_time - self.start_time).total_seconds()
        total_messages = sum(self.message_counts.values())
        
        return {
            "duration_seconds": duration,
            "total_messages": total_messages,
            "messages_per_second": total_messages / duration if duration > 0 else 0,
            "client_count": len(self.message_counts),
            "latency_stats": {
                "mean_ms": statistics.mean(self.latencies),
                "median_ms": statistics.median(self.latencies),
                "p95_ms": statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) > 20 else max(self.latencies),
                "p99_ms": statistics.quantiles(self.latencies, n=100)[98] if len(self.latencies) > 100 else max(self.latencies),
                "min_ms": min(self.latencies),
                "max_ms": max(self.latencies)
            }
        }

async def performance_client(client_id: str, monitor: PerformanceMonitor, duration: int):
    """Client that measures performance metrics"""
    async with websockets.connect(PROXY_URL) as ws:
        # Auth
        await ws.send(json.dumps({"action": "auth", "params": POLYGON_API_KEY}))
        await ws.recv()
        
        # Subscribe to high-volume symbols
        symbols = ["SPY", "QQQ", "AAPL", "TSLA", "AMD"]
        sub_params = ",".join([f"T.{s},Q.{s}" for s in symbols])
        await ws.send(json.dumps({"action": "subscribe", "params": sub_params}))
        
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                # Measure receive latency
                start = time.perf_counter()
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                latency_ms = (time.perf_counter() - start) * 1000
                
                monitor.record_latency(latency_ms)
                monitor.record_message(client_id)
                
                # Parse message to verify correctness
                data = json.loads(msg)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[{client_id}] Error: {e}")
                break

async def run_performance_test(client_count: int = 100, duration: int = 60):
    """Run performance test with specified number of clients"""
    print(f"Starting performance test with {client_count} clients for {duration} seconds...")
    
    monitor = PerformanceMonitor()
    monitor.start_time = datetime.now()
    
    # Create all clients
    tasks = []
    for i in range(client_count):
        tasks.append(performance_client(f"perf_{i}", monitor, duration))
    
    # Run all clients concurrently
    await asyncio.gather(*tasks)
    
    monitor.end_time = datetime.now()
    
    # Print results
    stats = monitor.get_stats()
    print("\n=== Performance Test Results ===")
    print(f"Duration: {stats['duration_seconds']:.1f} seconds")
    print(f"Total Messages: {stats['total_messages']:,}")
    print(f"Messages/Second: {stats['messages_per_second']:.0f}")
    print(f"Active Clients: {stats['client_count']}")
    print("\nLatency Statistics:")
    for key, value in stats['latency_stats'].items():
        print(f"  {key}: {value:.2f}")

if __name__ == "__main__":
    # Run with different client counts
    asyncio.run(run_performance_test(client_count=10, duration=30))
    asyncio.run(run_performance_test(client_count=50, duration=30))
    asyncio.run(run_performance_test(client_count=100, duration=30))
```

##### Test Script 4: Cluster Test (`scripts/test_clusters.py`)
```python
#!/usr/bin/env python3
"""
Test multiple Polygon clusters (stocks, options, forex, crypto).
"""
import asyncio
import websockets
import json
import os

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha")

PROXY_URL = "ws://localhost:8765"
SYMBOLS = ["AAPL", "GOOGL", "SPY"]
MESSAGE_TYPES = ["T", "Q", "A", "AM", "LULD", "FMV"]  # All available stock data types

async def test_stocks_feed():
    """Test the stocks feed"""
    try:
        async with websockets.connect(PROXY_URL) as ws:
            print(f"[stocks] Connected to {PROXY_URL}")

            # Authenticate
            await ws.send(json.dumps({"action": "auth", "params": POLYGON_API_KEY}))
            response = await ws.recv()
            print(f"[stocks] Auth response: {response}")

            # Subscribe
            subscriptions = []
            for symbol in SYMBOLS:
                for msg_type in MESSAGE_TYPES:
                    subscriptions.append(f"{msg_type}.{symbol}")

            sub_msg = {"action": "subscribe", "params": ",".join(subscriptions)}
            await ws.send(json.dumps(sub_msg))
            print(f"[stocks] Subscribed to: {subscriptions}")

            # Receive messages for 30 seconds
            message_count = 0
            start_time = asyncio.get_event_loop().time()

            while asyncio.get_event_loop().time() - start_time < 30:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    message_count += 1
                    if message_count % 100 == 0:
                        print(f"[stocks] Received {message_count} messages")
                except asyncio.TimeoutError:
                    continue

            print(f"[stocks] Total messages: {message_count}")
            return message_count

    except Exception as e:
        print(f"[stocks] Error: {e}")
        return 0

if __name__ == "__main__":
    asyncio.run(test_stocks_feed())
```

#### Test Execution Plan

- [ ] **Test Environment Setup**
  - [ ] Create `.env` file with `POLYGON_API_KEY=EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha`
  - [ ] Ensure proxy is running on correct ports
  - [ ] Set up monitoring for resource usage
  - [ ] Prepare test data collection

- [ ] **Test Execution Sequence**
  1. [ ] Run basic connectivity test (single client)
  2. [ ] Run multi-client same symbols test (10 clients)
  3. [ ] Run multi-client different symbols test (10 clients)
  4. [ ] Run subscription management test (20 clients, dynamic)
  5. [ ] Run performance test (10, 50, 100 clients)
  6. [ ] Run 24-hour stability test

- [ ] **Metrics to Collect**
  - [ ] Connection success rate
  - [ ] Message delivery rate
  - [ ] Latency percentiles (p50, p95, p99)
  - [ ] Memory usage over time
  - [ ] CPU usage under load
  - [ ] Network bandwidth usage
  - [ ] Error rates and types
  - [ ] Recovery time after failure

### Phase 6: Documentation

#### TODO List - Documentation

- [ ] **WebSocket API Documentation**
  - [ ] Connection guide for each cluster
  - [ ] Authentication details
  - [ ] Message format specifications
  - [ ] Subscription/unsubscription flow
  - [ ] Error codes and handling

- [ ] **Deployment Guide**
  - [ ] System requirements
  - [ ] Installation steps
  - [ ] Configuration options
  - [ ] Security considerations
  - [ ] Monitoring setup

- [ ] **Developer Guide**
  - [ ] Architecture overview
  - [ ] Code structure explanation
  - [ ] Adding new clusters
  - [ ] Creating test scenarios
  - [ ] Troubleshooting guide

## Key Implementation Details

### Subscription Management (Wildcard + Specific Symbols)

```rust
use std::collections::{HashMap, HashSet};
use tokio::time::{Duration, Instant};

/// Simple subscription tracker that handles wildcards and specific symbols
pub struct SubscriptionManager {
    // Client ID -> Their subscriptions (can include "*" for wildcard)
    client_subs: HashMap<Uuid, HashSet<String>>,
    
    // Track who has wildcard
    wildcard_clients: HashSet<Uuid>,
    
    // Symbol -> Set of clients (for specific subscriptions)
    symbol_to_clients: HashMap<String, HashSet<Uuid>>,
    
    // Symbols to unsubscribe upstream (with timestamp for delayed cleanup)
    pending_unsubs: HashMap<String, Instant>,
}

impl SubscriptionManager {
    pub fn add_subscription(&mut self, client_id: Uuid, symbols: Vec<String>) {
        for symbol in symbols {
            if symbol == "*" {
                // Client wants everything
                self.wildcard_clients.insert(client_id);
            } else {
                // Specific symbol subscription
                self.symbol_to_clients
                    .entry(symbol.clone())
                    .or_default()
                    .insert(client_id);
            }
            
            self.client_subs
                .entry(client_id)
                .or_default()
                .insert(symbol);
                
            // Remove from pending unsubs if it was scheduled
            self.pending_unsubs.remove(&symbol);
        }
    }
    
    pub fn remove_subscription(&mut self, client_id: Uuid, symbols: Vec<String>) {
        for symbol in symbols {
            if symbol == "*" {
                self.wildcard_clients.remove(&client_id);
            } else {
                if let Some(clients) = self.symbol_to_clients.get_mut(&symbol) {
                    clients.remove(&client_id);
                    
                    // Schedule upstream unsub if no clients left
                    if clients.is_empty() && !self.wildcard_clients.is_empty() {
                        // Don't unsub if we have wildcard clients
                        continue;
                    }
                    
                    if clients.is_empty() {
                        // Schedule for removal in 30 seconds
                        self.pending_unsubs.insert(symbol.clone(), Instant::now());
                    }
                }
            }
            
            if let Some(subs) = self.client_subs.get_mut(&client_id) {
                subs.remove(&symbol);
            }
        }
    }
    
    pub fn get_clients_for_message(&self, symbol: &str) -> Vec<Uuid> {
        let mut clients = Vec::new();
        
        // Add all wildcard subscribers
        clients.extend(self.wildcard_clients.iter().cloned());
        
        // Add specific symbol subscribers
        if let Some(symbol_clients) = self.symbol_to_clients.get(symbol) {
            clients.extend(symbol_clients.iter().cloned());
        }
        
        clients
    }
    
    pub fn get_upstream_subscriptions(&self) -> Vec<String> {
        // If anyone has wildcard, subscribe to * upstream
        if !self.wildcard_clients.is_empty() {
            return vec!["*".to_string()];
        }
        
        // Otherwise, collect all specific symbols
        self.symbol_to_clients.keys().cloned().collect()
    }
    
    pub fn cleanup_pending_unsubs(&mut self) -> Vec<String> {
        let now = Instant::now();
        let mut to_unsub = Vec::new();
        
        self.pending_unsubs.retain(|symbol, time| {
            if now.duration_since(*time) > Duration::from_secs(30) {
                to_unsub.push(symbol.clone());
                false // Remove from pending
            } else {
                true // Keep in pending
            }
        });
        
        to_unsub
    }
    
    pub fn remove_client(&mut self, client_id: Uuid) {
        // Get all their subscriptions
        if let Some(subs) = self.client_subs.remove(&client_id) {
            let symbols: Vec<String> = subs.into_iter().collect();
            self.remove_subscription(client_id, symbols);
        }
    }
}
```

### Usage Example

```rust
// Client A subscribes to Trades for AAPL only
manager.add_subscription(client_a, "T.AAPL");

// Client B subscribes to Quotes for AAPL only
manager.add_subscription(client_b, "Q.AAPL");

// Client C subscribes to wildcard (gets everything)
manager.add_subscription(client_c, "*");

// Upstream subscription will be "T.*,Q.*,A.*,AM.*,LULD.*,FMV.*" because Client C has wildcard

// When routing a Trade message for AAPL (ev: "T", sym: "AAPL"):
// - Client A gets it (subscribed to T.AAPL)
// - Client C gets it (wildcard subscriber)
// - Client B does NOT get it (only subscribed to Q.AAPL, not T.AAPL)

// When routing a Quote message for AAPL (ev: "Q", sym: "AAPL"):
// - Client B gets it (subscribed to Q.AAPL)
// - Client C gets it (wildcard subscriber)
// - Client A does NOT get it (only subscribed to T.AAPL, not Q.AAPL)

// If Client C unsubscribes from *:
// Upstream changes to "T.AAPL,Q.AAPL" (only the specific TYPE.SYMBOL subscriptions)

// If Client A unsubscribes from T.AAPL:
// T.AAPL is scheduled for removal in 30 seconds (in case they resubscribe quickly)
// Upstream becomes just "Q.AAPL"
```

### Simple WebSocket Connection Management

```rust
use tokio_tungstenite::{connect_async, tungstenite::Message};
use futures_util::{StreamExt, SinkExt};
use std::time::Duration;

/// Simple upstream connection with auto-reconnect
pub struct UpstreamConnection {
    url: String,
    api_key: String,
    tx: mpsc::Sender<String>,  // Send messages to router
}

impl UpstreamConnection {
    pub async fn run(&mut self) {
        loop {
            if let Err(e) = self.connect_and_forward().await {
                error!("Connection failed: {}", e);
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }
    
    async fn connect_and_forward(&mut self) -> Result<()> {
        // Connect with API key in URL (Polygon style)
        let url = format!("{}?apiKey={}", self.url, self.api_key);
        let (ws_stream, _) = connect_async(&url).await?;
        let (mut write, mut read) = ws_stream.split();
        
        info!("Connected to {}", self.url);
        
        // Simple ping every 30 seconds to keep connection alive
        let mut ping_interval = tokio::time::interval(Duration::from_secs(30));
        
        loop {
            tokio::select! {
                // Forward messages from Polygon to router
                Some(msg) = read.next() => {
                    match msg? {
                        Message::Text(text) => {
                            let _ = self.tx.send(text).await;
                        }
                        Message::Close(_) => break,
                        _ => {} // Ignore binary, ping, pong
                    }
                }
                
                // Send ping to keep alive
                _ = ping_interval.tick() => {
                    if write.send(Message::Ping(vec![])).await.is_err() {
                        break; // Connection lost
                    }
                }
            }
        }
        
        Ok(())
    }
}

/// Simple client handler
pub async fn handle_client(
    ws: WebSocket,
    mut rx: mpsc::Receiver<String>,
    router: Arc<Router>,
) {
    let (mut ws_tx, mut ws_rx) = ws.split();
    let client_id = Uuid::new_v4();
    
    // Forward messages from router to client
    let forward_task = async move {
        while let Some(msg) = rx.recv().await {
            if ws_tx.send(Message::Text(msg)).await.is_err() {
                break;
            }
        }
    };
    
    // Handle messages from client
    let receive_task = async move {
        while let Some(Ok(msg)) = ws_rx.next().await {
            if let Message::Text(text) = msg {
                router.handle_client_message(client_id, text).await;
            }
        }
        router.remove_client(client_id).await;
    };
    
    // Run both tasks, exit when either completes
    tokio::select! {
        _ = forward_task => {},
        _ = receive_task => {},
    }
}
```

### Message Format
```rust
// Polygon message structure
#[derive(Deserialize, Serialize)]
#[serde(tag = "ev")]
enum PolygonMessage {
    #[serde(rename = "T")]
    Trade {
        sym: String,
        x: i32,      // Exchange ID
        p: f64,      // Price
        s: i64,      // Size
        t: i64,      // Timestamp
        c: Vec<i32>, // Conditions
    },
    #[serde(rename = "Q")]
    Quote {
        sym: String,
        bx: i32,     // Bid exchange
        bp: f64,     // Bid price
        bs: i64,     // Bid size
        ax: i32,     // Ask exchange
        ap: f64,     // Ask price
        as_: i64,    // Ask size (as is keyword)
        t: i64,      // Timestamp
    },
    #[serde(rename = "A")]
    Aggregate {
        sym: String,
        v: i64,      // Volume
        av: i64,     // Accumulated volume
        op: f64,     // Open price
        vw: f64,     // VWAP
        o: f64,      // Open
        c: f64,      // Close
        h: f64,      // High
        l: f64,      // Low
        a: f64,      // Average
        z: i64,      // Average trade size
        s: i64,      // Starting timestamp
        e: i64,      // Ending timestamp
    },
    #[serde(rename = "status")]
    Status {
        status: String,
        message: String,
    },
}
```

### Subscription Format
```rust
// Polygon uses comma-separated strings
fn format_subscription(symbols: &[String], types: &[String]) -> String {
    let mut params = Vec::new();
    for symbol in symbols {
        for msg_type in types {
            params.push(format!("{}.{}", msg_type, symbol));
        }
    }
    params.join(",")
}
```

### Stocks Feed Configuration
```rust
const POLYGON_STOCKS_URL: &str = "wss://socket.polygon.io/stocks";
const DEFAULT_PROXY_PORT: u16 = 8765;
```

## Configuration Example

### .env.example
```bash
# Polygon API Configuration
POLYGON_API_KEY=EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha

# Proxy Configuration
PROXY_STOCKS_PORT=8765          # Stocks WebSocket proxy port

# Connection Settings
MAX_CLIENTS=1000                # Max downstream clients
RECONNECT_DELAY_MS=1000         # Upstream reconnection delay
HEARTBEAT_INTERVAL_SEC=30       # WebSocket heartbeat interval
MESSAGE_BUFFER_SIZE=10000       # Per-client message buffer

# Test Mode
ENABLE_TEST_MODE=false          # Enable test data injection
TEST_SCENARIO=normal            # Test scenario to use
MIX_TEST_DATA=false             # Mix test with real data

# Monitoring
LOG_LEVEL=info                  # Log level (debug, info, warn, error)
ENABLE_METRICS=true             # Enable Prometheus metrics
METRICS_PORT=9090               # Metrics endpoint port
```

## Success Criteria

### Functional Requirements
- [ ] Successfully proxy Polygon stocks WebSocket feed
- [ ] Handle 100+ concurrent client connections
- [ ] Maintain < 10ms routing latency
- [ ] Provide seamless test data injection
- [ ] Zero message loss during reconnection
- [ ] Support wildcard subscriptions

### Performance Targets
- [ ] Handle 50,000+ messages/second
- [ ] Memory usage < 500MB under normal load
- [ ] CPU usage < 50% on 4-core system
- [ ] Reconnection time < 5 seconds
- [ ] Client connection time < 100ms

### Operational Requirements
- [ ] 99.9% uptime (excluding upstream issues)
- [ ] Graceful degradation on upstream failure
- [ ] Complete audit logging
- [ ] Real-time monitoring capabilities
- [ ] Easy configuration management

## Development Timeline

### Week 1: Foundation
- Project setup and structure
- Basic WebSocket proxy for stocks cluster
- Simple client connection handling

### Week 2: Full WebSocket
- Subscription management
- Reconnection logic
- Error handling

### Week 3: Test System
- Mock data generator
- Scenario system
- Test mode integration

### Week 4: Production Ready
- Monitoring and metrics
- Performance optimization
- Documentation
- Deployment setup

## Risk Mitigation

### Technical Risks
1. **Rate Limiting**: Implement client-side rate limiting and backoff
2. **Memory Leaks**: Use proper cleanup and bounded channels
3. **Connection Storms**: Implement connection throttling and jitter
4. **Data Consistency**: Use checksums and sequence numbers

### Operational Risks
1. **API Changes**: Version detection and compatibility layer
2. **Credential Management**: Secure storage and rotation
3. **Downstream Failures**: Circuit breakers and client isolation
4. **Capacity Planning**: Monitor and alert on resource usage

## Next Steps

1. Review and approve this plan
2. Set up development environment
3. Create initial Rust project structure
4. Implement Phase 1 (Project Setup)
5. Begin Phase 2 (Core WebSocket Proxy)

## Notes

- Consider implementing WebSocket compression for bandwidth optimization
- Plan for horizontal scaling if single instance becomes bottleneck
- Consider adding support for Polygon's Launchpad (edge) servers for lower latency
- Implement message deduplication for clients subscribing to same symbols
- Add support for Polygon's snapshot messages on connection
- For multi-feed support (options, forex, crypto), each feed would need its own proxy instance