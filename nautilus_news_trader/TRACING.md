# End-to-End News Article Tracing

## Overview

Every news article from Benzinga is tracked with a **correlation ID** (trace ID) that flows through the entire system, allowing you to trace the complete journey from news receipt to trade execution and PnL.

## Correlation ID Source

The trace ID is the **Benzinga story ID** extracted from React Fiber:
```javascript
// In benzinga-scraper/index.js
const fiber = element.__reactFiber$...;
const storyId = fiber?.pendingProps?.story?.id;  // e.g., "3183003"
```

This ID is:
- Benzinga's internal article ID
- Consistent across all systems
- Visible in logs as `[TRACE:3183003]`

## Complete Journey

### 1. News Receipt (Controller)
```
📋 [TRACE:3183003] News data keys: [...]
🆔 [TRACE:3183003] News ID: 3183003
📰 [TRACE:3183003] News (2543ms / 2.5s old): Tesla announces new product
🎯 [TRACE:3183003] Tickers: TSLA
🔗 [TRACE:3183003] URL: https://www.benzinga.com/news/...
📅 [TRACE:3183003] Published: 2025-11-24T12:00:00Z
```

### 2. Volume Validation (Controller)
```
📊 [TRACE:3183003] Checking TSLA on Polygon...
✅ [TRACE:3183003] Trading detected: 1000 shares @ $250.00
💰 [TRACE:3183003] Position size: $1250.50
```

### 3. Strategy Spawn (Controller)
```
🚀 [TRACE:3183003] SPAWNING NEWS TRADING STRATEGY for TSLA
   [TRACE:3183003] Position size: $1250.50
   [TRACE:3183003] Entry price: $250.00
   [TRACE:3183003] Exit after: 7 minutes
✅ [TRACE:3183003] Strategy started successfully: news_TSLA_1732450800
```

### 4. Strategy Execution (Strategy)
```
🚀 [TRACE:3183003] NewsVolumeStrategy starting for TSLA
   [TRACE:3183003] Strategy ID: news_TSLA_1732450800
   [TRACE:3183003] Position size: $1250.50
   [TRACE:3183003] Entry price: $250.00
📰 [TRACE:3183003] News Details:
   [TRACE:3183003] Headline: Tesla announces new product
   [TRACE:3183003] URL: https://www.benzinga.com/news/...
   [TRACE:3183003] Ticker: TSLA
```

### 5. Trade Execution (Strategy)
```
✅ [TRACE:3183003] BUY order placed: TSLA x5 @ $252.50 (Order: abc-123-def)
✅ [TRACE:3183003] SELL order placed: TSLA x5 @ $255.00 (Order: xyz-789-ghi)
```

### 6. Final PnL (Strategy)
```
🛑 [TRACE:3183003] NewsVolumeStrategy stopped for TSLA
💰 [TRACE:3183003] FINAL PnL: $12.50 (+0.99%)
   [TRACE:3183003] Entry: $252.50 x 5
   [TRACE:3183003] Exit: $255.00 x 5
```

## Searching Logs in GCP

### Trace Single News Article
```
logName="projects/gnw-trader/logs/news_trader" AND jsonPayload.message=~"TRACE:3183003"
```

### Find All Profitable Trades
```
logName="projects/gnw-trader/logs/news_trader" AND jsonPayload.message=~"FINAL PnL.*\\+"
```

### Find All Losing Trades
```
logName="projects/gnw-trader/logs/news_trader" AND jsonPayload.message=~"FINAL PnL.*-"
```

### Find Trades for Specific Ticker
```
logName="projects/gnw-trader/logs/news_trader" AND jsonPayload.message=~"TRACE:.*TSLA"
```

### Find High-Volume News (>10k shares)
```
logName="projects/gnw-trader/logs/news_trader" AND jsonPayload.message=~"Trading detected: [0-9]{5,}"
```

## Use Cases

### 1. Audit Trail
- Regulatory compliance: Complete record of why trade was made
- Debugging: Understand why specific news triggered/didn't trigger trade
- Performance analysis: Measure latency at each stage

### 2. Performance Analysis
Track timing:
- News age when received (ms precision)
- Volume check duration
- Strategy spawn time
- Order placement time
- Total news → PnL time

### 3. News-to-PnL Attribution
Link every trade back to originating news:
- Which headlines are profitable?
- Which tickers respond best?
- Which sources are most actionable?

### 4. Debugging Failed Trades
Trace why news didn't result in trade:
```
[TRACE:3183003] News too old: 15.3s > 10s
[TRACE:3183003] No trading activity for TSLA, skipping
[TRACE:3183003] Position $50.00 < min $100, skipping
```

## Implementation Details

**Files Modified:**
- `benzinga_scraper/index.js` - Extract story ID from React Fiber
- `actors/pubsub_news_controller.py` - Add trace ID to all logs
- `strategies/news_volume_strategy.py` - Pass trace ID through, log PnL

**Data Flow:**
```
Benzinga Pro (React Fiber)
  ↓ story.id
Scraper (index.js)
  ↓ Pub/Sub message with 'id' field
Controller (pubsub_news_controller.py)
  ↓ correlation_id parameter
Strategy (news_volume_strategy.py)
  ↓ config.correlation_id
Logs (news-trader.log + GCP Cloud Logging)
```

## Future Enhancements

1. **Structured JSON Logs**: Full JSON with severity levels
2. **BigQuery Export**: Export traces to BigQuery for analysis
3. **Dashboard**: Real-time trace visualization
4. **Metrics**: Aggregate PnL by trace ID, ticker, source
5. **Alerts**: Alert on trace IDs with errors or high losses
