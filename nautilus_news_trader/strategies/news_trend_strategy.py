#!/usr/bin/env python3
"""
News Trend Strategy for NautilusTrader.

This strategy implements V16/V12 backtest features:
1. Trend score calculation (EMA alignment + slope + smoothness)
2. Trend-based entry (trend_strength >= 95)
3. Trend-based exit (trend_strength < 64)
4. Continuous monitoring loop
5. Danger zone checks (price distance from EMAs)

Uses NautilusTrader's Alpaca execution adapter for order management.
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
import time
import threading
import numpy as np
import pandas as pd
import requests
import os

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.enums import OrderSide, TimeInForce, BarAggregation, PriceType
from nautilus_trader.model.orders import LimitOrder
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.data import Bar, BarType, BarSpecification

# Import trade notifier for GCP alerts (optional for backtest)
try:
    from utils.trade_notifier import get_trade_notifier
except ImportError:
    # Backtest mode - no trade notifications
    def get_trade_notifier():
        return None

# Import trade database for persistence
try:
    from shared.trade_db import get_trade_db
except ImportError:
    try:
        from nautilus_news_trader.shared.trade_db import get_trade_db
    except ImportError:
        def get_trade_db():
            return None

# Import event emitter for SSE streaming
try:
    from utils.event_emitter import emit_strategy_stopped
except ImportError:
    try:
        from nautilus_news_trader.utils.event_emitter import emit_strategy_stopped
    except ImportError:
        def emit_strategy_stopped(*args, **kwargs):
            pass

# Strategy version - bump when logic changes
STRATEGY_VERSION = "1"

# Trend score thresholds (from V12 backtest)
TREND_ENTRY_THRESHOLD = 95.0    # Enter when trend_strength >= this
TREND_EXIT_THRESHOLD = 64.0     # Exit when trend_strength < this

# Danger zone thresholds
MAX_EMA8_DISTANCE_PCT = 15.0    # Skip entry if price >15% from EMA8
MAX_EMA21_DISTANCE_PCT = 25.0   # Skip entry if price >25% from EMA21

# Monitoring interval (seconds)
TREND_CHECK_INTERVAL = 1.0      # Check trend every 1 second


class NewsTrendStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for NewsTrendStrategy."""

    # Required fields
    ticker: str
    instrument_id: str
    strategy_id: str

    # Trading parameters
    position_size_usd: Decimal = Decimal("1000")
    entry_price: Decimal = Decimal("100")
    limit_order_offset_pct: float = 0.01
    extended_hours: bool = True

    # Trend parameters
    trend_entry_threshold: float = TREND_ENTRY_THRESHOLD
    trend_exit_threshold: float = TREND_EXIT_THRESHOLD
    max_ema8_distance_pct: float = MAX_EMA8_DISTANCE_PCT
    max_ema21_distance_pct: float = MAX_EMA21_DISTANCE_PCT
    trend_check_interval: float = TREND_CHECK_INTERVAL

    # Bar catch-up parameters (buffered data from news publish to now)
    bar_interval_seconds: int = 1   # Use 1-second bars for EMAs
    catchup_seconds: int = 60       # Seconds of buffered bars (60s buffer)
    min_catchup_bars: int = 30      # Minimum bars needed for EMA calculation
    entry_window_seconds: int = 60  # Keep checking trend for N seconds after news

    # News metadata
    news_headline: str = ""
    publishing_date: str = ""  # ISO format for catch-up timestamp
    news_url: str = ""
    correlation_id: str = ""

    # Polygon API key (for live price updates during monitoring)
    polygon_api_key: str = ""


