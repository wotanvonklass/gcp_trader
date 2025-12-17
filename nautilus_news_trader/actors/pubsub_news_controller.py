#!/usr/bin/env python3
"""
Pub/Sub News Controller for NautilusTrader.

This controller subscribes to GCP Pub/Sub benzinga-news topic and spawns
trading strategies for each qualifying news event.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Set
from concurrent.futures import TimeoutError
import asyncio

# Import NautilusTrader components
from nautilus_trader.trading.controller import Controller
from nautilus_trader.trading.trader import Trader
from nautilus_trader.common.config import ActorConfig

# Import Google Cloud Pub/Sub
from google.cloud import pubsub_v1


class PubSubNewsControllerConfig(ActorConfig, frozen=True):
    """
    Configuration for PubSubNewsController.
    """
    # Pub/Sub configuration
    project_id: str = "gnw-trader"
    subscription_id: str = "benzinga-news-trader"

    # News filtering
    min_news_age_seconds: int = 2
    max_news_age_seconds: int = 30

    # Trading parameters
    volume_percentage: float = 0.05
    min_position_size: float = 100.0
    max_position_size: float = 20000.0
    limit_order_offset_pct: float = 0.01
    exit_delay_minutes: int = 7
    extended_hours: bool = True

    # Parallel test mode - spawn second strategy at different volume %
    parallel_test_mode: bool = False
    parallel_volume_percentage: float = 0.10  # 10% for parallel test

    # Polygon API
    polygon_api_key: str = ""

    # Alpaca credentials (for direct API use)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""


class PubSubNewsController(Controller):
    """
    Nautilus Controller that subscribes to Pub/Sub and spawns strategies.

    For each news event:
    1. Check if news is 2-10 seconds old
    2. Query Polygon for trading volume
    3. If volume exists, spawn a strategy to trade
    """

    def __init__(self, trader: Trader, config: Optional[PubSubNewsControllerConfig] = None):
        if config is None:
            config = PubSubNewsControllerConfig()
        super().__init__(trader, config=config)
        self._controller_config = config

        self.log.info("🔧 PubSubNewsController.__init__() called")

        # Initialize Pub/Sub subscriber
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(
            self._controller_config.project_id,
            self._controller_config.subscription_id
        )

        self.streaming_pull_future = None
        self.message_count = 0
        self.health_check_task = None
        self.health_check_stop_event = None

    def on_start(self):
        """Called when controller starts - NautilusTrader lifecycle method."""
        self.log.info("🚀 PubSubNewsController.on_start() - Starting Pub/Sub News Controller")
        self.log.info(f"📡 Subscribing to: {self.subscription_path}")
        self.log.info(f"⏰ News age filter: {self._controller_config.min_news_age_seconds}-{self._controller_config.max_news_age_seconds}s")
        self.log.info(f"💰 Position limits: ${self._controller_config.min_position_size}-${self._controller_config.max_position_size}")
        self.log.info(f"📊 Volume %: {self._controller_config.volume_percentage * 100}%")
        self.log.info(f"⏱️ Exit delay: {self._controller_config.exit_delay_minutes} minutes")
        self.log.info(f"🌙 Extended hours: {self._controller_config.extended_hours}")

        # Log parallel test mode
        if self._controller_config.parallel_test_mode:
            self.log.info(f"🔀 PARALLEL TEST MODE ENABLED - will spawn TWO strategies per news:")
            self.log.info(f"   📊 Primary: {self._controller_config.volume_percentage * 100}% volume (news_ prefix)")
            self.log.info(f"   📊 Parallel: {self._controller_config.parallel_volume_percentage * 100}% volume (news10_ prefix)")

        # Start Pub/Sub subscription in background
        self._start_pubsub_subscription()

        # Start periodic health check
        self._start_health_check()

    def on_run(self):
        """Called when controller is running."""
        self.log.info("🏃 PubSubNewsController.on_run() - Controller is now running")

    def on_stop(self):
        """Called when controller stops."""
        self.log.info("🛑 PubSubNewsController.on_stop() - Cleaning up resources")

        # Stop health check thread
        if self.health_check_stop_event:
            self.health_check_stop_event.set()

        # Stop Pub/Sub subscription
        if self.streaming_pull_future:
            self.streaming_pull_future.cancel()
            try:
                self.streaming_pull_future.result()
            except:
                pass

        self.log.info("✅ PubSubNewsController stopped successfully")

    def _start_pubsub_subscription(self):
        """Start Pub/Sub subscription in background."""
        try:
            self.log.info("📬 Starting Pub/Sub streaming pull...")

            # Start streaming pull
            self.streaming_pull_future = self.subscriber.subscribe(
                self.subscription_path,
                callback=self._message_callback
            )

            self.log.info("✅ Pub/Sub subscription active")

        except Exception as e:
            self.log.error(f"❌ Failed to start Pub/Sub subscription: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _message_callback(self, message: pubsub_v1.subscriber.message.Message):
        """Callback for Pub/Sub messages."""
        try:
            # Debug: Log message attributes and raw bytes
            self.log.info(f"🔍 Message ID: {message.message_id}")
            self.log.info(f"🔍 Message attributes: {message.attributes}")
            self.log.info(f"🔍 Message data type: {type(message.data)}")
            self.log.info(f"🔍 Message data bytes (len={len(message.data)}): {message.data[:100]}")

            # Debug: Log raw message data
            raw_data = message.data.decode('utf-8')
            self.log.info(f"🔍 Raw message data (len={len(raw_data)}): {raw_data[:200]}")

            # Skip corrupt messages (just dash or empty)
            if len(raw_data) <= 2 or raw_data.strip() in ['-', '']:
                self.log.warning(f"⚠️ Skipping corrupt message ID {message.message_id}: '{raw_data}'")
                message.ack()
                return

            # Decode message
            news_data = json.loads(raw_data)

            # Acknowledge message immediately
            message.ack()

            # Skip heartbeat messages
            if news_data.get('type') == 'heartbeat':
                self.log.debug(f"💓 Heartbeat received: {news_data.get('status')}")
                return

            self.message_count += 1

            # Extract basic info for initial log
            headline = news_data.get('headline', 'No headline')[:100]
            news_id = news_data.get('id', '')
            trace_id = str(news_id) if news_id else 'unknown'

            # Calculate age if we have timestamp
            age_str = ""
            pub_time_str = (news_data.get('published') or
                           news_data.get('publishedAt') or
                           news_data.get('updated') or
                           news_data.get('updatedAt') or
                           news_data.get('created') or
                           news_data.get('capturedAt'))

            if pub_time_str:
                try:
                    pub_time = datetime.fromisoformat(pub_time_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    age_seconds = (now - pub_time).total_seconds()
                    age_ms = age_seconds * 1000
                    age_str = f" ({age_ms:.0f}ms)"
                except:
                    pass

            self.log.info(f"📰 [TRACE:{trace_id}] Received news #{self.message_count}{age_str}: {headline}")

            # Process news event
            self._process_news_event(news_data)

        except Exception as e:
            self.log.error(f"❌ Error in message callback: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            message.nack()

    def _process_news_event(self, news_data: dict):
        """Process a news event and spawn strategy if it qualifies."""
        try:
            # Extract news details
            headline = news_data.get('headline', '')
            tickers = news_data.get('tickers', [])
            url = news_data.get('url', '')
            news_id = news_data.get('id', '')

            # Use news ID as correlation ID for end-to-end tracing
            # Prefix with ticker for easier filtering/searching
            if news_id:
                base_id = str(news_id)
                # Prefix with first ticker if available
                if tickers and len(tickers) > 0:
                    first_ticker = tickers[0].split(':')[-1]  # Remove exchange prefix if present
                    correlation_id = f"{first_ticker}_{base_id}"
                else:
                    correlation_id = base_id
            else:
                import uuid
                correlation_id = str(uuid.uuid4())[:8]

            # Log all available timestamp fields to understand the data
            self.log.info(f"📋 [TRACE:{correlation_id}] News data keys: {list(news_data.keys())}")
            self.log.info(f"🆔 [TRACE:{correlation_id}] News ID: {news_id if news_id else 'generated'}")

            # Try different timestamp fields in order of preference
            # createdAt = Benzinga's publication time (ISO format)
            # updatedAt = when news was updated
            # capturedAt = when we captured it
            pub_time_str = (news_data.get('createdAt') or
                           news_data.get('updatedAt') or
                           news_data.get('capturedAt'))

            if not tickers:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] No tickers in news: {headline}")
                self.log.info(f"   [TRACE:{correlation_id}] URL: {url}")
                return

            if not pub_time_str:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] No timestamp found in news data")
                return

            # Parse publication time
            pub_time = datetime.fromisoformat(pub_time_str.replace('Z', '+00:00'))

            # Check timing (news should be 2-10 seconds old)
            now = datetime.now(timezone.utc)
            age_seconds = (now - pub_time).total_seconds()
            age_ms = age_seconds * 1000

            self.log.info(f"📰 [TRACE:{correlation_id}] News ({age_ms:.0f}ms / {age_seconds:.1f}s old): {headline}")
            self.log.info(f"🎯 [TRACE:{correlation_id}] Tickers: {', '.join(tickers)}")
            self.log.info(f"🔗 [TRACE:{correlation_id}] URL: {url}")
            self.log.info(f"📅 [TRACE:{correlation_id}] Published: {pub_time_str}, Now: {now.isoformat()}")

            # No minimum age check - process news as fast as possible

            if age_seconds > self._controller_config.max_news_age_seconds:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] News too old: {age_seconds:.1f}s > {self._controller_config.max_news_age_seconds}s")
                return

            # Process each ticker
            for ticker in tickers:
                # Clean ticker (remove exchange prefix if present)
                symbol = ticker.split(':')[-1]

                # Check if already has position or strategy for this ticker
                if self._has_position_or_strategy(symbol):
                    self.log.info(f"⏭️  [TRACE:{correlation_id}] Skipping {symbol} - already has position/strategy")
                    continue

                # For test news (with [TEST] in headline), skip Polygon check and use mock data
                if '[TEST]' in headline:
                    self.log.info(f"🧪 [TRACE:{correlation_id}] TEST NEWS detected - using mock volume data")
                    # Fetch real price from Polygon for test orders to actually fill
                    test_price = self._get_polygon_quote(symbol)
                    if not test_price:
                        self.log.warning(f"⚠️  [TRACE:{correlation_id}] Could not get Polygon quote for {symbol}, using fallback $100")
                        test_price = 100.00
                    self.log.info(f"🧪 [TRACE:{correlation_id}] Using real price from Polygon: ${test_price:.2f}")
                    volume_data = {
                        'symbol': symbol,
                        'volume': 10000,  # Mock volume
                        'avg_price': test_price,  # Real price from Polygon
                        'last_price': test_price,
                        'bars_count': 3,
                        'timestamp': datetime.now(timezone.utc)
                    }
                else:
                    # Check Polygon for trading activity
                    self.log.info(f"📊 [TRACE:{correlation_id}] Checking {symbol} on Polygon...")
                    volume_data = self._check_polygon_trading(symbol, correlation_id)

                    if not volume_data:
                        self.log.info(f"⏭️  [TRACE:{correlation_id}] DECISION: Skip {symbol} - no trading activity in last 3s")
                        continue

                self.log.info(f"✅ [TRACE:{correlation_id}] Trading detected: {volume_data['volume']:,.0f} shares @ ${volume_data['last_price']:.2f}")

                # Calculate position size
                position_size = self._calculate_position_size(volume_data, correlation_id)

                if position_size == 0:
                    continue

                # Spawn strategy for this ticker
                self._spawn_news_trading_strategy(symbol, position_size, volume_data, headline, pub_time, url, correlation_id)

        except Exception as e:
            self.log.error(f"❌ Error processing news event: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _get_polygon_quote(self, symbol: str) -> Optional[float]:
        """Get current quote from Polygon for a symbol."""
        try:
            import requests

            polygon_key = self._controller_config.polygon_api_key
            if not polygon_key:
                self.log.warning("Polygon API key not configured")
                return None

            # Get last trade from Polygon (most accurate current price)
            url = f"https://api.polygon.io/v2/last/trade/{symbol}"
            params = {'apiKey': polygon_key}

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', {})
                price = results.get('p')  # Last trade price
                if price:
                    return float(price)

            # Fallback to last quote if no trade
            quote_url = f"https://api.polygon.io/v3/quotes/{symbol}"
            quote_params = {'apiKey': polygon_key, 'limit': 1, 'sort': 'timestamp', 'order': 'desc'}

            quote_response = requests.get(quote_url, params=quote_params, timeout=5)
            if quote_response.status_code == 200:
                quote_data = quote_response.json()
                results = quote_data.get('results', [])
                if results:
                    # Use ask price for buy orders
                    ask_price = results[0].get('ask_price')
                    if ask_price:
                        return float(ask_price)
                    bid_price = results[0].get('bid_price')
                    if bid_price:
                        return float(bid_price)

            self.log.warning(f"Polygon quote request failed: {response.status_code}")
            return None

        except Exception as e:
            self.log.error(f"Error getting Polygon quote: {e}")
            return None

    def _check_polygon_trading(self, symbol: str, correlation_id: str = "") -> Optional[dict]:
        """Check if there has been trading activity on Polygon in last 3 seconds."""
        try:
            import requests

            # Get current time
            now = datetime.now(timezone.utc)

            # Calculate 3 seconds before now
            three_sec_ago = now - timedelta(seconds=3)

            # Format timestamps for Polygon API (milliseconds)
            from_ms = int(three_sec_ago.timestamp() * 1000)
            to_ms = int(now.timestamp() * 1000)

            # Query Polygon 1-second bars
            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/second/{from_ms}/{to_ms}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'apiKey': self._controller_config.polygon_api_key
            }

            self.log.info(f"   📊 [TRACE:{correlation_id}] Polygon query: {symbol} from {three_sec_ago.strftime('%H:%M:%S.%f')[:-3]} to {now.strftime('%H:%M:%S.%f')[:-3]} UTC")

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            results_count = data.get('resultsCount', 0)

            if results_count == 0:
                self.log.info(f"   📊 [TRACE:{correlation_id}] Polygon response: 0 bars in 3s window → NO ACTIVITY")
                return None

            results = data.get('results', [])
            if not results:
                self.log.info(f"   📊 [TRACE:{correlation_id}] Polygon response: resultsCount={results_count} but empty results → NO ACTIVITY")
                return None

            # Calculate total volume and average price over last 3 seconds
            total_volume = sum(bar['v'] for bar in results)
            total_value = sum(bar['v'] * bar['c'] for bar in results)
            avg_price = total_value / total_volume if total_volume > 0 else 0
            last_bar = results[-1]

            # Log detailed bar info
            self.log.info(f"   📊 [TRACE:{correlation_id}] Polygon response: {len(results)} bars, {total_volume:,.0f} shares total")
            for i, bar in enumerate(results):
                bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=timezone.utc)
                self.log.info(f"      [TRACE:{correlation_id}] Bar {i+1}: {bar_time.strftime('%H:%M:%S')} | {bar['v']:,.0f} shares @ ${bar['c']:.2f}")

            return {
                'symbol': symbol,
                'volume': total_volume,
                'avg_price': avg_price,
                'last_price': last_bar['c'],
                'bars_count': len(results),
                'timestamp': datetime.fromtimestamp(last_bar['t'] / 1000, tz=timezone.utc)
            }

        except Exception as e:
            self.log.error(f"   ❌ [TRACE:{correlation_id}] Polygon API error for {symbol}: {e}")
            return None

    def _calculate_position_size(self, volume_data: dict, correlation_id: str = "") -> float:
        """Calculate position size based on volume. Returns USD amount to trade."""
        # Calculate 5% of last 3s USD volume
        usd_volume = volume_data['volume'] * volume_data['avg_price']
        position_size = usd_volume * self._controller_config.volume_percentage

        # Log calculation details
        self.log.info(f"   💰 [TRACE:{correlation_id}] Position calc: {volume_data['volume']:,.0f} shares × ${volume_data['avg_price']:.2f} = ${usd_volume:,.2f} USD volume")
        self.log.info(f"   💰 [TRACE:{correlation_id}] Position calc: ${usd_volume:,.2f} × {self._controller_config.volume_percentage*100:.0f}% = ${position_size:,.2f}")

        # Apply limits
        if position_size < self._controller_config.min_position_size:
            self.log.info(f"   ⏭️  [TRACE:{correlation_id}] DECISION: Skip - position ${position_size:.2f} < min ${self._controller_config.min_position_size}")
            return 0

        if position_size > self._controller_config.max_position_size:
            self.log.info(f"   ⚠️  [TRACE:{correlation_id}] Position ${position_size:.2f} > max ${self._controller_config.max_position_size}, capping")
            position_size = self._controller_config.max_position_size

        self.log.info(f"   ✅ [TRACE:{correlation_id}] DECISION: Trade - position size ${position_size:,.2f}")
        return position_size

    def _has_position_or_strategy(self, ticker: str) -> bool:
        """Check if there's already a position or running strategy for this ticker."""
        # Check for running strategies
        all_strategies = self._trader.strategies()
        for strategy in all_strategies:
            if hasattr(strategy, 'ticker') and strategy.ticker == ticker:
                if strategy.state.name == "RUNNING":
                    self.log.debug(f"Found running strategy for {ticker}")
                    return True

        # Check for existing positions in NautilusTrader cache
        from nautilus_trader.model.identifiers import InstrumentId
        try:
            instrument_id = InstrumentId.from_str(f"{ticker}.ALPACA")
            positions = self._trader.portfolio.positions(instrument_id=instrument_id)

            for position in positions:
                if position.is_open():
                    self.log.debug(f"Found open position in portfolio for {ticker}")
                    return True
        except:
            pass

        # Also check Alpaca API directly (positions may exist but not be in NautilusTrader cache after restart)
        try:
            import requests
            import os

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
                        self.log.info(f"🛡️ Found existing Alpaca position for {ticker}: {qty} shares")
                        return True
        except Exception as e:
            self.log.debug(f"Alpaca position check failed for {ticker}: {e}")
            pass

        return False

    def _spawn_news_trading_strategy(self, ticker: str, position_size: float, volume_data: dict, headline: str, pub_time: datetime, url: str = "", correlation_id: str = ""):
        """Spawn a simple news trading strategy."""
        try:
            self.log.info(f"   🚀 [TRACE:{correlation_id}] SPAWNING NEWS TRADING STRATEGY for {ticker}")
            self.log.info(f"      [TRACE:{correlation_id}] Position size: ${position_size:.2f}")
            self.log.info(f"      [TRACE:{correlation_id}] Entry price: ${volume_data['last_price']:.2f}")
            self.log.info(f"      [TRACE:{correlation_id}] Exit after: {self._controller_config.exit_delay_minutes} minutes")

            # Create instrument first and add to cache
            from nautilus_trader.test_kit.providers import TestInstrumentProvider
            instrument = TestInstrumentProvider.equity(symbol=ticker, venue="ALPACA")

            # Get cache from trader
            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)
                self.log.info(f"   📊 Added instrument to cache: {instrument.id}")

            # Import strategy
            from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig
            from decimal import Decimal

            # Create strategy configuration
            strategy_id = f"news_{ticker}_{int(pub_time.timestamp())}"
            strategy_config = NewsVolumeStrategyConfig(
                ticker=ticker,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,

                # Trading parameters
                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._controller_config.limit_order_offset_pct,
                exit_delay_minutes=self._controller_config.exit_delay_minutes,
                extended_hours=self._controller_config.extended_hours,

                # News metadata
                news_headline=headline[:200] if headline else "",
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=correlation_id,
            )

            # Create strategy instance
            strategy = NewsVolumeStrategy(config=strategy_config)

            # Add to trader
            self._trader.add_strategy(strategy)

            # Start the strategy (using trader.start_strategy, not strategy.start)
            self._trader.start_strategy(strategy.id)

            self.log.info(f"   ✅ [TRACE:{correlation_id}] Strategy started successfully: {strategy_id}")

            # PARALLEL TEST MODE: Spawn a second strategy at different volume %
            if self._controller_config.parallel_test_mode:
                self._spawn_parallel_strategy(ticker, volume_data, headline, pub_time, url, correlation_id, instrument)

        except Exception as e:
            self.log.error(f"   ❌ Failed to spawn strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _spawn_parallel_strategy(self, ticker: str, volume_data: dict, headline: str, pub_time: datetime, url: str, correlation_id: str, instrument):
        """Spawn a parallel strategy at 10% volume for testing parallel execution."""
        try:
            from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig
            from decimal import Decimal

            # Calculate position size at parallel volume percentage (10%)
            usd_volume = volume_data['volume'] * volume_data['avg_price']
            parallel_position_size = usd_volume * self._controller_config.parallel_volume_percentage

            # Apply same limits
            if parallel_position_size < self._controller_config.min_position_size:
                self.log.info(f"   ⏭️  [TRACE:{correlation_id}] Parallel strategy skip - position ${parallel_position_size:.2f} < min")
                return

            if parallel_position_size > self._controller_config.max_position_size:
                parallel_position_size = self._controller_config.max_position_size

            parallel_correlation_id = f"{correlation_id}_10pct"
            self.log.info(f"   🔀 [TRACE:{parallel_correlation_id}] SPAWNING PARALLEL 10% STRATEGY for {ticker}")
            self.log.info(f"      [TRACE:{parallel_correlation_id}] Position size: ${parallel_position_size:.2f}")

            # Create parallel strategy with news10_ prefix
            parallel_strategy_id = f"news10_{ticker}_{int(pub_time.timestamp())}"
            parallel_config = NewsVolumeStrategyConfig(
                ticker=ticker,
                instrument_id=str(instrument.id),
                strategy_id=parallel_strategy_id,

                position_size_usd=Decimal(str(parallel_position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._controller_config.limit_order_offset_pct,
                exit_delay_minutes=self._controller_config.exit_delay_minutes,
                extended_hours=self._controller_config.extended_hours,

                news_headline=f"[10%] {headline[:190]}" if headline else "[10%]",
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=parallel_correlation_id,
            )

            parallel_strategy = NewsVolumeStrategy(config=parallel_config)
            self._trader.add_strategy(parallel_strategy)
            self._trader.start_strategy(parallel_strategy.id)

            self.log.info(f"   ✅ [TRACE:{parallel_correlation_id}] Parallel 10% strategy started: {parallel_strategy_id}")

        except Exception as e:
            self.log.error(f"   ❌ Failed to spawn parallel strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _start_health_check(self):
        """Start periodic Alpaca health check (every 5 minutes)."""
        import threading
        import sys
        import os

        # Ensure utils path is available in thread
        news_trader_path = "/opt/news-trader"
        if os.path.exists(news_trader_path) and news_trader_path not in sys.path:
            sys.path.insert(0, news_trader_path)

        # Create stop event for graceful shutdown
        self.health_check_stop_event = threading.Event()

        def run_health_check():
            """Run health check and log results."""
            try:
                from utils.alpaca_health import check_alpaca_health, log_health_check

                result = check_alpaca_health(
                    self._controller_config.alpaca_api_key,
                    self._controller_config.alpaca_secret_key
                )

                # Log with INFO level if healthy, ERROR if not
                log_health_check(result, log_level="INFO")

                if not result['healthy']:
                    self.log.error("⚠️ Alpaca connection unhealthy - trades may fail!")
            except ImportError as e:
                self.log.error(f"Health check import error: {e}")
                self.log.error(f"sys.path: {sys.path}")

        def periodic_check():
            """Run health check periodically."""
            import time
            while not self.health_check_stop_event.is_set():
                try:
                    run_health_check()
                except Exception as e:
                    self.log.error(f"Health check error: {e}")

                # Wait 5 minutes (checking stop event every second for responsive shutdown)
                for _ in range(300):
                    if self.health_check_stop_event.is_set():
                        break
                    time.sleep(1)

        # Start health check thread
        self.health_check_task = threading.Thread(target=periodic_check, daemon=True)
        self.health_check_task.start()
        self.log.info("🏥 Periodic health check started (every 5 minutes)")
