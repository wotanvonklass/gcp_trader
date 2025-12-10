#!/usr/bin/env python3
"""Test 500ms bars with actually trading symbol"""

import asyncio
import websockets
import json

async def test():
    print("Step 1: Find an active symbol...")
    ws1 = await websockets.connect("ws://localhost:8767")
    await ws1.send(json.dumps({"action": "auth", "params": "test"}))
    await ws1.recv()

    # Subscribe to T.* to see what's trading
    await ws1.send(json.dumps({"action": "subscribe", "params": "T.*"}))
    await ws1.recv()

    active_symbols = set()
    for _ in range(20):
        try:
            msg = await asyncio.wait_for(ws1.recv(), timeout=0.5)
            data = json.loads(msg)
            if isinstance(data, list):
                for item in data:
                    if item.get("ev") == "T":
                        active_symbols.add(item["sym"])
        except:
            break

    await ws1.close()

    if not active_symbols:
        print("No active symbols found! Market might be closed.")
        return

    test_symbol = list(active_symbols)[0]
    print(f"Found active symbol: {test_symbol}")
    print(f"Total active symbols: {len(active_symbols)}")

    print(f"\nStep 2: Test 500ms bars for {test_symbol}...")
    ws2 = await websockets.connect("ws://localhost:8765")

    # Auth
    await ws2.send(json.dumps({"action": "auth", "params": "test"}))
    print(f"Auth: {(await ws2.recv())}")

    # Subscribe to both trades AND 500ms bars
    await ws2.send(json.dumps({
        "action": "subscribe",
        "params": f"T.{test_symbol},500Ms.{test_symbol}"
    }))
    print(f"Subscribe: {await ws2.recv()}")

    # Collect data
    print(f"\nWaiting for data (15 seconds)...")
    trades = 0
    bars = 0

    for i in range(15):
        try:
            msg = await asyncio.wait_for(ws2.recv(), timeout=1.0)
            data = json.loads(msg)

            if isinstance(data, list):
                for item in data:
                    if item.get("ev") == "T":
                        trades += 1
                        if trades <= 3:
                            print(f"  ✓ Trade: {item['sym']} @ ${item['p']}")
                    elif item.get("T") == "b":  # Bar
                        bars += 1
                        if bars <= 3:
                            print(f"  ✓ 500ms Bar: {item['S']} OHLC={item['o']}/{item['h']}/{item['l']}/{item['c']} V={item['v']}")
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"Error: {e}")

    await ws2.close()

    print(f"\n{'='*60}")
    print("RESULTS:")
    print(f"{'='*60}")
    print(f"Trades received: {trades}")
    print(f"500ms bars received: {bars}")

    if trades > 0 and bars > 0:
        print("\n✓ SUCCESS: Both trades AND 500ms bars working!")
    elif trades > 0 and bars == 0:
        print("\n✗ FAIL: Trades working but NO 500ms bars generated")
    elif trades == 0:
        print("\n⚠ WARNING: No trades received (market might be too quiet)")

asyncio.run(test())
