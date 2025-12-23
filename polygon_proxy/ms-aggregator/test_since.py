#!/usr/bin/env python3
"""
Test 'since' parameter for buffered bar replay.

Run ms-aggregator first:
  ENABLE_FAKE_DATA=true POLYGON_API_KEY=test FIREHOSE_URL=ws://localhost:8767 cargo run

Then run this test:
  python test_since.py
"""

import asyncio
import json
import time

try:
    import websockets
except ImportError:
    print("Please install websockets: pip install websockets")
    exit(1)

AGGREGATOR_URL = "ws://localhost:8768"

async def test_since():
    print(f"Connecting to {AGGREGATOR_URL}...")

    async with websockets.connect(AGGREGATOR_URL) as ws:
        # Authenticate
        await ws.send(json.dumps({"action": "auth", "params": "test"}))
        auth_resp = await ws.recv()
        print(f"Auth: {auth_resp}")

        # Wait a few seconds for buffer to fill
        print("\nWaiting 3 seconds for buffer to accumulate trades...")
        await asyncio.sleep(3)

        # Subscribe with 'since' = 2 seconds ago
        since_ms = int((time.time() - 2) * 1000)  # 2 seconds ago
        sub_msg = {
            "action": "subscribe",
            "params": "250Ms.FAKETICKER",
            "since": since_ms
        }
        print(f"Subscribing with since={since_ms} (2 seconds ago)")
        await ws.send(json.dumps(sub_msg))
        sub_resp = await ws.recv()
        print(f"Subscribe: {sub_resp}")

        # Collect bars for 3 seconds
        print("\nWaiting for bars...")
        print("-" * 60)

        replay_bars = []
        live_bars = []
        start = time.time()
        now_ms = int(time.time() * 1000)

        try:
            while (time.time() - start) < 3:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    data = json.loads(msg)

                    if isinstance(data, list):
                        for item in data:
                            if item.get("ev") == "MB":
                                end_ts = item.get("e", 0)
                                age_ms = now_ms - end_ts
                                is_replay = age_ms > 500  # >500ms old = replay

                                sym = item.get("sym", "")
                                o = item.get("o", 0)
                                c = item.get("c", 0)
                                v = item.get("v", 0)
                                n = item.get("n", 0)

                                label = "REPLAY" if is_replay else "LIVE"
                                print(f"  [{label}] {sym} O={o:.2f} C={c:.2f} V={v} N={n} (age={age_ms}ms)")

                                if is_replay:
                                    replay_bars.append(item)
                                else:
                                    live_bars.append(item)
                    else:
                        print(f"  {data}")

                except asyncio.TimeoutError:
                    pass
        except KeyboardInterrupt:
            pass

        print("-" * 60)
        print(f"\nSummary:")
        print(f"  Replay bars (historical): {len(replay_bars)}")
        print(f"  Live bars: {len(live_bars)}")

        if replay_bars:
            print("\n✅ 'since' parameter working! Received buffered bars on subscribe.")
        else:
            print("\n⚠️  No replay bars received. Buffer may be empty or 'since' too recent.")

if __name__ == "__main__":
    asyncio.run(test_since())
