#!/usr/bin/env python3
"""Debug test to see actual data flow"""

import asyncio
import websockets
import json

async def test():
    print("Connecting to filtered proxy...")
    ws = await websockets.connect("ws://localhost:8765")

    # Auth
    await ws.send(json.dumps({"action": "auth", "params": "test"}))
    print(f"Auth: {await ws.recv()}")

    # Subscribe to 500Ms.TSLA
    print("\nSubscribing to 500Ms.TSLA...")
    await ws.send(json.dumps({"action": "subscribe", "params": "500Ms.TSLA"}))
    print(f"Subscribe response: {await ws.recv()}")

    # Wait for data
    print("\nWaiting for data (30 seconds)...")
    for i in range(30):
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            print(f"[{i}s] Received: {msg[:200]}")
        except asyncio.TimeoutError:
            print(f"[{i}s] No data...")

    await ws.close()

asyncio.run(test())
