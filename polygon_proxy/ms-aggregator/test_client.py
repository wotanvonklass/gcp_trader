#!/usr/bin/env python3
"""
Test client for ms-aggregator proxy
Subscribes to millisecond bars and displays them
"""

import asyncio
import websockets
import json
from datetime import datetime
import argparse


async def test_ms_aggregator(subscriptions="100Ms.AAPL,250Ms.AAPL"):
    url = "ws://localhost:8768"
    print(f"[{datetime.now()}] Connecting to {url}...")

    async with websockets.connect(url) as ws:
        # 1. Authenticate
        auth_msg = json.dumps({
            "action": "auth",
            "params": "test_api_key"
        })
        await ws.send(auth_msg)
        print(f"[{datetime.now()}] Sent authentication")

        # 2. Subscribe to millisecond bars
        subscribe_msg = json.dumps({
            "action": "subscribe",
            "params": subscriptions
        })
        await ws.send(subscribe_msg)
        print(f"[{datetime.now()}] Subscribed to: {subscriptions}")
        print(f"[{datetime.now()}] Waiting for millisecond bars...")
        print("-" * 80)

        # 3. Receive and display bars
        message_count = 0
        try:
            async with asyncio.timeout(60):  # Run for 60 seconds
                async for message in ws:
                    data = json.loads(message)

                    if isinstance(data, list):
                        for item in data:
                            if item.get("ev") == "MB":
                                message_count += 1
                                symbol = item["sym"]
                                interval = item["interval"]
                                open_price = item["o"]
                                high = item["h"]
                                low = item["l"]
                                close = item["c"]
                                volume = item["v"]
                                num_trades = item["n"]
                                start_ts = item["s"]
                                end_ts = item["e"]

                                print(f"[{datetime.now()}] {symbol} {interval}ms bar:")
                                print(f"  OHLC: {open_price:.2f} / {high:.2f} / {low:.2f} / {close:.2f}")
                                print(f"  Volume: {volume} ({num_trades} trades)")
                                print(f"  Time: {start_ts} - {end_ts}")
                                print("-" * 80)
                            elif item.get("ev") == "status":
                                print(f"[{datetime.now()}] Status: {item}")
                    else:
                        print(f"[{datetime.now()}] Received: {data}")

        except asyncio.TimeoutError:
            print(f"\n[{datetime.now()}] Test complete after 60 seconds")
            print(f"Total bars received: {message_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test ms-aggregator proxy")
    parser.add_argument(
        "--subscriptions",
        default="100Ms.AAPL,250Ms.AAPL",
        help="Comma-separated subscriptions (e.g., '100Ms.AAPL,500Ms.*')"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("MS-AGGREGATOR TEST CLIENT")
    print("=" * 80)

    asyncio.run(test_ms_aggregator(args.subscriptions))
