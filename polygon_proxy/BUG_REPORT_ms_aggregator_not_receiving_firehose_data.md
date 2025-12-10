# Bug Report: MS Aggregator Not Receiving Data from Firehose Proxy

**Date:** 2025-10-13
**Severity:** HIGH
**Status:** UNRESOLVED

## Summary

The millisecond bar aggregator (ms-aggregator) successfully connects to the firehose proxy but does not receive any trade data, despite the firehose receiving and logging 219,000+ trade messages from Polygon. This prevents real-time 500ms bars from being generated and sent to browser clients.

## Environment

- **Firehose Proxy:** v1.0 (Rust)
- **MS Aggregator:** v1.0 (Rust)
- **Polygon API Key:** EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha (working key)
- **Market Status:** OPEN (13:15 EDT / 17:15 UTC)
- **Log Level:** RUST_LOG=debug

## Expected Behavior

1. Firehose proxy connects to Polygon WebSocket
2. Firehose receives trade data and logs "Received message from Polygon"
3. Firehose broadcasts messages to connected clients (ms-aggregator)
4. MS aggregator receives trades and logs "Received trade: SYM @ PRICE"
5. MS aggregator aggregates trades into bars
6. MS aggregator sends bars to subscribed browser clients
7. Browser chart updates every 500ms with new bars

## Actual Behavior

1. ✅ Firehose proxy connects to Polygon WebSocket
2. ✅ Firehose receives trade data (219,119 lines logged)
3. ✅ MS aggregator connects to firehose
4. ❌ MS aggregator does NOT receive any trades (log shows only "waiting for data...")
5. ❌ No bars are generated
6. ❌ Browser receives no real-time updates
7. ❌ Chart remains static

## Data Flow Status

```
Polygon WebSocket ✅ → Firehose Proxy ✅ → [BREAK] ❌ → MS Aggregator ❌ → Browser Client
```

**The break occurs between firehose and ms-aggregator despite successful WebSocket connection.**

## Evidence

### Firehose Proxy Logs

**Connection established:**
```
[2025-10-13T17:13:36.659753Z] INFO Client fc77ef78-2335-44ee-be40-c353454de53a connected from 127.0.0.1:50186
[2025-10-13T17:13:36.659844Z] INFO Client fc77ef78-2335-44ee-be40-c353454de53a added to broadcast list (1 total)
```

**Trades flowing from Polygon:**
```
[2025-10-13T17:13:37.662029Z] INFO Received message from Polygon: [{"ev":"T","sym":"TSLA","i":"640850","x":4,"p":427.5288,"s":1,...}]
[2025-10-13T17:13:37.684860Z] INFO Received message from Polygon: [{"ev":"T","sym":"TSLA","i":"640851","x":4,"p":427.51,"s":20,...}]
[2025-10-13T17:16:21.647978Z] INFO Received message from Polygon: [{"ev":"T","sym":"TSLA","i":"643589","x":4,"p":428.235,"s":1,...}]
```

**Log size indicates massive data flow:**
```bash
$ wc -l /tmp/firehose_debug.log
219119 /tmp/firehose_debug.log
```

### MS Aggregator Logs

**Connection established:**
```
[2025-10-13T17:15:46.690462Z] INFO Starting Polygon Millisecond Bar Aggregator
[2025-10-13T17:15:46.690629Z] INFO Connecting to firehose at ws://localhost:8767
[2025-10-13T17:15:46.691171Z] DEBUG Client handshake done.
[2025-10-13T17:15:46.691183Z] INFO Connected to firehose proxy
[2025-10-13T17:15:46.691215Z] INFO Subscribed to T.* from firehose, waiting for data...
```

**NO trade data received (should see "Received trade" logs):**
```bash
$ grep "Received trade" /tmp/ms_agg_debug2.log
(no results)
```

**Log size confirms no data processing:**
```bash
$ wc -l /tmp/ms_agg_debug2.log
35 /tmp/ms_agg_debug2.log  # Only connection logs, no trade data
```

**Browser clients connected and subscribed:**
```
[2025-10-13T17:15:51.113152Z] INFO Client d23a3674-f07e-499c-a634-961a27f86d3d authenticated
[2025-10-13T17:15:51.113487Z] INFO Client d23a3674-f07e-499c-a634-961a27f86d3d subscribed to 500Ms.TSLA
```

## Root Cause Analysis

### Confirmed Working Components

1. **Polygon → Firehose:** Direct Python test shows trades flowing:
   ```python
   # test_polygon_direct.py successfully receives:
   {"ev":"T","sym":"TSLA","i":"640850","x":4,"p":428.46,"s":1,...}
   ```

2. **Firehose Broadcasting Logic:** Code at `src/upstream.rs:81-86` shows:
   ```rust
   Message::Text(text) => {
       info!("Received message from Polygon: {}", &text[..text.len().min(200)]);
       // Broadcast to all connected clients
       if let Err(e) = self.broadcast_tx.send(text).await {
           warn!("Failed to broadcast message: {}", e);
       }
   }
   ```
   - No warnings logged, so `broadcast_tx.send()` succeeds

3. **Broadcaster Client List:** MS aggregator IS in the client list:
   ```
   Client c125d1e1-2748-4a4a-8a67-028c675183bc added to broadcast list (1 total)
   ```

### Suspected Issue

**The broadcast channel messages are being sent but NOT received by ms-aggregator's WebSocket client.**

Possible causes:
1. **Channel buffer overflow:** Messages may be dropped if ms-aggregator's receive buffer fills up
2. **WebSocket message queue:** Firehose may be queuing messages but not flushing them
3. **Tokio select! race condition:** MS aggregator's receive loop may be blocked or not processing
4. **Silent connection drop:** Connection may appear alive but actually dead

