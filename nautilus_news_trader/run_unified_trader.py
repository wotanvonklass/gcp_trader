#!/usr/bin/env python3
"""
Unified News Trading System with Nautilus and Pub/Sub.

This script starts a NautilusTrader system with V16 features:
- Price filter (<$5.00)
- Session filter (Extended + Closing hours)
- Positive momentum filter (ret_3s > 0)
- Market cap filter (<$50M)

Spawns 3 strategies per news event:
1. NewsVolumeStrategy (5% volume) - Simple fixed-time exit
2. NewsTrendStrategy - Trend-based entry/exit
3. NewsVolumeStrategy (10% volume) - Parallel test
"""

import argparse
import sys
import signal
import logging
import os
import fcntl
import atexit
from pathlib import Path
from datetime import datetime

# Setup JSON logging for GCP Cloud Logging
from utils.json_logging import setup_json_logging
logger = setup_json_logging(logging.getLogger(__name__), level=logging.INFO)

# Also configure root logger for JSON output
root_logger = logging.getLogger()
setup_json_logging(root_logger, level=logging.INFO)

# Add news-trader to path for local imports
news_trader_path = "/opt/news-trader"
if os.path.exists(news_trader_path) and news_trader_path not in sys.path:
    sys.path.insert(0, news_trader_path)

# Use private Nautilus installation (with Alpaca adapters)
custom_nautilus_path = "/opt/nautilus_trader_private"
if os.path.exists(custom_nautilus_path) and custom_nautilus_path not in sys.path:
    sys.path.insert(0, custom_nautilus_path)
    logger.info(f"Using private Nautilus installation from: {custom_nautilus_path}")

# Import NautilusTrader components
from nautilus_trader.config import TradingNodeConfig, LoggingConfig, CacheConfig, MessageBusConfig
from nautilus_trader.live.config import LiveExecEngineConfig, LiveRiskEngineConfig, LiveDataEngineConfig
from nautilus_trader.trading.config import ImportableControllerConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId

# Import custom adapters from nautilus_trader_private
from nautilus_trader.adapters.alpaca.config import AlpacaExecClientConfig
from nautilus_trader.adapters.alpaca.factories import AlpacaLiveExecClientFactory
from nautilus_trader.adapters.polygon.config import PolygonDataClientConfig
from nautilus_trader.adapters.polygon.factories import PolygonLiveDataClientFactory

# Runner directory management
RUNNER_DIR = Path("/opt/news-trader/runner")
lock_file_handle = None
config_dir = None


def setup_config_directory() -> tuple[Path, str]:
    """Setup config directory structure and return paths."""
    global config_dir

    # Create config-specific directory for unified controller
    config_dir = RUNNER_DIR / "unified"
    config_dir.mkdir(parents=True, exist_ok=True)

    pid_file = config_dir / "process.pid"
    return pid_file, "unified"


