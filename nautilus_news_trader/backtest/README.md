# News Trading Backtest Framework

Backtests news trading strategies using NautilusTrader's `BacktestEngine` with simulated execution.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      BacktestEngine                              │
│  - Simulated exchange (order matching, fills, slippage)         │
│  - Event-driven processing in timestamp order                    │
│  - Same execution logic as live trading                          │
└─────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ BenzingaNewsData│  │ Historical Bars │  │ Simulated       │
│ (custom Data)   │  │ (1-second OHLCV)│  │ Exchange        │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                ┌─────────────────────────┐
                │ BacktestNewsController  │
                │ - Same logic as live    │
                │ - Filters, sizing       │
                │ - Spawns strategies     │
                └─────────────────────────┘
                              │
                              ▼
                ┌─────────────────────────┐
                │ NewsVolumeStrategy      │
                │ - Entry limit order     │
                │ - Timed exit            │
                │ - Real order matching   │
                └─────────────────────────┘
```

## Key Insight

The **controller and strategy logic are identical** to production. Only the data sources differ:

| Component | Live | Backtest |
|-----------|------|----------|
| News events | Pub/Sub subscription | `BenzingaNewsData` via `add_data()` |
| Market data | Polygon API | `HistoricalDataProvider` |
| Execution | Alpaca API | Simulated exchange |
| Time | Real clock | Simulated clock |

## Quick Start

```python
from datetime import datetime, timezone
from backtest import BacktestRunner

# Backtest KALA news event
runner = BacktestRunner(
    initial_capital=100_000,
    volume_percentage=0.05,  # 5% of 3s volume
)

results = runner.run_single_event(
    ticker="KALA",
    news_time=datetime(2024, 12, 1, 12, 0, 3, tzinfo=timezone.utc),
    headline="KALA announces FDA approval...",
)

print(f"Strategies spawned: {results['strategies_spawned']}")
print(f"Account: {results['account_report']}")
print(f"Fills: {results['order_fills']}")
```

## CLI Usage

```bash
# Backtest single event
python -m backtest.runner --ticker KALA --date 2024-12-01 --time 12:00:03

# With custom parameters
python -m backtest.runner \
    --ticker KALA \
    --date 2024-12-01 \
    --time 12:00:03 \
    --headline "FDA approval announced" \
    --capital 50000 \
    --volume-pct 0.10
```

## Components

### BenzingaNewsData
Custom `Data` subclass that flows through NautilusTrader's event loop:
```python
from backtest.news_data import BenzingaNewsData

event = BenzingaNewsData(
    news_id="12345",
    headline="Breaking news...",
    tickers=["KALA"],
    url="https://...",
    source="Benzinga",
    tags=["FDA"],
    ts_event=1701432003000000000,  # nanoseconds
    ts_init=1701432003000000000,
)
```

### HistoricalDataProvider
Provides market data lookups by timestamp:
```python
from backtest.data_provider import HistoricalDataProvider

# From Polygon API
provider = HistoricalDataProvider.from_polygon_api(
    symbols=["KALA"],
    start_date=start,
    end_date=end,
    api_key="your_key",
)

# Or from CSV
provider = HistoricalDataProvider.from_polygon_csv(
    csv_paths={"KALA": "data/kala_1s.csv"},
    market_caps={"KALA": 50_000_000},
)

# Query like live Polygon client
volume_data = provider.check_trading_activity("KALA", news_time)
```

### BacktestNewsController
Same filtering and spawning logic as production controller:
- News age filter
- Price filter
- Momentum filter
- Market cap filter
- Volume-based position sizing
- Spawns `NewsVolumeStrategy` instances

## Extending

### Add custom filters
Modify `BacktestNewsControllerConfig` and `_process_ticker()` method.

### Different strategy
Create a new controller that spawns your strategy instead of `NewsVolumeStrategy`.

### Multiple events
```python
news_events = [
    BenzingaNewsData.from_dict(e) for e in historical_events
]

results = runner.run_from_events(
    news_events=news_events,
    data_provider=provider,
    start_time=start,
    end_time=end,
)
```
