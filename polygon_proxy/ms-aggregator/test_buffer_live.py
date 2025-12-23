#!/usr/bin/env python3
"""
Test trade buffer with fake data from the proxy stack.

Run the full stack first:
  Terminal 1: cd firehose-proxy && cargo run
  Terminal 2: cd ms-aggregator && cargo run
  Terminal 3: cd filtered-proxy && ENABLE_FAKE_DATA=true cargo run

Then run this test:
  python test_buffer_live.py
"""

import asyncio
import json
import websockets
from datetime import datetime

PROXY_URL = "ws://localhost:8765"  # Filtered proxy

async def test_buffer():
    print(f"Connecting to {PROXY_URL}...")

    async with websockets.connect(PROXY_URL) as ws:
        # Authenticate
        await ws.send(json.dumps({"action": "auth", "params": "test"}))
        auth_resp = await ws.recv()
        print(f"Auth response: {auth_resp}")

        # Subscribe to FAKETICKER trades and 250ms bars
        sub_msg = {"action": "subscribe", "params": "T.FAKETICKER,250Ms.FAKETICKER"}
        await ws.send(json.dumps(sub_msg))
        sub_resp = await ws.recv()
        print(f"Subscribe response: {sub_resp}")

        # Collect messages for 10 seconds
        print("\nCollecting data for 10 seconds...")
        print("-" * 60)

        trade_count = 0
        bar_count = 0
        start_time = datetime.now()

        try:
            while (datetime.now() - start_time).seconds < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)

                    # Handle array of messages
                    if isinstance(data, list):
                        for item in data:
                            ev = item.get("ev", "")
                            sym = item.get("sym", "")

                            if ev == "T":
                                trade_count += 1
                                ts = item.get("t", 0)
                                price = item.get("p", 0)
                                print(f"  Trade: {sym} @ ${price:.2f} (ts={ts})")
                            elif ev == "MB":
                                bar_count += 1
                                interval = item.get("interval", 0)
                                o = item.get("o", 0)
                                h = item.get("h", 0)
                                l = item.get("l", 0)
                                c = item.get("c", 0)
                                v = item.get("v", 0)
                                n = item.get("n", 0)
                                s = item.get("s", 0)
                                e = item.get("e", 0)
                                print(f"  Bar: {sym} {interval}ms O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} V={v} N={n}")
                    else:
                        print(f"  Other: {data}")

                except asyncio.TimeoutError:
                    pass
        except KeyboardInterrupt:
            pass

        print("-" * 60)
        print(f"\nSummary:")
        print(f"  Trades received: {trade_count}")
        print(f"  Bars received: {bar_count}")

        if bar_count > 0:
            print(f"\n✅ Buffer is working! Received {bar_count} millisecond bars from {trade_count} trades")
        else:
            print(f"\n⚠️  No bars received. Check if ms-aggregator is running and connected.")

if __name__ == "__main__":
    asyncio.run(test_buffer())