def acquire_single_instance_lock():
    """Ensure only one instance runs using PID file lock."""
    global lock_file_handle

    PID_FILE, config_name = setup_config_directory()

    try:
        lock_file_handle = open(PID_FILE, 'w')
        fcntl.lockf(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        pid = os.getpid()
        lock_file_handle.seek(0)
        lock_file_handle.write(f"{pid}\n")
        lock_file_handle.flush()
        os.fsync(lock_file_handle.fileno())

        def cleanup():
            try:
                if lock_file_handle:
                    lock_file_handle.close()
                if PID_FILE.exists():
                    PID_FILE.unlink()
                    logger.info(f"Released lock")
            except Exception as e:
                logger.warning(f"Error during cleanup: {e}")

        def signal_handler(signum, frame):
            logger.info(f"\nReceived signal {signum}, shutting down gracefully...")
            cleanup()
            sys.exit(0)

        atexit.register(cleanup)
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        logger.info(f"Acquired lock (PID: {pid})")
        logger.info(f"Config directory: {config_dir}")
        return config_dir

    except IOError:
        if PID_FILE.exists():
            try:
                with open(PID_FILE, 'r') as f:
                    existing_pid = f.read().strip()

                if existing_pid:
                    try:
                        os.kill(int(existing_pid), 0)
                        logger.error(f"Another instance is already running (PID: {existing_pid})")
                        logger.error(f"   To stop it: kill {existing_pid}")
                        sys.exit(1)
                    except (OSError, ValueError):
                        logger.warning(f"Found stale PID file for dead process {existing_pid}, cleaning up...")
                        PID_FILE.unlink()
                        return acquire_single_instance_lock()
                else:
                    logger.warning(f"Found empty PID file, removing it...")
                    PID_FILE.unlink()
                    return acquire_single_instance_lock()

            except Exception as e:
                logger.error(f"Error checking PID file: {e}")
                logger.error(f"   Try removing {PID_FILE} manually")
                sys.exit(1)
        else:
            logger.error(f"Cannot create lock file {PID_FILE}")
            sys.exit(1)


def main():
    """Main entry point for unified news trading system."""
    logger.info("=" * 70)
    logger.info("UNIFIED NEWS TRADING SYSTEM - V16 FEATURES")
    logger.info("=" * 70)

    # Acquire single instance lock
    config_dir = acquire_single_instance_lock()

    # Get Alpaca credentials
    alpaca_api_key = os.getenv("ALPACA_API_KEY")
    alpaca_secret_key = os.getenv("ALPACA_SECRET_KEY")

    if alpaca_api_key and alpaca_secret_key:
        logger.info(f"Alpaca credentials found: {alpaca_api_key[:10]}...")

        logger.info("Running Alpaca health check...")
        from utils.alpaca_health import require_healthy_alpaca
        try:
            account_info = require_healthy_alpaca(alpaca_api_key, alpaca_secret_key)
            logger.info(f"Alpaca account validated - Ready to trade")
        except RuntimeError as e:
            logger.error(f"Alpaca health check failed: {e}")
            logger.error("   Cannot start trading system with invalid Alpaca credentials")
            sys.exit(1)
    else:
        logger.error("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        sys.exit(1)

    # Get Polygon API key
    polygon_api_key = os.getenv("POLYGON_API_KEY")
    if not polygon_api_key:
        logger.error("POLYGON_API_KEY must be set")
        sys.exit(1)

    # Get Pub/Sub configuration
    project_id = os.getenv("GCP_PROJECT_ID")
    subscription_id = os.getenv("PUBSUB_SUBSCRIPTION")
    if not project_id or not subscription_id:
        logger.error("GCP_PROJECT_ID and PUBSUB_SUBSCRIPTION must be set")
        sys.exit(1)

    logger.info(f"Pub/Sub: {project_id}/{subscription_id}")

    # Get proxy URLs
    trade_updates_ws_url = os.getenv("TRADE_UPDATES_WS_URL", "ws://localhost:8099/trade-updates-paper")
    polygon_proxy_url = os.getenv("POLYGON_PROXY_URL", "ws://localhost:8765")

    logger.info(f"Trade updates proxy: {trade_updates_ws_url}")
    logger.info(f"Polygon proxy: {polygon_proxy_url}")

    # V16 Filter configuration from environment
    max_price = float(os.getenv("MAX_PRICE", 5.00))
    max_market_cap = float(os.getenv("MAX_MARKET_CAP", 50_000_000))
    require_positive_momentum = os.getenv("REQUIRE_POSITIVE_MOMENTUM", "true").lower() == "true"
    session_filter_enabled = os.getenv("SESSION_FILTER_ENABLED", "true").lower() == "true"

    # Strategy enable flags
    enable_volume_strategy = os.getenv("ENABLE_VOLUME_STRATEGY", "true").lower() == "true"
    enable_trend_strategy = os.getenv("ENABLE_TREND_STRATEGY", "true").lower() == "true"
    enable_parallel_strategy = os.getenv("ENABLE_PARALLEL_STRATEGY", "true").lower() == "true"

    logger.info("")
    logger.info("V16 FILTERS:")
    logger.info(f"   Price filter: < ${max_price:.2f}")
    logger.info(f"   Market cap filter: < ${max_market_cap/1e6:.0f}M")
    logger.info(f"   Momentum filter: {'Positive only' if require_positive_momentum else 'Disabled'}")
    logger.info(f"   Session filter: {'Extended + Closing' if session_filter_enabled else 'Disabled'}")
    logger.info("")
    logger.info("STRATEGIES:")
    logger.info(f"   1. NewsVolumeStrategy (5%): {'Enabled' if enable_volume_strategy else 'Disabled'}")
    logger.info(f"   2. NewsTrendStrategy: {'Enabled' if enable_trend_strategy else 'Disabled'}")
    logger.info(f"   3. NewsVolumeStrategy (10%): {'Enabled' if enable_parallel_strategy else 'Disabled'}")
    logger.info("")

    # Create controller configuration
    controller_config = ImportableControllerConfig(
        controller_path="actors.unified_news_controller:UnifiedNewsController",
        config_path="actors.unified_news_controller:UnifiedNewsControllerConfig",
        config={
            # Pub/Sub configuration
            "project_id": project_id,
            "subscription_id": subscription_id,

            # News filtering
            "max_news_age_seconds": int(os.getenv("MAX_NEWS_AGE_SECONDS", 10)),

            # V16 Filters
            "max_price": max_price,
            "max_market_cap": max_market_cap,
            "require_positive_momentum": require_positive_momentum,
            "session_filter_enabled": session_filter_enabled,

            # Strategy 1: NewsVolumeStrategy (5%)
            "enable_volume_strategy": enable_volume_strategy,
            "volume_percentage": float(os.getenv("VOLUME_PERCENTAGE", 0.05)),
            "volume_exit_delay_minutes": int(os.getenv("EXIT_DELAY_MINUTES", 7)),

            # Strategy 2: NewsTrendStrategy
            "enable_trend_strategy": enable_trend_strategy,
            "trend_entry_threshold": float(os.getenv("TREND_ENTRY_THRESHOLD", 95.0)),
            "trend_exit_threshold": float(os.getenv("TREND_EXIT_THRESHOLD", 64.0)),

            # Strategy 3: NewsVolumeStrategy (10%)
            "enable_parallel_strategy": enable_parallel_strategy,
            "parallel_volume_percentage": float(os.getenv("PARALLEL_VOLUME_PERCENTAGE", 0.10)),

            # Position limits
            "min_position_size": float(os.getenv("MIN_POSITION_SIZE", 100)),
            "max_position_size": float(os.getenv("MAX_POSITION_SIZE", 20000)),
            "limit_order_offset_pct": float(os.getenv("LIMIT_ORDER_OFFSET_PCT", 0.01)),
            "extended_hours": os.getenv("EXTENDED_HOURS", "true").lower() == "true",

            # API keys
            "polygon_api_key": polygon_api_key,
            "alpaca_api_key": alpaca_api_key,
            "alpaca_secret_key": alpaca_secret_key,
        },
    )

    logger.info("Controller configured")

    # Create TradingNode configuration
    node_config = TradingNodeConfig(
        trader_id=TraderId("UNIFIED-TRADER"),

        controller=controller_config,

        data_clients={
            "POLYGON": PolygonDataClientConfig(
                api_key=polygon_api_key,
                base_url_ws=polygon_proxy_url,
                subscribe_trades=True,
                subscribe_quotes=True,
                subscribe_bars=True,
                subscribe_second_aggregates=True,
                include_extended_hours=os.getenv("EXTENDED_HOURS", "true").lower() == "true",
            ),
        },

        exec_clients={
            "ALPACA": AlpacaExecClientConfig(
                api_key=alpaca_api_key,
                secret_key=alpaca_secret_key,
                paper_trading=True,
                validate_orders=True,
                trade_updates_ws_url=trade_updates_ws_url,
                trade_updates_auth_key="nautilus",
                trade_updates_auth_secret="nautilus",
            ),
        },

        cache=CacheConfig(),
        message_bus=MessageBusConfig(),

        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="INFO",
            log_directory=str(config_dir / "logs") if config_dir else "/opt/news-trader/logs",
            log_file_name=f"unified_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            log_file_format=None,
            bypass_logging=False,
        ),
    )

    # Initialize trading node
    logger.info("Initializing TradingNode...")
    trading_node = TradingNode(config=node_config)

    # Register adapter factories
    logger.info("Registering Polygon data client factory...")
    trading_node.add_data_client_factory("POLYGON", PolygonLiveDataClientFactory)

    logger.info("Registering Alpaca execution client factory...")
    trading_node.add_exec_client_factory("ALPACA", AlpacaLiveExecClientFactory)

    # Build the trading node
    logger.info("Building TradingNode...")
    trading_node.build()
    logger.info("TradingNode built successfully")

    logger.info("")
    logger.info("=" * 70)
    logger.info("UNIFIED NEWS TRADING SYSTEM OPERATIONAL")
    logger.info("=" * 70)
    logger.info("Press Ctrl+C to stop")
    logger.info("")

    return trading_node


if __name__ == "__main__":
    print("=" * 70)
    print("UNIFIED NEWS TRADING SYSTEM - V16 FEATURES")
    print("=" * 70)
    print("NautilusTrader with Polygon Proxy + Alpaca")
    print("   Data: Polygon WebSocket proxy (ws://localhost:8765)")
    print("   Execution: Alpaca via trade updates proxy (ws://localhost:8099)")
    print()
    print("V16 Filters: Price <$5, Session (Extended+Closing), Momentum, MarketCap <$50M")
    print("Strategies: Volume(5%) + Trend + Volume(10%)")
    print()

    node = None
    try:
        node = main()
        if node:
            node.run()
        else:
            print("Failed to initialize trading node")
    except KeyboardInterrupt:
        print("\nUnified trading system interrupted")
    except Exception as e:
        print(f"\nSystem error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if node:
            node.dispose()
            print("System disposed")
