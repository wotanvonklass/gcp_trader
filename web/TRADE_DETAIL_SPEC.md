# Trade Detail View Specification

## Visual Design (ASCII Art)

### Trade Detail Page Layout

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  ← Back to Trades                                             /trades/abc123    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────────────┐│
│  │ TICKER              │ │ P&L                 │ │ DURATION                    ││
│  │ AAPL                │ │ +$45.23 (+1.2%)     │ │ 7m 32s                      ││
│  │ Long Position       │ │ ███████████ Win     │ │ 15:32:12 → 15:39:44 CET     ││
│  └─────────────────────┘ └─────────────────────┘ └─────────────────────────────┘│
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐│
│  │ HEADLINE                                                                    ││
│  │ "Apple announces new iPhone with revolutionary AI features"                 ││
│  │ Source: Benzinga Pro  •  News Age: 2.3s  •  Volume: $45,230                 ││
│  └─────────────────────────────────────────────────────────────────────────────┘│
│                                                                                 │
│  Timeframe: [1s] [5s] [15s] [1m] [5m]                                          │
│            ─────                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────────┐│
│  │                           AAPL Price Chart                                  ││
│  │  $152 ┤                                                                     ││
│  │       │         ┌─┐                                                         ││
│  │       │   ●    ╱│ │╲   ┌─┐                                                  ││
│  │  $151 ┤  NEWS ╱ └─┘ ╲ ╱│ │╲        ┌─┐                                      ││
│  │       │  ┌─┐ ╱       ╲╱ └─┘ ╲     ╱│ │╲  EXIT                               ││
│  │       │ ╱│ │╱  ▲            ╲ ┌─┐ ╱ └─┘ ╲  ▼                                ││
│  │  $150 ┤╱ └─┘ ENTRY           ╲│ │╱       ╲────────────                       ││
│  │       │                       └─┘                                            ││
│  │  $149 ┤───────────────────────────────────────────────────────────────────  ││
│  │       └──────────────────────────────────────────────────────────────────── ││
│  │       15:31    15:33    15:35    15:37    15:39    15:41                    ││
│  │                  │        │                          │                      ││
│  │                NEWS    ENTRY                       EXIT                     ││
│  │                                                                             ││
│  │  Vol  ████  ██  ████  ██████  ████  ██  ████  ██  ████                      ││
│  │       ────────────────────────────────────────────────────────────────────  ││
│  └─────────────────────────────────────────────────────────────────────────────┘│
│                                                                                 │
│  ┌──────────────────────────────┐ ┌────────────────────────────────────────────┐│
│  │ ENTRY DETAILS                │ │ EXIT DETAILS                               ││
│  │ ─────────────────────────────│ │ ────────────────────────────────────────── ││
│  │ Order Type:    Limit         │ │ Order Type:    Market                      ││
│  │ Limit Price:   $150.25       │ │ Fill Price:    $151.48                     ││
│  │ Fill Price:    $150.23       │ │ Fill Time:     15:39:44.123 CET            ││
│  │ Fill Time:     15:32:12.456  │ │ Exit Reason:   Scheduled Exit (7m)         ││
│  │ Quantity:      30 shares     │ │ Slippage:      -$0.02 (-0.01%)             ││
│  │ Slippage:      +$0.02        │ │                                            ││
│  └──────────────────────────────┘ └────────────────────────────────────────────┘│
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Chart Markers Detail

```
   News Marker (Orange Circle)     Entry Marker (Green Arrow)     Exit Marker (Red Arrow)
              │                              │                              │
   ┌──────────┴──────────┐       ┌──────────┴──────────┐       ┌───────────┴───────────┐
   │  ●                  │       │  ▲                  │       │          ▼            │
   │  │ NEWS 15:32:10    │       │  │ Entry $150.23    │       │  Exit $151.48         │
   │  │                  │       │  │                  │       │          │            │
   │ ┌┴┐                 │       │ ┌┴┐                 │       │         ┌┴┐           │
   │ │ │                 │       │ │ │                 │       │         │ │           │
   │ └─┘                 │       │ └─┘                 │       │         └─┘           │
   └─────────────────────┘       └─────────────────────┘       └───────────────────────┘

   Timeline:
   ─────────────────────────────────────────────────────────────────────────────────────
   │                                                                                   │
   ●────────────────▲───────────────────────────────────────────────▼─────────────────│
   │                │                                               │                 │
   NEWS          ENTRY                                            EXIT                │
   15:32:10      15:32:12                                        15:39:44             │
   │             (+2s from news)                                 (+7m 32s)            │
   ─────────────────────────────────────────────────────────────────────────────────────

   Marker Shapes:
   ──────────────
   'circle'    ●  - News event (orange #f97316)
   'arrowUp'   ▲  - Entry (green #22c55e)
   'arrowDown' ▼  - Exit (red #ef4444)
```

