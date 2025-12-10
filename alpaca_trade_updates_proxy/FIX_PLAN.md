# Trade Updates Proxy Fix Plan

## Problem
Upstream WebSocket to Alpaca silently dies. Proxy blocks forever on dead connection. No visibility, no recovery.

## KISS Solution

### 1. Add Periodic Ping (Primary Fix)
```rust
// In connect_and_stream(), spawn a ping task alongside the read loop:

let write = Arc::new(Mutex::new(write));
let write_clone = write.clone();

// Ping task - sends ping every 30s to detect dead connections
let ping_task = tokio::spawn(async move {
    loop {
        sleep(Duration::from_secs(30)).await;
        let mut w = write_clone.lock().await;
        if w.send(Message::Ping(vec![1, 2, 3, 4])).await.is_err() {
            break;  // Connection dead
        }
    }
});

// Read loop
while let Some(msg) = read.next().await {
    match msg {
        Ok(Message::Pong(_)) => {
            println!("[{}] Pong received - connection alive", self.feed_type.name());
        }
        // ... rest of handling
    }
}

ping_task.abort();
```

**Why this works even with no trading:**
- Every 30s we SEND a ping
- If connection is dead, `send()` fails → error → reconnect
- If connection is alive, we get Pong back (logged for visibility)
- No dependency on Alpaca sending us anything

### 2. Log Forwarded Messages (Visibility)
```rust
async fn broadcast_to_clients(&self, message: &str) {
    // Add this line:
    println!("[{}] Broadcasting: {}", self.feed_type.name(),
             &message[..message.len().min(100)]);
    // ... rest of function
}
```

### 3. Daily Restart via Cron (Belt + Suspenders)
```bash
# /etc/cron.d/alpaca-trade-proxy
0 9 * * * root systemctl restart alpaca-trade-proxy
```
Same as scraper - daily restart at 4 AM ET prevents long-running connection issues.

## Implementation Order
1. Add daily cron restart (immediate mitigation - 1 min)
2. Add message logging (visibility - 5 min)
3. Add read timeout with ping (proper fix - 15 min)
4. Rebuild and deploy

## Test
1. Deploy updated proxy
2. Restart strategies so they reconnect
3. Place test order via Alpaca web UI
4. Verify fill event appears in proxy logs AND strategy logs

## Not Doing (YAGNI)
- Health HTTP endpoint (overkill for single-use proxy)
- Metrics/prometheus (same)
- Complex reconnect strategies (simple exponential backoff is fine)
- Multiple upstream connections (single connection is sufficient)
