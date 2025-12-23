#!/usr/bin/env python3
"""
Test trade buffer with fake data.

Run ms-aggregator first:
  ENABLE_FAKE_DATA=true cargo run

Then run this test:
  python test_buffer.py
"""

import asyncio
import json
import websockets

AGGREGATOR_URL = "ws://localhost:8768"

async def test_buffer():
    print(f"Connecting to {AGGREGATOR_URL}...")

    async with websockets.connect(AGGREGATOR_URL) as ws:
        # Authenticate
        await ws.send(json.dumps({"action": "auth", "params": "test"}))
        auth_resp = await ws.recv()
        print(f"Auth: {auth_resp}")

        # Subscribe to 250ms bars for FAKETICKER
        sub_msg = {"action": "subscribe", "params": "250Ms.FAKETICKER"}
        await ws.send(json.dumps(sub_msg))
        sub_resp = await ws.recv()
        print(f"Subscribe: {sub_resp}")

        # Collect bars for 5 seconds
        print("\nWaiting for bars (5 seconds)...")
        print("-" * 60)

        bar_count = 0
        start = asyncio.get_event_loop().time()

        try:
            while (asyncio.get_event_loop().time() - start) < 5:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)

                    if isinstance(data, list):
                        for item in data:
                            if item.get("ev") == "MB":
                                bar_count += 1
                                sym = item.get("sym", "")
                                o = item.get("o", 0)
                                h = item.get("h", 0)
                                l = item.get("l", 0)
                                c = item.get("c", 0)
                                v = item.get("v", 0)
                                n = item.get("n", 0)
                                print(f"  Bar #{bar_count}: {sym} O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} V={v} N={n}")
                    else:
                        print(f"  {data}")

                except asyncio.TimeoutError:
                    pass
        except KeyboardInterrupt:
            pass

        print("-" * 60)
        print(f"\nReceived {bar_count} bars in 5 seconds")

        if bar_count > 0:
            print("✅ Buffer and bar generation working!")
        else:
            print("⚠️  No bars received")

if __name__ == "__main__":
    asyncio.run(test_buffer())
