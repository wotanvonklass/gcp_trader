#!/usr/bin/env python3
"""
Send test news to Pub/Sub for E2E testing of NewsVolumeStrategy.

Usage:
    # Happy path test with AAPL
    python send_test_news.py --ticker AAPL

    # Test with custom headline
    python send_test_news.py --ticker TSLA --headline "Tesla announces new product"

    # Test stale news (rejected)
    python send_test_news.py --ticker AAPL --age 15

    # Test fresh news (rejected)
    python send_test_news.py --ticker AAPL --age 1

    # Test no tickers
    python send_test_news.py --no-ticker

    # Test multiple tickers
    python send_test_news.py --tickers AAPL,MSFT
"""

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from google.cloud import pubsub_v1

PROJECT_ID = "gnw-trader"
TOPIC_ID = "benzinga-news"


def send_test_news(
    tickers: list[str],
    headline: str = None,
    age_seconds: int = 5,
    test_name: str = "E2E Test"
):
    """Send test news to Pub/Sub."""

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

    # Generate unique ID
    test_id = f"test_{int(time.time() * 1000)}"

    # Calculate timestamps
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(seconds=age_seconds)

    # Build headline
    if headline is None:
        if tickers:
            headline = f"[TEST] {test_name} for {', '.join(tickers)}"
        else:
            headline = f"[TEST] {test_name} - No tickers"
    elif not headline.startswith("[TEST]"):
        headline = f"[TEST] {headline}"

    # Build news data
    news_data = {
        "id": test_id,
        "storyId": test_id,
        "nodeId": 99999999,
        "headline": headline,
        "teaserText": f"Test news for E2E testing - {test_name}",
        "body": f"This is a test news article for automated testing. Test ID: {test_id}",
        "author": "Test Bot",
        "createdAt": created_at.isoformat(),
        "updatedAt": created_at.isoformat(),
        "tickers": tickers,
        "quotes": [],
        "source": "Test",
        "sourceGroup": "test",
        "sourceFull": "Test Bot",
        "channels": ["test"],
        "tags": ["test"],
        "sentiment": "neutral",
        "isBzPost": False,
        "isBzProPost": False,
        "partnerURL": "",
        "eventId": None,
        "capturedAt": now.isoformat()
    }

    # Publish
    message_data = json.dumps(news_data).encode("utf-8")
    future = publisher.publish(topic_path, message_data)
    message_id = future.result()

    print(f"\n{'='*60}")
    print(f"TEST NEWS PUBLISHED")
    print(f"{'='*60}")
    print(f"Test Name:    {test_name}")
    print(f"Message ID:   {message_id}")
    print(f"Test ID:      {test_id}")
    print(f"Tickers:      {tickers if tickers else 'None'}")
    print(f"Headline:     {headline}")
    print(f"Age:          {age_seconds}s (created at {created_at.strftime('%H:%M:%S')} UTC)")
    print(f"Published at: {now.strftime('%H:%M:%S')} UTC")
    print(f"{'='*60}")
    print(f"\nExpected behavior:")

    if not tickers:
        print("  - News should be SKIPPED (no tickers)")
    elif age_seconds < 2:
        print("  - News should be SKIPPED (too fresh)")
    elif age_seconds > 10:
        print("  - News should be SKIPPED (too old)")
    else:
        print("  - Strategy should SPAWN for each ticker")
        print("  - BUY order should be placed (mock volume data)")
        print("  - Exit timer scheduled (2 min)")
        print("  - SELL order after timeout")

    print(f"\nMonitor with:")
    print(f'  gcloud logging read \'jsonPayload.message=~"TRACE:.*{test_id[:20]}"\' --project={PROJECT_ID} --limit=30')

    return test_id, message_id


def main():
    parser = argparse.ArgumentParser(description="Send test news to Pub/Sub")
    parser.add_argument("--ticker", type=str, help="Single ticker symbol (e.g., AAPL)")
    parser.add_argument("--tickers", type=str, help="Comma-separated tickers (e.g., AAPL,MSFT)")
    parser.add_argument("--no-ticker", action="store_true", help="Send news without tickers")
    parser.add_argument("--headline", type=str, help="Custom headline")
    parser.add_argument("--age", type=int, default=5, help="News age in seconds (default: 5)")
    parser.add_argument("--test-name", type=str, default="E2E Test", help="Test name for logging")

    args = parser.parse_args()

    # Determine tickers
    if args.no_ticker:
        tickers = []
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    elif args.ticker:
        tickers = [args.ticker.upper()]
    else:
        # Default to AAPL
        tickers = ["AAPL"]

    send_test_news(
        tickers=tickers,
        headline=args.headline,
        age_seconds=args.age,
        test_name=args.test_name
    )


if __name__ == "__main__":
    main()
