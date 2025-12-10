#!/usr/bin/env python3
import asyncio
import websockets
import json

async def test_connection():
    try:
        print("Connecting to filtered proxy at ws://localhost:8765...")
        async with websockets.connect("ws://localhost:8765") as ws:
            print("✅ Connected!")

            # Auth
            auth_msg = {"action": "auth", "params": "MdHapjkP8r7K6y30JH_WCxwVW19eMh3Y"}
            await ws.send(json.dumps(auth_msg))
            print(f"Sent auth: {auth_msg}")

            # Receive response
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {response}")

            # Subscribe
            sub_msg = {"action": "subscribe", "params": "T.AAPL"}
            await ws.send(json.dumps(sub_msg))
            print(f"Sent subscribe: {sub_msg}")

            # Wait for data
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    print(f"Message {i+1}: {msg}")
                except asyncio.TimeoutError:
                    print(f"Timeout waiting for message {i+1}")

    except Exception as e:
        print(f"❌ Error: {e}")

asyncio.run(test_connection())