### Trades List View (Clickable Rows)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  TRADES                                Total P&L: +$234.50     Win Rate: 62%    │
├─────────────────────────────────────────────────────────────────────────────────┤
│  Filter: [All] [Winners] [Losers]                                               │
├─────────┬────────┬──────────────┬─────────┬─────────┬─────┬──────────┬──────────┤
│  Time   │ Ticker │ Strategy     │ Entry   │ Exit    │ Qty │    P&L   │ Headline │
├─────────┼────────┼──────────────┼─────────┼─────────┼─────┼──────────┼──────────┤
│ 15:32 → │ AAPL   │ NewsVolume   │ $150.23 │ $151.48 │  30 │  +$45.23 │ Apple... │ ← Click
│ 14:18 → │ TSLA   │ NewsVolume   │ $245.10 │ $242.55 │  15 │  -$38.25 │ Tesla... │
│ 13:45 → │ NVDA   │ NewsVolume   │ $890.50 │ $895.20 │   5 │  +$23.50 │ Nvidi... │
│ 12:30 → │ META   │ NewsVolume   │ $520.00 │ $518.50 │  10 │  -$15.00 │ Meta ... │
│  ...    │  ...   │     ...      │   ...   │   ...   │ ... │    ...   │   ...    │
└─────────┴────────┴──────────────┴─────────┴─────────┴─────┴──────────┴──────────┘
                           │
                           ▼
              Click row → Navigate to /trades/{strategyId}
```

---

## URL Routes

```
/trades                         → Trades list view
/trades/{strategyId}            → Trade detail view (default tf=1s)
/trades/{strategyId}?tf=5s      → Trade detail with 5-second bars
/trades/{strategyId}?tf=15s     → Trade detail with 15-second bars
/trades/{strategyId}?tf=1m      → Trade detail with 1-minute bars
/trades/{strategyId}?tf=5m      → Trade detail with 5-minute bars
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  FRONTEND                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  TradesView.tsx                                                                 │
│  ├── List Mode (no strategyId param)                                            │
│  │   └── Clickable rows → navigate to /trades/{id}                              │
│  │                                                                              │
│  └── Detail Mode (strategyId in URL)                                            │
│      ├── Trade info cards                                                       │
│      ├── Timeframe selector                                                     │
│      └── TradingChart.tsx                                                       │
│          ├── Candlestick series (main)                                          │
│          ├── Volume histogram (overlay, bottom 30%)                             │
│          └── Entry/Exit markers                                                 │
│                                                                                 │
│  api.ts                                                                         │
│  ├── getStrategyById(id) → GET /strategies/{id}                                 │
│  └── getMarketBars(ticker, from, to, tf, ts) → GET /market/bars/{ticker}        │
│                                                                                 │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │
                                     │ HTTP
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  BACKEND                                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  news_api.py (FastAPI)                                                          │
│  ├── GET /strategies/{strategy_id} → Fetch strategy by ID                       │
│  └── GET /market/bars/{ticker}     → Proxy to Polygon API                       │
│      └── ?from_ts=...&to_ts=...&timeframe=1&timespan=second                     │
│                                                                                 │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │
                                     │ HTTP
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               POLYGON.IO API                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}         │
│  └── Returns OHLCV bars: { results: [{ t, o, h, l, c, v, vw, n }, ...] }         │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Files to Modify/Create

### Backend (1 file, 2 endpoints)

