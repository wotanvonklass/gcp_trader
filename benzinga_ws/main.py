#!/usr/bin/env python3
"""Benzinga WebSocket News Client with GCP Cloud Logging."""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone

import websockets
from google.cloud import logging as cloud_logging

# Configuration from environment
BENZINGA_API_KEY = os.environ.get("BENZINGA_API_KEY")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "gnw-trader")
WS_URL = "wss://api.benzinga.com/api/v1/news/stream"
RECONNECT_DELAY = 5  # seconds

# Filter: only process news matching these channels (empty = all)
# Common channels: "Press Releases", "News", "Markets", "Trading Ideas", etc.
CHANNEL_FILTER = os.environ.get("CHANNEL_FILTER", "Press Releases")
CHANNEL_FILTER_SET = set(c.strip() for c in CHANNEL_FILTER.split(",") if c.strip()) if CHANNEL_FILTER else set()

# Initialize GCP Cloud Logging
logging_client = cloud_logging.Client(project=GCP_PROJECT_ID)
logger = logging_client.logger("benzinga-news-ws")


def log_news(news_data: dict, action: str, event_id: int, timestamp: str) -> None:
    """Log news item to GCP Cloud Logging with structured data."""
    content = news_data.get("content", {})

    # Extract securities/tickers
    securities = content.get("securities", [])
    tickers = [s.get("symbol", "") for s in securities if s.get("symbol")]

    # Build structured log entry
    log_entry = {
        "event_id": event_id,
        "action": action,
        "event_timestamp": timestamp,
        "article_id": content.get("id"),
        "revision_id": content.get("revision_id"),
        "type": content.get("type"),
        "title": content.get("title"),
        "teaser": content.get("teaser"),
        "url": content.get("url"),
        "created_at": content.get("created_at"),
        "updated_at": content.get("updated_at"),
        "channels": content.get("channels", []),
        "tickers": tickers,
        "securities": securities,
        "authors": content.get("authors"),
        "body_length": len(content.get("body", "")),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    # Log to GCP with severity based on action
    severity = "INFO"
    if action == "Removed":
        severity = "WARNING"

    logger.log_struct(log_entry, severity=severity)

    # Also print to stdout for container logs
    ticker_str = ",".join(tickers) if tickers else "N/A"
    print(f"[{timestamp}] {action}: {content.get('title', 'N/A')[:80]} | Tickers: {ticker_str}")


async def connect_and_stream():
    """Connect to Benzinga WebSocket and stream news."""
    if not BENZINGA_API_KEY:
        print("ERROR: BENZINGA_API_KEY environment variable not set")
        sys.exit(1)

    url = f"{WS_URL}?token={BENZINGA_API_KEY}"

    while True:
        try:
            print(f"Connecting to Benzinga WebSocket...")

            async with websockets.connect(
                url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                print("Connected to Benzinga WebSocket")
                logger.log_text("Connected to Benzinga WebSocket", severity="INFO")

                async for message in ws:
                    try:
                        data = json.loads(message)

                        api_version = data.get("api_version")
                        kind = data.get("kind")
                        stream_data = data.get("data", {})

                        event_id = stream_data.get("id")
                        action = stream_data.get("action")
                        timestamp = stream_data.get("timestamp")
                        content = stream_data.get("content", {})
                        channels = set(content.get("channels", []))

                        # Filter by channel if configured
                        if CHANNEL_FILTER_SET and not channels.intersection(CHANNEL_FILTER_SET):
                            continue  # Skip non-matching news

                        # Log the news item
                        log_news(stream_data, action, event_id, timestamp)

                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
                        logger.log_text(f"JSON decode error: {e}", severity="ERROR")
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        logger.log_text(f"Error processing message: {e}", severity="ERROR")

        except websockets.ConnectionClosed as e:
            print(f"Connection closed: {e}. Reconnecting in {RECONNECT_DELAY}s...")
            logger.log_text(f"Connection closed: {e}", severity="WARNING")
            await asyncio.sleep(RECONNECT_DELAY)

        except Exception as e:
            print(f"Connection error: {e}. Reconnecting in {RECONNECT_DELAY}s...")
            logger.log_text(f"Connection error: {e}", severity="ERROR")
            await asyncio.sleep(RECONNECT_DELAY)


def main():
    """Main entry point."""
    print("Benzinga WebSocket News Client")
    print(f"GCP Project: {GCP_PROJECT_ID}")
    print(f"Log name: benzinga-news-ws")
    print(f"Channel filter: {CHANNEL_FILTER or 'None (all channels)'}")

    # Handle graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown_handler(sig, frame):
        print("\nShutting down...")
        logger.log_text("Shutting down", severity="INFO")
        loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        loop.run_until_complete(connect_and_stream())
    except KeyboardInterrupt:
        print("\nShutdown requested")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
