#!/usr/bin/env python3
"""
Simple client to subscribe to TSLA trades for testing proxy resource usage
"""

import asyncio
import json
import os
import websockets
from datetime import datetime

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha")
PROXY_URL = "ws://localhost:8765"

async def tsla_client():
    """Connect and subscribe to TSLA trades"""
    try:
        # Connect
        ws = await websockets.connect(PROXY_URL)
        print(f"[{datetime.now()}] Connected to proxy")

        # Authenticate
        auth_msg = {"action": "auth", "params": POLYGON_API_KEY}
        await ws.send(json.dumps(auth_msg))
        response = await ws.recv()
        print(f"[{datetime.now()}] Auth response: {response}")

        # Subscribe to TSLA trades and quotes
        sub_msg = {"action": "subscribe", "params": "T.TSLA,Q.TSLA"}
        await ws.send(json.dumps(sub_msg))
        response = await ws.recv()
        print(f"[{datetime.now()}] Subscribe response: {response}")

        # Receive messages
        message_count = 0
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                message_count += 1

                if message_count % 10 == 0:
                    print(f"[{datetime.now()}] Received {message_count} messages")

                # Print first few messages to see what we're getting
                if message_count <= 3:
                    data = json.loads(msg)
                    print(f"  Sample message: {data}")

            except asyncio.TimeoutError:
                print(f"[{datetime.now()}] No messages for 5 seconds (total: {message_count})")
            except Exception as e:
                print(f"[{datetime.now()}] Error: {e}")
                break

    except Exception as e:
        print(f"[{datetime.now()}] Connection error: {e}")
    finally:
        if 'ws' in locals():
            await ws.close()

if __name__ == "__main__":
    print("Starting TSLA client...")
    print(f"Connecting to {PROXY_URL}")
    try:
        asyncio.run(tsla_client())
    except KeyboardInterrupt:
        print("\nClient stopped")