| File | Changes |
|------|---------|
| `nautilus_news_trader/news_api.py` | Add `GET /market/bars/{ticker}` (Polygon proxy) |
| | Add `GET /strategies/{strategy_id}` (fetch by ID) |

### Frontend (5 files)

| File | Changes |
|------|---------|
| `web/src/App.tsx` | Add route `/trades/:strategyId` |
| `web/src/api.ts` | Add `getMarketBars()`, `getStrategyById()` |
| `web/src/types.ts` | Add `OHLCVBar`, `MarketBarsResponse`, `StrategyDetail` |
| `web/src/components/TradesView.tsx` | Add detail view, clickable rows |
| `web/src/components/TradingChart.tsx` | **NEW** - Candlestick chart component |

---

## Implementation Details

### 1. Backend: OHLCV Proxy Endpoint

```python
# nautilus_news_trader/news_api.py

import requests

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")

@app.get("/market/bars/{ticker}")
async def get_market_bars(
    ticker: str,
    from_ts: int = Query(..., description="Start timestamp (ms)"),
    to_ts: int = Query(..., description="End timestamp (ms)"),
    timeframe: str = Query(default="1", description="Multiplier: 1, 5, 15"),
    timespan: str = Query(default="second", description="second, minute"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Proxy to Polygon.io aggregates endpoint for OHLCV data."""
    verify_api_key(x_api_key)

    if not POLYGON_API_KEY:
        raise HTTPException(500, "Polygon API key not configured")

    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{timeframe}/{timespan}/{from_ts}/{to_ts}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            raise HTTPException(response.status_code, f"Polygon API error: {response.text}")
        return response.json()
    except requests.RequestException as e:
        raise HTTPException(502, f"Failed to fetch from Polygon: {str(e)}")
```

### 2. Backend: Get Strategy by ID

```python
@app.get("/strategies/{strategy_id}")
async def get_strategy_by_id(
    strategy_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get a specific strategy execution by ID."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    strategy = db.get_strategy_by_id(strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")
    return strategy
```

### 3. Frontend Types

```typescript
// web/src/types.ts

export interface OHLCVBar {
  t: number    // timestamp (ms)
  o: number    // open
  h: number    // high
  l: number    // low
  c: number    // close
  v: number    // volume
  vw?: number  // volume-weighted avg price
  n?: number   // number of trades
}

export interface MarketBarsResponse {
  ticker: string
  status: string
  resultsCount: number
  results: OHLCVBar[]
}

export interface StrategyDetail {
  id: string
  news_id: string
  ticker: string
  strategy_type?: string
  strategy_name?: string
  entry_price?: number
  exit_price?: number
  entry_time?: string
  exit_time?: string
  qty?: number
  pnl?: number
  pnl_percent?: number
  status: string
  stop_reason?: string
  headline?: string
  pub_time?: string
}
```

### 4. Frontend API Functions

```typescript
// web/src/api.ts

export async function getMarketBars(
  ticker: string,
  fromTs: number,
  toTs: number,
  timeframe: string = '1',
  timespan: string = 'second'
): Promise<MarketBarsResponse> {
  const params = new URLSearchParams({
    from_ts: String(fromTs),
    to_ts: String(toTs),
    timeframe,
    timespan,
  })
  return fetchApi(`/market/bars/${ticker}?${params}`)
}

export async function getStrategyById(strategyId: string): Promise<StrategyDetail> {
  return fetchApi(`/strategies/${strategyId}`)
}
```

### 5. TradingChart Component (lightweight-charts v5)

