#!/usr/bin/env python3
"""
News Trading System with Nautilus and Pub/Sub.

This script starts a NautilusTrader system that subscribes to Pub/Sub news
and spawns trading strategies for each qualifying event.
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
    logger.info(f"📦 Using private Nautilus installation from: {custom_nautilus_path}")

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

    # Create config-specific directory
    config_dir = RUNNER_DIR / "default"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create paths for PID file
    pid_file = config_dir / "process.pid"

    return pid_file, "default"


def acquire_single_instance_lock():
    """Ensure only one instance runs using PID file lock."""
    global lock_file_handle

    # Setup config directory and get PID file path
    PID_FILE, config_name = setup_config_directory()

    try:
        # Open or create PID file
        lock_file_handle = open(PID_FILE, 'w')

        # Try to acquire exclusive lock (non-blocking)
        fcntl.lockf(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Write our PID
        pid = os.getpid()
        lock_file_handle.seek(0)
        lock_file_handle.write(f"{pid}\n")
        lock_file_handle.flush()
        os.fsync(lock_file_handle.fileno())

        # Clean up on exit
        def cleanup():
            try:
                if lock_file_handle:
                    lock_file_handle.close()
                if PID_FILE.exists():
                    PID_FILE.unlink()
                    logger.info(f"🔓 Released lock")
            except Exception as e:
                logger.warning(f"⚠️ Error during cleanup: {e}")

        def signal_handler(signum, frame):
            logger.info(f"\n📍 Received signal {signum}, shutting down gracefully...")
            cleanup()
            sys.exit(0)

        # Register cleanup handlers
        atexit.register(cleanup)
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        logger.info(f"🔒 Acquired lock (PID: {pid})")
        logger.info(f"📁 Config directory: {config_dir}")
        return config_dir

    except IOError:
        # Lock failed - check if we can clean up stale locks
        if PID_FILE.exists():
            try:
                with open(PID_FILE, 'r') as f:
                    existing_pid = f.read().strip()

                if existing_pid:
                    # Check if process is actually running
                    try:
                        os.kill(int(existing_pid), 0)
                        # Process is running, refuse to start
                        logger.error(f"❌ Another instance is already running (PID: {existing_pid})")
                        logger.error(f"   To stop it: kill {existing_pid}")
                        sys.exit(1)
                    except (OSError, ValueError):
                        # Process is dead, clean up the stale PID file
                        logger.warning(f"⚠️ Found stale PID file for dead process {existing_pid}, cleaning up...")
                        PID_FILE.unlink()
                        # Retry lock acquisition
                        return acquire_single_instance_lock()
                else:
                    # PID file is empty
                    logger.warning(f"⚠️ Found empty PID file, removing it...")
                    PID_FILE.unlink()
                    return acquire_single_instance_lock()

            except Exception as e:
                logger.error(f"❌ Error checking PID file: {e}")
                logger.error(f"   Try removing {PID_FILE} manually")
                sys.exit(1)
        else:
            logger.error(f"❌ Cannot create lock file {PID_FILE}")
            sys.exit(1)


def main():
    """Main entry point for news trading system."""
    logger.info("🚀 NEWS TRADING SYSTEM WITH NAUTILUS & PUB/SUB")
    logger.info("=" * 60)

    # Acquire single instance lock
    config_dir = acquire_single_instance_lock()

    # Get Alpaca credentials from environment
    alpaca_api_key = os.getenv("ALPACA_API_KEY")
    alpaca_secret_key = os.getenv("ALPACA_SECRET_KEY")

    if alpaca_api_key and alpaca_secret_key:
        logger.info(f"📊 Alpaca credentials found: {alpaca_api_key[:10]}...")

        # Validate Alpaca authentication on startup
        logger.info("🏥 Running Alpaca health check...")
        from utils.alpaca_health import require_healthy_alpaca
        try:
            account_info = require_healthy_alpaca(alpaca_api_key, alpaca_secret_key)
            logger.info(f"✅ Alpaca account validated - Ready to trade")
        except RuntimeError as e:
            logger.error(f"❌ Alpaca health check failed: {e}")
            logger.error("   Cannot start trading system with invalid Alpaca credentials")
            sys.exit(1)
    else:
        logger.error("❌ ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        sys.exit(1)

    # Get Polygon API key
    polygon_api_key = os.getenv("POLYGON_API_KEY")
    if not polygon_api_key:
        logger.error("❌ POLYGON_API_KEY must be set")
        sys.exit(1)

    # Get Pub/Sub configuration
    project_id = os.getenv("GCP_PROJECT_ID")
    subscription_id = os.getenv("PUBSUB_SUBSCRIPTION")
    if not project_id or not subscription_id:
        logger.error("❌ GCP_PROJECT_ID and PUBSUB_SUBSCRIPTION must be set")
        sys.exit(1)

    logger.info(f"📡 Pub/Sub: {project_id}/{subscription_id}")
    logger.info(f"📊 Data: Polygon WebSocket proxy (ws://localhost:8765)")
    logger.info(f"⚡ Execution: Alpaca via trade updates proxy (ws://localhost:8099)")
    logger.info("")

    # Get trade updates proxy URL (defaults to localhost)
    trade_updates_ws_url = os.getenv("TRADE_UPDATES_WS_URL", "ws://localhost:8099/trade-updates-paper")

    # Get Polygon proxy URL (defaults to localhost)
    polygon_proxy_url = os.getenv("POLYGON_PROXY_URL", "ws://localhost:8765")

    logger.info(f"🔌 Trade updates proxy: {trade_updates_ws_url}")
    logger.info(f"🔌 Polygon proxy: {polygon_proxy_url}")
    logger.info("")

    # Build strategies JSON from environment or use default
    # Format: '[{"name":"vol5","volume_percentage":0.05,"exit_delay_minutes":7},...]'
    strategies_json = os.getenv("STRATEGIES_JSON", "")
    if not strategies_json:
        # Default: single strategy using legacy env vars for backward compatibility
        strategies_json = '[{"name":"vol","volume_percentage":' + os.getenv("VOLUME_PERCENTAGE", "0.05") + ',"exit_delay_minutes":' + os.getenv("EXIT_DELAY_MINUTES", "7") + ',"min_position_size":' + os.getenv("MIN_POSITION_SIZE", "100") + ',"max_position_size":' + os.getenv("MAX_POSITION_SIZE", "20000") + ',"limit_order_offset_pct":' + os.getenv("LIMIT_ORDER_OFFSET_PCT", "0.01") + '}]'

    # Log strategies configuration
    import json
    try:
        strategies_list = json.loads(strategies_json)
        logger.info(f"📊 Strategies configured: {len(strategies_list)}")
        for s in strategies_list:
            logger.info(f"   • {s.get('name', 'vol')}: {s.get('volume_percentage', 0.05)*100}% vol, {s.get('exit_delay_minutes', 7)}min exit")
    except json.JSONDecodeError:
        logger.warning(f"⚠️ Invalid STRATEGIES_JSON, using default single strategy")

    # Create controller configuration
    controller_config = ImportableControllerConfig(
        controller_path="actors.pubsub_news_controller:PubSubNewsController",
        config_path="actors.pubsub_news_controller:PubSubNewsControllerConfig",
        config={
            # Pub/Sub configuration
            "project_id": project_id,
            "subscription_id": subscription_id,

            # News filtering
            "min_news_age_seconds": int(os.getenv("MIN_NEWS_AGE_SECONDS", 2)),
            "max_news_age_seconds": int(os.getenv("MAX_NEWS_AGE_SECONDS", 30)),

            # Default trading parameters (used when strategies_json is empty)
            "volume_percentage": float(os.getenv("VOLUME_PERCENTAGE", 0.05)),
            "min_position_size": float(os.getenv("MIN_POSITION_SIZE", 100)),
            "max_position_size": float(os.getenv("MAX_POSITION_SIZE", 20000)),
            "limit_order_offset_pct": float(os.getenv("LIMIT_ORDER_OFFSET_PCT", 0.01)),
            "exit_delay_minutes": int(os.getenv("EXIT_DELAY_MINUTES", 7)),
            "extended_hours": os.getenv("EXTENDED_HOURS", "true").lower() == "true",

            # Multi-strategy configuration (JSON string)
            "strategies_json": strategies_json,

            # Polygon API key (for REST API calls)
            "polygon_api_key": polygon_api_key,

            # Alpaca credentials (for health check)
            "alpaca_api_key": alpaca_api_key,
            "alpaca_secret_key": alpaca_secret_key,
        },
    )

    logger.info("📋 Controller configured")

    # Create TradingNode configuration with Polygon data and Alpaca execution
    node_config = TradingNodeConfig(
        trader_id=TraderId("NEWS-TRADER"),

        # Controller configuration
        controller=controller_config,

        # Data client: Polygon WebSocket proxy
        data_clients={
            "POLYGON": PolygonDataClientConfig(
                api_key=polygon_api_key,
                base_url_ws=polygon_proxy_url,  # Use local polygon proxy
                subscribe_trades=True,
                subscribe_quotes=True,
                subscribe_bars=True,
                subscribe_second_aggregates=True,
                include_extended_hours=os.getenv("EXTENDED_HOURS", "true").lower() == "true",
            ),
        },

        # Execution client: Alpaca via trade updates proxy
        exec_clients={
            "ALPACA": AlpacaExecClientConfig(
                api_key=alpaca_api_key,
                secret_key=alpaca_secret_key,
                paper_trading=True,  # Paper trading for safety
                validate_orders=True,
                trade_updates_ws_url=trade_updates_ws_url,  # Use trade updates proxy
                trade_updates_auth_key="nautilus",  # Default proxy auth
                trade_updates_auth_secret="nautilus",  # Default proxy auth
            ),
        },

        # Infrastructure
        cache=CacheConfig(),
        message_bus=MessageBusConfig(),

        # Logging
        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="INFO",
            log_directory=str(config_dir / "logs") if config_dir else "/opt/news-trader/logs",
            log_file_name=f"trader_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            log_file_format=None,
            bypass_logging=False,
        ),
    )

    # Initialize trading node
    logger.info("🔧 Initializing TradingNode...")
    trading_node = TradingNode(config=node_config)

    # Register adapter factories
    logger.info("📦 Registering Polygon data client factory...")
    trading_node.add_data_client_factory("POLYGON", PolygonLiveDataClientFactory)

    logger.info("📦 Registering Alpaca execution client factory...")
    trading_node.add_exec_client_factory("ALPACA", AlpacaLiveExecClientFactory)

    # Build the trading node
    logger.info("🔧 Building TradingNode...")
    trading_node.build()
    logger.info("✅ TradingNode built successfully")

    logger.info("✅ News trading system operational!")
    logger.info("📰 PubSubNewsController will spawn strategies from Pub/Sub news...")
    logger.info("⏹️ Press Ctrl+C to stop")
    logger.info("")

    return trading_node


if __name__ == "__main__":
    """
    News Trading System with Nautilus & Pub/Sub
    """

    print("News Trading System with Nautilus & Pub/Sub")
    print("=" * 60)
    print("🎯 NautilusTrader with Polygon Proxy + Alpaca")
    print("   Data: Polygon WebSocket proxy (ws://localhost:8765)")
    print("   Execution: Alpaca via trade updates proxy (ws://localhost:8099)")
    print()

    node = None
    try:
        # Get the trading node from main()
        node = main()
        # Run it
        if node:
            node.run()
        else:
            print("💥 Failed to initialize trading node")
    except KeyboardInterrupt:
        print("\n👋 News trading system interrupted")
    except Exception as e:
        print(f"\n💥 System error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Dispose properly
        if node:
            node.dispose()
            print("🔚 System disposed")
