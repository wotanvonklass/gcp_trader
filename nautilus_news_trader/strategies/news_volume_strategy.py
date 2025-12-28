#!/usr/bin/env python3
"""
Simple News Volume Strategy for NautilusTrader.

This strategy:
1. Enters position immediately with limit order (1% offset)
2. Exits after configured delay (default 7 minutes)

Uses NautilusTrader's Alpaca execution adapter for proper order management.
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional
import time
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.enums import OrderSide, TimeInForce, OrderStatus, BarAggregation, PriceType
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

# Import trade database (optional for backtest)
try:
    from shared.trade_db import get_trade_db
except ImportError:
    try:
        from nautilus_news_trader.shared.trade_db import get_trade_db
    except ImportError:
        def get_trade_db():
            return None

# Import event emitter for real-time monitoring
try:
    from utils.event_emitter import (
        emit_order_placed,
        emit_order_filled,
        emit_order_cancelled,
        emit_strategy_stopped,
    )
    EVENT_EMITTER_AVAILABLE = True
except ImportError:
    EVENT_EMITTER_AVAILABLE = False
    def emit_order_placed(*args, **kwargs): pass
    def emit_order_filled(*args, **kwargs): pass
    def emit_order_cancelled(*args, **kwargs): pass
    def emit_strategy_stopped(*args, **kwargs): pass

# Strategy version - bump when logic changes
STRATEGY_VERSION = "1"


class NewsVolumeStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for NewsVolumeStrategy."""

    # Required fields
    ticker: str
    instrument_id: str
    strategy_id: str

    # Trading parameters
    position_size_usd: Decimal = Decimal("1000")
    entry_price: Decimal = Decimal("100")
    limit_order_offset_pct: float = 0.01
    exit_delay_minutes: int = 7
    extended_hours: bool = True

    # Bar catch-up parameters (data from news publish time to now)
    bar_interval_ms: int = 250    # Millisecond bar interval
    catchup_seconds: int = 5      # Seconds of buffered bars to request (news reaction window)
    min_catchup_volume: int = 100 # Minimum shares in catch-up period to enter

    # News metadata
    news_headline: str = ""
    publishing_date: str = ""  # ISO format: "2024-01-15T10:30:00+00:00"
    news_url: str = ""
    correlation_id: str = ""
    news_id: str = ""  # For event emission to News API


