#!/usr/bin/env python3
"""
Volume 10% Strategy Controller.

Spawns NewsVolumeStrategy with 10% of 3-second volume.
Fixed 7-minute exit.
"""

from datetime import datetime
from typing import Optional
from decimal import Decimal

from nautilus_trader.trading.trader import Trader
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from shared.base_controller import BaseNewsController, BaseNewsControllerConfig
from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig, STRATEGY_VERSION

# Strategy name for order ID grouping
STRATEGY_NAME = "vol10"


class Volume10PctControllerConfig(BaseNewsControllerConfig, frozen=True):
    """Configuration for Volume 10% Controller."""

    # Disable V16 filters for volume strategy
    require_positive_momentum: bool = False
    session_filter_enabled: bool = False
    max_market_cap: float = 1e12  # No market cap filter

    # Strategy-specific
    volume_percentage: float = 0.10
    exit_delay_minutes: int = 7


class Volume10PctController(BaseNewsController):
    """Controller that spawns NewsVolumeStrategy at 10% volume."""

    def __init__(self, trader: Trader, config: Optional[Volume10PctControllerConfig] = None):
        if config is None:
            config = Volume10PctControllerConfig()
        super().__init__(trader, config)

    def _get_strategy_name(self) -> str:
        return "Volume10Pct"

    def _calculate_position_size(self, volume_data: dict, trace_id: str) -> float:
        """Calculate position size as 10% of 3s USD volume."""
        usd_volume = volume_data['volume'] * volume_data['avg_price']
        position_size = usd_volume * self._config.volume_percentage

        if position_size < self._config.min_position_size:
            self.log.info(f"[{trace_id}] Position ${position_size:.2f} < min ${self._config.min_position_size}")
            return 0

        if position_size > self._config.max_position_size:
            position_size = self._config.max_position_size

        self.log.info(f"[{trace_id}] Position size: ${position_size:.2f} (10% of ${usd_volume:.2f})")
        return position_size

    def _spawn_strategy(self, symbol: str, position_size: float, volume_data: dict,
                        headline: str, pub_time: datetime, url: str, trace_id: str):
        """Spawn NewsVolumeStrategy instance."""
        try:
            # Create instrument
            instrument = TestInstrumentProvider.equity(symbol=symbol, venue="ALPACA")
            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)

            # Create strategy
            strategy_id = f"vol10_{symbol}_{int(pub_time.timestamp())}"
            order_id_tag = f"s_{STRATEGY_NAME}_v{STRATEGY_VERSION}_{symbol}"
            strategy_config = NewsVolumeStrategyConfig(
                order_id_tag=order_id_tag,
                ticker=symbol,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,
                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._config.limit_order_offset_pct,
                exit_delay_minutes=self._config.exit_delay_minutes,
                extended_hours=self._config.extended_hours,
                news_headline=headline[:200],
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=trace_id,
            )

            strategy = NewsVolumeStrategy(config=strategy_config)
            self._trader.add_strategy(strategy)
            self._trader.start_strategy(strategy.id)

            self.log.info(f"[{trace_id}] Spawned vol10 strategy: ${position_size:.2f}")

        except Exception as e:
            self.log.error(f"[{trace_id}] Failed to spawn strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
