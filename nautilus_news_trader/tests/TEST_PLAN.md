# News Trading Strategy - E2E Test Plan

## Overview

This test plan covers end-to-end testing of the NewsVolumeStrategy with paper trading execution on Alpaca. Tests use `[TEST]` prefix in headlines to bypass Polygon volume checks and use mock data.

## Prerequisites

- News-trader service running on GCP (`news-trader` VM)
- Alpaca paper trading account connected
- Pub/Sub topic `benzinga-news` accessible
- Exit delay set to 2 minutes for faster testing

## Test News Format

```json
{
  "id": "test_<timestamp>",
  "storyId": "test_<timestamp>",
  "headline": "[TEST] Test headline for TICKER",
  "tickers": ["TICKER"],
  "createdAt": "<ISO timestamp within 2-10s>",
  "source": "Test",
  "capturedAt": "<ISO timestamp>"
}
```

## Test Cases

### TC1: Happy Path - Full Lifecycle
**Objective:** Verify complete buy → hold → sell cycle

**Steps:**
1. Publish test news for actively traded stock (AAPL, SPY, TSLA)
2. Verify BUY order placed and filled
3. Wait 2 minutes for exit timer
4. Verify SELL order placed and filled
5. Verify position closed with PnL logged

**Expected:**
- Strategy spawns within 1s
- BUY limit order placed (entry price + 1%)
- Exit timer scheduled (2 min)
- SELL limit order placed (current price - 1%)
- Position closed, PnL logged

---

### TC2: Service Restart with Open Position
**Objective:** Verify on_stop() exits position when service restarts

**Steps:**
1. Publish test news, wait for BUY fill
2. Restart news-trader service before 2-min exit
3. Verify exit order placed on stop
4. Verify position closed

**Expected:**
- `on_stop()` detects open position
- EXIT SELL order placed immediately
- Position closed

---

### TC3: Service Restart with Pending Entry Order
**Objective:** Verify on_stop() cancels unfilled entry order

**Steps:**
1. Publish test news for low-liquidity stock
2. Restart service before entry fills
3. Verify entry order cancelled

**Expected:**
- `on_stop()` cancels pending entry order
- No orphaned orders

---

### TC4: Partial Fill Handling
**Objective:** Verify strategy handles partial fills correctly

**Steps:**
1. Publish test news for medium-liquidity stock
2. Monitor for partial fill events
3. Verify exit sells full position (not just last fill)

**Expected:**
- Multiple OrderFilled events handled
- Exit timer scheduled after first fill
- Full position exited (sum of all fills)

---

### TC5: No Tickers in News
**Objective:** Verify news without tickers is skipped

**Steps:**
1. Publish test news with empty tickers array
2. Verify logged as "No tickers in news"

**Expected:**
- No strategy spawned
- Logged: `⏭️ No tickers in news`

---

### TC6: News Too Old (>10s)
**Objective:** Verify stale news is rejected

**Steps:**
1. Publish test news with createdAt > 10s ago
2. Verify logged as "News too old"

**Expected:**
- No strategy spawned
- Logged: `⏭️ News too old: X.Xs > 10s`

---

### TC7: News Too Fresh (<2s)
**Objective:** Verify very fresh news is rejected

**Steps:**
1. Publish test news with createdAt < 2s ago
2. Verify logged as "News too fresh"

**Expected:**
- No strategy spawned
- Logged: `⏭️ News too fresh: X.Xs < 2s`

---

### TC8: Duplicate Strategy Prevention
**Objective:** Verify same ticker doesn't spawn multiple strategies

**Steps:**
1. Publish test news for AAPL
2. Wait for strategy to start
3. Publish another test news for AAPL
4. Verify second news skipped

**Expected:**
- First strategy runs
- Second news logged: `⏭️ Skipping AAPL - already has position/strategy`

---

### TC9: Order Rejected
**Objective:** Verify strategy handles rejected orders gracefully

**Steps:**
1. Publish test news with invalid ticker or after hours
2. Monitor for order rejection
3. Verify strategy stops cleanly

**Expected:**
- Order rejected by Alpaca
- Strategy logs error and stops
- No orphaned state

---

### TC10: Multiple Tickers in News
**Objective:** Verify each ticker spawns separate strategy

**Steps:**
1. Publish test news with multiple tickers: ["AAPL", "MSFT"]
2. Verify both strategies spawn
3. Verify both complete independently

**Expected:**
- Two strategies spawned
- Each runs full lifecycle independently

---

## Test Execution Scripts

### Run Single Test
```bash
python tests/send_test_news.py --ticker AAPL --test-name "TC1 Happy Path"
```

### Run Restart Test
```bash
python tests/send_test_news.py --ticker SPY --test-name "TC2 Restart"
# Wait 30s, then:
gcloud compute ssh news-trader --zone=us-east4-a --project=gnw-trader --command='sudo systemctl restart news-trader'
```

### Monitor Logs
```bash
gcloud logging read 'resource.type="gce_instance" AND labels."compute.googleapis.com/resource_name"="news-trader" AND jsonPayload.message=~"TEST"' --project=gnw-trader --limit=50
```

---

## Actively Traded Stocks for Testing

During US market hours (15:30-22:00 CET):
- **High liquidity:** AAPL, MSFT, TSLA, SPY, QQQ, NVDA
- **Medium liquidity:** AMD, META, AMZN, GOOG

During pre-market (10:00-15:30 CET):
- Use stocks with earnings or news that day
- Check Polygon for recent trades first

---

## Pass/Fail Criteria

| Test | Pass Condition |
|------|----------------|
| TC1 | Position opened and closed within 3 min |
| TC2 | Position closed on restart |
| TC3 | Entry order cancelled on restart |
| TC4 | Full quantity sold (not partial) |
| TC5 | No strategy spawned |
| TC6 | No strategy spawned |
| TC7 | No strategy spawned |
| TC8 | Only one strategy running |
| TC9 | Strategy stopped, no orphaned state |
| TC10 | Both strategies complete |

---

## Cleanup After Testing

1. Check Alpaca for open positions: `alpaca-py positions`
2. Cancel any open orders: `alpaca-py orders cancel-all`
3. Reset exit delay: `EXIT_DELAY_MINUTES=7`
