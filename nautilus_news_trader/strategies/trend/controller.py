#!/usr/bin/env python3
"""
Trend Strategy Controller.

Spawns NewsTrendStrategy with trend-based entry/exit.
Entry: trend_strength >= 95
Exit: trend_strength < 64
"""

from datetime import datetime
from typing import Optional
from decimal import Decimal

from nautilus_trader.trading.trader import Trader
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from shared.base_controller import BaseNewsController, BaseNewsControllerConfig
from strategies.news_trend_strategy import NewsTrendStrategy, NewsTrendStrategyConfig, STRATEGY_VERSION

# Strategy name for order ID grouping
STRATEGY_NAME = "trend"


class TrendControllerConfig(BaseNewsControllerConfig, frozen=True):
    """Configuration for Trend Controller."""

    # Strategy-specific
    volume_percentage: float = 0.05  # For position sizing
    trend_entry_threshold: float = 95.0
    trend_exit_threshold: float = 64.0
    historical_bars: int = 300  # For EMA calculation


class TrendController(BaseNewsController):
    """Controller that spawns NewsTrendStrategy with trend-based entry/exit."""

    def __init__(self, trader: Trader, config: Optional[TrendControllerConfig] = None):
        if config is None:
            config = TrendControllerConfig()
        super().__init__(trader, config)

    def _get_strategy_name(self) -> str:
        return "Trend"

    def _calculate_position_size(self, volume_data: dict, trace_id: str) -> float:
        """Calculate position size as 5% of 3s USD volume."""
        usd_volume = volume_data['volume'] * volume_data['avg_price']
        position_size = usd_volume * self._config.volume_percentage

        if position_size < self._config.min_position_size:
            self.log.info(f"[{trace_id}] Position ${position_size:.2f} < min ${self._config.min_position_size}")
            return 0

        if position_size > self._config.max_position_size:
            position_size = self._config.max_position_size

        self.log.info(f"[{trace_id}] Position size: ${position_size:.2f}")
        return position_size

    def _spawn_strategy(self, symbol: str, position_size: float, volume_data: dict,
                        headline: str, pub_time: datetime, url: str, trace_id: str):
        """Spawn NewsTrendStrategy instance."""
        try:
            # Create instrument
            instrument = TestInstrumentProvider.equity(symbol=symbol, venue="ALPACA")
            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)

            # Create strategy
            strategy_id = f"trend_{symbol}_{int(pub_time.timestamp())}"
            order_id_tag = f"s_{STRATEGY_NAME}_v{STRATEGY_VERSION}_{symbol}"
            strategy_config = NewsTrendStrategyConfig(
                order_id_tag=order_id_tag,
                ticker=symbol,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,
                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._config.limit_order_offset_pct,
                extended_hours=self._config.extended_hours,
                trend_entry_threshold=self._config.trend_entry_threshold,
                trend_exit_threshold=self._config.trend_exit_threshold,
                historical_bars=self._config.historical_bars,
                news_headline=headline[:200],
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=trace_id,
                polygon_api_key=self._config.polygon_api_key,
            )

            strategy = NewsTrendStrategy(config=strategy_config)
            self._trader.add_strategy(strategy)
            self._trader.start_strategy(strategy.id)

            self.log.info(f"[{trace_id}] Spawned trend strategy: ${position_size:.2f}")
            self.log.info(f"[{trace_id}]   Entry: trend >= {self._config.trend_entry_threshold}")
            self.log.info(f"[{trace_id}]   Exit: trend < {self._config.trend_exit_threshold}")

        except Exception as e:
            self.log.error(f"[{trace_id}] Failed to spawn strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
