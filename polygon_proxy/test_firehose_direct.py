#!/usr/bin/env python3
"""Test firehose directly to see if trades are coming from Polygon"""

import asyncio
import websockets
import json

async def test():
    print("Connecting directly to firehose (port 8767)...")
    ws = await websockets.connect("ws://localhost:8767")

    # Auth
    await ws.send(json.dumps({"action": "auth", "params": "test"}))
    print(f"Auth: {await ws.recv()}")

    # Subscribe to T.TSLA
    print("\nSubscribing to T.TSLA...")
    await ws.send(json.dumps({"action": "subscribe", "params": "T.TSLA"}))
    print(f"Subscribe response: {await ws.recv()}")

    # Wait for trades
    print("\nWaiting for TSLA trades (10 seconds)...")
    count = 0
    for i in range(10):
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            data = json.loads(msg)
            if isinstance(data, list):
                for item in data:
                    if item.get("ev") == "T":
                        count += 1
                        if count <= 3:  # Show first 3
                            print(f"  Trade: {item['sym']} @ ${item['p']} size={item['s']}")
        except asyncio.TimeoutError:
            print(f"[{i}s] No trades...")
        except:
            pass

    print(f"\nTotal trades received: {count}")
    await ws.close()

asyncio.run(test())