```typescript
// web/src/components/TradingChart.tsx

import { useRef, useEffect } from 'react'
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  HistogramSeries,
} from 'lightweight-charts'
import type { OHLCVBar } from '../types'

interface TradingChartProps {
  bars: OHLCVBar[]
  newsTime?: number    // timestamp in ms - when news was published
  entryTime?: number   // timestamp in ms - when entry was filled
  entryPrice?: number
  exitTime?: number    // timestamp in ms - when exit was filled
  exitPrice?: number
  ticker: string
}

export function TradingChart({
  bars,
  newsTime,
  entryTime,
  entryPrice,
  exitTime,
  exitPrice,
  ticker,
}: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return

    // Create chart with dark theme
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#1e293b' },
        textColor: '#cbd5e1',
      },
      grid: {
        vertLines: { color: '#334155' },
        horzLines: { color: '#334155' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
      },
    })

    // Add candlestick series (v5 syntax)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      borderVisible: false,
    })

    // Convert bars to chart format (time in seconds)
    const candleData = bars.map(bar => ({
      time: bar.t / 1000,
      open: bar.o,
      high: bar.h,
      low: bar.l,
      close: bar.c,
    }))
    candleSeries.setData(candleData)

    // Add volume series as overlay (bottom 30%)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',  // overlay
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    })

    const volumeData = bars.map(bar => ({
      time: bar.t / 1000,
      value: bar.v,
      color: bar.c >= bar.o ? '#22c55e40' : '#ef444440',
    }))
    volumeSeries.setData(volumeData)

    // Add news/entry/exit markers (v5 syntax)
    const markers = []

    // News event marker (orange circle)
    if (newsTime) {
      markers.push({
        time: newsTime / 1000,
        position: 'aboveBar' as const,
        color: '#f97316',  // orange
        shape: 'circle' as const,
        text: 'NEWS',
      })
    }

    // Entry marker (green arrow up)
    if (entryTime && entryPrice) {
      markers.push({
        time: entryTime / 1000,
        position: 'belowBar' as const,
        color: '#22c55e',  // green
        shape: 'arrowUp' as const,
        text: `Entry $${entryPrice.toFixed(2)}`,
      })
    }

    // Exit marker (red arrow down)
    if (exitTime && exitPrice) {
      markers.push({
        time: exitTime / 1000,
        position: 'aboveBar' as const,
        color: '#ef4444',  // red
        shape: 'arrowDown' as const,
        text: `Exit $${exitPrice.toFixed(2)}`,
      })
    }

    if (markers.length > 0) {
      createSeriesMarkers(candleSeries, markers)
    }

    // Fit content to view
    chart.timeScale().fitContent()

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({
        width: containerRef.current?.clientWidth || 800,
      })
    })
    resizeObserver.observe(containerRef.current)

    // Cleanup
    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [bars, newsTime, entryTime, entryPrice, exitTime, exitPrice])

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-2">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-400">{ticker}</span>
        <span className="text-xs text-gray-500">
          Powered by TradingView Lightweight Charts
        </span>
      </div>
      <div ref={containerRef} style={{ height: '400px' }} />
    </div>
  )
}
```

---

## Timeframe Mapping

| UI Button | `timeframe` | `timespan` | Description |
|-----------|-------------|------------|-------------|
| 1s        | 1           | second     | 1-second bars |
| 5s        | 5           | second     | 5-second bars |
| 15s       | 15          | second     | 15-second bars |
| 1m        | 1           | minute     | 1-minute bars |
| 5m        | 5           | minute     | 5-minute bars |

---

## Time Window Calculation

```typescript
// Calculate time range: 1 min before news → 1 min after exit
const newsTime = new Date(strategy.pub_time).getTime()  // ms
const exitTime = new Date(strategy.exit_time).getTime() // ms

const fromTs = newsTime - (60 * 1000)   // 1 min before news
const toTs = exitTime + (60 * 1000)     // 1 min after exit
```

---

## Environment Variables

| Variable | Location | Purpose |
|----------|----------|---------|
| `POLYGON_API_KEY` | Backend | Polygon.io API authentication |
| `NEWS_API_KEY` | Backend | News API authentication |
| `VITE_API_URL` | Frontend | Backend API URL |
| `VITE_API_KEY` | Frontend | API key for requests |

---

## Data Flow Sequence

```
1. User clicks trade row in /trades
   │
   ▼
2. Navigate to /trades/{strategyId}?tf=1s
   │
   ▼
3. TradesView detects strategyId param
   │
   ├──► 4a. Fetch strategy: GET /strategies/{strategyId}
   │        Returns: ticker, entry/exit times, prices, P&L
   │
   └──► 4b. Calculate time range (1 min before news → 1 min after exit)
   │
   ▼
5. Fetch OHLCV: GET /market/bars/{ticker}?from_ts=...&to_ts=...&timeframe=1&timespan=second
   │
   ▼
6. news_api.py proxies to Polygon.io
   │
   ▼
7. Return OHLCV bars to frontend
   │
   ▼
8. TradingChart renders:
   ├── Candlestick series
   ├── Volume histogram (bottom 30%)
   └── Markers:
       ├── News event (orange circle) - pub_time
       ├── Entry (green arrow up) - entry_time
       └── Exit (red arrow down) - exit_time
```

