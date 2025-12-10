#!/usr/bin/env python3
"""
Backtest runner for news trading strategies.

Wires together:
- BacktestEngine with simulated exchange
- BacktestNewsController
- Historical market data
- News events

Usage:
    python -m backtest.runner --ticker KALA --date 2024-12-01
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.model.data import CustomData, DataType, Bar, BarType
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from backtest.news_data import BenzingaNewsData, BENZINGA_NEWS_DATA_TYPE
from backtest.backtest_controller import BacktestNewsController, BacktestNewsControllerConfig
from backtest.data_provider import HistoricalDataProvider


class BacktestRunner:
    """
    Runs backtests for news trading strategies.

    Example:
        runner = BacktestRunner()
        results = runner.run_single_event(
            ticker="KALA",
            news_time=datetime(2024, 12, 1, 12, 0, 3, tzinfo=timezone.utc),
            headline="KALA announces FDA approval...",
        )
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        volume_percentage: float = 0.05,
        polygon_api_key: Optional[str] = None,
        log_level: str = "INFO",
    ):
        self.initial_capital = initial_capital
        self.volume_percentage = volume_percentage
        self.polygon_api_key = polygon_api_key or os.getenv("POLYGON_API_KEY")
        self.log_level = log_level

    def run_single_event(
        self,
        ticker: str,
        news_time: datetime,
        headline: str,
        data_provider: Optional[HistoricalDataProvider] = None,
        market_data_window_minutes: int = 15,
    ) -> dict:
        """
        Backtest a single news event.

        Parameters
        ----------
        ticker : str
            The ticker symbol (e.g., "KALA")
        news_time : datetime
            When the news was published (UTC)
        headline : str
            News headline
        data_provider : HistoricalDataProvider, optional
            Pre-loaded data provider. If None, fetches from Polygon.
        market_data_window_minutes : int
            Minutes of market data to load around news event

        Returns
        -------
        dict
            Backtest results including trades, PnL, etc.
        """
        # Fetch historical data if not provided
        if data_provider is None:
            start = news_time - timedelta(minutes=1)
            end = news_time + timedelta(minutes=market_data_window_minutes)

            data_provider = HistoricalDataProvider.from_polygon_api(
                symbols=[ticker],
                start_date=start,
                end_date=end,
                api_key=self.polygon_api_key,
                log_func=print,
            )

        # Create news event
        news_event = BenzingaNewsData(
            news_id=f"backtest_{ticker}_{int(news_time.timestamp())}",
            headline=headline,
            tickers=[ticker],
            url="",
            source="Backtest",
            tags=[],
            ts_event=int(news_time.timestamp() * 1e9),
            ts_init=int(news_time.timestamp() * 1e9),
        )

        # Run backtest
        return self._run_backtest(
            news_events=[news_event],
            data_provider=data_provider,
            tickers=[ticker],
            start_time=news_time - timedelta(seconds=5),
            end_time=news_time + timedelta(minutes=market_data_window_minutes),
        )

    def run_from_events(
        self,
        news_events: List[BenzingaNewsData],
        data_provider: HistoricalDataProvider,
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """
        Run backtest with pre-loaded news events and market data.

        Parameters
        ----------
        news_events : List[BenzingaNewsData]
            List of news events to process
        data_provider : HistoricalDataProvider
            Historical market data provider
        start_time : datetime
            Backtest start time
        end_time : datetime
            Backtest end time

        Returns
        -------
        dict
            Backtest results
        """
        # Get unique tickers
        tickers = set()
        for event in news_events:
            for ticker in event.tickers:
                tickers.add(ticker.split(":")[-1])

        return self._run_backtest(
            news_events=news_events,
            data_provider=data_provider,
            tickers=list(tickers),
            start_time=start_time,
            end_time=end_time,
        )

    def _run_backtest(
        self,
        news_events: List[BenzingaNewsData],
        data_provider: HistoricalDataProvider,
        tickers: List[str],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Run the actual backtest."""

        # Configure engine
        config = BacktestEngineConfig(
            trader_id=TraderId("BACKTEST-001"),
            logging=LoggingConfig(log_level=self.log_level),
        )
        engine = BacktestEngine(config=config)

        # Add venue (simulated exchange)
        ALPACA = Venue("ALPACA")
        engine.add_venue(
            venue=ALPACA,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=USD,
            starting_balances=[Money(self.initial_capital, USD)],
        )

        # Add instruments
        instruments = {}
        for ticker in tickers:
            instrument = TestInstrumentProvider.equity(symbol=ticker, venue="ALPACA")
            engine.add_instrument(instrument)
            instruments[ticker] = instrument

        # Convert historical bars to NautilusTrader format and add as data
        for ticker in tickers:
            bars_df = data_provider.get_bars_for_period(ticker, start_time, end_time)
            if bars_df is not None and not bars_df.empty:
                bars = self._convert_bars(bars_df, instruments[ticker])
                if bars:
                    engine.add_data(bars)
                    print(f"Added {len(bars)} bars for {ticker}")

        # Wrap news events in CustomData and add
        news_data = []
        for event in news_events:
            wrapped = CustomData(BENZINGA_NEWS_DATA_TYPE, event)
            news_data.append(wrapped)

        if news_data:
            engine.add_data(news_data, client_id=ClientId("BACKTEST"))
            print(f"Added {len(news_data)} news events")

        # Create controller with historical data provider
        controller_config = BacktestNewsControllerConfig(
            volume_percentage=self.volume_percentage,
        )

        # Create and add controller with trader reference
        controller = BacktestNewsController(
            trader=engine.trader,
            config=controller_config,
            data_provider=data_provider,
        )
        engine.add_actor(controller)

        # Enable dynamic strategy creation by marking trader as having a controller
        # This allows strategies to be added during runtime via Controller.create_strategy()
        engine.trader._has_controller = True

        # Run backtest
        print(f"\nRunning backtest from {start_time} to {end_time}...")
        engine.run()

        # Collect results
        results = {
            "start_time": start_time,
            "end_time": end_time,
            "news_events": len(news_events),
            "strategies_spawned": len(controller._spawned_strategies),
            "account_report": engine.trader.generate_account_report(ALPACA),
            "order_fills": engine.trader.generate_order_fills_report(),
            "positions": engine.trader.generate_positions_report(),
        }

        # Cleanup
        engine.dispose()

        return results

    def _convert_bars(self, df, instrument) -> List[Bar]:
        """Convert DataFrame bars to NautilusTrader Bar objects."""
        from nautilus_trader.model.data import Bar, BarSpecification, BarType
        from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
        from nautilus_trader.model.objects import Price, Quantity

        bar_spec = BarSpecification(
            step=1,
            aggregation=BarAggregation.SECOND,
            price_type=PriceType.LAST,
        )
        bar_type = BarType(
            instrument_id=instrument.id,
            bar_spec=bar_spec,
            aggregation_source=AggregationSource.EXTERNAL,
        )

        # Get instrument price precision (typically 2 for equities)
        price_precision = instrument.price_precision

        bars = []
        for idx, row in df.iterrows():
            ts_event = int(idx.timestamp() * 1e9)
            bar = Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{row['open']:.{price_precision}f}"),
                high=Price.from_str(f"{row['high']:.{price_precision}f}"),
                low=Price.from_str(f"{row['low']:.{price_precision}f}"),
                close=Price.from_str(f"{row['close']:.{price_precision}f}"),
                volume=Quantity.from_str(f"{row['volume']:.0f}"),
                ts_event=ts_event,
                ts_init=ts_event,
            )
            bars.append(bar)

        return bars


def main():
    """Example: Backtest KALA news event."""
    import argparse

    parser = argparse.ArgumentParser(description="Backtest news trading strategy")
    parser.add_argument("--ticker", default="KALA", help="Ticker symbol")
    parser.add_argument("--date", default="2024-12-01", help="News date (YYYY-MM-DD)")
    parser.add_argument("--time", default="12:00:03", help="News time UTC (HH:MM:SS)")
    parser.add_argument("--headline", default="Test news headline", help="News headline")
    parser.add_argument("--capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--volume-pct", type=float, default=0.05, help="Volume percentage")
    args = parser.parse_args()

    # Parse datetime
    dt_str = f"{args.date}T{args.time}"
    news_time = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)

    print("=" * 60)
    print("NEWS TRADING BACKTEST")
    print("=" * 60)
    print(f"Ticker: {args.ticker}")
    print(f"News time: {news_time}")
    print(f"Headline: {args.headline}")
    print(f"Capital: ${args.capital:,.0f}")
    print(f"Volume %: {args.volume_pct * 100:.0f}%")
    print()

    runner = BacktestRunner(
        initial_capital=args.capital,
        volume_percentage=args.volume_pct,
        log_level="INFO",
    )

    results = runner.run_single_event(
        ticker=args.ticker,
        news_time=news_time,
        headline=args.headline,
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
