#!/usr/bin/env python3
"""
Volume 10% Strategy Runner.

Independent process for NewsVolumeStrategy at 10% volume.
"""

import sys
import os
import signal
import logging
import fcntl
import atexit
from pathlib import Path
from datetime import datetime

# Add parent paths for imports
script_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(script_dir))

news_trader_path = "/opt/news-trader"
if os.path.exists(news_trader_path) and news_trader_path not in sys.path:
    sys.path.insert(0, news_trader_path)

custom_nautilus_path = "/opt/nautilus_trader_private"
if os.path.exists(custom_nautilus_path) and custom_nautilus_path not in sys.path:
    sys.path.insert(0, custom_nautilus_path)

from utils.json_logging import setup_json_logging
logger = setup_json_logging(logging.getLogger(__name__), level=logging.INFO)
root_logger = logging.getLogger()
setup_json_logging(root_logger, level=logging.INFO)

from nautilus_trader.config import TradingNodeConfig, LoggingConfig, CacheConfig, MessageBusConfig
from nautilus_trader.trading.config import ImportableControllerConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.adapters.alpaca.config import AlpacaExecClientConfig
from nautilus_trader.adapters.alpaca.factories import AlpacaLiveExecClientFactory
from nautilus_trader.adapters.polygon.config import PolygonDataClientConfig
from nautilus_trader.adapters.polygon.factories import PolygonLiveDataClientFactory

# Use local runner dir for development, /opt for production
_opt_runner = Path("/opt/news-trader/runner")
_local_runner = Path(__file__).parent.parent.parent / "runner"
RUNNER_DIR = _opt_runner if _opt_runner.parent.exists() and os.access(_opt_runner.parent, os.W_OK) else _local_runner
STRATEGY_NAME = "volume_10pct"
lock_file_handle = None


def acquire_lock():
    """Ensure only one instance runs."""
    global lock_file_handle

    config_dir = RUNNER_DIR / STRATEGY_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    pid_file = config_dir / "process.pid"

    try:
        lock_file_handle = open(pid_file, 'w')
        fcntl.lockf(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        pid = os.getpid()
        lock_file_handle.write(f"{pid}\n")
        lock_file_handle.flush()
        os.fsync(lock_file_handle.fileno())

        def cleanup():
            try:
                if lock_file_handle:
                    lock_file_handle.close()
                if pid_file.exists():
                    pid_file.unlink()
            except Exception:
                pass

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            cleanup()
            sys.exit(0)

        atexit.register(cleanup)
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        logger.info(f"Acquired lock (PID: {pid})")
        return config_dir

    except IOError:
        if pid_file.exists():
            with open(pid_file, 'r') as f:
                existing_pid = f.read().strip()
            try:
                os.kill(int(existing_pid), 0)
                logger.error(f"Another instance running (PID: {existing_pid})")
                sys.exit(1)
            except (OSError, ValueError):
                pid_file.unlink()
                return acquire_lock()
        sys.exit(1)


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("VOLUME 10% STRATEGY")
    logger.info("=" * 60)

    config_dir = acquire_lock()

    # Get credentials
    alpaca_api_key = os.getenv("ALPACA_API_KEY")
    alpaca_secret_key = os.getenv("ALPACA_SECRET_KEY")
    polygon_api_key = os.getenv("POLYGON_API_KEY")
    project_id = os.getenv("GCP_PROJECT_ID")
    subscription_id = os.getenv("PUBSUB_SUBSCRIPTION")

    if not all([alpaca_api_key, alpaca_secret_key, polygon_api_key, project_id, subscription_id]):
        logger.error("Missing required environment variables")
        sys.exit(1)

    # Validate Alpaca
    from utils.alpaca_health import require_healthy_alpaca
    try:
        require_healthy_alpaca(alpaca_api_key, alpaca_secret_key)
        logger.info("Alpaca validated")
    except RuntimeError as e:
        logger.error(f"Alpaca health check failed: {e}")
        sys.exit(1)

    trade_updates_ws_url = os.getenv("TRADE_UPDATES_WS_URL", "ws://localhost:8099/trade-updates-paper")
    polygon_proxy_url = os.getenv("POLYGON_PROXY_URL", "ws://localhost:8765")

    # Controller config
    controller_config = ImportableControllerConfig(
        controller_path="strategies.volume_10pct.controller:Volume10PctController",
        config_path="strategies.volume_10pct.controller:Volume10PctControllerConfig",
        config={
            "project_id": project_id,
            "subscription_id": "benzinga-news-vol10",  # Dedicated subscription
            "max_news_age_seconds": int(os.getenv("MAX_NEWS_AGE_SECONDS", 10)),
            "max_price": float(os.getenv("MAX_PRICE", 5.00)),
            # Volume strategy: no V16 filters
            "max_market_cap": 1e12,
            "require_positive_momentum": False,
            "session_filter_enabled": False,
            "volume_percentage": float(os.getenv("VOLUME_PERCENTAGE", 0.10)),
            "exit_delay_minutes": int(os.getenv("EXIT_DELAY_MINUTES", 7)),
            "min_position_size": float(os.getenv("MIN_POSITION_SIZE", 100)),
            "max_position_size": float(os.getenv("MAX_POSITION_SIZE", 20000)),
            "limit_order_offset_pct": float(os.getenv("LIMIT_ORDER_OFFSET_PCT", 0.01)),
            "extended_hours": os.getenv("EXTENDED_HOURS", "true").lower() == "true",
            "polygon_api_key": polygon_api_key,
            "alpaca_api_key": alpaca_api_key,
            "alpaca_secret_key": alpaca_secret_key,
        },
    )

    # Node config
    node_config = TradingNodeConfig(
        trader_id=TraderId("VOL10-TRADER"),
        controller=controller_config,
        data_clients={
            "POLYGON": PolygonDataClientConfig(
                api_key=polygon_api_key,
                base_url_ws=polygon_proxy_url,
                subscribe_trades=True,
                subscribe_quotes=True,
                subscribe_bars=True,
                subscribe_second_aggregates=True,
                include_extended_hours=True,
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
            log_directory=str(config_dir / "logs"),
            log_file_name=f"vol10_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            bypass_logging=False,
        ),
    )

    logger.info("Initializing TradingNode...")
    trading_node = TradingNode(config=node_config)
    trading_node.add_data_client_factory("POLYGON", PolygonLiveDataClientFactory)
    trading_node.add_exec_client_factory("ALPACA", AlpacaLiveExecClientFactory)
    trading_node.build()

    logger.info("Volume 10% Strategy OPERATIONAL")
    logger.info("Press Ctrl+C to stop")

    return trading_node


if __name__ == "__main__":
    node = None
    try:
        node = main()
        if node:
            node.run()
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if node:
            node.dispose()
