#!/usr/bin/env python3
"""
Backtest-compatible News Controller.

This controller can run in both live and backtest mode:
- Live: Uses Pub/Sub subscription + live Polygon API
- Backtest: Receives BenzingaNewsData events + uses HistoricalDataProvider

The key insight is that the controller logic is identical - only the
data source changes.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Protocol

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.trading.controller import Controller
from nautilus_trader.trading.trader import Trader
from nautilus_trader.model.data import DataType
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from backtest.news_data import BenzingaNewsData, BENZINGA_NEWS_DATA_TYPE
from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig, STRATEGY_VERSION


class MarketDataProvider(Protocol):
    """Protocol for market data providers (live or historical)."""

    def check_trading_activity(self, symbol: str, at_time: datetime, trace_id: str = "") -> Optional[dict]:
        ...

    def get_market_cap(self, symbol: str) -> Optional[float]:
        ...


class BacktestNewsControllerConfig(ActorConfig, frozen=True):
    """Configuration for backtest news controller."""

    # Strategy parameters
    volume_percentage: float = 0.05
    exit_delay_minutes: int = 7
    min_position_size: float = 100.0
    max_position_size: float = 20000.0
    limit_order_offset_pct: float = 0.01

    # V16 Filters
    max_price: float = 5.00
    max_market_cap: float = 50_000_000
    require_positive_momentum: bool = True

    # News age filter (seconds) - in backtest, this filters based on simulated time
    max_news_age_seconds: int = 10


class BacktestNewsController(Controller):
    """
    News controller that works in both live and backtest mode.

    In backtest mode:
    - Subscribes to BenzingaNewsData via NautilusTrader's data engine
    - Uses injected HistoricalDataProvider for market data
    - Strategies execute against simulated exchange

    The controller logic (filtering, position sizing, strategy spawning)
    is identical to production - only the data source differs.
    """

    def __init__(
        self,
        trader: Trader,
        config: BacktestNewsControllerConfig,
        data_provider: MarketDataProvider,
    ):
        super().__init__(trader, config=config)
        self._config = config
        self._data_provider = data_provider
        self._spawned_strategies = []

    def on_start(self):
        """Subscribe to news data when controller starts."""
        self.log.info("BacktestNewsController starting")
        self.log.info(f"  Volume %: {self._config.volume_percentage * 100:.0f}%")
        self.log.info(f"  Exit delay: {self._config.exit_delay_minutes} min")
        self.log.info(f"  Max price: ${self._config.max_price}")
        self.log.info(f"  Max market cap: ${self._config.max_market_cap / 1e6:.0f}M")

        # Subscribe to news data - the backtest engine will deliver events
        self.subscribe_data(BENZINGA_NEWS_DATA_TYPE)
        self.log.info("Subscribed to BenzingaNewsData")

    def on_data(self, data):
        """Handle incoming data events."""
        if isinstance(data, BenzingaNewsData):
            self._process_news_event(data)

    def _process_news_event(self, news: BenzingaNewsData):
        """Process a news event (same logic as live controller)."""
        headline = news.headline
        tickers = news.tickers
        url = news.url
        news_id = news.news_id

        if not tickers:
            return

        # Get current simulated time from clock
        now_ns = self.clock.timestamp_ns()
        now = datetime.fromtimestamp(now_ns / 1e9, tz=timezone.utc)

        # Calculate news age
        pub_time = datetime.fromtimestamp(news.ts_event / 1e9, tz=timezone.utc)
        age_seconds = (now - pub_time).total_seconds()

        # Generate correlation ID
        first_ticker = tickers[0].split(":")[-1] if tickers else "UNK"
        correlation_id = f"{first_ticker}_{news_id}"

        # Age filter
        if age_seconds > self._config.max_news_age_seconds:
            self.log.debug(f"[{correlation_id}] News too old: {age_seconds:.1f}s")
            return

        self.log.info(f"[{correlation_id}] Processing: {headline[:80]}")
        self.log.info(f"[{correlation_id}] Tickers: {', '.join(tickers)}, Age: {age_seconds:.1f}s")

        # Process each ticker
        for ticker in tickers:
            symbol = ticker.split(":")[-1]
            self._process_ticker(symbol, headline, pub_time, url, correlation_id)

    def _process_ticker(
        self,
        symbol: str,
        headline: str,
        pub_time: datetime,
        url: str,
        correlation_id: str,
    ):
        """Process a single ticker from news event."""
        trace_id = f"{correlation_id}_{symbol}"

        # Check if already has strategy for this ticker
        for strategy in self._spawned_strategies:
            if strategy.ticker == symbol:
                self.log.info(f"[{trace_id}] Already has strategy")
                return

        # Get market data at news time
        volume_data = self._data_provider.check_trading_activity(
            symbol, pub_time, trace_id
        )

        if not volume_data:
            self.log.debug(f"[{trace_id}] No trading activity")
            return

        current_price = volume_data["last_price"]
        price_3s_ago = volume_data.get("price_3s_ago", current_price)

        # Price filter
        if current_price > self._config.max_price:
            self.log.info(f"[{trace_id}] Price ${current_price:.2f} > max ${self._config.max_price}")
            return

        # Momentum filter
        if self._config.require_positive_momentum:
            momentum = (current_price - price_3s_ago) / price_3s_ago if price_3s_ago > 0 else 0
            if momentum <= 0:
                self.log.info(f"[{trace_id}] Negative momentum: {momentum:.2%}")
                return

        # Market cap filter
        market_cap = self._data_provider.get_market_cap(symbol)
        if market_cap and market_cap > self._config.max_market_cap:
            self.log.info(f"[{trace_id}] Market cap ${market_cap/1e6:.0f}M > max")
            return

        # Calculate position size
        usd_volume = volume_data["volume"] * volume_data["avg_price"]
        position_size = usd_volume * self._config.volume_percentage

        if position_size < self._config.min_position_size:
            self.log.info(f"[{trace_id}] Position ${position_size:.2f} < min")
            return

        if position_size > self._config.max_position_size:
            position_size = self._config.max_position_size

        self.log.info(f"[{trace_id}] Position size: ${position_size:.2f}")
        self.log.info(f"[{trace_id}] ALL FILTERS PASSED - spawning strategy")

        # Spawn strategy
        self._spawn_strategy(symbol, position_size, volume_data, headline, pub_time, url, trace_id)

    def _spawn_strategy(
        self,
        symbol: str,
        position_size: float,
        volume_data: dict,
        headline: str,
        pub_time: datetime,
        url: str,
        trace_id: str,
    ):
        """Spawn NewsVolumeStrategy instance."""
        try:
            # Create instrument
            instrument = TestInstrumentProvider.equity(symbol=symbol, venue="ALPACA")
            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)

            # Create strategy config
            strategy_id = f"vol_{symbol}_{int(pub_time.timestamp())}"
            order_id_tag = f"bt_{symbol}"

            strategy_config = NewsVolumeStrategyConfig(
                order_id_tag=order_id_tag,
                ticker=symbol,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,
                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data["last_price"])),
                limit_order_offset_pct=self._config.limit_order_offset_pct,
                exit_delay_minutes=self._config.exit_delay_minutes,
                extended_hours=True,
                news_headline=headline[:200],
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=trace_id,
            )

            # Create and start strategy using Controller's create_strategy method
            # This properly handles adding strategies during runtime
            strategy = NewsVolumeStrategy(config=strategy_config)
            self.create_strategy(strategy, start=True)
            self._spawned_strategies.append(strategy)

            self.log.info(f"[{trace_id}] Spawned strategy: ${position_size:.2f}")

        except Exception as e:
            self.log.error(f"[{trace_id}] Failed to spawn strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def on_stop(self):
        """Clean up when controller stops."""
        self.log.info(f"BacktestNewsController stopped. Spawned {len(self._spawned_strategies)} strategies.")
