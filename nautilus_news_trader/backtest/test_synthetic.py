#!/usr/bin/env python3
"""
Test backtest with synthetic data to verify strategy spawning and execution.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.runner import BacktestRunner
from backtest.data_provider import HistoricalDataProvider
from backtest.news_data import BenzingaNewsData


def create_synthetic_data(
    symbol: str,
    start_time: datetime,
    duration_minutes: int = 15,
    initial_price: float = 1.0,
    volume_per_second: int = 10000,
) -> pd.DataFrame:
    """Create synthetic 1-second bar data."""
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    price = initial_price
    for i in range(duration_minutes * 60):
        ts = start_time + timedelta(seconds=i)
        timestamps.append(ts)

        # Simple price movement with slight upward bias
        change = 0.001 * (1 if i % 3 == 0 else -0.5)
        new_price = price * (1 + change)

        opens.append(price)
        highs.append(max(price, new_price) * 1.002)
        lows.append(min(price, new_price) * 0.998)
        closes.append(new_price)
        volumes.append(volume_per_second)

        price = new_price

    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    }, index=pd.DatetimeIndex(timestamps, tz=timezone.utc))

    return df


def main():
    print("=" * 60)
    print("SYNTHETIC BACKTEST TEST")
    print("=" * 60)

    # Test parameters
    symbol = "TEST"
    news_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
    initial_price = 2.50  # Under $5 max price filter

    # Create synthetic data - start 1 minute before news, continue 15 min after
    data_start = news_time - timedelta(minutes=1)
    df = create_synthetic_data(
        symbol=symbol,
        start_time=data_start,
        duration_minutes=20,
        initial_price=initial_price,
        volume_per_second=5000,
    )

    print(f"Created synthetic data: {len(df)} bars")
    print(f"Price range: ${df['close'].min():.4f} - ${df['close'].max():.4f}")
    print(f"Time range: {df.index[0]} to {df.index[-1]}")

    # Create data provider
    data_provider = HistoricalDataProvider(
        bars_data={symbol: df},
        market_caps={symbol: 25_000_000},  # $25M market cap (under $50M filter)
        log_func=print,
    )

    # Check trading activity works
    activity = data_provider.check_trading_activity(symbol, news_time, "test")
    print(f"\nTrading activity at news time: {activity}")

    # Create news event
    news_event = BenzingaNewsData(
        news_id="test_123",
        headline="TEST announces positive Phase 3 trial results",
        tickers=[symbol],
        url="https://example.com/news",
        source="Test",
        tags=["FDA", "Clinical Trial"],
        ts_event=int(news_time.timestamp() * 1e9),
        ts_init=int(news_time.timestamp() * 1e9),
    )

    # Run backtest
    runner = BacktestRunner(
        initial_capital=100_000,
        volume_percentage=0.05,
        log_level="INFO",
    )

    print("\n" + "=" * 60)
    print("RUNNING BACKTEST")
    print("=" * 60)

    results = runner.run_from_events(
        news_events=[news_event],
        data_provider=data_provider,
        start_time=news_time - timedelta(seconds=5),
        end_time=news_time + timedelta(minutes=15),
    )

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Strategies spawned: {results['strategies_spawned']}")
    print(f"\nAccount Report:\n{results['account_report']}")
    print(f"\nOrder Fills:\n{results['order_fills']}")
    print(f"\nPositions:\n{results['positions']}")


if __name__ == "__main__":
    main()