---

## Testing

### 1. Backend API Testing (curl)

```bash
# Set API URL and key
API_URL="http://localhost:8100"
API_KEY="ntr_2025_pako"

# Test: Get strategy by ID
curl -s -H "X-API-Key: $API_KEY" \
  "$API_URL/strategies/{strategy_id}" | jq

# Test: Get OHLCV bars (1-second bars)
curl -s -H "X-API-Key: $API_KEY" \
  "$API_URL/market/bars/AAPL?from_ts=1702900000000&to_ts=1702901000000&timeframe=1&timespan=second" | jq

# Test: Get OHLCV bars (5-minute bars)
curl -s -H "X-API-Key: $API_KEY" \
  "$API_URL/market/bars/AAPL?from_ts=1702900000000&to_ts=1702910000000&timeframe=5&timespan=minute" | jq

# Test: List trades to get real strategy IDs
curl -s -H "X-API-Key: $API_KEY" \
  "$API_URL/news?traded_only=true&limit=5" | jq '.[].id'
```

### 2. Frontend URL Testing

```
# List view
http://localhost:5173/trades

# Detail view (replace with real strategy ID from step 1)
http://localhost:5173/trades/{strategy_id}

# With different timeframes
http://localhost:5173/trades/{strategy_id}?tf=1s
http://localhost:5173/trades/{strategy_id}?tf=5s
http://localhost:5173/trades/{strategy_id}?tf=15s
http://localhost:5173/trades/{strategy_id}?tf=1m
http://localhost:5173/trades/{strategy_id}?tf=5m
```

### 3. Manual Test Checklist

```
Backend:
[ ] GET /strategies/{id} returns strategy with all fields
[ ] GET /strategies/{id} returns 404 for invalid ID
[ ] GET /market/bars/{ticker} returns OHLCV data
[ ] GET /market/bars/{ticker} handles invalid ticker gracefully
[ ] GET /market/bars/{ticker} works with all timeframes (1s, 5s, 15s, 1m, 5m)

Frontend - List View (/trades):
[ ] Shows all completed trades
[ ] Filter buttons work (All/Winners/Losers)
[ ] Clicking row navigates to detail view
[ ] Summary stats are correct (Total P&L, Win Rate)

Frontend - Detail View (/trades/{id}):
[ ] Back button works
[ ] Trade info cards display correctly
[ ] Timeframe buttons switch chart resolution
[ ] URL updates when changing timeframe (?tf=...)
[ ] Direct URL access works (copy/paste URL)

Frontend - Chart:
[ ] Candlesticks render correctly
[ ] Volume bars show at bottom (30% height)
[ ] NEWS marker (orange circle) visible at pub_time
[ ] ENTRY marker (green arrow up) visible at entry_time
[ ] EXIT marker (red arrow down) visible at exit_time
[ ] Chart auto-fits to show all data
[ ] Zoom/pan works with mouse

Edge Cases:
[ ] Handle missing entry_time (order never filled)
[ ] Handle missing exit_time (still open position)
[ ] Handle no OHLCV data (market closed, invalid ticker)
[ ] Handle very short trades (< 1 minute)
[ ] Handle long trades (> 30 minutes)
```

### 4. Get Real Test Data

```bash
# Find a real strategy ID to test with
API_URL="http://35.236.202.231:8100"
API_KEY="ntr_2025_pako"

# Get recent traded news events
curl -s -H "X-API-Key: $API_KEY" \
  "$API_URL/news?traded_only=true&limit=3" | jq '.[] | {id, headline, tickers}'

# Get strategies for a news event
curl -s -H "X-API-Key: $API_KEY" \
  "$API_URL/news/{news_id}/strategies" | jq '.strategies[] | {id, ticker, entry_price, exit_price, pnl}'
```