class NewsVolumeStrategy(Strategy):
    """
    Simple strategy that enters on news and exits after delay.

    Lifecycle:
    1. on_start(): Place entry limit order via Nautilus, subscribe to market data
    2. on_order_filled(): Schedule exit timer
    3. on_timer(): Place exit order using real-time quote data
    4. on_position_closed(): Stop strategy

    Position Isolation:
    This strategy is fully isolated - multiple instances can trade the same
    ticker simultaneously without conflicts. Position queries are filtered
    by strategy_id, ensuring each strategy only sees/manages its own position.
    Position IDs follow NautilusTrader's format: {instrument_id}-{strategy_id}
    """

    def __init__(self, config: NewsVolumeStrategyConfig):
        super().__init__(config)
        self._config = config

        # Store ticker for identification
        self.ticker = config.ticker

        # Create Alpaca instrument ID for execution
        self.instrument_id = InstrumentId(
            symbol=Symbol(config.ticker),
            venue=Venue("ALPACA")
        )

        # Create Polygon instrument ID for market data
        self.polygon_instrument_id = InstrumentId(
            symbol=Symbol(config.ticker),
            venue=Venue("POLYGON")
        )

        # Track state
        self.entry_order_id = None
        self.exit_order_id = None
        self.entry_filled = False
        self.entry_timer_set = False
        self.exit_timer_set = False
        self.entry_timeout_set = False  # 5-second entry timeout
        self.awaiting_entry_cancel = False  # Waiting for cancel confirmation after timeout

        # Get instrument reference
        self.instrument: Optional[Instrument] = None

        # Initialize trade notifier for email alerts
        self.trade_notifier = get_trade_notifier()

        # Initialize trade database for order tracking
        self._trade_db = get_trade_db()

        # Slippage and latency tracking
        self.entry_order_time_ms: Optional[float] = None  # When entry order was submitted
        self.exit_order_time_ms: Optional[float] = None   # When exit order was submitted
        self.exit_decision_price: Optional[float] = None  # Market price when exit was decided
        self.entry_fill_price: Optional[float] = None     # Actual entry fill price (avg)

        # Real-time market data from WebSocket
        self.last_trade_price: Optional[float] = None
        self.last_trade_time_ns: Optional[int] = None
        self.last_bid_price: Optional[float] = None
        self.last_ask_price: Optional[float] = None
        self.last_quote_time_ns: Optional[int] = None

        # Bar catch-up tracking (buffered data from news publish to now)
        self.catchup_complete = False
        self.catchup_since_ms: Optional[int] = None  # Timestamp for bar replay
        self.catchup_bar_count = 0
        self.catchup_volume = 0  # Total volume from catch-up bars
        self.catchup_last_close = 0.0  # Last bar close price (used for entry)
        self.live_bar_count = 0
        self.bar_type: Optional[BarType] = None
        self.entry_decision_made = False  # Prevent duplicate entry attempts

        # Parse publishing_date to get catchup_since_ms
        if config.publishing_date:
            try:
                pub_time = datetime.fromisoformat(config.publishing_date.replace('Z', '+00:00'))
                # Request bars from N seconds before news publish time
                catchup_start = pub_time - timedelta(seconds=config.catchup_seconds)
                self.catchup_since_ms = int(catchup_start.timestamp() * 1000)
            except Exception:
                self.catchup_since_ms = None

        # Status logging
        self.status_timer_set = False

    def _subscribe_bars_with_catchup(self):
        """Subscribe to millisecond bars with 'since' for catch-up replay."""
        trace_id = self._config.correlation_id

        # Create bar specification for millisecond bars
        bar_spec = BarSpecification(
            step=self._config.bar_interval_ms,
            aggregation=BarAggregation.MILLISECOND,
            price_type=PriceType.LAST,
        )

        # Create bar type for Polygon instrument
        self.bar_type = BarType(
            instrument_id=self.polygon_instrument_id,
            bar_spec=bar_spec,
        )

        # Try to get the Polygon data client and subscribe with 'since'
        if self.catchup_since_ms:
            self.log.info(
                f"📊 [TRACE:{trace_id}] Subscribing to {self._config.bar_interval_ms}ms bars "
                f"with since={self.catchup_since_ms} (catchup={self._config.catchup_seconds}s)"
            )

            # Get data clients from cache/trader to call subscribe_bars_with_since
            try:
                # Access the data engine's clients
                data_engine = self.msgbus._endpoints.get("DataEngine.execute")
                if data_engine:
                    # Find Polygon data client
                    for client in data_engine._clients.values():
                        if hasattr(client, 'subscribe_bars_with_since'):
                            # Call the custom method with since parameter
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

        # Fallback: use standard subscription (no catch-up replay)
        self.log.info(f"📊 [TRACE:{trace_id}] Subscribing to {self._config.bar_interval_ms}ms bars (no catchup)")
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        """Handle incoming bars - accumulate volume during catch-up, trigger entry when complete."""
        if bar.bar_type != self.bar_type:
            return

        trace_id = self._config.correlation_id
        current_time_ms = self.clock.timestamp_ms()
        bar_end_time_ms = bar.ts_event // 1_000_000  # Convert nanoseconds to milliseconds

        # Calculate bar age
        bar_age_ms = current_time_ms - bar_end_time_ms

        # Bars older than 500ms are catch-up (buffered replay)
        is_catchup = bar_age_ms > 500

        if is_catchup:
            self.catchup_bar_count += 1
            # Accumulate volume and track last close price
            bar_volume = int(bar.volume)
            bar_close = float(bar.close)
            self.catchup_volume += bar_volume
            self.catchup_last_close = bar_close  # Always use most recent bar close

            self.log.debug(
                f"   [TRACE:{trace_id}] CATCHUP bar #{self.catchup_bar_count}: "
                f"C={bar_close:.2f} V={bar_volume} (total={self.catchup_volume}) "
                f"(age={bar_age_ms}ms)"
            )
        else:
            # First live bar = catch-up complete
            if not self.catchup_complete:
                self.catchup_complete = True
                self._cancel_catchup_timeout()
                self._check_volume_and_enter()

            self.live_bar_count += 1
            # Update last trade price from bar close
            self.last_trade_price = float(bar.close)
            self.last_trade_time_ns = bar.ts_event

            self.log.debug(
                f"   [TRACE:{trace_id}] LIVE bar #{self.live_bar_count}: "
                f"O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}"
            )

    def _cancel_catchup_timeout(self):
        """Cancel the catch-up timeout timer."""
        try:
            timer_name = f"catchup_timeout_{self._config.strategy_id}"
            self.clock.cancel_timer(timer_name)
        except Exception:
            pass  # Timer may have already fired

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

        # Position status
        if self.entry_filled:
            pos_status = "FILLED"
        elif self.entry_order_id:
            pos_status = "PENDING_FILL"
        elif self.entry_decision_made:
            pos_status = "SKIPPED"
        elif self.catchup_complete:
            pos_status = "READY"
        else:
            pos_status = "CATCHUP"

        # Calculate time remaining until exit
        exit_remaining = ""
        if self.entry_filled and self.exit_timer_set:
            exit_remaining = f" | Exit in ~{self._config.exit_delay_minutes}min"

        self.log.info(f"📈 [TRACE:{trace_id}] STATUS [{pos_status}] {self.ticker}:{exit_remaining}")
        self.log.info(f"   [TRACE:{trace_id}]   Bars: {self.catchup_bar_count} catchup + {self.live_bar_count} live")
        self.log.info(f"   [TRACE:{trace_id}]   Volume: {self.catchup_volume:,} (min: {self._config.min_catchup_volume:,})")
        self.log.info(f"   [TRACE:{trace_id}]   Last close: ${self.catchup_last_close:.4f} | Live: ${self.last_trade_price or 0:.4f}")

    def _check_volume_and_enter(self):
        """Check catch-up volume and enter if sufficient."""
        if self.entry_decision_made:
            return
        self.entry_decision_made = True

        trace_id = self._config.correlation_id

        self.log.info(
            f"📊 [TRACE:{trace_id}] CATCH-UP COMPLETE: "
            f"{self.catchup_bar_count} bars, {self.catchup_volume:,} shares, last=${self.catchup_last_close:.2f}"
        )

        # Check minimum volume threshold
        min_volume = self._config.min_catchup_volume
        if self.catchup_volume < min_volume:
            self.log.info(
                f"⏭️  [TRACE:{trace_id}] SKIP: Volume {self.catchup_volume:,} < min {min_volume:,}"
            )
            self.stop()
            return

        self.log.info(
            f"✅ [TRACE:{trace_id}] Volume OK: {self.catchup_volume:,} >= {min_volume:,}"
        )

        # Use last bar close price (most current price from catch-up window)
        entry_price = self.catchup_last_close if self.catchup_last_close > 0 else float(self._config.entry_price)
        self.log.info(f"   [TRACE:{trace_id}] Using last bar close ${entry_price:.2f} for entry")

        # Place entry order
        self._place_entry_order_with_price(entry_price)

    def _place_entry_order_with_price(self, entry_price: float):
        """Place limit buy order with given price."""
        try:
            trace_id = self._config.correlation_id

            # Calculate limit price (1% above current to ensure fill)
            limit_price = entry_price * (1 + self._config.limit_order_offset_pct)

            # Calculate quantity
            position_size = float(self._config.position_size_usd)
            qty = int(position_size / limit_price)

            if qty == 0:
                self.log.warning(f"⏭️  [TRACE:{trace_id}] SKIP: Calculated qty=0 for ${position_size} @ ${limit_price}")
                self.stop()
                return

            # Create limit order using Nautilus order factory
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

            # Record order submission time for latency tracking
            self.entry_order_time_ms = time.time() * 1000

            # Submit order through Nautilus execution engine
            self.submit_order(order)

            # Set up entry tracking (fast-fill check and timeout)
            self._setup_entry_tracking()

            # Store order in database
            if self._trade_db:
                self._trade_db.insert_order(
                    order_id=str(order.client_order_id),
                    strategy_id=self._config.strategy_id,
                    side='buy',
                    qty=qty,
                    limit_price=limit_price,
                )

            # Emit order placed event
            emit_order_placed(
                news_id=self._config.news_id,
                strategy_id=self._config.strategy_id,
                order_id=str(order.client_order_id),
                order_role='entry',
                side='buy',
                order_type='limit',
                qty=qty,
                limit_price=limit_price,
            )

            # Send trade notification via GCP (skip in backtest mode)
            if self.trade_notifier:
                self.trade_notifier.notify_trade(
                    side='BUY',
                    ticker=self.ticker,
                    quantity=qty,
                    price=limit_price,
                    order_id=str(order.client_order_id),
                    news_headline=self._config.news_headline,
                    strategy_id=self._config.strategy_id
                )

        except Exception as e:
            self.log.error(f"❌ [TRACE:{trace_id}] Error placing entry order: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            self.stop()

    def _setup_entry_tracking(self):
        """Set up fast-fill check and entry timeout after order placed."""
        trace_id = self._config.correlation_id

        # Check for fast fills that arrive before RUNNING state
        self.entry_timer_set = True
        self.clock.set_time_alert_ns(
            name=f"check_fill_{self._config.strategy_id}",
            alert_time_ns=self.clock.timestamp_ns() + 1_000_000,  # 1ms
            callback=self._check_fast_fill,
        )

        # Set 5-second timeout for entry order
        self.entry_timeout_set = True
        self.clock.set_timer(
            name=f"entry_timeout_{self._config.strategy_id}",
            interval=pd.Timedelta(seconds=5),
            callback=self._on_entry_timeout,
        )
        self.log.info(f"⏱️  [TRACE:{trace_id}] Entry timeout set: 5 seconds")

    def _get_current_price(self) -> Optional[float]:
        """Get current price - prefer WebSocket data, fallback to HTTP API."""
        trace_id = self._config.correlation_id

        # Priority 1: Use real-time WebSocket trade data (most accurate)
        if self.last_trade_price and self.last_trade_time_ns:
            age_seconds = (self.clock.timestamp_ns() - self.last_trade_time_ns) / 1e9
            if age_seconds < 60:  # Fresh data (< 60 seconds old)
                self.log.info(f"   [TRACE:{trace_id}] Using WebSocket trade: ${self.last_trade_price:.4f} ({age_seconds:.1f}s ago)")
                return self.last_trade_price
            else:
                self.log.warning(f"   [TRACE:{trace_id}] WebSocket trade stale: {age_seconds:.0f}s old")

        # Priority 2: Use real-time WebSocket quote data (bid price for selling)
        if self.last_bid_price and self.last_quote_time_ns:
            age_seconds = (self.clock.timestamp_ns() - self.last_quote_time_ns) / 1e9
            if age_seconds < 60:  # Fresh data (< 60 seconds old)
                self.log.info(f"   [TRACE:{trace_id}] Using WebSocket quote bid: ${self.last_bid_price:.4f} ({age_seconds:.1f}s ago)")
                return self.last_bid_price
            else:
                self.log.warning(f"   [TRACE:{trace_id}] WebSocket quote stale: {age_seconds:.0f}s old")

        # Priority 3: Check NautilusTrader cache for Polygon data
        cached_trade = self.cache.trade_tick(self.polygon_instrument_id)
        if cached_trade:
            self.log.info(f"   [TRACE:{trace_id}] Using cached trade: ${float(cached_trade.price):.4f}")
            return float(cached_trade.price)

        cached_quote = self.cache.quote_tick(self.polygon_instrument_id)
        if cached_quote:
            self.log.info(f"   [TRACE:{trace_id}] Using cached quote bid: ${float(cached_quote.bid_price):.4f}")
            return float(cached_quote.bid_price)

        # Priority 4: Fallback to HTTP API (slower but reliable)
        self.log.info(f"   [TRACE:{trace_id}] No WebSocket data, falling back to HTTP API")
        return self._get_price_from_http()

    def _get_price_from_http(self) -> Optional[float]:
        """Fallback: Get current price from Polygon HTTP API."""
        try:
            import requests
            import os
            from datetime import datetime, timezone, timedelta

            polygon_key = os.environ.get('POLYGON_API_KEY')
            if not polygon_key:
                self.log.warning("POLYGON_API_KEY not found in environment")
                return None

            # Get last trade from Polygon (most accurate current price)
            url = f"https://api.polygon.io/v2/last/trade/{self.ticker}?apiKey={polygon_key}"

            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', {})
                price = results.get('p')  # Last trade price
                timestamp_ns = results.get('t')  # Timestamp in nanoseconds

                if price and timestamp_ns:
                    # Check quote freshness (reject if older than 60 seconds)
                    trade_time = datetime.fromtimestamp(timestamp_ns / 1e9, tz=timezone.utc)
                    age_seconds = (datetime.now(timezone.utc) - trade_time).total_seconds()

                    self.log.info(f"   HTTP Polygon last trade: ${price:.4f} ({age_seconds:.1f}s ago)")

                    if age_seconds > 60:
                        self.log.warning(f"HTTP Polygon trade stale: {age_seconds:.0f}s old")

                    return float(price)
                elif price:
                    self.log.info(f"   HTTP Polygon last trade: ${price:.4f} (no timestamp)")
                    return float(price)
            else:
                self.log.warning(f"HTTP Polygon trade request failed: {response.status_code}")

            # Fallback: Get latest bar if no trade
            now = datetime.now(timezone.utc)
            start = (now - timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
            end = now.strftime('%Y-%m-%dT%H:%M:%SZ')

            bar_url = f"https://api.polygon.io/v2/aggs/ticker/{self.ticker}/range/1/second/{start}/{end}?apiKey={polygon_key}&limit=10&sort=desc"

            bar_response = requests.get(bar_url, timeout=5)
            if bar_response.status_code == 200:
                bar_data = bar_response.json()
                bars = bar_data.get('results', [])
                if bars:
                    latest_bar = bars[0]
                    close_price = latest_bar.get('c')
                    if close_price:
                        self.log.info(f"   HTTP Polygon bar fallback: ${close_price:.4f}")
                        return float(close_price)

            return None

        except Exception as e:
            self.log.error(f"Error getting HTTP Polygon price: {e}")
            return None

    def on_start(self):
        """Called when strategy starts - place entry order and subscribe to market data."""
        trace_id = self._config.correlation_id
        self.log.info(f"🚀 [TRACE:{trace_id}] NewsVolumeStrategy starting for {self.ticker}")
        self.log.info(f"   [TRACE:{trace_id}] Strategy ID: {self._config.strategy_id}")
        self.log.info(f"   [TRACE:{trace_id}] Position size: ${self._config.position_size_usd}")
        self.log.info(f"   [TRACE:{trace_id}] Entry price: ${self._config.entry_price}")
        self.log.info(f"   [TRACE:{trace_id}] Limit offset: {self._config.limit_order_offset_pct * 100}%")
        self.log.info(f"   [TRACE:{trace_id}] Exit delay: {self._config.exit_delay_minutes} minutes")
        self.log.info(f"   [TRACE:{trace_id}] Extended hours: {self._config.extended_hours}")
        self.log.info(f"📰 [TRACE:{trace_id}] News Details:")
        self.log.info(f"   [TRACE:{trace_id}] Headline: {self._config.news_headline}")
        self.log.info(f"   [TRACE:{trace_id}] Published: {self._config.publishing_date}")
        self.log.info(f"   [TRACE:{trace_id}] URL: {self._config.news_url}")
        self.log.info(f"   [TRACE:{trace_id}] Ticker: {self.ticker}")

        # Get instrument from cache
        self.instrument = self.cache.instrument(self.instrument_id)
        if not self.instrument:
            self.log.error(f"❌ Could not find instrument {self.instrument_id} in cache")
            self.stop()
            return

        # Subscribe to real-time market data from Polygon proxy for exit pricing
        try:
            self.log.info(f"📊 [TRACE:{trace_id}] Subscribing to Polygon data for {self.polygon_instrument_id}")
            self.subscribe_trade_ticks(self.polygon_instrument_id)
            self.subscribe_quote_ticks(self.polygon_instrument_id)
            self.log.info(f"✅ [TRACE:{trace_id}] Subscribed to trades and quotes via WebSocket")
        except Exception as e:
            self.log.warning(f"⚠️ [TRACE:{trace_id}] Could not subscribe to Polygon data: {e}")
            self.log.warning(f"   [TRACE:{trace_id}] Will use HTTP API fallback for exit pricing")

        # Subscribe to millisecond bars with 'since' for catch-up replay
        # Entry will be triggered in on_bar() after catch-up completes and volume is validated
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

    def _check_fast_fill(self, event):
        """Check cache for fast fills that arrived before RUNNING state."""
        self.entry_timer_set = False
        trace_id = self._config.correlation_id

        if not self.entry_order_id:
            return

        # Check if order filled but callback was missed (fast fill before RUNNING)
        order = self.cache.order(self.entry_order_id)
        if order and order.status == OrderStatus.FILLED and not self.entry_filled:
            self.log.info(f"⚡ [TRACE:{trace_id}] Fast fill detected via cache check - order filled before RUNNING state")
            self.entry_filled = True
            self.entry_fill_price = float(order.avg_px) if order.avg_px else None
            self._cancel_entry_timeout()  # Cancel timeout since we filled
            self._schedule_exit()
        elif not self.entry_filled:
            self.log.info(f"   [TRACE:{trace_id}] Cache check complete - order not yet filled, waiting for callback")

    def _on_entry_timeout(self, event):
        """Handle 5-second entry timeout - cancel unfilled order or let partial fills run.

        IMPORTANT: We don't stop immediately after requesting cancel. We wait for either:
        - OrderCancelled event -> safe to stop (no position)
        - OrderFilled event -> order filled despite cancel request, must manage position
        """
        self.entry_timeout_set = False
        trace_id = self._config.correlation_id

        if not self.entry_order_id:
            return

        order = self.cache.order(self.entry_order_id)
        if not order:
            return

        # Check if order has any fills
        filled_qty = float(order.filled_qty) if order.filled_qty else 0

        if filled_qty == 0 and order.is_open:
            # No fills at all - request cancel but WAIT for confirmation before stopping
            self.log.warning(f"⏰ [TRACE:{trace_id}] Entry timeout: No fills after 5s - requesting cancel")
            self.awaiting_entry_cancel = True  # Flag that we're waiting for cancel confirmation
            try:
                self.cancel_order(order)
                self.log.info(f"🧹 [TRACE:{trace_id}] Cancel requested - waiting for confirmation")
                # NOTE: Don't stop here! Wait for on_order_cancelled or on_order_filled
            except Exception as e:
                self.log.error(f"❌ [TRACE:{trace_id}] Error requesting cancel: {e}")
                self.awaiting_entry_cancel = False
                self.stop()  # Only stop if cancel request itself fails
        elif filled_qty > 0 and order.is_open:
            # Partial fill - cancel remaining unfilled portion, keep strategy running
            unfilled_qty = float(order.quantity) - filled_qty
            self.log.info(f"⏰ [TRACE:{trace_id}] Entry timeout: Partial fill ({filled_qty:.0f} filled, {unfilled_qty:.0f} unfilled)")
            self.log.info(f"🧹 [TRACE:{trace_id}] Cancelling unfilled portion, strategy continues with filled shares")
            try:
                self.cancel_order(order)
            except Exception as e:
                self.log.warning(f"⚠️  [TRACE:{trace_id}] Error cancelling partial entry order: {e}")
            # Don't stop - let strategy run with filled shares
        else:
            self.log.info(f"⏰ [TRACE:{trace_id}] Entry timeout: Order already fully filled or closed")

    def _cancel_entry_timeout(self):
        """Cancel the entry timeout timer (called when entry fills)."""
        if self.entry_timeout_set:
            try:
                timer_name = f"entry_timeout_{self._config.strategy_id}"
                self.clock.cancel_timer(timer_name)
                self.entry_timeout_set = False
            except Exception:
                pass  # Timer may have already fired

    def _cancel_unfilled_entry_order(self):
        """Cancel any remaining unfilled portion of entry order (handles partial fills after exit)."""
        if not self.entry_order_id:
            return

        try:
            order = self.cache.order(self.entry_order_id)
            if order and order.is_open:
                trace_id = self._config.correlation_id
                filled_qty = float(order.filled_qty) if order.filled_qty else 0
                unfilled_qty = float(order.quantity) - filled_qty
                if unfilled_qty > 0:
                    self.log.info(f"🧹 [TRACE:{trace_id}] Cancelling unfilled entry order: {unfilled_qty:.0f} shares remaining")
                    self.cancel_order(order)
        except Exception as e:
            self.log.warning(f"Error cancelling unfilled entry order: {e}")

    def _place_entry_order(self):
        """Place limit buy order using config entry price (legacy method)."""
        self._place_entry_order_with_price(float(self._config.entry_price))

    def on_order_accepted(self, order):
        """Called when order is accepted by execution venue."""
        trace_id = self._config.correlation_id
        self.log.info(f"📝 [TRACE:{trace_id}] Order ACCEPTED: {order.client_order_id}")

    def on_order_filled(self, event):
        """Called when an order is filled - schedule exit."""
        trace_id = self._config.correlation_id
        fill_time_ms = time.time() * 1000
        fill_price = float(event.last_px)

        self.log.info(f"✅ [TRACE:{trace_id}] Order FILLED: {event.client_order_id}")
        self.log.info(f"   [TRACE:{trace_id}] Side: {event.order_side}")
        self.log.info(f"   [TRACE:{trace_id}] Filled qty: {event.last_qty}")
        self.log.info(f"   [TRACE:{trace_id}] Fill price: {event.last_px}")

        # Update order in database with fill info
        if self._trade_db:
            self._trade_db.update_order_filled(
                order_id=str(event.client_order_id),
                filled_qty=float(event.last_qty),
                filled_price=fill_price,
            )

        # Check if this is the entry order - use safe comparison
        is_entry_order = (
            self.entry_order_id is not None and
            event.client_order_id is not None and
            str(event.client_order_id) == str(self.entry_order_id)
        )

        if is_entry_order and not self.entry_filled:
            self.entry_filled = True
            self.entry_fill_price = fill_price

            # Handle race condition: if we requested cancel but got filled anyway
            if self.awaiting_entry_cancel:
                self.log.warning(f"⚠️  [TRACE:{trace_id}] Order FILLED despite cancel request - proceeding with position")
                self.awaiting_entry_cancel = False

            # Cancel entry timeout since we got a fill
            self._cancel_entry_timeout()

            # Emit order filled event for entry
            emit_order_filled(
                news_id=self._config.news_id,
                strategy_id=self._config.strategy_id,
                order_id=str(event.client_order_id),
                order_role='entry',
                fill_price=fill_price,
                qty=float(event.last_qty),
            )

            # Calculate entry slippage with error handling
            try:
                entry_price = float(self._config.entry_price)
                if entry_price > 0:
                    entry_slippage = fill_price - entry_price
                    entry_slippage_pct = (entry_slippage / entry_price) * 100

                    latency_ms = 0
                    if self.entry_order_time_ms:
                        latency_ms = fill_time_ms - self.entry_order_time_ms

                    self.log.info(f"📊 [TRACE:{trace_id}] ENTRY SLIPPAGE: ${entry_slippage:+.4f} ({entry_slippage_pct:+.2f}%)")
                    self.log.info(f"   [TRACE:{trace_id}] Decision price: ${entry_price:.4f} → Fill: ${fill_price:.4f}")
                    self.log.info(f"⏱️  [TRACE:{trace_id}] ENTRY LATENCY: {latency_ms:.0f}ms (order → fill)")
            except Exception as e:
                self.log.warning(f"   [TRACE:{trace_id}] Could not calculate entry slippage: {e}")

            # CRITICAL: Always schedule exit, even if slippage calculation failed
            self._schedule_exit()

        # Check if this is the exit order - use safe comparison
        is_exit_order = (
            self.exit_order_id is not None and
            event.client_order_id is not None and
            str(event.client_order_id) == str(self.exit_order_id)
        )

        if is_exit_order:
            # Emit order filled event for exit
            emit_order_filled(
                news_id=self._config.news_id,
                strategy_id=self._config.strategy_id,
                order_id=str(event.client_order_id),
                order_role='exit',
                fill_price=fill_price,
                qty=float(event.last_qty),
            )

            # Calculate exit slippage with error handling
            try:
                if self.exit_decision_price and self.exit_decision_price > 0:
                    exit_slippage = self.exit_decision_price - fill_price
                    exit_slippage_pct = (exit_slippage / self.exit_decision_price) * 100

                    latency_ms = 0
                    if self.exit_order_time_ms:
                        latency_ms = fill_time_ms - self.exit_order_time_ms

                    self.log.info(f"📊 [TRACE:{trace_id}] EXIT SLIPPAGE: ${exit_slippage:+.4f} ({exit_slippage_pct:+.2f}%)")
                    self.log.info(f"   [TRACE:{trace_id}] Decision price: ${self.exit_decision_price:.4f} → Fill: ${fill_price:.4f}")
                    self.log.info(f"⏱️  [TRACE:{trace_id}] EXIT LATENCY: {latency_ms:.0f}ms (order → fill)")

                    # Calculate total round-trip slippage
                    if self.entry_fill_price and float(self._config.entry_price) > 0:
                        entry_slip = self.entry_fill_price - float(self._config.entry_price)
                        exit_slip = self.exit_decision_price - fill_price
                        total_slippage = entry_slip + exit_slip
                        total_slippage_pct = (total_slippage / float(self._config.entry_price)) * 100
                        self.log.info(f"📊 [TRACE:{trace_id}] TOTAL ROUND-TRIP SLIPPAGE: ${total_slippage:+.4f} ({total_slippage_pct:+.2f}%)")
            except Exception as e:
                self.log.warning(f"   [TRACE:{trace_id}] Could not calculate exit slippage: {e}")

            # Cancel any remaining unfilled portion of entry order (handles partial fills)
            self._cancel_unfilled_entry_order()

    def on_order_rejected(self, event):
        """Called when order is rejected."""
        trace_id = self._config.correlation_id
        self.log.error(f"❌ [TRACE:{trace_id}] Order REJECTED: {event.client_order_id}")
        self.log.error(f"   [TRACE:{trace_id}] Reason: {event.reason}")
        self.stop()

    def on_order_cancelled(self, event):
        """Called when order cancellation is confirmed.

        This handles the safe shutdown after entry timeout:
        - If we were awaiting cancel confirmation, now safe to stop
        - If order was cancelled for other reasons, log it
        """
        trace_id = self._config.correlation_id

        # Check if this is the entry order we were waiting to cancel
        is_entry_cancel = (
            self.awaiting_entry_cancel and
            self.entry_order_id is not None and
            str(event.client_order_id) == str(self.entry_order_id)
        )

        if is_entry_cancel:
            self.log.info(f"✅ [TRACE:{trace_id}] Entry order cancel CONFIRMED - safe to stop")
            self.awaiting_entry_cancel = False

            # Update order status in database
            if self._trade_db:
                self._trade_db.update_order_cancelled(str(event.client_order_id))

            self.stop()
        else:
            self.log.info(f"📝 [TRACE:{trace_id}] Order CANCELLED: {event.client_order_id}")

    def on_trade_tick(self, tick):
        """Handle incoming trade ticks from Polygon WebSocket."""
        # Only process ticks for our instrument
        if tick.instrument_id == self.polygon_instrument_id:
            self.last_trade_price = float(tick.price)
            self.last_trade_time_ns = tick.ts_event
            # Debug logging (commented out for production to reduce noise)
            # self.log.debug(f"Trade tick: {self.ticker} @ ${self.last_trade_price:.4f}")

    def on_quote_tick(self, tick):
        """Handle incoming quote ticks from Polygon WebSocket."""
        # Only process ticks for our instrument
        if tick.instrument_id == self.polygon_instrument_id:
            self.last_bid_price = float(tick.bid_price)
            self.last_ask_price = float(tick.ask_price)
            self.last_quote_time_ns = tick.ts_event
            # Debug logging (commented out for production to reduce noise)
            # self.log.debug(f"Quote tick: {self.ticker} bid=${self.last_bid_price:.4f} ask=${self.last_ask_price:.4f}")

    def on_timer(self, event):
        """Handle timer events."""
        if event.name == f"exit_{self._config.strategy_id}":
            self.log.info(f"⏰ Exit timer fired for {self.ticker}")
            self._place_exit_order()

    def _schedule_exit(self):
        """Schedule exit order after delay."""
        if self.exit_timer_set:
            return

        try:
            # Set timer for exit
            timer_name = f"exit_{self._config.strategy_id}"
            delay_seconds = self._config.exit_delay_minutes * 60

            self.clock.set_timer(
                name=timer_name,
                interval=pd.Timedelta(seconds=delay_seconds),
                callback=self.on_timer
            )

            self.exit_timer_set = True
            self.log.info(f"⏰ Scheduled exit for {self.ticker} in {self._config.exit_delay_minutes} minutes")

        except Exception as e:
            self.log.error(f"❌ Error scheduling exit: {e}")

    def _place_exit_order(self):
        """Place limit sell order to exit position using Nautilus execution."""
        try:
            # Get current position from Nautilus cache (filtered by strategy_id for isolation)
            positions = self.cache.positions_open(
                instrument_id=self.instrument_id,
                strategy_id=self.id,
            )
            position = positions[0] if positions else None

            if not position:
                self.log.warning(f"No open position for {self.ticker} (strategy: {self.id})")
                self.stop()
                return

            # positions_open() only returns non-flat positions, so no need to check is_flat
            qty = position.quantity
            trace_id = self._config.correlation_id

            # Get current market price (WebSocket data preferred, HTTP API fallback)
            self.log.info(f"📊 [TRACE:{trace_id}] Getting current price for exit...")
            current_price = self._get_current_price()
            if not current_price:
                self.log.error(f"❌ [TRACE:{trace_id}] No market data available for {self.ticker}")
                self.stop()
                return

            # Store decision price for slippage calculation
            self.exit_decision_price = current_price

            # Calculate limit price (1% below current for quick fill)
            limit_price = current_price * (1 - self._config.limit_order_offset_pct)

            # Create sell order using Nautilus order factory
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
            self.log.info(f"   [TRACE:{trace_id}] Exit decision price: ${current_price:.4f}")

            # Record order submission time for latency tracking
            self.exit_order_time_ms = time.time() * 1000

            # Submit order through Nautilus execution engine
            self.submit_order(order)

            # Store order in database
            if self._trade_db:
                self._trade_db.insert_order(
                    order_id=str(order.client_order_id),
                    strategy_id=self._config.strategy_id,
                    side='sell',
                    qty=int(qty),
                    limit_price=limit_price,
                )

            # Emit order placed event for exit
            emit_order_placed(
                news_id=self._config.news_id,
                strategy_id=self._config.strategy_id,
                order_id=str(order.client_order_id),
                order_role='exit',
                side='sell',
                order_type='limit',
                qty=int(qty),
                limit_price=limit_price,
            )

            # Send trade notification via GCP (skip in backtest mode)
            if self.trade_notifier:
                self.trade_notifier.notify_trade(
                    side='SELL',
                    ticker=self.ticker,
                    quantity=int(qty),
                    price=limit_price,
                    order_id=str(order.client_order_id),
                    news_headline=self._config.news_headline,
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

        # Stop strategy after position is closed
        self.stop()

    def on_stop(self):
        """Called when strategy stops - cancel pending orders, unsubscribe data, and exit any open position."""
        trace_id = self._config.correlation_id
        self.log.info(f"🛑 [TRACE:{trace_id}] NewsVolumeStrategy stopping for {self.ticker}")

        # Log final indicator values for comparison with historical fetch
        self.log.info(f"📊 [TRACE:{trace_id}] FINAL INDICATORS (for comparison):")
        self.log.info(f"   [TRACE:{trace_id}]   Catchup bars: {self.catchup_bar_count}")
        self.log.info(f"   [TRACE:{trace_id}]   Catchup volume: {self.catchup_volume:,}")
        self.log.info(f"   [TRACE:{trace_id}]   Last close: ${self.catchup_last_close:.4f}")
        self.log.info(f"   [TRACE:{trace_id}]   Final price: ${self.last_trade_price or 0:.4f}")

        # Cancel status logging timer
        if self.status_timer_set:
            try:
                self.clock.cancel_timer(f"status_log_{self._config.strategy_id}")
                self.status_timer_set = False
            except Exception:
                pass

        # Mark strategy as stopped in database
        stop_reason = "completed" if self.entry_filled else "no_fill"
        if self._trade_db:
            self._trade_db.update_strategy_stopped(self._config.strategy_id, stop_reason)

        # Emit strategy stopped event
        emit_strategy_stopped(
            news_id=self._config.news_id,
            strategy_id=self._config.strategy_id,
            reason=stop_reason,
        )

        # Unsubscribe from Polygon market data
        try:
            self.unsubscribe_trade_ticks(self.polygon_instrument_id)
            self.unsubscribe_quote_ticks(self.polygon_instrument_id)
            if self.bar_type:
                self.unsubscribe_bars(self.bar_type)
            self.log.info(f"   [TRACE:{trace_id}] Unsubscribed from Polygon data")
        except Exception as e:
            self.log.warning(f"   [TRACE:{trace_id}] Error unsubscribing from Polygon data: {e}")

        # Cancel catch-up timeout timer
        self._cancel_catchup_timeout()

        # Cancel fast-fill check timer if still pending
        if self.entry_timer_set:
            try:
                timer_name = f"check_fill_{self._config.strategy_id}"
                self.clock.cancel_time_alert(timer_name)
                self.entry_timer_set = False
                self.log.info(f"   [TRACE:{trace_id}] Cancelled pending fast-fill check")
            except Exception as e:
                self.log.warning(f"   [TRACE:{trace_id}] Error cancelling fast-fill check: {e}")

        # Cancel entry timeout timer if still pending
        self._cancel_entry_timeout()

        # Cancel any unfilled portion of entry order (handles partial fills too)
        self._cancel_unfilled_entry_order()

        # Get current position from cache (filtered by strategy_id for isolation)
        positions = self.cache.positions_open(
            instrument_id=self.instrument_id,
            strategy_id=self.id,
        )
        position = positions[0] if positions else None

        if position:
            # positions_open() only returns non-flat positions, so we have an open position
            self.log.info(f"⚠️  [TRACE:{trace_id}] Open position detected on stop (strategy: {self.id}) - placing exit order")
            self._place_exit_order_on_stop()
        else:
            self.log.info(f"   [TRACE:{trace_id}] No position to close")

    def _place_exit_order_on_stop(self):
        """Place limit sell order to exit position when strategy is stopped."""
        try:
            trace_id = self._config.correlation_id

            # Get current position from Nautilus cache (filtered by strategy_id for isolation)
            positions = self.cache.positions_open(
                instrument_id=self.instrument_id,
                strategy_id=self.id,
            )
            position = positions[0] if positions else None

            if not position:
                self.log.warning(f"   [TRACE:{trace_id}] No open position for {self.ticker} (strategy: {self.id})")
                return

            # positions_open() only returns non-flat positions
            qty = position.quantity

            # Get current market price from Polygon
            current_price = self._get_current_price()
            if not current_price:
                # Fallback to cache
                last_quote = self.cache.quote_tick(self.instrument_id)
                if last_quote:
                    current_price = float(last_quote.bid_price)
                else:
                    last_trade = self.cache.trade_tick(self.instrument_id)
                    if last_trade:
                        current_price = float(last_trade.price)

            if not current_price:
                # Last resort: use entry price
                current_price = float(self._config.entry_price)
                self.log.warning(f"   [TRACE:{trace_id}] No market data, using entry price: ${current_price:.2f}")

            # Store decision price for slippage calculation
            self.exit_decision_price = current_price

            # Calculate limit price (1% below current for quick fill)
            limit_price = current_price * (1 - self._config.limit_order_offset_pct)

            # Create sell order using Nautilus order factory
            order: LimitOrder = self.order_factory.limit(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty,
                price=self.instrument.make_price(limit_price),
                time_in_force=TimeInForce.DAY,
                post_only=False,
            )

            self.exit_order_id = order.client_order_id
            self.log.info(f"✅ [TRACE:{trace_id}] Submitting EXIT SELL order (on_stop): {self.ticker} x{qty} @ ${limit_price:.2f}")
            self.log.info(f"   [TRACE:{trace_id}] Exit decision price: ${current_price:.4f}")

            # Record order submission time for latency tracking
            self.exit_order_time_ms = time.time() * 1000

            # Submit order through Nautilus execution engine
            self.submit_order(order)

            # Store order in database
            if self._trade_db:
                self._trade_db.insert_order(
                    order_id=str(order.client_order_id),
                    strategy_id=self._config.strategy_id,
                    side='sell',
                    qty=int(qty),
                    limit_price=limit_price,
                )

            # Send trade notification via GCP (skip in backtest mode)
            if self.trade_notifier:
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
            self.log.error(f"❌ [TRACE:{trace_id}] Error placing exit order on stop: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
