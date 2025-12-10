#!/usr/bin/env python3
"""
Unified News Controller for NautilusTrader.

This controller subscribes to GCP Pub/Sub benzinga-news topic and spawns
multiple trading strategies for each qualifying news event.

V16 Features:
- Price filter (<$5.00)
- Session filter (Extended + Closing hours only)
- Positive momentum filter (ret_3s > 0)
- Market cap filter (<$50M)

Strategies spawned per event:
1. NewsVolumeStrategy (5% volume) - Simple fixed-time exit
2. NewsTrendStrategy - Trend-based entry/exit
3. NewsVolumeStrategy (10% volume) - Parallel test
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Set, Dict, List
from concurrent.futures import TimeoutError
import asyncio
import threading
import requests

from nautilus_trader.trading.controller import Controller
from nautilus_trader.trading.trader import Trader
from nautilus_trader.common.config import ActorConfig

from google.cloud import pubsub_v1


# Session definitions (US Eastern Time)
SESSIONS = {
    'pre_market_early': (4, 0, 7, 0),      # 4:00-7:00 AM ET
    'pre_market_late': (7, 0, 9, 30),      # 7:00-9:30 AM ET
    'regular_open': (9, 30, 10, 0),        # 9:30-10:00 AM ET
    'regular_morning': (10, 0, 12, 0),     # 10:00 AM-12:00 PM ET
    'regular_afternoon': (12, 0, 15, 30),  # 12:00-3:30 PM ET
    'regular_closing': (15, 30, 16, 0),    # 3:30-4:00 PM ET
    'post_market': (16, 0, 20, 0),         # 4:00-8:00 PM ET
}

# Allowed sessions for trading (Extended + Closing)
ALLOWED_SESSIONS = ['pre_market_early', 'pre_market_late', 'post_market', 'regular_closing']


class UnifiedNewsControllerConfig(ActorConfig, frozen=True):
    """Configuration for UnifiedNewsController."""

    # Pub/Sub configuration
    project_id: str = "gnw-trader"
    subscription_id: str = "benzinga-news-trader"

    # News filtering
    max_news_age_seconds: int = 10

    # V16 Filters
    max_price: float = 5.00              # Price filter: < $5.00
    max_market_cap: float = 50_000_000   # Market cap filter: < $50M
    require_positive_momentum: bool = True  # Momentum filter: ret_3s > 0
    session_filter_enabled: bool = True  # Session filter: Extended + Closing

    # Strategy 1: NewsVolumeStrategy (5% volume)
    enable_volume_strategy: bool = True
    volume_percentage: float = 0.05
    volume_exit_delay_minutes: int = 7

    # Strategy 2: NewsTrendStrategy
    enable_trend_strategy: bool = True
    trend_entry_threshold: float = 95.0
    trend_exit_threshold: float = 64.0

    # Strategy 3: NewsVolumeStrategy (10% volume - parallel test)
    enable_parallel_strategy: bool = True
    parallel_volume_percentage: float = 0.10

    # Position limits
    min_position_size: float = 100.0
    max_position_size: float = 20000.0
    limit_order_offset_pct: float = 0.01
    extended_hours: bool = True

    # API keys
    polygon_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""


class UnifiedNewsController(Controller):
    """
    Unified Nautilus Controller that spawns multiple strategies per news event.

    For each qualifying news event:
    1. Apply V16 filters (price, session, momentum, market cap)
    2. Spawn NewsVolumeStrategy (5%)
    3. Spawn NewsTrendStrategy
    4. Spawn NewsVolumeStrategy (10%)
    """

    def __init__(self, trader: Trader, config: Optional[UnifiedNewsControllerConfig] = None):
        if config is None:
            config = UnifiedNewsControllerConfig()
        super().__init__(trader, config=config)
        self._controller_config = config

        self.log.info("🔧 UnifiedNewsController.__init__() called")

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

        # Cache for market cap lookups
        self.market_cap_cache: Dict[str, Optional[float]] = {}

    def on_start(self):
        """Called when controller starts."""
        self.log.info("🚀 UnifiedNewsController.on_start() - Starting Unified News Controller")
        self.log.info(f"📡 Subscribing to: {self.subscription_path}")
        self.log.info(f"")
        self.log.info(f"📋 V16 FILTERS:")
        self.log.info(f"   💲 Price filter: < ${self._controller_config.max_price:.2f}")
        self.log.info(f"   🏢 Market cap filter: < ${self._controller_config.max_market_cap/1e6:.0f}M")
        self.log.info(f"   📈 Momentum filter: {'Positive only' if self._controller_config.require_positive_momentum else 'Disabled'}")
        self.log.info(f"   🕐 Session filter: {'Extended + Closing' if self._controller_config.session_filter_enabled else 'Disabled'}")
        self.log.info(f"")
        self.log.info(f"📊 STRATEGIES:")
        self.log.info(f"   1️⃣  NewsVolumeStrategy (5%): {'Enabled' if self._controller_config.enable_volume_strategy else 'Disabled'}")
        self.log.info(f"   2️⃣  NewsTrendStrategy: {'Enabled' if self._controller_config.enable_trend_strategy else 'Disabled'}")
        self.log.info(f"   3️⃣  NewsVolumeStrategy (10%): {'Enabled' if self._controller_config.enable_parallel_strategy else 'Disabled'}")
        self.log.info(f"")
        self.log.info(f"💰 Position limits: ${self._controller_config.min_position_size}-${self._controller_config.max_position_size}")

        self._start_pubsub_subscription()
        self._start_health_check()

    def on_run(self):
        """Called when controller is running."""
        self.log.info("🏃 UnifiedNewsController.on_run() - Controller is now running")

    def on_stop(self):
        """Called when controller stops."""
        self.log.info("🛑 UnifiedNewsController.on_stop() - Cleaning up resources")

        if self.health_check_stop_event:
            self.health_check_stop_event.set()

        if self.streaming_pull_future:
            self.streaming_pull_future.cancel()
            try:
                self.streaming_pull_future.result()
            except:
                pass

        self.log.info("✅ UnifiedNewsController stopped successfully")

    def _start_pubsub_subscription(self):
        """Start Pub/Sub subscription in background."""
        try:
            self.log.info("📬 Starting Pub/Sub streaming pull...")

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
            raw_data = message.data.decode('utf-8')

            # Skip corrupt messages
            if len(raw_data) <= 2 or raw_data.strip() in ['-', '']:
                message.ack()
                return

            news_data = json.loads(raw_data)
            message.ack()

            # Skip heartbeat messages
            if news_data.get('type') == 'heartbeat':
                return

            self.message_count += 1
            headline = news_data.get('headline', 'No headline')[:100]
            self.log.info(f"📰 Received news #{self.message_count}: {headline}")

            # Process news event
            self._process_news_event(news_data)

        except Exception as e:
            self.log.error(f"❌ Error in message callback: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")
            message.nack()

    def _process_news_event(self, news_data: dict):
        """Process a news event and spawn strategies if it qualifies."""
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
                self.log.info(f"⏭️  [TRACE:{correlation_id}] No tickers in news")
                return

            if not pub_time_str:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] No timestamp found")
                return

            pub_time = datetime.fromisoformat(pub_time_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            age_seconds = (now - pub_time).total_seconds()

            # Check news age
            if age_seconds > self._controller_config.max_news_age_seconds:
                self.log.info(f"⏭️  [TRACE:{correlation_id}] News too old: {age_seconds:.1f}s")
                return

            self.log.info(f"📰 [TRACE:{correlation_id}] Processing: {headline[:80]}")
            self.log.info(f"   [TRACE:{correlation_id}] Tickers: {', '.join(tickers)}")
            self.log.info(f"   [TRACE:{correlation_id}] Age: {age_seconds:.1f}s")

            # ============ SESSION FILTER ============
            if self._controller_config.session_filter_enabled:
                current_session = self._get_current_session(now)
                if current_session not in ALLOWED_SESSIONS:
                    self.log.info(f"⏭️  [TRACE:{correlation_id}] Session filter: {current_session} not in {ALLOWED_SESSIONS}")
                    return
                self.log.info(f"✅ [TRACE:{correlation_id}] Session filter passed: {current_session}")

            # Process each ticker
            for ticker in tickers:
                symbol = ticker.split(':')[-1]
                self._process_ticker(symbol, headline, pub_time, url, correlation_id, news_data)

        except Exception as e:
            self.log.error(f"❌ Error processing news event: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _process_ticker(self, symbol: str, headline: str, pub_time: datetime,
                        url: str, correlation_id: str, news_data: dict):
        """Process a single ticker from news event."""
        try:
            trace_id = f"{correlation_id}_{symbol}"

            # Check if already has position or strategy
            if self._has_position_or_strategy(symbol):
                self.log.info(f"⏭️  [TRACE:{trace_id}] Already has position/strategy")
                return

            # ============ GET POLYGON DATA (volume + price) ============
            # For test news, use mock data
            if '[TEST]' in headline:
                self.log.info(f"🧪 [TRACE:{trace_id}] TEST NEWS - using mock data")
                test_price = self._get_alpaca_quote(symbol) or 100.00
                volume_data = {
                    'symbol': symbol,
                    'volume': 10000,
                    'avg_price': test_price,
                    'last_price': test_price,
                    'price_3s_ago': test_price * 0.99,  # Mock positive momentum
                    'bars_count': 3,
                }
            else:
                volume_data = self._check_polygon_trading(symbol, trace_id)
                if not volume_data:
                    self.log.info(f"⏭️  [TRACE:{trace_id}] No trading activity in last 3s")
                    return

            current_price = volume_data['last_price']

            # ============ PRICE FILTER ============
            if current_price >= self._controller_config.max_price:
                self.log.info(f"⏭️  [TRACE:{trace_id}] Price filter: ${current_price:.2f} >= ${self._controller_config.max_price:.2f}")
                return
            self.log.info(f"✅ [TRACE:{trace_id}] Price filter passed: ${current_price:.2f}")

            # ============ MOMENTUM FILTER ============
            if self._controller_config.require_positive_momentum:
                price_3s_ago = volume_data.get('price_3s_ago', current_price)
                if price_3s_ago > 0:
                    ret_3s = (current_price - price_3s_ago) / price_3s_ago
                    if ret_3s <= 0:
                        self.log.info(f"⏭️  [TRACE:{trace_id}] Momentum filter: ret_3s={ret_3s*100:.2f}% <= 0")
                        return
                    self.log.info(f"✅ [TRACE:{trace_id}] Momentum filter passed: ret_3s={ret_3s*100:.2f}%")

            # ============ MARKET CAP FILTER ============
            market_cap = self._get_market_cap(symbol)
            if market_cap is not None:
                if market_cap >= self._controller_config.max_market_cap:
                    self.log.info(f"⏭️  [TRACE:{trace_id}] Market cap filter: ${market_cap/1e6:.1f}M >= ${self._controller_config.max_market_cap/1e6:.0f}M")
                    return
                self.log.info(f"✅ [TRACE:{trace_id}] Market cap filter passed: ${market_cap/1e6:.1f}M")
            else:
                self.log.info(f"⚠️  [TRACE:{trace_id}] Market cap unknown - proceeding anyway")

            # ============ ALL FILTERS PASSED - SPAWN STRATEGIES ============
            self.log.info(f"🎯 [TRACE:{trace_id}] ALL FILTERS PASSED - Spawning strategies")

            strategies_spawned = 0

            # Strategy 1: NewsVolumeStrategy (5%)
            if self._controller_config.enable_volume_strategy:
                position_size = self._calculate_position_size(volume_data, self._controller_config.volume_percentage, trace_id)
                if position_size > 0:
                    self._spawn_volume_strategy(
                        symbol, position_size, volume_data, headline, pub_time, url,
                        trace_id, prefix="news", exit_delay=self._controller_config.volume_exit_delay_minutes
                    )
                    strategies_spawned += 1

            # Strategy 2: NewsTrendStrategy
            if self._controller_config.enable_trend_strategy:
                # Use same position size calculation as volume strategy for consistency
                position_size = self._calculate_position_size(volume_data, self._controller_config.volume_percentage, trace_id)
                if position_size > 0:
                    self._spawn_trend_strategy(
                        symbol, position_size, volume_data, headline, pub_time, url, trace_id
                    )
                    strategies_spawned += 1

            # Strategy 3: NewsVolumeStrategy (10%)
            if self._controller_config.enable_parallel_strategy:
                position_size = self._calculate_position_size(volume_data, self._controller_config.parallel_volume_percentage, trace_id)
                if position_size > 0:
                    self._spawn_volume_strategy(
                        symbol, position_size, volume_data, headline, pub_time, url,
                        trace_id, prefix="news10", exit_delay=self._controller_config.volume_exit_delay_minutes
                    )
                    strategies_spawned += 1

            self.log.info(f"✅ [TRACE:{trace_id}] Spawned {strategies_spawned} strategies for {symbol}")

        except Exception as e:
            self.log.error(f"❌ [TRACE:{correlation_id}] Error processing ticker {symbol}: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _get_current_session(self, now: datetime) -> str:
        """Determine current trading session based on US Eastern time."""
        import pytz

        # Convert to US Eastern
        eastern = pytz.timezone('US/Eastern')
        now_et = now.astimezone(eastern)

        hour = now_et.hour
        minute = now_et.minute
        time_decimal = hour + minute / 60.0

        for session_name, (start_h, start_m, end_h, end_m) in SESSIONS.items():
            start = start_h + start_m / 60.0
            end = end_h + end_m / 60.0
            if start <= time_decimal < end:
                return session_name

        return 'outside_hours'

    def _check_polygon_trading(self, symbol: str, trace_id: str) -> Optional[dict]:
        """Check trading activity on Polygon in last 3 seconds."""
        try:
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

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if not results:
                return None

            total_volume = sum(bar['v'] for bar in results)
            total_value = sum(bar['v'] * bar['c'] for bar in results)
            avg_price = total_value / total_volume if total_volume > 0 else 0

            first_bar = results[0]
            last_bar = results[-1]

            self.log.info(f"   📊 [TRACE:{trace_id}] Polygon: {len(results)} bars, {total_volume:,.0f} shares @ ${last_bar['c']:.2f}")

            return {
                'symbol': symbol,
                'volume': total_volume,
                'avg_price': avg_price,
                'last_price': last_bar['c'],
                'price_3s_ago': first_bar['o'],  # Open of first bar = price 3s ago
                'bars_count': len(results),
            }

        except Exception as e:
            self.log.error(f"   ❌ [TRACE:{trace_id}] Polygon error: {e}")
            return None

    def _get_market_cap(self, symbol: str) -> Optional[float]:
        """Get market cap for a symbol from Polygon."""
        # Check cache first
        if symbol in self.market_cap_cache:
            return self.market_cap_cache[symbol]

        try:
            url = f"https://api.polygon.io/v3/reference/tickers/{symbol}"
            params = {'apiKey': self._controller_config.polygon_api_key}

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', {})
                market_cap = results.get('market_cap')

                # Cache the result
                self.market_cap_cache[symbol] = market_cap
                return market_cap

            self.market_cap_cache[symbol] = None
            return None

        except Exception as e:
            self.log.debug(f"Market cap lookup failed for {symbol}: {e}")
            self.market_cap_cache[symbol] = None
            return None

    def _get_alpaca_quote(self, symbol: str) -> Optional[float]:
        """Get current quote from Alpaca."""
        try:
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
                return float(quote.get('ap') or quote.get('bp') or 0)
            return None

        except Exception:
            return None

    def _calculate_position_size(self, volume_data: dict, volume_pct: float, trace_id: str) -> float:
        """Calculate position size based on volume percentage."""
        usd_volume = volume_data['volume'] * volume_data['avg_price']
        position_size = usd_volume * volume_pct

        if position_size < self._controller_config.min_position_size:
            self.log.info(f"   ⏭️  [TRACE:{trace_id}] Position ${position_size:.2f} < min ${self._controller_config.min_position_size}")
            return 0

        if position_size > self._controller_config.max_position_size:
            position_size = self._controller_config.max_position_size

        return position_size

    def _has_position_or_strategy(self, ticker: str) -> bool:
        """Check if there's already a position or running strategy for this ticker."""
        # Check running strategies
        for strategy in self._trader.strategies():
            if hasattr(strategy, 'ticker') and strategy.ticker == ticker:
                if strategy.state.name == "RUNNING":
                    return True

        # Check Alpaca API directly
        try:
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
        except Exception:
            pass

        return False

    def _spawn_volume_strategy(self, ticker: str, position_size: float, volume_data: dict,
                               headline: str, pub_time: datetime, url: str, trace_id: str,
                               prefix: str = "news", exit_delay: int = 7):
        """Spawn a NewsVolumeStrategy instance."""
        try:
            from nautilus_trader.test_kit.providers import TestInstrumentProvider
            from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig
            from decimal import Decimal

            # Create instrument
            instrument = TestInstrumentProvider.equity(symbol=ticker, venue="ALPACA")
            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)

            # Create strategy
            strategy_id = f"{prefix}_{ticker}_{int(pub_time.timestamp())}"
            strategy_config = NewsVolumeStrategyConfig(
                ticker=ticker,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,
                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._controller_config.limit_order_offset_pct,
                exit_delay_minutes=exit_delay,
                extended_hours=self._controller_config.extended_hours,
                news_headline=headline[:200],
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=trace_id,
            )

            strategy = NewsVolumeStrategy(config=strategy_config)
            self._trader.add_strategy(strategy)
            self._trader.start_strategy(strategy.id)

            self.log.info(f"   🚀 [TRACE:{trace_id}] Spawned {prefix} strategy: ${position_size:.2f}")

        except Exception as e:
            self.log.error(f"   ❌ [TRACE:{trace_id}] Failed to spawn volume strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _spawn_trend_strategy(self, ticker: str, position_size: float, volume_data: dict,
                              headline: str, pub_time: datetime, url: str, trace_id: str):
        """Spawn a NewsTrendStrategy instance."""
        try:
            from nautilus_trader.test_kit.providers import TestInstrumentProvider
            from strategies.news_trend_strategy import NewsTrendStrategy, NewsTrendStrategyConfig
            from decimal import Decimal

            # Create instrument
            instrument = TestInstrumentProvider.equity(symbol=ticker, venue="ALPACA")
            cache = self._trader._cache
            if not cache.instrument(instrument.id):
                cache.add_instrument(instrument)

            # Create strategy
            strategy_id = f"trend_{ticker}_{int(pub_time.timestamp())}"
            strategy_config = NewsTrendStrategyConfig(
                ticker=ticker,
                instrument_id=str(instrument.id),
                strategy_id=strategy_id,
                position_size_usd=Decimal(str(position_size)),
                entry_price=Decimal(str(volume_data['last_price'])),
                limit_order_offset_pct=self._controller_config.limit_order_offset_pct,
                extended_hours=self._controller_config.extended_hours,
                trend_entry_threshold=self._controller_config.trend_entry_threshold,
                trend_exit_threshold=self._controller_config.trend_exit_threshold,
                news_headline=headline[:200],
                publishing_date=pub_time.isoformat(),
                news_url=url,
                correlation_id=trace_id,
                polygon_api_key=self._controller_config.polygon_api_key,
            )

            strategy = NewsTrendStrategy(config=strategy_config)
            self._trader.add_strategy(strategy)
            self._trader.start_strategy(strategy.id)

            self.log.info(f"   🚀 [TRACE:{trace_id}] Spawned trend strategy: ${position_size:.2f}")

        except Exception as e:
            self.log.error(f"   ❌ [TRACE:{trace_id}] Failed to spawn trend strategy: {e}")
            import traceback
            self.log.error(f"Traceback: {traceback.format_exc()}")

    def _start_health_check(self):
        """Start periodic Alpaca health check."""
        import os

        news_trader_path = "/opt/news-trader"
        if os.path.exists(news_trader_path) and news_trader_path not in sys.path:
            sys.path.insert(0, news_trader_path)

        self.health_check_stop_event = threading.Event()

        def run_health_check():
            try:
                from utils.alpaca_health import check_alpaca_health, log_health_check

                result = check_alpaca_health(
                    self._controller_config.alpaca_api_key,
                    self._controller_config.alpaca_secret_key
                )
                log_health_check(result, log_level="INFO")

                if not result['healthy']:
                    self.log.error("⚠️ Alpaca connection unhealthy!")
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
        self.log.info("🏥 Periodic health check started (every 5 minutes)")
