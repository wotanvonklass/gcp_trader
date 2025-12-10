#!/usr/bin/env python3
"""
Pub/Sub News Controller (10% Volume) for NautilusTrader.

This is a parallel controller that trades 10% of USD volume.
Used for testing parallel strategy execution alongside the main 5% controller.
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


class PubSubNewsController10PctConfig(ActorConfig, frozen=True):
    """
    Configuration for PubSubNewsController10Pct.
    """
    # Pub/Sub configuration
    project_id: str = "gnw-trader"
    subscription_id: str = "benzinga-news-trader"

    # News filtering
    min_news_age_seconds: int = 2
    max_news_age_seconds: int = 10

    # Trading parameters - 10% of volume (vs 5% in main controller)
    volume_percentage: float = 0.10
    min_position_size: float = 100.0
    max_position_size: float = 20000.0
    limit_order_offset_pct: float = 0.01
    exit_delay_minutes: int = 7
    extended_hours: bool = True

    # Polygon API
    polygon_api_key: str = ""

    # Alpaca credentials (for direct API use)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""


class PubSubNewsController10Pct(Controller):
    """
    Nautilus Controller that subscribes to Pub/Sub and spawns strategies at 10% volume.

    This runs in parallel with the main 5% controller to test concurrent execution.
    Uses "news10_" prefix for strategy IDs to differentiate from main controller.
    """

    def __init__(self, trader: Trader, config: Optional[PubSubNewsController10PctConfig] = None):
        if config is None:
            config = PubSubNewsController10PctConfig()
        super().__init__(trader, config=config)
        self._controller_config = config

        self.log.info("🔧 PubSubNewsController10Pct.__init__() called (10% volume)")

        # Initialize Pub/Sub subscriber
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(
            self._controller_config.project_id,
            self._controller_config.subscription_id
        )

        self.streaming_pull_future = None
        self.message_count = 0

    def on_start(self):
        """Called when controller starts - NautilusTrader lifecycle method."""
        self.log.info("🚀 PubSubNewsController10Pct.on_start() - Starting 10% Volume Controller")
        self.log.info(f"📡 Subscribing to: {self.subscription_path}")
        self.log.info(f"⏰ News age filter: {self._controller_config.min_news_age_seconds}-{self._controller_config.max_news_age_seconds}s")
        self.log.info(f"💰 Position limits: ${self._controller_config.min_position_size}-${self._controller_config.max_position_size}")
        self.log.info(f"📊 Volume %: {self._controller_config.volume_percentage * 100}% (10% controller)")
        self.log.info(f"⏱️ Exit delay: {self._controller_config.exit_delay_minutes} minutes")
        self.log.info(f"🌙 Extended hours: {self._controller_config.extended_hours}")

        # Start Pub/Sub subscription in background
        self._start_pubsub_subscription()

    def on_run(self):
        """Called when controller is running."""
        self.log.info("🏃 PubSubNewsController10Pct.on_run() - 10% Controller is now running")

    def on_stop(self):
        """Called when controller stops."""
        self.log.info("🛑 PubSubNewsController10Pct.on_stop() - Cleaning up resources")

        # Stop Pub/Sub subscription
        if self.streaming_pull_future:
            self.streaming_pull_future.cancel()
            try:
                self.streaming_pull_future.result()
            except:
                pass

        self.log.info("✅ PubSubNewsController10Pct stopped successfully")

    def _start_pubsub_subscription(self):
        """Start Pub/Sub subscription in background."""
        try:
            self.log.info("📬 Starting Pub/Sub streaming pull (10% controller)...")

            # Start streaming pull
            self.streaming_pull_future = self.subscriber.subscribe(
                self.subscription_path,
                callback=self._message_callback
            )

            self.log.info("✅ Pub/Sub subscription active (10% controller)")

        except Exception as e:
            self.log.error(f"❌ Failed to start Pub/Sub subscription: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _message_callback(self, message: pubsub_v1.subscriber.message.Message):
        """Callback for Pub/Sub messages."""
        try:
            # Debug: Log message receipt
            self.log.info(f"🔍 [10%] Message ID: {message.message_id}")

            # Decode message
            raw_data = message.data.decode('utf-8')

            # Skip corrupt messages
            if len(raw_data) <= 2 or raw_data.strip() in ['-', '']:
                message.ack()
                return

            news_data = json.loads(raw_data)

            # Acknowledge message immediately
            message.ack()

            # Skip heartbeat messages
            if news_data.get('type') == 'heartbeat':
                return

            self.message_count += 1

            # Extract basic info
            headline = news_data.get('headline', 'No headline')[:100]
            news_id = news_data.get('id', '')

            self.log.info(f"📰 [10%] Received news #{self.message_count}: {headline}")

            # Process news event
            self._process_news_event(news_data)

        except Exception as e:
            self.log.error(f"❌ [10%] Error in message callback: {e}")
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

            # Build correlation ID with 10% prefix
            if news_id:
                base_id = str(news_id)
                if tickers and len(tickers) > 0:
                    first_ticker = tickers[0].split(':')[-1]
                    correlation_id = f"{first_ticker}_10pct_{base_id}"
                else:
                    correlation_id = f"10pct_{base_id}"
            else:
                import uuid
                correlation_id = f"10pct_{str(uuid.uuid4())[:8]}"

            self.log.info(f"📋 [TRACE:{correlation_id}] Processing news (10% controller)")

            # Get timestamp
            pub_time_str = (news_data.get('createdAt') or
                           news_data.get('updatedAt') or
                           news_data.get('capturedAt'))

            if not tickers:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] No tickers in news")
                return

            if not pub_time_str:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] No timestamp found")
                return

            # Parse publication time
            pub_time = datetime.fromisoformat(pub_time_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            age_seconds = (now - pub_time).total_seconds()

            self.log.info(f"📰 [TRACE:{correlation_id}] News age: {age_seconds:.1f}s, Tickers: {', '.join(tickers)}")

            if age_seconds > self._controller_config.max_news_age_seconds:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] News too old: {age_seconds:.1f}s")
                return

            # Process each ticker
            for ticker in tickers:
                symbol = ticker.split(':')[-1]

                # Check for existing position/strategy (use 10pct prefix)
                if self._has_position_or_strategy(symbol):
                    self.log.info(f"⏭️  [TRACE:{correlation_id}] Skipping {symbol} - already has position/strategy")
                    continue

                # Handle test news
                if '[TEST]' in headline:
                    self.log.info(f"🧪 [TRACE:{correlation_id}] TEST NEWS - using mock volume")
                    test_price = self._get_alpaca_quote(symbol) or 100.00
                    volume_data = {
                        'symbol': symbol,
                        'volume': 10000,
                        'avg_price': test_price,
                        'last_price': test_price,
                        'bars_count': 3,
                        'timestamp': datetime.now(timezone.utc)
                    }
                else:
                    # Check Polygon for trading activity
                    self.log.info(f"📊 [TRACE:{correlation_id}] Checking {symbol} on Polygon...")
                    volume_data = self._check_polygon_trading(symbol, correlation_id)

                    if not volume_data:
                        self.log.info(f"⏭️  [TRACE:{correlation_id}] Skip {symbol} - no trading activity")
                        continue

                self.log.info(f"✅ [TRACE:{correlation_id}] Trading detected: {volume_data['volume']:,.0f} shares @ ${volume_data['last_price']:.2f}")

                # Calculate position size (10% of volume)
                position_size = self._calculate_position_size(volume_data, correlation_id)

                if position_size == 0:
                    continue

                # Spawn strategy
                self._spawn_news_trading_strategy(symbol, position_size, volume_data, headline, pub_time, url, correlation_id)

        except Exception as e:
            self.log.error(f"❌ [10%] Error processing news: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _get_alpaca_quote(self, symbol: str) -> Optional[float]:
        """Get current quote from Alpaca."""
        try:
            import requests
            import os

            api_key = os.environ.get('ALPACA_API_KEY')
            secret_key = os.environ.get('ALPACA_SECRET_KEY')

            if not api_key or not secret_key:
                return None

            url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
            headers = {
                'APCA-API-KEY-ID': api_key,
                'APCA-API-SECRET-KEY': secret_key
            }

            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                quote = data.get('quote', {})
                return float(quote.get('ap') or quote.get('bp') or 0) or None

            return None

        except Exception as e:
            self.log.error(f"Error getting Alpaca quote: {e}")
            return None

    def _check_polygon_trading(self, symbol: str, correlation_id: str = "") -> Optional[dict]:
        """Check if there has been trading activity on Polygon in last 3 seconds."""
        try:
            import requests

            now = datetime.now(timezone.utc)
            three_sec_ago = now - timedelta(seconds=3)

            from_ms = int(three_sec_ago.timestamp() * 1000)
            to_ms = int(now.timestamp() * 1000)

            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/second/{from_ms}/{to_ms}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'apiKey': self._controller_config.polygon_api_key
            }

            self.log.info(f"   📊 [TRACE:{correlation_id}] Polygon query: {symbol}")

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if not results:
                return None

            total_volume = sum(bar['v'] for bar in results)
            total_value = sum(bar['v'] * bar['c'] for bar in results)
            avg_price = total_value / total_volume if total_volume > 0 else 0
            last_bar = results[-1]

            self.log.info(f"   📊 [TRACE:{correlation_id}] Polygon: {len(results)} bars, {total_volume:,.0f} shares")

            return {
                'symbol': symbol,
                'volume': total_volume,
                'avg_price': avg_price,
                'last_price': last_bar['c'],
                'bars_count': len(results),
                'timestamp': datetime.fromtimestamp(last_bar['t'] / 1000, tz=timezone.utc)
            }

        except Exception as e:
            self.log.error(f"   ❌ [TRACE:{correlation_id}] Polygon error: {e}")
            return None

    def _calculate_position_size(self, volume_data: dict, correlation_id: str = "") -> float:
        """Calculate position size based on 10% of volume."""
        usd_volume = volume_data['volume'] * volume_data['avg_price']
        position_size = usd_volume * self._controller_config.volume_percentage  # 10%

        self.log.info(f"   💰 [TRACE:{correlation_id}] Position calc: ${usd_volume:,.2f} × {self._controller_config.volume_percentage*100:.0f}% = ${position_size:,.2f}")

        if position_size < self._controller_config.min_position_size:
            self.log.info(f"   ⏭️  [TRACE:{correlation_id}] Skip - position ${position_size:.2f} < min ${self._controller_config.min_position_size}")
            return 0

        if position_size > self._controller_config.max_position_size:
            self.log.info(f"   ⚠️  [TRACE:{correlation_id}] Capping at ${self._controller_config.max_position_size}")
            position_size = self._controller_config.max_position_size

        self.log.info(f"   ✅ [TRACE:{correlation_id}] DECISION: Trade ${position_size:,.2f}")
        return position_size

    def _has_position_or_strategy(self, ticker: str) -> bool:
        """Check if there's already a position or running strategy for this ticker (10% strategies only)."""
        # Check for running 10% strategies (prefix: news10_)
        all_strategies = self._trader.strategies()
        for strategy in all_strategies:
            if hasattr(strategy, 'ticker') and strategy.ticker == ticker:
                # Only check strategies from this controller (news10_ prefix)
                strategy_id = str(strategy.id)
                if "news10_" in strategy_id and strategy.state.name == "RUNNING":
                    self.log.debug(f"Found running 10% strategy for {ticker}")
                    return True

        # Check Alpaca for existing positions (shared between controllers)
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
                        self.log.info(f"🛡️ [10%] Found existing Alpaca position for {ticker}: {qty} shares")
                        return True
        except:
            pass

        return False

    def _spawn_news_trading_strategy(self, ticker: str, position_size: float, volume_data: dict, headline: str, pub_time: datetime, url: str = "", correlation_id: str = ""):
        """Spawn a news trading strategy with 10% volume sizing."""
        try:
            self.log.info(f"   🚀 [TRACE:{correlation_id}] SPAWNING 10% STRATEGY for {ticker}")
            self.log.info(f"      [TRACE:{correlation_id}] Position size: ${position_size:.2f}")
            self.log.info(f"      [TRACE:{correlation_id}] Entry price: ${volume_data['last_price']:.2f}")

            # Create instrument and add to cache
            from nautilus_trader.test_kit.providers import TestInstrumentProvider
            instrument = TestInstrumentProvider.equity(symbol=ticker, venue="ALPACA")

            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)
                self.log.info(f"   📊 Added instrument to cache: {instrument.id}")

            # Import strategy
            from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig
            from decimal import Decimal

            # Use news10_ prefix for 10% strategies
            strategy_id = f"news10_{ticker}_{int(pub_time.timestamp())}"
            strategy_config = NewsVolumeStrategyConfig(
                ticker=ticker,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,

                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._controller_config.limit_order_offset_pct,
                exit_delay_minutes=self._controller_config.exit_delay_minutes,
                extended_hours=self._controller_config.extended_hours,

                news_headline=f"[10%] {headline[:190]}" if headline else "[10%]",
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=correlation_id,
            )

            strategy = NewsVolumeStrategy(config=strategy_config)

            self._trader.add_strategy(strategy)
            self._trader.start_strategy(strategy.id)

            self.log.info(f"   ✅ [TRACE:{correlation_id}] 10% Strategy started: {strategy_id}")

        except Exception as e:
            self.log.error(f"   ❌ [10%] Failed to spawn strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
