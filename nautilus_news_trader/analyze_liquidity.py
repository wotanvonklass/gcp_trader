#!/usr/bin/env python3
"""Analyze liquidity at order submission times."""

import os
import requests
from datetime import datetime

API_KEY = os.environ.get("POLYGON_API_KEY")

def get_trades(ticker, timestamp_str, window_seconds=30):
    """Get trades around a timestamp"""
    ts = datetime.fromisoformat(timestamp_str.replace("+00:00", ""))

    # Convert to nanoseconds for Polygon
    ts_ns = int(ts.timestamp() * 1e9)
    start_ns = int(ts_ns - (window_seconds * 1e9))
    end_ns = int(ts_ns + (window_seconds * 1e9))

    url = f"https://api.polygon.io/v3/trades/{ticker}"
    params = {
        "timestamp.gte": start_ns,
        "timestamp.lte": end_ns,
        "limit": 100,
        "apiKey": API_KEY
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        return data.get("results", [])
    except Exception as e:
        print(f"  Error fetching trades: {e}")
        return []

# Orders that did not fill
unfilled = [
    ("CVBF", "2025-12-17T21:15:03", 20.93),
    ("HTBK", "2025-12-17T21:15:03", 12.70),
    ("AXIL", "2025-12-18T10:00:05", 8.59),
    ("CAMP", "2025-12-18T12:00:04", 7.88),
    ("GANX", "2025-12-18T12:00:05", 4.20),
]

# Orders that filled
filled = [
    ("KMX", "2025-12-17T21:10:02", 41.77),
    ("BDRX", "2025-12-18T13:30:05", 4.49),
]

print("=" * 80)
print("UNFILLED ORDERS - Liquidity Analysis (30 sec window)")
print("=" * 80)

for ticker, ts, limit_px in unfilled:
    trades = get_trades(ticker, ts)
    print(f"\n{ticker} @ {ts} UTC | Our limit: ${limit_px:.2f}")

    if not trades:
        print("  NO TRADES in 30-second window - no liquidity!")
    else:
        prices = [t["price"] for t in trades]
        sizes = [t["size"] for t in trades]
        print(f"  Trades: {len(trades)} | Volume: {sum(sizes):,} shares")
        print(f"  Price range: ${min(prices):.2f} - ${max(prices):.2f}")
        print(f"  Avg price: ${sum(prices)/len(prices):.2f}")

        # Check if our limit was reachable
        if limit_px >= min(prices):
            print(f"  -> Our limit ${limit_px:.2f} WAS within range - should have filled!")
        else:
            print(f"  -> Our limit ${limit_px:.2f} was BELOW market (min: ${min(prices):.2f})")

print("\n" + "=" * 80)
print("FILLED ORDERS - Comparison")
print("=" * 80)

for ticker, ts, limit_px in filled:
    trades = get_trades(ticker, ts)
    print(f"\n{ticker} @ {ts} UTC | Our limit: ${limit_px:.2f}")

    if trades:
        prices = [t["price"] for t in trades]
        sizes = [t["size"] for t in trades]
        print(f"  Trades: {len(trades)} | Volume: {sum(sizes):,} shares")
        print(f"  Price range: ${min(prices):.2f} - ${max(prices):.2f}")
    else:
        print("  NO TRADES found (but order filled via Alpaca)")
