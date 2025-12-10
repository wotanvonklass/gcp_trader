"""
Backtesting framework for news trading strategies.

This module provides a complete backtesting infrastructure that:
1. Reuses the actual controller and strategy logic
2. Uses NautilusTrader's BacktestEngine with simulated execution
3. Feeds historical news events and market data

Usage:
    from backtest import BacktestRunner
    from backtest.news_data import BenzingaNewsData
    from backtest.data_provider import HistoricalDataProvider

    # Simple single-event backtest
    runner = BacktestRunner(initial_capital=100_000, volume_percentage=0.05)
    results = runner.run_single_event(
        ticker="KALA",
        news_time=datetime(2024, 12, 1, 12, 0, 3, tzinfo=timezone.utc),
        headline="KALA announces FDA approval..."
    )

    # Or with pre-loaded data
    data_provider = HistoricalDataProvider.from_polygon_api(
        symbols=["KALA", "AKBA"],
        start_date=start,
        end_date=end,
        api_key="your_key"
    )

    news_events = [
        BenzingaNewsData.from_dict(event_dict)
        for event_dict in historical_news
    ]

    results = runner.run_from_events(
        news_events=news_events,
        data_provider=data_provider,
        start_time=start,
        end_time=end,
    )
"""

from backtest.news_data import BenzingaNewsData, BENZINGA_NEWS_DATA_TYPE
from backtest.data_provider import HistoricalDataProvider, MarketDataProvider
from backtest.backtest_controller import BacktestNewsController, BacktestNewsControllerConfig
from backtest.runner import BacktestRunner

__all__ = [
    "BacktestRunner",
    "BenzingaNewsData",
    "BENZINGA_NEWS_DATA_TYPE",
    "HistoricalDataProvider",
    "MarketDataProvider",
    "BacktestNewsController",
    "BacktestNewsControllerConfig",
]