class NewsTrendStrategy(Strategy):
    """
    Trend-based news trading strategy.

    Lifecycle:
    1. on_start(): Fetch historical bars, calculate EMAs, check entry conditions
    2. If trend_strength >= 95 and not in danger zone: Enter position
    3. Monitor trend_strength every second
    4. When trend_strength < 64: Exit position
    5. on_position_closed(): Stop strategy

    Position Isolation:
    Multiple instances can trade same ticker. Position queries filtered by strategy_id.
    """

    def __init__(self, config: NewsTrendStrategyConfig):
        super().__init__(config)
        self._config = config

        self.ticker = config.ticker
        self.instrument_id = InstrumentId(
            symbol=Symbol(config.ticker),
            venue=Venue("ALPACA")
        )
        # Polygon instrument ID for data subscription
        self.polygon_instrument_id = InstrumentId(
            symbol=Symbol(config.ticker),
            venue=Venue("POLYGON")
        )

        # State tracking
        self.entry_order_id = None
        self.exit_order_id = None
        self.entry_filled = False
        self.entry_timer_set = False
        self.position_open = False
        self.monitoring_active = False
        self.stop_monitoring = threading.Event()
        self.entry_decision_made = False

        # Bar catch-up tracking
        self.catchup_complete = False
        self.catchup_since_ms: Optional[int] = None
        self.catchup_bar_count = 0
        self.catchup_prices: List[float] = []  # Close prices for EMA calculation
        self.catchup_volumes: List[int] = []   # Volumes for analysis
        self.live_bar_count = 0
        self.bar_type: Optional[BarType] = None

        # Parse publishing_date to get catchup_since_ms and entry window
        self.entry_window_end_ms: Optional[int] = None  # Deadline for trend entry check
        if config.publishing_date:
            try:
                pub_time = datetime.fromisoformat(config.publishing_date.replace('Z', '+00:00'))
                catchup_start = pub_time - timedelta(seconds=config.catchup_seconds)
                self.catchup_since_ms = int(catchup_start.timestamp() * 1000)
                # Entry window = pub_time + entry_window_seconds
                entry_deadline = pub_time + timedelta(seconds=config.entry_window_seconds)
                self.entry_window_end_ms = int(entry_deadline.timestamp() * 1000)
            except Exception:
                self.catchup_since_ms = None
                self.entry_window_end_ms = None

        # EMA data (calculated from catch-up bars)
        self.current_trend_strength: float = 0.0
        self.current_ema8: float = 0.0
        self.current_ema21: float = 0.0
        self.current_ema55: float = 0.0
        self.current_price: float = 0.0
        self.catchup_vwap: float = 0.0

        # Instrument reference
        self.instrument: Optional[Instrument] = None

        # Trade notifier
        self.trade_notifier = get_trade_notifier()

        # Trade database for persistence
        self._trade_db = get_trade_db()

        # Stop reason tracking
        self._stop_reason: Optional[str] = None

        # Latency tracking
        self.entry_order_time_ms: Optional[float] = None
        self.exit_order_time_ms: Optional[float] = None
        self.exit_decision_price: Optional[float] = None
        self.entry_fill_price: Optional[float] = None

        # Status logging
        self.status_timer_set = False

    def on_start(self):
        """Called when strategy starts - subscribe to bars and wait for catch-up."""
        trace_id = self._config.correlation_id
        self.log.info(f"🚀 [TRACE:{trace_id}] NewsTrendStrategy starting for {self.ticker}")
        self.log.info(f"   [TRACE:{trace_id}] Strategy ID: {self._config.strategy_id}")
        self.log.info(f"   [TRACE:{trace_id}] Position size: ${self._config.position_size_usd}")
        self.log.info(f"   [TRACE:{trace_id}] Entry threshold: trend >= {self._config.trend_entry_threshold}")
        self.log.info(f"   [TRACE:{trace_id}] Exit threshold: trend < {self._config.trend_exit_threshold}")
        self.log.info(f"📰 [TRACE:{trace_id}] News: {self._config.news_headline}")

        # Get instrument from cache
        self.instrument = self.cache.instrument(self.instrument_id)
        if not self.instrument:
            self.log.error(f"❌ Could not find instrument {self.instrument_id} in cache")
            self.stop()
            return

        # Subscribe to 1-second bars with catch-up
        # Entry will be triggered in on_bar() after catch-up completes
        try:
            self._subscribe_bars_with_catchup()
            self.log.info(f"📡 [TRACE:{trace_id}] Waiting for catch-up bars...")
        except Exception as e:
            self.log.error(f"❌ [TRACE:{trace_id}] Could not subscribe to bars: {e}")
            self.stop()
            return

        # Set catch-up timeout - if no bars arrive within 10 seconds, skip
        self.clock.set_timer(
            name=f"catchup_timeout_{self._config.strategy_id}",
            interval=pd.Timedelta(seconds=10),
            callback=self._on_catchup_timeout,
        )
        self.log.info(f"⏱️  [TRACE:{trace_id}] Catch-up timeout set: 10 seconds")

        # Set up periodic status logging every 10 seconds
        self.clock.set_timer(
            name=f"status_log_{self._config.strategy_id}",
            interval=pd.Timedelta(seconds=10),
            callback=self._on_status_timer,
        )
        self.status_timer_set = True

    def _subscribe_bars_with_catchup(self):
        """Subscribe to 1-second bars with 'since' for catch-up replay."""
        trace_id = self._config.correlation_id

        # Create bar specification for 1-second bars
        bar_spec = BarSpecification(
            step=1,
            aggregation=BarAggregation.SECOND,
            price_type=PriceType.LAST,
        )

        # Create bar type for Polygon instrument
        self.bar_type = BarType(
            instrument_id=self.polygon_instrument_id,
            bar_spec=bar_spec,
        )

        # Subscribe with 'since' for catch-up
        if self.catchup_since_ms:
            self.log.info(
                f"📊 [TRACE:{trace_id}] Subscribing to 1s bars "
                f"with since={self.catchup_since_ms} (catchup={self._config.catchup_seconds}s)"
            )

            # Try to get the Polygon data client for since parameter
            try:
                data_engine = self.msgbus._endpoints.get("DataEngine.execute")
                if data_engine:
                    for client in data_engine._clients.values():
                        if hasattr(client, 'subscribe_bars_with_since'):
                            import asyncio
                            asyncio.create_task(
                                client.subscribe_bars_with_since(
                                    self.bar_type,
                                    since_ms=self.catchup_since_ms,
                                )
                            )
                            self.log.info(f"✅ [TRACE:{trace_id}] Bar subscription sent with since parameter")
                            return
            except Exception as e:
                self.log.warning(f"⚠️ [TRACE:{trace_id}] Could not access data client: {e}")

        # Fallback: use standard subscription
        self.log.info(f"📊 [TRACE:{trace_id}] Subscribing to 1s bars (no catchup)")
        self.subscribe_bars(self.bar_type)

    def _cancel_catchup_timeout(self):
        """Cancel the catch-up timeout timer."""
        try:
            timer_name = f"catchup_timeout_{self._config.strategy_id}"
            self.clock.cancel_timer(timer_name)
        except Exception:
            pass

    def _on_catchup_timeout(self, event):
        """Handle catch-up timeout - no bars received."""
        trace_id = self._config.correlation_id
        if not self.catchup_complete and not self.entry_decision_made:
            self.log.warning(f"⏰ [TRACE:{trace_id}] Catch-up timeout: no bars received in 10s")
            self.log.info(f"⏭️  [TRACE:{trace_id}] SKIP: No market data available")
            self.entry_decision_made = True
            self.stop()

    def _on_status_timer(self, event):
        """Log full status every 10 seconds."""
        trace_id = self._config.correlation_id
        total_volume = sum(self.catchup_volumes) if self.catchup_volumes else 0

        # Position status
        if self.position_open:
            pos_status = "OPEN"
        elif self.entry_filled:
            pos_status = "CLOSED"
        elif self.entry_decision_made:
            pos_status = "SKIPPED"
        else:
            pos_status = "PENDING"

        self.log.info(f"📈 [TRACE:{trace_id}] STATUS [{pos_status}] {self.ticker}:")
        self.log.info(f"   [TRACE:{trace_id}]   Bars: {self.catchup_bar_count} catchup + {self.live_bar_count} live")
        self.log.info(f"   [TRACE:{trace_id}]   Volume: {total_volume:,}")
        self.log.info(f"   [TRACE:{trace_id}]   Price: ${self.current_price:.4f} | VWAP: ${self.catchup_vwap:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   EMA8: ${self.current_ema8:.4f} | EMA21: ${self.current_ema21:.4f} | EMA55: ${self.current_ema55:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   Trend: {self.current_trend_strength:.1f} (entry>={self._config.trend_entry_threshold}, exit<{self._config.trend_exit_threshold})")

    def on_bar(self, bar: Bar):
        """Handle incoming bars - accumulate during catch-up, then check trend."""
        if bar.bar_type != self.bar_type:
            return

        trace_id = self._config.correlation_id
        current_time_ms = self.clock.timestamp_ms()
        bar_end_time_ms = bar.ts_event // 1_000_000

        bar_age_ms = current_time_ms - bar_end_time_ms
        is_catchup = bar_age_ms > 500

        if is_catchup:
            self.catchup_bar_count += 1
            bar_close = float(bar.close)
            bar_volume = int(bar.volume)
            self.catchup_prices.append(bar_close)
            self.catchup_volumes.append(bar_volume)

            self.log.debug(
                f"   [TRACE:{trace_id}] CATCHUP bar #{self.catchup_bar_count}: "
                f"C={bar_close:.2f} V={bar_volume} (age={bar_age_ms}ms)"
            )
        else:
            # First live bar = catch-up complete
            if not self.catchup_complete:
                self.catchup_complete = True
                self._cancel_catchup_timeout()
                self._calculate_emas_and_check_entry()

            self.live_bar_count += 1
            bar_close = float(bar.close)

            # Update EMAs incrementally
            self._update_ema_incremental(bar_close)

            # Check entry window and trend conditions
            if not self.entry_decision_made and not self.entry_filled:
                self._check_trend_entry_window()

            self.log.debug(
                f"   [TRACE:{trace_id}] LIVE bar #{self.live_bar_count}: "
                f"C={bar_close:.2f} trend={self.current_trend_strength:.1f}"
            )

    def _check_trend_entry_window(self):
        """Check trend condition during entry window (1 minute after news)."""
        trace_id = self._config.correlation_id
        current_ms = self.clock.timestamp_ms()

        # Check if entry window expired
        if self.entry_window_end_ms and current_ms > self.entry_window_end_ms:
            self.log.info(
                f"⏱️  [TRACE:{trace_id}] Entry window expired, trend={self.current_trend_strength:.1f}"
            )
            self.log.info(f"⏭️  [TRACE:{trace_id}] SKIP: Trend never reached {self._config.trend_entry_threshold}")
            self.entry_decision_made = True
            self.stop()
            return

        # Check danger zone
        ema8_distance = abs((self.current_price - self.current_ema8) / self.current_ema8 * 100) if self.current_ema8 > 0 else 0
        ema21_distance = abs((self.current_price - self.current_ema21) / self.current_ema21 * 100) if self.current_ema21 > 0 else 0

        in_danger_zone = (
            ema8_distance > self._config.max_ema8_distance_pct or
            ema21_distance > self._config.max_ema21_distance_pct
        )

        if in_danger_zone:
            return  # Still in danger zone, keep waiting

        # Check trend entry condition
        if self.current_trend_strength >= self._config.trend_entry_threshold:
            self.log.info(
                f"✅ [TRACE:{trace_id}] Trend reached {self.current_trend_strength:.1f} >= {self._config.trend_entry_threshold}"
            )
            self.entry_decision_made = True
            self._place_entry_order_with_price(self.current_price)

    def _calculate_emas_and_check_entry(self):
        """Calculate EMAs from catch-up bars and do first trend check."""
        if self.entry_decision_made:
            return

        trace_id = self._config.correlation_id

        # Check minimum bars
        min_bars = self._config.min_catchup_bars
        if self.catchup_bar_count < min_bars:
            self.log.info(
                f"⏭️  [TRACE:{trace_id}] SKIP: Only {self.catchup_bar_count} bars < min {min_bars}"
            )
            self.stop()
            return

        # Calculate EMAs from catch-up prices
        prices = np.array(self.catchup_prices)
        volumes = np.array(self.catchup_volumes)

        # Calculate VWAP
        total_volume = volumes.sum()
        if total_volume > 0:
            self.catchup_vwap = (prices * volumes).sum() / total_volume
        else:
            self.catchup_vwap = prices[-1] if len(prices) > 0 else 0

        # Calculate EMAs using pandas for accuracy
        df = pd.DataFrame({'close': prices})
        df['ema8'] = df['close'].ewm(span=8, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()

        # Get current values
        self.current_price = prices[-1]
        self.current_ema8 = df['ema8'].iloc[-1]
        self.current_ema21 = df['ema21'].iloc[-1]
        self.current_ema55 = df['ema55'].iloc[-1] if len(prices) >= 55 else df['ema21'].iloc[-1]

        # Calculate trend strength (simplified for 60 bars)
        self._calculate_trend_strength_from_df(df)

        self.log.info(
            f"📊 [TRACE:{trace_id}] CATCH-UP COMPLETE: "
            f"{self.catchup_bar_count} bars, {total_volume:,} volume, VWAP=${self.catchup_vwap:.2f}"
        )
        self.log.info(
            f"   [TRACE:{trace_id}] Price: ${self.current_price:.2f}, "
            f"EMA8: ${self.current_ema8:.2f}, EMA21: ${self.current_ema21:.2f}"
        )
        self.log.info(f"   [TRACE:{trace_id}] Trend strength: {self.current_trend_strength:.1f}")

        # Check danger zone
        ema8_distance = abs((self.current_price - self.current_ema8) / self.current_ema8 * 100) if self.current_ema8 > 0 else 0
        ema21_distance = abs((self.current_price - self.current_ema21) / self.current_ema21 * 100) if self.current_ema21 > 0 else 0

        self.log.info(
            f"   [TRACE:{trace_id}] EMA8 distance: {ema8_distance:.1f}% (max: {self._config.max_ema8_distance_pct}%)"
        )
        self.log.info(
            f"   [TRACE:{trace_id}] EMA21 distance: {ema21_distance:.1f}% (max: {self._config.max_ema21_distance_pct}%)"
        )

        in_danger_zone = (
            ema8_distance > self._config.max_ema8_distance_pct or
            ema21_distance > self._config.max_ema21_distance_pct
        )

        if in_danger_zone:
            self.log.info(f"⏭️  [TRACE:{trace_id}] SKIP: In DANGER ZONE")
            self.stop()
            return

        # Check trend entry condition
        if self.current_trend_strength >= self._config.trend_entry_threshold:
            self.log.info(
                f"✅ [TRACE:{trace_id}] Trend OK: {self.current_trend_strength:.1f} >= {self._config.trend_entry_threshold}"
            )
            self.entry_decision_made = True
            self._place_entry_order_with_price(self.catchup_vwap)
        else:
            # Don't skip yet - keep monitoring during entry window
            remaining_ms = (self.entry_window_end_ms - self.clock.timestamp_ms()) if self.entry_window_end_ms else 0
            remaining_sec = max(0, remaining_ms / 1000)
            self.log.info(
                f"👁️  [TRACE:{trace_id}] Trend {self.current_trend_strength:.1f} < {self._config.trend_entry_threshold}, "
                f"monitoring for {remaining_sec:.0f}s..."
            )
            # entry_decision_made stays False, will keep checking in on_bar()

    def _calculate_trend_strength_from_df(self, df: pd.DataFrame):
        """Calculate trend strength from catch-up bar dataframe."""
        # EMA alignment score (0-100)
        # With 60 bars, we only have EMA8, EMA21, EMA55 reliably
        alignment = 0
        if df['ema8'].iloc[-1] > df['ema21'].iloc[-1]:
            alignment += 50
        if df['ema21'].iloc[-1] > df['ema55'].iloc[-1]:
            alignment += 50

        # EMA slope strength (0-100) - are EMAs rising?
        slope_8 = (df['ema8'].iloc[-1] - df['ema8'].iloc[-5]) / df['ema8'].iloc[-5] * 100 if len(df) >= 5 else 0
        slope_21 = (df['ema21'].iloc[-1] - df['ema21'].iloc[-5]) / df['ema21'].iloc[-5] * 100 if len(df) >= 5 else 0

        # Positive slope = bullish, normalize to 0-100
        slope_score = min(100, max(0, (slope_8 + slope_21) * 10 + 50))

        # Final trend strength
        self.current_trend_strength = 0.6 * alignment + 0.4 * slope_score

    def _update_ema_incremental(self, new_price: float):
        """Update EMAs incrementally with new price for live monitoring."""
        def update_ema(old_ema: float, price: float, span: int) -> float:
            alpha = 2 / (span + 1)
            return alpha * price + (1 - alpha) * old_ema

        self.current_price = new_price
        self.current_ema8 = update_ema(self.current_ema8, new_price, 8)
        self.current_ema21 = update_ema(self.current_ema21, new_price, 21)
        self.current_ema55 = update_ema(self.current_ema55, new_price, 55)

        # Recalculate alignment-based trend strength
        alignment = 0
        if self.current_ema8 > self.current_ema21:
            alignment += 50
        if self.current_ema21 > self.current_ema55:
            alignment += 50

        self.current_trend_strength = alignment

        # Check exit condition only when position is open (not during entry monitoring)
        if self.position_open and self.entry_filled:
            if self.current_trend_strength < self._config.trend_exit_threshold:
                trace_id = self._config.correlation_id
                self.log.info(f"📉 [TRACE:{trace_id}] TREND EXIT: {self.current_trend_strength:.1f} < {self._config.trend_exit_threshold}")
                self._place_exit_order()

    def _place_entry_order_with_price(self, entry_price: float):
        """Place limit buy order with given price."""
        try:
            trace_id = self._config.correlation_id

            limit_price = entry_price * (1 + self._config.limit_order_offset_pct)
            position_size = float(self._config.position_size_usd)
            qty = int(position_size / limit_price)

            if qty == 0:
                self.log.warning(f"⏭️  [TRACE:{trace_id}] SKIP: Calculated qty=0")
                self.stop()
                return

            order: LimitOrder = self.order_factory.limit(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=self.instrument.make_qty(qty),
                price=self.instrument.make_price(limit_price),
                time_in_force=TimeInForce.DAY,
                post_only=False,
            )

            self.entry_order_id = order.client_order_id
            self.log.info(f"✅ [TRACE:{trace_id}] Submitting BUY: {self.ticker} x{qty} @ ${limit_price:.2f}")
            self.log.info(f"   [TRACE:{trace_id}] Trend: {self.current_trend_strength:.1f}, VWAP: ${entry_price:.2f}")

            self.entry_order_time_ms = time.time() * 1000
            self.submit_order(order)

            # Set up entry tracking
            self.entry_timer_set = True
            self.clock.set_time_alert_ns(
                name=f"check_fill_{self._config.strategy_id}",
                alert_time_ns=self.clock.timestamp_ns() + 1_000_000,
                callback=self._check_fast_fill,
            )

            if self.trade_notifier:
                self.trade_notifier.notify_trade(
                    side='BUY',
                    ticker=self.ticker,
                    quantity=qty,
                    price=limit_price,
                    order_id=str(order.client_order_id),
                    news_headline=f"[TREND:{self.current_trend_strength:.0f}] {self._config.news_headline}",
                    strategy_id=self._config.strategy_id
                )

        except Exception as e:
            self.log.error(f"❌ [TRACE:{trace_id}] Error placing entry order: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            self.stop()

    def _fetch_and_calculate_emas(self) -> bool:
        """DEPRECATED: Now using catch-up bars instead of REST API."""
        return False  # No longer used
        try:
            # Calculate time range - fetch last N minutes of 1-second bars
            now = datetime.now(timezone.utc)
            bars_needed = self._config.historical_bars
            from_time = now - timedelta(seconds=bars_needed + 60)  # Extra buffer

            from_ms = int(from_time.timestamp() * 1000)
            to_ms = int(now.timestamp() * 1000)

            # Query Polygon for 1-second bars
            url = f"https://api.polygon.io/v2/aggs/ticker/{self.ticker}/range/1/second/{from_ms}/{to_ms}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'limit': 50000,
                'apiKey': self._config.polygon_api_key
            }

            self.log.info(f"   [TRACE:{trace_id}] Fetching {bars_needed}+ bars from Polygon...")

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if len(results) < 200:
                self.log.warning(f"   [TRACE:{trace_id}] Insufficient bars: {len(results)} < 200 minimum")
                return False

            self.log.info(f"   [TRACE:{trace_id}] Received {len(results)} bars from Polygon")

            # Convert to DataFrame
            self.bars_df = pd.DataFrame(results)
            self.bars_df['timestamp'] = pd.to_datetime(self.bars_df['t'], unit='ms', utc=True)
            self.bars_df = self.bars_df.set_index('timestamp')

            # Calculate EMAs
            self.bars_df['ema8'] = self.bars_df['c'].ewm(span=8, adjust=False).mean()
            self.bars_df['ema21'] = self.bars_df['c'].ewm(span=21, adjust=False).mean()
            self.bars_df['ema55'] = self.bars_df['c'].ewm(span=55, adjust=False).mean()
            self.bars_df['ema100'] = self.bars_df['c'].ewm(span=100, adjust=False).mean()
            self.bars_df['ema200'] = self.bars_df['c'].ewm(span=200, adjust=False).mean()

            # Calculate trend strength
            self._calculate_trend_strength()

            # Store current values
            last_row = self.bars_df.iloc[-1]
            self.current_price = last_row['c']
            self.current_ema8 = last_row['ema8']
            self.current_ema21 = last_row['ema21']
            self.current_ema55 = last_row['ema55']
            self.current_ema100 = last_row['ema100']
            self.current_ema200 = last_row['ema200']
            self.current_trend_strength = last_row['trend_strength']

            return True

        except Exception as e:
            self.log.error(f"❌ [TRACE:{trace_id}] Error fetching historical data: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _calculate_trend_strength(self):
        """
        Calculate composite trend strength (0-100) from V12 methodology:
        - 40% EMA alignment
        - 40% EMA slope strength
        - 20% Slope smoothness
        """
        df = self.bars_df

        # 1. EMA ALIGNMENT (0-100%)
        cond1 = (df['ema8'] > df['ema21']).astype(int)
        cond2 = (df['ema21'] > df['ema55']).astype(int)
        cond3 = (df['ema55'] > df['ema100']).astype(int)
        cond4 = (df['ema100'] > df['ema200']).astype(int)
        alignment_pct = (cond1 + cond2 + cond3 + cond4) / 4.0 * 100

        # 2. EMA SLOPE STRENGTH (0-100%)
        slope_8 = df['ema8'].pct_change() * 100
        slope_21 = df['ema21'].pct_change() * 100
        slope_55 = df['ema55'].pct_change() * 100

        # Normalize slopes to 0-1 range
        def normalize_slope(s):
            s_clean = s.fillna(0)
            s_min = s_clean.min()
            s_max = s_clean.max()
            if s_max == s_min:
                return pd.Series(0.5, index=s.index)
            return (s_clean - s_min) / (s_max - s_min)

        norm_slope_8 = normalize_slope(slope_8)
        norm_slope_21 = normalize_slope(slope_21)
        norm_slope_55 = normalize_slope(slope_55)

        ema_slope_strength = ((norm_slope_8 + norm_slope_21 + norm_slope_55) / 3.0) * 100

        # 3. SLOPE SMOOTHNESS (0-100%)
        slope_21_std = slope_21.rolling(20, min_periods=1).std().fillna(0)
        slope_smoothness = (1 / (1 + slope_21_std)) * 100

        # 4. FINAL TREND STRENGTH (weighted combination)
        df['trend_strength'] = (
            0.4 * alignment_pct +
            0.4 * ema_slope_strength +
            0.2 * slope_smoothness
        )

        # Fill any NaN values
        df['trend_strength'] = df['trend_strength'].fillna(0)

    def _start_danger_zone_monitoring(self):
        """Monitor for price to pull back from danger zone, then enter."""
        trace_id = self._config.correlation_id
        self.log.info(f"👁️  [TRACE:{trace_id}] Starting danger zone monitoring...")

        def monitor_pullback():
            check_count = 0
            max_checks = 60  # Max 60 seconds of monitoring

            while not self.stop_monitoring.is_set() and check_count < max_checks:
                try:
                    # Fetch latest price
                    current_price = self._get_polygon_quote()
                    if current_price is None:
                        time.sleep(1)
                        check_count += 1
                        continue

                    # Recalculate EMA distances
                    ema8_distance = abs((current_price - self.current_ema8) / self.current_ema8 * 100)
                    ema21_distance = abs((current_price - self.current_ema21) / self.current_ema21 * 100)

                    in_danger_zone = (
                        ema8_distance > self._config.max_ema8_distance_pct or
                        ema21_distance > self._config.max_ema21_distance_pct
                    )

                    if not in_danger_zone:
                        self.log.info(f"✅ [TRACE:{trace_id}] Pulled back from danger zone!")
                        self.log.info(f"   [TRACE:{trace_id}] EMA8 distance: {ema8_distance:.2f}%, EMA21: {ema21_distance:.2f}%")

                        # Update current price
                        self.current_price = current_price

                        # Check trend condition again
                        if self.current_trend_strength >= self._config.trend_entry_threshold:
                            self._place_entry_order()
                            return
                        else:
                            self.log.info(f"⏭️  [TRACE:{trace_id}] Trend too weak after pullback")
                            self.stop()
                            return

                    time.sleep(1)
                    check_count += 1

                except Exception as e:
                    self.log.error(f"❌ [TRACE:{trace_id}] Danger zone monitoring error: {e}")
                    time.sleep(1)
                    check_count += 1

            # Timeout - stop strategy
            self.log.info(f"⏱️  [TRACE:{trace_id}] Danger zone monitoring timeout (60s)")
            self.stop()

        # Run in background thread
        thread = threading.Thread(target=monitor_pullback, daemon=True)
        thread.start()

    def _start_trend_monitoring(self):
        """Start background thread to monitor trend for exit."""
        trace_id = self._config.correlation_id
        self.monitoring_active = True
        self.log.info(f"👁️  [TRACE:{trace_id}] Starting trend monitoring (exit when < {self._config.trend_exit_threshold})")

        def monitor_trend():
            while not self.stop_monitoring.is_set() and self.position_open:
                try:
                    # Fetch latest bar and update EMAs
                    if self._update_trend():
                        self.log.debug(f"   [TRACE:{trace_id}] Trend: {self.current_trend_strength:.2f}")

                        # Check exit condition
                        if self.current_trend_strength < self._config.trend_exit_threshold:
                            self.log.info(f"📉 [TRACE:{trace_id}] TREND EXIT SIGNAL!")
                            self.log.info(f"   [TRACE:{trace_id}] trend_strength {self.current_trend_strength:.2f} < {self._config.trend_exit_threshold}")
                            self._place_exit_order()
                            return

                    time.sleep(self._config.trend_check_interval)

                except Exception as e:
                    self.log.error(f"❌ [TRACE:{trace_id}] Trend monitoring error: {e}")
                    time.sleep(1)

        # Run in background thread
        thread = threading.Thread(target=monitor_trend, daemon=True)
        thread.start()

    def _update_trend(self) -> bool:
        """Fetch latest bar and update trend strength."""
        try:
            # Get latest price from Alpaca
            current_price = self._get_polygon_quote()
            if current_price is None:
                return False

            self.current_price = current_price

            # Update EMAs incrementally (exponential smoothing)
            def update_ema(old_ema: float, new_price: float, span: int) -> float:
                alpha = 2 / (span + 1)
                return alpha * new_price + (1 - alpha) * old_ema

            self.current_ema8 = update_ema(self.current_ema8, current_price, 8)
            self.current_ema21 = update_ema(self.current_ema21, current_price, 21)
            self.current_ema55 = update_ema(self.current_ema55, current_price, 55)
            self.current_ema100 = update_ema(self.current_ema100, current_price, 100)
            self.current_ema200 = update_ema(self.current_ema200, current_price, 200)

            # Calculate alignment score (0-100)
            alignment = 0
            if self.current_ema8 > self.current_ema21:
                alignment += 25
            if self.current_ema21 > self.current_ema55:
                alignment += 25
            if self.current_ema55 > self.current_ema100:
                alignment += 25
            if self.current_ema100 > self.current_ema200:
                alignment += 25

            # Simplified trend strength (primarily alignment-based during monitoring)
            # Full slope calculation would require bar history - use alignment as proxy
            self.current_trend_strength = alignment

            return True

        except Exception as e:
            self.log.error(f"Error updating trend: {e}")
            return False

    def _get_polygon_quote(self) -> Optional[float]:
        """Get current price from Polygon for exit pricing."""
        try:
            polygon_key = self._config.polygon_api_key
            if not polygon_key:
                polygon_key = os.environ.get('POLYGON_API_KEY')
            if not polygon_key:
                return None

            # Get last trade from Polygon (most accurate current price)
            url = f"https://api.polygon.io/v2/last/trade/{self.ticker}"
            params = {'apiKey': polygon_key}

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', {})
                price = results.get('p')  # Last trade price
                if price:
                    return float(price)

            # Fallback to last quote if no trade
            quote_url = f"https://api.polygon.io/v3/quotes/{self.ticker}"
            quote_params = {'apiKey': polygon_key, 'limit': 1, 'sort': 'timestamp', 'order': 'desc'}

            quote_response = requests.get(quote_url, params=quote_params, timeout=5)
            if quote_response.status_code == 200:
                quote_data = quote_response.json()
                results = quote_data.get('results', [])
                if results:
                    # Use bid price for sell orders
                    bid_price = results[0].get('bid_price')
                    if bid_price:
                        return float(bid_price)
                    ask_price = results[0].get('ask_price')
                    if ask_price:
                        return float(ask_price)

            return None

        except Exception as e:
            self.log.error(f"Error getting Polygon quote: {e}")
            return None

    def _check_fast_fill(self, event):
        """Check cache for fast fills that arrived before RUNNING state."""
        self.entry_timer_set = False
        trace_id = self._config.correlation_id

        if not self.entry_order_id:
            return

        order = self.cache.order(self.entry_order_id)
        if order and order.is_filled and not self.entry_filled:
            self.log.info(f"⚡ [TRACE:{trace_id}] Fast fill detected via cache check")
            self.entry_filled = True
            self.position_open = True
            self.entry_fill_price = float(order.avg_px) if order.avg_px else None
            self._start_trend_monitoring()
        elif not self.entry_filled:
            self.log.info(f"   [TRACE:{trace_id}] Cache check complete - waiting for fill callback")

    def _place_entry_order(self):
        """Place limit buy order with offset to ensure fill."""
        try:
            trace_id = self._config.correlation_id

            entry_price = float(self._config.entry_price)
            limit_price = entry_price * (1 + self._config.limit_order_offset_pct)

            position_size = float(self._config.position_size_usd)
            qty = int(position_size / limit_price)

            if qty == 0:
                self.log.warning(f"Calculated qty=0 for ${position_size} @ ${limit_price}")
                self.stop()
                return

            order: LimitOrder = self.order_factory.limit(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=self.instrument.make_qty(qty),
                price=self.instrument.make_price(limit_price),
                time_in_force=TimeInForce.DAY,
                post_only=False,
            )

            self.entry_order_id = order.client_order_id
            self.log.info(f"✅ [TRACE:{trace_id}] Submitting BUY order: {self.ticker} x{qty} @ ${limit_price:.2f}")
            self.log.info(f"   [TRACE:{trace_id}] Trend strength: {self.current_trend_strength:.2f}")

            self.entry_order_time_ms = time.time() * 1000
            self.submit_order(order)

            self.trade_notifier.notify_trade(
                side='BUY',
                ticker=self.ticker,
                quantity=qty,
                price=limit_price,
                order_id=str(order.client_order_id),
                news_headline=f"[TREND:{self.current_trend_strength:.0f}] {self._config.news_headline}",
                strategy_id=self._config.strategy_id
            )

        except Exception as e:
            self.log.error(f"❌ Error placing entry order: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            self.stop()

    def on_order_accepted(self, order):
        """Called when order is accepted by execution venue."""
        trace_id = self._config.correlation_id
        self.log.info(f"📝 [TRACE:{trace_id}] Order ACCEPTED: {order.client_order_id}")

    def on_order_filled(self, event):
        """Called when an order is filled."""
        trace_id = self._config.correlation_id
        fill_time_ms = time.time() * 1000
        fill_price = float(event.last_px)

        self.log.info(f"✅ [TRACE:{trace_id}] Order FILLED: {event.client_order_id}")
        self.log.info(f"   [TRACE:{trace_id}] Side: {event.order_side}, Qty: {event.last_qty}, Price: {event.last_px}")

        is_entry_order = (
            self.entry_order_id is not None and
            event.client_order_id is not None and
            str(event.client_order_id) == str(self.entry_order_id)
        )

        if is_entry_order and not self.entry_filled:
            self.entry_filled = True
            self.position_open = True
            self.entry_fill_price = fill_price

            # Log slippage
            try:
                entry_price = float(self._config.entry_price)
                if entry_price > 0:
                    slippage = fill_price - entry_price
                    slippage_pct = (slippage / entry_price) * 100
                    latency_ms = fill_time_ms - self.entry_order_time_ms if self.entry_order_time_ms else 0
                    self.log.info(f"📊 [TRACE:{trace_id}] ENTRY SLIPPAGE: ${slippage:+.4f} ({slippage_pct:+.2f}%)")
                    self.log.info(f"⏱️  [TRACE:{trace_id}] ENTRY LATENCY: {latency_ms:.0f}ms")
            except Exception as e:
                self.log.warning(f"Could not calculate slippage: {e}")

            # Start trend monitoring for exit
            self._start_trend_monitoring()

        is_exit_order = (
            self.exit_order_id is not None and
            event.client_order_id is not None and
            str(event.client_order_id) == str(self.exit_order_id)
        )

        if is_exit_order:
            self.position_open = False
            try:
                if self.exit_decision_price and self.exit_decision_price > 0:
                    slippage = self.exit_decision_price - fill_price
                    slippage_pct = (slippage / self.exit_decision_price) * 100
                    self.log.info(f"📊 [TRACE:{trace_id}] EXIT SLIPPAGE: ${slippage:+.4f} ({slippage_pct:+.2f}%)")

                    if self.entry_fill_price and float(self._config.entry_price) > 0:
                        entry_slip = self.entry_fill_price - float(self._config.entry_price)
                        exit_slip = self.exit_decision_price - fill_price
                        total = entry_slip + exit_slip
                        total_pct = (total / float(self._config.entry_price)) * 100
                        self.log.info(f"📊 [TRACE:{trace_id}] TOTAL SLIPPAGE: ${total:+.4f} ({total_pct:+.2f}%)")
            except Exception as e:
                self.log.warning(f"Could not calculate exit slippage: {e}")

    def on_order_rejected(self, event):
        """Called when order is rejected."""
        trace_id = self._config.correlation_id
        self.log.error(f"❌ [TRACE:{trace_id}] Order REJECTED: {event.client_order_id}")
        self.log.error(f"   [TRACE:{trace_id}] Reason: {event.reason}")
        self.stop()

    def on_order_cancelled(self, event):
        """Called when order cancellation is confirmed."""
        trace_id = self._config.correlation_id
        self.log.info(f"📝 [TRACE:{trace_id}] Order CANCELLED: {event.client_order_id}")

        # Update order status in database
        if self._trade_db:
            self._trade_db.update_order_cancelled(str(event.client_order_id))

    def _place_exit_order(self):
        """Place limit sell order to exit position."""
        try:
            trace_id = self._config.correlation_id

            positions = self.cache.positions_open(
                instrument_id=self.instrument_id,
                strategy_id=self.id,
            )
            position = positions[0] if positions else None

            if not position:
                self.log.warning(f"No open position for {self.ticker}")
                self.stop()
                return

            qty = position.quantity

            current_price = self._get_polygon_quote()
            if not current_price:
                last_quote = self.cache.quote_tick(self.instrument_id)
                if last_quote:
                    current_price = float(last_quote.bid_price)
                else:
                    last_trade = self.cache.trade_tick(self.instrument_id)
                    if last_trade:
                        current_price = float(last_trade.price)
                    else:
                        self.log.error(f"No market data for {self.ticker}")
                        self.stop()
                        return

            self.exit_decision_price = current_price
            limit_price = current_price * (1 - self._config.limit_order_offset_pct)

            order: LimitOrder = self.order_factory.limit(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty,
                price=self.instrument.make_price(limit_price),
                time_in_force=TimeInForce.DAY,
                post_only=False,
            )

            self.exit_order_id = order.client_order_id
            self.log.info(f"✅ [TRACE:{trace_id}] Submitting SELL order: {self.ticker} x{qty} @ ${limit_price:.2f}")
            self.log.info(f"   [TRACE:{trace_id}] Exit trigger: trend_strength {self.current_trend_strength:.2f}")

            self.exit_order_time_ms = time.time() * 1000
            self.submit_order(order)

            self.trade_notifier.notify_trade(
                side='SELL',
                ticker=self.ticker,
                quantity=int(qty),
                price=limit_price,
                order_id=str(order.client_order_id),
                news_headline=f"[TREND EXIT:{self.current_trend_strength:.0f}] {self._config.news_headline}",
                strategy_id=self._config.strategy_id
            )

        except Exception as e:
            self.log.error(f"❌ Error placing exit order: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            self.stop()

    def on_position_closed(self, position):
        """Called when position is closed."""
        trace_id = self._config.correlation_id
        self.log.info(f"💰 [TRACE:{trace_id}] Position CLOSED for {self.ticker}")
        self.log.info(f"   [TRACE:{trace_id}] Realized PnL: {position.realized_pnl}")
        self.position_open = False
        self.stop()

    def on_stop(self):
        """Called when strategy stops."""
        trace_id = self._config.correlation_id
        self.log.info(f"🛑 [TRACE:{trace_id}] NewsTrendStrategy stopping for {self.ticker}")

        # Log final indicator values for comparison with historical fetch
        self.log.info(f"📊 [TRACE:{trace_id}] FINAL INDICATORS (for comparison):")
        self.log.info(f"   [TRACE:{trace_id}]   Catchup bars: {self.catchup_bar_count}")
        self.log.info(f"   [TRACE:{trace_id}]   Catchup volume: {sum(self.catchup_volumes) if self.catchup_volumes else 0:,}")
        self.log.info(f"   [TRACE:{trace_id}]   VWAP: ${self.catchup_vwap:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   Final price: ${self.current_price:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   EMA8: ${self.current_ema8:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   EMA21: ${self.current_ema21:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   EMA55: ${self.current_ema55:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   Trend strength: {self.current_trend_strength:.1f}")

        # Signal monitoring threads to stop
        self.stop_monitoring.set()
        self.monitoring_active = False

        # Cancel catch-up timeout timer
        self._cancel_catchup_timeout()

        # Cancel status logging timer
        if self.status_timer_set:
            try:
                self.clock.cancel_timer(f"status_log_{self._config.strategy_id}")
                self.status_timer_set = False
            except Exception:
                pass

        # Unsubscribe from bars
        if self.bar_type:
            try:
                self.unsubscribe_bars(self.bar_type)
            except Exception:
                pass

        # Cancel fast-fill check timer
        if self.entry_timer_set:
            try:
                self.clock.cancel_time_alert(f"check_fill_{self._config.strategy_id}")
                self.entry_timer_set = False
            except Exception:
                pass

        # Cancel unfilled entry order
        if self.entry_order_id and not self.entry_filled:
            try:
                order = self.cache.order(self.entry_order_id)
                if order and order.is_open:
                    self.cancel_order(order)
                    self.log.info(f"✅ [TRACE:{trace_id}] Entry order cancel requested")
            except Exception as e:
                self.log.error(f"❌ Error cancelling entry order: {e}")

        # Exit any open position
        positions = self.cache.positions_open(
            instrument_id=self.instrument_id,
            strategy_id=self.id,
        )
        position = positions[0] if positions else None

        if position:
            self.log.info(f"⚠️  [TRACE:{trace_id}] Open position on stop - placing exit order")
            self._place_exit_order_on_stop()

        # Determine stop reason if not already set
        if not self._stop_reason:
            if self.entry_filled:
                self._stop_reason = "completed"
            elif not self.catchup_complete:
                self._stop_reason = "insufficient_bars"
            elif not self.entry_decision_made:
                self._stop_reason = "no_trend"
            else:
                self._stop_reason = "no_fill"

        # Update database with strategy stopped
        if self._trade_db:
            try:
                self._trade_db.update_strategy_stopped(self._config.strategy_id, self._stop_reason)
                self.log.info(f"   [TRACE:{trace_id}] Database updated: stopped with reason '{self._stop_reason}'")
            except Exception as e:
                self.log.error(f"   [TRACE:{trace_id}] Error updating database: {e}")

        # Emit strategy stopped event for SSE streaming
        emit_strategy_stopped(
            news_id=self._config.news_id,
            strategy_id=self._config.strategy_id,
            reason=self._stop_reason,
        )

    def _place_exit_order_on_stop(self):
        """Place exit order when strategy is stopped with open position."""
        try:
            trace_id = self._config.correlation_id

            positions = self.cache.positions_open(
                instrument_id=self.instrument_id,
                strategy_id=self.id,
            )
            position = positions[0] if positions else None

            if not position:
                return

            qty = position.quantity

            current_price = self._get_polygon_quote()
            if not current_price:
                last_quote = self.cache.quote_tick(self.instrument_id)
                if last_quote:
                    current_price = float(last_quote.bid_price)
                else:
                    last_trade = self.cache.trade_tick(self.instrument_id)
                    if last_trade:
                        current_price = float(last_trade.price)

            if not current_price:
                current_price = float(self._config.entry_price)
                self.log.warning(f"   [TRACE:{trace_id}] Using entry price: ${current_price:.2f}")

            self.exit_decision_price = current_price
            limit_price = current_price * (1 - self._config.limit_order_offset_pct)

            order: LimitOrder = self.order_factory.limit(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty,
                price=self.instrument.make_price(limit_price),
                time_in_force=TimeInForce.DAY,
                post_only=False,
            )

            self.exit_order_id = order.client_order_id
            self.log.info(f"✅ [TRACE:{trace_id}] EXIT on stop: {self.ticker} x{qty} @ ${limit_price:.2f}")

            self.exit_order_time_ms = time.time() * 1000
            self.submit_order(order)

            self.trade_notifier.notify_trade(
                side='SELL',
                ticker=self.ticker,
                quantity=int(qty),
                price=limit_price,
                order_id=str(order.client_order_id),
                news_headline=f"[EXIT ON STOP] {self._config.news_headline}",
                strategy_id=self._config.strategy_id
            )

        except Exception as e:
            self.log.error(f"❌ Error placing exit on stop: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
