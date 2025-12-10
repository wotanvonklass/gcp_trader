#!/usr/bin/env python3
"""
Polygon Proxy Health Monitor
Checks that TSLA trades are flowing when markets are open
"""
import asyncio
import websockets
import json
import time
import requests
import sys
import logging
from datetime import datetime, timezone
from typing import Optional

# Configuration
POLYGON_API_KEY = "MdHapjkP8r7K6y30JH_WCxwVW19eMh3Y"
FILTERED_PROXY_URL = "ws://localhost:8765"
MS_AGGREGATOR_URL = "ws://localhost:8768"
MARKET_STATUS_URL = "https://api.polygon.io/v1/marketstatus/now"
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
TRADE_TIMEOUT_SECONDS = 300   # Alert if no trades in 5 minutes

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/polygon-monitor.log')
    ]
)
logger = logging.getLogger(__name__)


def check_market_status() -> dict:
    """Check if markets are currently open"""
    try:
        response = requests.get(
            MARKET_STATUS_URL,
            params={"apiKey": POLYGON_API_KEY},
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to get market status: {e}")
        return {}


def is_market_open(status: dict) -> bool:
    """Determine if market is open from status response"""
    if not status:
        return False

    # Check if any market is open (including extended hours)
    markets = status.get("market", "closed")
    exchanges = status.get("exchanges", {})

    # Market is open if nasdaq or nyse is open OR extended-hours
    nasdaq_status = exchanges.get("nasdaq", "closed")
    nyse_status = exchanges.get("nyse", "closed")

    nasdaq_open = nasdaq_status in ["open", "extended-hours"]
    nyse_open = nyse_status in ["open", "extended-hours"]

    return nasdaq_open or nyse_open


async def check_tsla_trades(timeout: int = 60) -> tuple[bool, Optional[str]]:
    """
    Check if TSLA trades are flowing through filtered-proxy
    Returns: (success, error_message)
    """
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(FILTERED_PROXY_URL) as ws:
                # Auth
                await ws.send(json.dumps({
                    "action": "auth",
                    "params": POLYGON_API_KEY
                }))
                await asyncio.sleep(0.5)

                # Subscribe to TSLA trades
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "params": "T.TSLA"
                }))

                # Wait for first trade
                async for message in ws:
                    if not message:
                        continue

                    try:
                        data = json.loads(message)
                        if isinstance(data, list):
                            for msg in data:
                                if msg.get("ev") == "T" and msg.get("sym") == "TSLA":
                                    price = msg.get("p", 0)
                                    size = msg.get("s", 0)
                                    logger.info(f"✓ TSLA trade received: ${price:.2f} x {size}")
                                    return (True, None)
                    except json.JSONDecodeError:
                        continue

    except asyncio.TimeoutError:
        error = f"Timeout: No TSLA trades received in {timeout} seconds"
        logger.error(f"✗ {error}")
        return (False, error)
    except Exception as e:
        error = f"Failed to check TSLA trades: {e}"
        logger.error(f"✗ {error}")
        return (False, error)

    return (False, "No TSLA trades found")


async def check_ms_aggregator(timeout: int = 60) -> tuple[bool, Optional[str]]:
    """
    Check if ms-aggregator is running and processing data
    Returns: (success, error_message)
    """
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(MS_AGGREGATOR_URL) as ws:
                # Auth
                await ws.send(json.dumps({
                    "action": "auth",
                    "params": POLYGON_API_KEY
                }))
                await asyncio.sleep(0.5)

                # Subscribe to 100ms TSLA bars
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "params": "100Ms.TSLA"
                }))

                # Wait for first bar
                async for message in ws:
                    if not message:
                        continue

                    try:
                        data = json.loads(message)
                        if isinstance(data, list) and len(data) > 0:
                            bar = data[0]
                            if bar.get("ev") == "MB":
                                logger.info(f"✓ ms-aggregator bar received: TSLA 100ms bar")
                                return (True, None)
                    except json.JSONDecodeError:
                        continue

    except asyncio.TimeoutError:
        error = f"Timeout: No bars from ms-aggregator in {timeout} seconds"
        logger.error(f"✗ {error}")
        return (False, error)
    except Exception as e:
        error = f"Failed to check ms-aggregator: {e}"
        logger.error(f"✗ {error}")
        return (False, error)

    return (False, "No bars received from ms-aggregator")


def send_alert(message: str):
    """
    Send alert (can be extended to send emails, SMS, Slack, etc.)
    For now, just logs and writes to alert file
    """
    logger.critical(f"🚨 ALERT: {message}")

    # Write to alert file for monitoring systems to pick up
    with open('/var/log/polygon-alerts.log', 'a') as f:
        timestamp = datetime.now(timezone.utc).isoformat()
        f.write(f"{timestamp} ALERT: {message}\n")

    # Could add:
    # - GCP Cloud Logging
    # - Email via SendGrid
    # - Slack webhook
    # - PagerDuty
    # - SMS via Twilio


async def health_check():
    """Run a single health check"""
    logger.info("=" * 60)
    logger.info("Starting health check")

    # Check market status
    logger.info("Checking market status...")
    market_status = check_market_status()
    market_open = is_market_open(market_status)

    if market_open:
        logger.info("✓ Markets are OPEN - checking for TSLA trades")

        # Check filtered-proxy (TSLA trades)
        logger.info("Checking filtered-proxy for TSLA trades...")
        trades_ok, trade_error = await check_tsla_trades(timeout=60)

        if not trades_ok:
            send_alert(f"No TSLA trades detected during market hours: {trade_error}")

        # Check ms-aggregator
        logger.info("Checking ms-aggregator for bars...")
        aggregator_ok, agg_error = await check_ms_aggregator(timeout=60)

        if not aggregator_ok:
            send_alert(f"ms-aggregator not producing bars: {agg_error}")

        # Summary
        if trades_ok and aggregator_ok:
            logger.info("✅ All systems healthy")
        else:
            logger.error("❌ System health check FAILED")

    else:
        logger.info("ℹ️  Markets are CLOSED - skipping trade checks")
        logger.info(f"   Market status: {market_status.get('market', 'unknown')}")


async def monitor_loop():
    """Main monitoring loop"""
    logger.info("Polygon Proxy Monitor started")
    logger.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    logger.info(f"Trade timeout: {TRADE_TIMEOUT_SECONDS} seconds")

    while True:
        try:
            await health_check()
        except Exception as e:
            logger.error(f"Health check failed with exception: {e}")
            send_alert(f"Health check crashed: {e}")

        # Wait for next check
        logger.info(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(monitor_loop())
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Monitor crashed: {e}")
        sys.exit(1)
