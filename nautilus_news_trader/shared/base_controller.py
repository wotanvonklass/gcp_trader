#!/usr/bin/env python3
"""
Base News Controller for NautilusTrader.

Handles common Pub/Sub subscription and message processing.
Strategy-specific controllers inherit from this.
"""

import sys
import os
import json
import threading
import queue
from datetime import datetime, timezone
from typing import Optional

from nautilus_trader.trading.controller import Controller
from nautilus_trader.trading.trader import Trader
from nautilus_trader.common.config import ActorConfig

from google.cloud import pubsub_v1

from shared.filters import V16Filters
from shared.polygon_client import PolygonClient


class BaseNewsControllerConfig(ActorConfig, frozen=True):
    """Base configuration for news controllers."""

    # Pub/Sub configuration
    project_id: str = "gnw-trader"
    subscription_id: str = "benzinga-news-trader"

    # News filtering
    max_news_age_seconds: int = 10

    # V16 Filters
    max_price: float = 5.00
    max_market_cap: float = 50_000_000
    require_positive_momentum: bool = True
    session_filter_enabled: bool = True

    # Position limits
    min_position_size: float = 100.0
    max_position_size: float = 20000.0
    limit_order_offset_pct: float = 0.01
    extended_hours: bool = True

    # API keys
    polygon_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""


