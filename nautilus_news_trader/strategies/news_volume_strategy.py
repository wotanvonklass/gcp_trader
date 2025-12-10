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
from nautilus_trader.model.enums import OrderSide, TimeInForce, OrderStatus
from nautilus_trader.model.orders import LimitOrder
from nautilus_trader.model.instruments import Instrument

# Import trade notifier for GCP alerts (optional for backtest)
try:
    from utils.trade_notifier import get_trade_notifier
except ImportError:
    # Backtest mode - no trade notifications
    def get_trade_notifier():
        return None

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

    # News metadata
    news_headline: str = ""
    publishing_date: str = ""
    news_url: str = ""
    correlation_id: str = ""


class NewsVolumeStrategy(Strategy):
    """
    Simple strategy that enters on news and exits after delay.

    Lifecycle:
    1. on_start(): Place entry limit order via Nautilus
    2. on_order_filled(): Schedule exit timer
    3. on_timer(): Place exit order
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

        # Track state
        self.entry_order_id = None
        self.exit_order_id = None
        self.entry_filled = False
        self.entry_timer_set = False
        self.exit_timer_set = False

        # Get instrument reference
        self.instrument: Optional[Instrument] = None

        # Initialize trade notifier for email alerts
        self.trade_notifier = get_trade_notifier()

        # Slippage and latency tracking
        self.entry_order_time_ms: Optional[float] = None  # When entry order was submitted
        self.exit_order_time_ms: Optional[float] = None   # When exit order was submitted
        self.exit_decision_price: Optional[float] = None  # Market price when exit was decided
        self.entry_fill_price: Optional[float] = None     # Actual entry fill price (avg)

    def _get_alpaca_quote(self) -> Optional[float]:
        """Get current bid price from Alpaca for exit pricing."""
        try:
            import requests
            import os

            api_key = os.environ.get('ALPACA_API_KEY')
            secret_key = os.environ.get('ALPACA_SECRET_KEY')

            if not api_key or not secret_key:
                self.log.warning("Alpaca credentials not found in environment")
                return None

            url = f"https://data.alpaca.markets/v2/stocks/{self.ticker}/quotes/latest"
            headers = {
                'APCA-API-KEY-ID': api_key,
                'APCA-API-SECRET-KEY': secret_key
            }

            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                quote = data.get('quote', {})
                # For SELL, use bid price (what we can sell at)
                bid_price = quote.get('bp')
                if bid_price:
                    return float(bid_price)
                # Fallback to ask if no bid
                ask_price = quote.get('ap')
                if ask_price:
                    return float(ask_price)
            else:
                self.log.warning(f"Alpaca quote request failed: {response.status_code}")
                return None

        except Exception as e:
            self.log.error(f"Error getting Alpaca quote: {e}")
            return None

    def on_start(self):
        """Called when strategy starts - place entry order."""
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

        # Place entry order immediately for minimum latency
        self._place_entry_order()

        # IMPORTANT: NautilusTrader doesn't invoke event handlers until strategy is RUNNING.
        # If the order fills before RUNNING state (very fast fill), on_order_filled won't
        # be called. However, the cache IS updated with the fill.
        # Schedule an immediate check after RUNNING state to catch fast fills.
        self.entry_timer_set = True
        self.clock.set_time_alert_ns(
            name=f"check_fill_{self._config.strategy_id}",
            alert_time_ns=self.clock.timestamp_ns() + 1_000_000,  # 1ms - fires on next event loop
            callback=self._check_fast_fill,
        )

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
            self._schedule_exit()
        elif not self.entry_filled:
            self.log.info(f"   [TRACE:{trace_id}] Cache check complete - order not yet filled, waiting for callback")

    def _place_entry_order(self):
        """Place limit buy order with offset to ensure fill using Nautilus execution."""
        try:
            # Calculate limit price (1% above current to ensure fill)
            entry_price = float(self._config.entry_price)
            limit_price = entry_price * (1 + self._config.limit_order_offset_pct)

            # Calculate quantity
            position_size = float(self._config.position_size_usd)
            qty = int(position_size / limit_price)

            if qty == 0:
                self.log.warning(f"Calculated qty=0 for ${position_size} @ ${limit_price}")
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
            trace_id = self._config.correlation_id
            self.log.info(f"✅ [TRACE:{trace_id}] Submitting BUY order: {self.ticker} x{qty} @ ${limit_price:.2f}")

            # Record order submission time for latency tracking
            self.entry_order_time_ms = time.time() * 1000

            # Submit order through Nautilus execution engine
            self.submit_order(order)

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
            self.log.error(f"❌ Error placing entry order: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            self.stop()

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

        # Check if this is the entry order - use safe comparison
        is_entry_order = (
            self.entry_order_id is not None and
            event.client_order_id is not None and
            str(event.client_order_id) == str(self.entry_order_id)
        )

        if is_entry_order and not self.entry_filled:
            self.entry_filled = True
            self.entry_fill_price = fill_price

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

    def on_order_rejected(self, event):
        """Called when order is rejected."""
        trace_id = self._config.correlation_id
        self.log.error(f"❌ [TRACE:{trace_id}] Order REJECTED: {event.client_order_id}")
        self.log.error(f"   [TRACE:{trace_id}] Reason: {event.reason}")
        self.stop()

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

            # Get current market price - use Alpaca API for accurate pricing
            current_price = self._get_alpaca_quote()
            if not current_price:
                # Fallback to cache
                last_quote = self.cache.quote_tick(self.instrument_id)
                if last_quote:
                    current_price = float(last_quote.bid_price)
                else:
                    last_trade = self.cache.trade_tick(self.instrument_id)
                    if last_trade:
                        current_price = float(last_trade.price)
                    else:
                        self.log.error(f"No market data available for {self.ticker}")
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
            trace_id = self._config.correlation_id
            self.log.info(f"✅ [TRACE:{trace_id}] Submitting SELL order: {self.ticker} x{qty} @ ${limit_price:.2f}")
            self.log.info(f"   [TRACE:{trace_id}] Exit decision price: ${current_price:.4f}")

            # Record order submission time for latency tracking
            self.exit_order_time_ms = time.time() * 1000

            # Submit order through Nautilus execution engine
            self.submit_order(order)

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
        """Called when strategy stops - cancel pending orders and exit any open position."""
        trace_id = self._config.correlation_id
        self.log.info(f"🛑 [TRACE:{trace_id}] NewsVolumeStrategy stopping for {self.ticker}")

        # Cancel fast-fill check timer if still pending
        if self.entry_timer_set:
            try:
                timer_name = f"check_fill_{self._config.strategy_id}"
                self.clock.cancel_time_alert(timer_name)
                self.entry_timer_set = False
                self.log.info(f"   [TRACE:{trace_id}] Cancelled pending fast-fill check")
            except Exception as e:
                self.log.warning(f"   [TRACE:{trace_id}] Error cancelling fast-fill check: {e}")

        # Cancel unfilled entry order if exists
        if self.entry_order_id and not self.entry_filled:
            self.log.info(f"   [TRACE:{trace_id}] Cancelling unfilled entry order: {self.entry_order_id}")
            try:
                order = self.cache.order(self.entry_order_id)
                if order and order.is_open:
                    self.cancel_order(order)
                    self.log.info(f"✅ [TRACE:{trace_id}] Entry order cancel requested")
            except Exception as e:
                self.log.error(f"❌ [TRACE:{trace_id}] Error cancelling entry order: {e}")

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

            # Get current market price - use Alpaca API for accurate pricing
            current_price = self._get_alpaca_quote()
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