## Code Locations

### Firehose Proxy
- **Broadcast send:** `/home/ubuntu/code/polygon_proxy/firehose-proxy/src/upstream.rs:82-86`
- **Broadcaster:** `/home/ubuntu/code/polygon_proxy/firehose-proxy/src/broadcaster.rs:38-54`
- **Client handler:** `/home/ubuntu/code/polygon_proxy/firehose-proxy/src/client_handler.rs`

### MS Aggregator
- **Upstream receive:** `/home/ubuntu/code/polygon_proxy/ms-aggregator/src/upstream.rs`
- **Trade processing:** Look for "Received trade" and "Received non-trade message" debug logs

## Reproduction Steps

1. Start firehose proxy:
   ```bash
   cd /home/ubuntu/code/polygon_proxy/firehose-proxy
   RUST_LOG=debug ./target/release/firehose_proxy > /tmp/firehose_debug.log 2>&1 &
   ```

2. Start ms-aggregator:
   ```bash
   cd /home/ubuntu/code/polygon_proxy/ms-aggregator
   RUST_LOG=debug ./target/release/ms_aggregator > /tmp/ms_agg_debug2.log 2>&1 &
   ```

3. Wait 10 seconds for data flow

4. Check logs:
   ```bash
   # Firehose should show trades
   grep "TSLA" /tmp/firehose_debug.log | head -3

   # MS aggregator should show trades (BUT DOESN'T)
   grep "Received trade" /tmp/ms_agg_debug2.log
   ```

## Previous Issues Resolved

1. ✅ **Wrong API key:** Changed from `MdHapjkP8r7K6y30JH_WCxwVW19eMh3Y` to `EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha`
2. ✅ **Connection limit:** Killed conflicting `polygon_rest_proxy` processes
3. ✅ **WebSocket port:** Browser now correctly connects to port 8768
4. ✅ **Authentication flow:** Browser immediately subscribes after auth (no waiting for response)

## Debugging Suggestions

### 1. Add More Logging to Firehose Broadcaster

In `firehose-proxy/src/broadcaster.rs:38-54`, change line 46 from `debug!` to `info!`:
```rust
info!("Broadcasting message to {} clients: {}", client_count, &message[..message.len().min(100)]);
```

### 2. Check Channel Send Success

In `firehose-proxy/src/upstream.rs:84`, add confirmation:
```rust
match self.broadcast_tx.send(text.clone()).await {
    Ok(_) => debug!("Successfully sent to broadcast channel"),
    Err(e) => warn!("Failed to broadcast message: {}", e),
}
```

### 3. Verify MS Aggregator Receive Loop

Check if ms-aggregator's upstream.rs has a proper receive loop:
```rust
loop {
    tokio::select! {
        Some(msg) = ws_read.next() => {
            match msg {
                Ok(Message::Text(text)) => {
                    info!("RAW MESSAGE RECEIVED: {}", &text[..text.len().min(200)]);
                    // Process message...
                }
                ...
            }
        }
    }
}
```

### 4. Test Direct Firehose → Client Connection

Create a minimal Rust client to test if the broadcast mechanism works:
```rust
// test_firehose_client.rs
use tokio_tungstenite::connect_async;
use futures_util::StreamExt;

#[tokio::main]
async fn main() {
    let (ws_stream, _) = connect_async("ws://localhost:8767").await.unwrap();
    let (_, mut read) = ws_stream.split();

    while let Some(msg) = read.next().await {
        if let Ok(Message::Text(text)) = msg {
            println!("Received: {}", &text[..text.len().min(200)]);
        }
    }
}
```

### 5. Check for Backpressure

The `try_send` in broadcaster.rs:50 will fail if the channel is full:
```rust
if let Err(e) = tx.try_send(message.clone()) {
    debug!("Failed to send to client {}: {}", client_id, e);
}
```

Consider changing to blocking `send()` or increasing channel buffer size.

## Impact

**HIGH:** This completely blocks the real-time 500ms bar functionality. Users cannot see live price updates at sub-second granularity, which was the primary goal of the feature.

## Workaround

None currently available. The system requires the full data flow to function.

## Next Steps

1. Add extensive logging to both firehose and ms-aggregator receive paths
2. Verify channel buffer sizes and backpressure handling
3. Test with a minimal WebSocket client to isolate the issue
4. Consider using `send()` instead of `try_send()` in broadcaster
5. Add metrics/counters for messages sent vs. received

## Related Files

- `/home/ubuntu/code/polygon_proxy/firehose-proxy/src/upstream.rs`
- `/home/ubuntu/code/polygon_proxy/firehose-proxy/src/broadcaster.rs`
- `/home/ubuntu/code/polygon_proxy/firehose-proxy/src/client_handler.rs`
- `/home/ubuntu/code/polygon_proxy/ms-aggregator/src/upstream.rs`
- `/home/ubuntu/code/breaking_news/web/static/js/infinite-chart.js:2519-2552`

## Test Commands

```bash
# Monitor firehose activity
tail -f /tmp/firehose_debug.log | grep "TSLA\|Broadcasting"

# Monitor ms-aggregator activity
tail -f /tmp/ms_agg_debug2.log | grep "Received\|trade\|bar"

# Check connection status
lsof -i :8767  # Firehose proxy port
lsof -i :8768  # MS aggregator port

# Verify Polygon data is flowing
python3 /tmp/test_polygon_direct.py

# Check processes
ps aux | grep -E "(firehose|ms-aggregator|ms_aggregator)"
```

---

**Reported by:** Claude (AI Assistant)
**Date:** 2025-10-13 17:20 UTC
**Investigation Duration:** ~2 hours