class BaseNewsController(Controller):
    """
    Base controller with Pub/Sub subscription and V16 filters.

    Subclasses must implement:
    - _spawn_strategy(symbol, position_size, volume_data, headline, pub_time, url, trace_id)
    - _calculate_position_size(volume_data, trace_id) -> float
    - _get_strategy_name() -> str
    """

    def __init__(self, trader: Trader, config: BaseNewsControllerConfig):
        super().__init__(trader, config=config)
        self._config = config

        # Initialize Pub/Sub subscriber
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(
            self._config.project_id,
            self._config.subscription_id
        )

        # Initialize V16 filters
        self.filters = V16Filters(
            max_price=self._config.max_price,
            max_market_cap=self._config.max_market_cap,
            require_positive_momentum=self._config.require_positive_momentum,
            session_filter_enabled=self._config.session_filter_enabled,
            log_func=lambda msg: self.log.info(msg),
        )

        # Initialize Polygon client
        self.polygon = PolygonClient(
            api_key=self._config.polygon_api_key,
            log_func=lambda msg: self.log.info(msg),
        )

        self.streaming_pull_future = None
        self.message_count = 0
        self.health_check_task = None
        self.health_check_stop_event = None

        # Message queue for async processing (prevents callback blocking)
        self._message_queue = queue.Queue()
        self._queue_processor_threads = []
        self._queue_stop_event = threading.Event()

    def _get_strategy_name(self) -> str:
        """Return strategy name for logging. Override in subclass."""
        return "base"

    def _calculate_position_size(self, volume_data: dict, trace_id: str) -> float:
        """Calculate position size. Override in subclass."""
        raise NotImplementedError

    def _spawn_strategy(self, symbol: str, position_size: float, volume_data: dict,
                        headline: str, pub_time: datetime, url: str, trace_id: str):
        """Spawn strategy instance. Override in subclass."""
        raise NotImplementedError

    def on_start(self):
        """Called when controller starts."""
        strategy_name = self._get_strategy_name()
        self.log.info(f"Starting {strategy_name} Controller")
        self.log.info(f"Subscribing to: {self.subscription_path}")
        self.log.info(f"")
        self.log.info(f"V16 FILTERS:")
        self.log.info(f"   Price: < ${self._config.max_price:.2f}")
        self.log.info(f"   Market cap: < ${self._config.max_market_cap/1e6:.0f}M")
        self.log.info(f"   Momentum: {'Positive only' if self._config.require_positive_momentum else 'Disabled'}")
        self.log.info(f"   Session: {'Extended + Closing' if self._config.session_filter_enabled else 'Disabled'}")
        self.log.info(f"")
        self.log.info(f"Position limits: ${self._config.min_position_size}-${self._config.max_position_size}")

        self._start_queue_processor()
        self._start_pubsub_subscription()
        self._start_health_check()

    def on_run(self):
        """Called when controller is running."""
        self.log.info(f"{self._get_strategy_name()} Controller is now running")

    def on_stop(self):
        """Called when controller stops."""
        self.log.info(f"Stopping {self._get_strategy_name()} Controller")

        # Stop queue processors
        self._queue_stop_event.set()
        for thread in self._queue_processor_threads:
            if thread.is_alive():
                thread.join(timeout=2)

        if self.health_check_stop_event:
            self.health_check_stop_event.set()

        if self.streaming_pull_future:
            self.streaming_pull_future.cancel()
            try:
                self.streaming_pull_future.result()
            except:
                pass

        self.log.info(f"{self._get_strategy_name()} Controller stopped")

    def _start_queue_processor(self):
        """Start background threads to process queued messages in parallel."""
        NUM_WORKERS = 5  # Process up to 5 messages concurrently

        def process_queue(worker_id: int):
            while not self._queue_stop_event.is_set():
                try:
                    # Wait for message with timeout to allow checking stop event
                    try:
                        news_data = self._message_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    # Process the message
                    self._process_news_event(news_data)
                    self._message_queue.task_done()

                except Exception as e:
                    self.log.error(f"Error in queue processor {worker_id}: {e}")
                    import traceback
                    self.log.error(f"Traceback: {traceback.format_exc()}")

        # Start multiple worker threads for parallel processing
        self._queue_processor_threads = []
        for i in range(NUM_WORKERS):
            thread = threading.Thread(
                target=process_queue,
                args=(i,),
                daemon=True,
                name=f"{self._get_strategy_name()}-QueueProcessor-{i}"
            )
            thread.start()
            self._queue_processor_threads.append(thread)
        self.log.info(f"Message queue processor started ({NUM_WORKERS} workers)")

    def _start_pubsub_subscription(self):
        """Start Pub/Sub subscription in background."""
        try:
            self.log.info("Starting Pub/Sub streaming pull...")

            # Configure flow control to allow more concurrent messages
            # This prevents message loss during bursts
            flow_control = pubsub_v1.types.FlowControl(
                max_messages=1000,  # Allow up to 1000 outstanding messages
                max_bytes=100 * 1024 * 1024,  # 100 MB
            )

            # Use custom scheduler with more threads for faster callback processing
            # Must use ThreadScheduler, not raw ThreadPoolExecutor
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=10)
            scheduler = pubsub_v1.subscriber.scheduler.ThreadScheduler(executor=executor)

            self.streaming_pull_future = self.subscriber.subscribe(
                self.subscription_path,
                callback=self._message_callback,
                flow_control=flow_control,
                scheduler=scheduler,
            )

            self.log.info("Pub/Sub subscription active (max_messages=1000, scheduler_workers=10)")

        except Exception as e:
            self.log.error(f"Failed to start Pub/Sub subscription: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _message_callback(self, message: pubsub_v1.subscriber.message.Message):
        """Callback for Pub/Sub messages - ACK immediately and queue for processing."""
        try:
            raw_data = message.data.decode('utf-8')

            # Skip corrupt messages
            if len(raw_data) <= 2 or raw_data.strip() in ['-', '']:
                message.ack()
                return

            news_data = json.loads(raw_data)
            message.ack()  # ACK immediately to prevent blocking

            # Skip heartbeat messages
            if news_data.get('type') == 'heartbeat':
                return

            self.message_count += 1

            # Queue for async processing (don't block callback)
            self._message_queue.put(news_data)

        except Exception as e:
            self.log.error(f"Error in message callback: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            message.nack()

    def _process_news_event(self, news_data: dict):
        """Process a news event and spawn strategy if it qualifies."""
        try:
            headline = news_data.get('headline', '')
            tickers = news_data.get('tickers', [])
            url = news_data.get('url', '')
            news_id = news_data.get('id', '')

            # Generate correlation ID
            if news_id:
                base_id = str(news_id)
                if tickers:
                    first_ticker = tickers[0].split(':')[-1]
                    correlation_id = f"{first_ticker}_{base_id}"
                else:
                    correlation_id = base_id
            else:
                import uuid
                correlation_id = str(uuid.uuid4())[:8]

            # Get publication time
            pub_time_str = (news_data.get('createdAt') or
                           news_data.get('updatedAt') or
                           news_data.get('capturedAt'))

            if not tickers:
                return

            if not pub_time_str:
                return

            pub_time = datetime.fromisoformat(pub_time_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            age_seconds = (now - pub_time).total_seconds()

            # Check news age
            if age_seconds > self._config.max_news_age_seconds:
                self.log.debug(f"[{correlation_id}] News too old: {age_seconds:.1f}s")
                return

            self.log.info(f"[{correlation_id}] Processing: {headline[:80]}")
            self.log.info(f"[{correlation_id}] Tickers: {', '.join(tickers)}, Age: {age_seconds:.1f}s")

            # Session filter
            passed, msg = self.filters.check_session(now)
            if not passed:
                self.log.info(f"[{correlation_id}] {msg}")
                return

            # Process each ticker
            for ticker in tickers:
                symbol = ticker.split(':')[-1]
                self._process_ticker(symbol, headline, pub_time, url, correlation_id, news_data)

        except Exception as e:
            self.log.error(f"Error processing news event: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _process_ticker(self, symbol: str, headline: str, pub_time: datetime,
                        url: str, correlation_id: str, news_data: dict):
        """Process a single ticker from news event."""
        try:
            trace_id = f"{correlation_id}_{symbol}"

            # Check if already has position or strategy
            if self._has_position_or_strategy(symbol):
                self.log.info(f"[{trace_id}] Already has position/strategy")
                return

            # Get Polygon data
            if '[TEST]' in headline:
                self.log.info(f"[{trace_id}] TEST NEWS - fetching real Polygon data")
                volume_data = self.polygon.check_trading_activity(symbol, trace_id)
                if not volume_data:
                    # Fallback to mock if no real data
                    test_price = self._get_alpaca_quote(symbol) or 1.00
                    volume_data = {
                        'symbol': symbol,
                        'volume': 10000,
                        'avg_price': test_price,
                        'last_price': test_price,
                        'price_3s_ago': test_price * 0.99,
                        'bars_count': 3,
                    }
                    self.log.info(f"[{trace_id}] Using mock fallback (no Polygon data)")
            else:
                volume_data = self.polygon.check_trading_activity(symbol, trace_id)
                if not volume_data:
                    self.log.debug(f"[{trace_id}] No trading activity")
                    return

            current_price = volume_data['last_price']
            price_3s_ago = volume_data.get('price_3s_ago', current_price)

            # Price filter
            passed, msg = self.filters.check_price(current_price)
            if not passed:
                self.log.info(f"[{trace_id}] {msg}")
                return

            # Momentum filter
            passed, msg = self.filters.check_momentum(current_price, price_3s_ago)
            if not passed:
                self.log.info(f"[{trace_id}] {msg}")
                return

            # Market cap filter
            market_cap = self.polygon.get_market_cap(symbol)
            passed, msg = self.filters.check_market_cap(market_cap)
            if not passed:
                self.log.info(f"[{trace_id}] {msg}")
                return

            # Calculate position size
            position_size = self._calculate_position_size(volume_data, trace_id)
            if position_size <= 0:
                return

            # All filters passed - spawn strategy
            self.log.info(f"[{trace_id}] ALL FILTERS PASSED - spawning {self._get_strategy_name()}")
            self._spawn_strategy(symbol, position_size, volume_data, headline, pub_time, url, trace_id)

        except Exception as e:
            self.log.error(f"[{correlation_id}] Error processing ticker {symbol}: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _get_alpaca_quote(self, symbol: str) -> Optional[float]:
        """Get current quote from Alpaca."""
        try:
            api_key = os.environ.get('ALPACA_API_KEY')
            secret_key = os.environ.get('ALPACA_SECRET_KEY')

            if not api_key or not secret_key:
                return None

            import requests
            url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
            headers = {
                'APCA-API-KEY-ID': api_key,
                'APCA-API-SECRET-KEY': secret_key
            }

            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                quote = data.get('quote', {})
                return float(quote.get('ap') or quote.get('bp') or 0)
            return None

        except Exception:
            return None

    def _has_position_or_strategy(self, ticker: str) -> bool:
        """Check if there's already a position or running strategy for this ticker."""
        # Check running strategies
        for strategy in self._trader.strategies():
            if hasattr(strategy, 'ticker') and strategy.ticker == ticker:
                if strategy.state.name == "RUNNING":
                    return True

        # Check Alpaca API directly
        try:
            import requests

            api_key = os.environ.get('ALPACA_API_KEY')
            secret_key = os.environ.get('ALPACA_SECRET_KEY')

            if api_key and secret_key:
                url = f"https://paper-api.alpaca.markets/v2/positions/{ticker}"
                headers = {
                    'APCA-API-KEY-ID': api_key,
                    'APCA-API-SECRET-KEY': secret_key
                }

                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    position_data = response.json()
                    qty = float(position_data.get('qty', 0))
                    if qty != 0:
                        self.log.info(f"Found existing Alpaca position for {ticker}: {qty} shares")
                        return True
        except Exception:
            pass

        return False

    def _start_health_check(self):
        """Start periodic Alpaca health check."""
        news_trader_path = "/opt/news-trader"
        if os.path.exists(news_trader_path) and news_trader_path not in sys.path:
            sys.path.insert(0, news_trader_path)

        self.health_check_stop_event = threading.Event()

        def run_health_check():
            try:
                from utils.alpaca_health import check_alpaca_health, log_health_check

                result = check_alpaca_health(
                    self._config.alpaca_api_key,
                    self._config.alpaca_secret_key
                )
                log_health_check(result, log_level="INFO")

                if not result['healthy']:
                    self.log.error("Alpaca connection unhealthy!")
            except ImportError as e:
                self.log.error(f"Health check import error: {e}")

        def periodic_check():
            import time
            while not self.health_check_stop_event.is_set():
                try:
                    run_health_check()
                except Exception as e:
                    self.log.error(f"Health check error: {e}")

                for _ in range(300):
                    if self.health_check_stop_event.is_set():
                        break
                    time.sleep(1)

        self.health_check_task = threading.Thread(target=periodic_check, daemon=True)
        self.health_check_task.start()
        self.log.info("Periodic health check started (every 5 minutes)")
