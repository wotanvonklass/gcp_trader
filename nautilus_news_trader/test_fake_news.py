#!/usr/bin/env python3
"""
Test script to publish fake news for high-volume stocks.

Fetches top N stocks by volume from Polygon's market snapshot
and publishes test news messages to Pub/Sub.

Usage:
    python test_fake_news.py           # Top 3 stocks
    python test_fake_news.py -n 5      # Top 5 stocks
    python test_fake_news.py --dry-run # Show what would be published
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment
load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gnw-trader")
PUBSUB_TOPIC = "benzinga-news"


def get_market_snapshot():
    """Fetch full market snapshot from Polygon."""
    url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {"apiKey": POLYGON_API_KEY}

    print("Fetching market snapshot from Polygon...")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    if data.get("status") != "OK":
        raise Exception(f"Polygon API error: {data}")

    return data.get("tickers", [])


def get_top_volume_stocks(tickers, n=3, max_price=5.0):
    """
    Get top N stocks by volume, filtered by price.

    Args:
        tickers: List of ticker data from Polygon
        n: Number of stocks to return
        max_price: Maximum price filter (for penny stocks)
    """
    # Filter and sort
    filtered = []
    for t in tickers:
        ticker = t.get("ticker", "")

        # Use day data, fall back to prevDay for pre-market
        day = t.get("day", {})
        prev_day = t.get("prevDay", {})

        # Try day first, then prevDay
        volume = day.get("v", 0) or prev_day.get("v", 0)
        close = day.get("c", 0) or prev_day.get("c", 0)

        # Skip if no data
        if not volume or not close:
            continue

        # Skip if price too high (we want penny stocks for testing)
        if close > max_price:
            continue

        # Skip common ETFs and problem tickers
        skip_patterns = ["ETF", "PROSHARES", "DIREXION", "WARRANT", "-W"]
        if any(p in ticker.upper() for p in skip_patterns):
            continue

        # Skip tickers with special characters (warrants, units, etc.)
        if any(c in ticker for c in ["+", "^", "=", "."]):
            continue

        filtered.append({
            "ticker": ticker,
            "volume": volume,
            "price": close,
            "change_pct": t.get("todaysChangePerc", 0) or 0,
        })

    # Sort by volume descending
    filtered.sort(key=lambda x: x["volume"], reverse=True)

    return filtered[:n]


def publish_test_news(stocks, dry_run=False):
    """Publish test news messages to Pub/Sub using gcloud CLI."""
    import subprocess

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    results = []
    for stock in stocks:
        ticker = stock["ticker"]
        volume = stock["volume"]
        price = stock["price"]
        change = stock["change_pct"]

        # Create test news message
        news = {
            "headline": f"[TEST] Breaking: {ticker} Shows Unusual Activity - Volume Surge Detected",
            "tickers": [ticker],
            "source": "TestScript",
            "url": f"https://test.example.com/news/{ticker.lower()}",
            "tags": ["News", "Test"],
            "time": now,
            "capturedAt": now,
        }

        if dry_run:
            print(f"\n[DRY RUN] Would publish for {ticker}:")
            print(f"  Price: ${price:.2f}, Volume: {volume:,.0f}, Change: {change:+.2f}%")
            print(f"  Headline: {news['headline']}")
        else:
            # Publish to Pub/Sub using gcloud CLI
            message_json = json.dumps(news)
            cmd = [
                "gcloud", "pubsub", "topics", "publish", PUBSUB_TOPIC,
                f"--project={GCP_PROJECT_ID}",
                f"--message={message_json}"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # Extract message ID from output
                msg_id = result.stdout.strip().split(":")[-1].strip() if result.stdout else "unknown"
                print(f"✅ Published for {ticker} (msg_id: {msg_id})")
                print(f"   Price: ${price:.2f}, Volume: {volume:,.0f}, Change: {change:+.2f}%")
            else:
                print(f"❌ Failed to publish for {ticker}: {result.stderr}")

        results.append({
            "ticker": ticker,
            "price": price,
            "volume": volume,
            "news": news,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Publish test news for high-volume stocks")
    parser.add_argument("-n", "--count", type=int, default=3, help="Number of stocks (default: 3)")
    parser.add_argument("--max-price", type=float, default=5.0, help="Max stock price (default: $5.00)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be published without publishing")
    parser.add_argument("--ticker", type=str, help="Specific ticker to test (bypasses volume lookup)")
    args = parser.parse_args()

    if not POLYGON_API_KEY:
        print("ERROR: POLYGON_API_KEY not set in environment")
        sys.exit(1)

    print("=" * 60)
    print("TEST NEWS PUBLISHER")
    print("=" * 60)
    print(f"Project: {GCP_PROJECT_ID}")
    print(f"Topic: {PUBSUB_TOPIC}")
    print(f"Max Price Filter: ${args.max_price:.2f}")
    print()

    if args.ticker:
        # Use specific ticker
        stocks = [{
            "ticker": args.ticker.upper(),
            "volume": 1000000,
            "price": 1.00,
            "change_pct": 0.0,
        }]
        print(f"Using specified ticker: {args.ticker.upper()}")
    else:
        # Fetch from Polygon
        tickers = get_market_snapshot()
        print(f"Received {len(tickers)} tickers from Polygon")

        stocks = get_top_volume_stocks(tickers, n=args.count, max_price=args.max_price)

        if not stocks:
            print(f"No stocks found under ${args.max_price:.2f}")
            sys.exit(1)

        print(f"\nTop {len(stocks)} stocks by volume (price < ${args.max_price:.2f}):")
        for i, s in enumerate(stocks, 1):
            print(f"  {i}. {s['ticker']}: ${s['price']:.2f}, Vol: {s['volume']:,.0f}, Chg: {s['change_pct']:+.2f}%")

    print()

    if args.dry_run:
        print("DRY RUN MODE - No messages will be published")

    publish_test_news(stocks, dry_run=args.dry_run)

    print()
    print("=" * 60)
    if not args.dry_run:
        print(f"Published {len(stocks)} test news messages!")
        print("Check strategy logs to verify processing:")
        print("  gcloud compute ssh news-trader --zone=us-east4-a -- \\")
        print("    'grep -E \"Processing:|PASSED|spawn\" /opt/news-trader/runner/volume_5pct/logs/stdout.log | tail -20'")
    print("=" * 60)


if __name__ == "__main__":
    main()
