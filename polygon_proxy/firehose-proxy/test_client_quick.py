#!/usr/bin/env python3
"""
Quick test client for Polygon Firehose Proxy
Runs for 5 seconds to verify connection and auth
"""

import asyncio
import websockets
import json
from datetime import datetime

PROXY_URL = "ws://localhost:8767"
AUTH_TOKEN = "firehose-token-12345"


async def test_firehose():
    """Connect to firehose proxy and receive messages for 5 seconds"""
    print(f"[{datetime.now()}] Connecting to {PROXY_URL}...")

    try:
        async with websockets.connect(PROXY_URL) as ws:
            print(f"[{datetime.now()}] Connected!")

            # Authenticate
            auth_msg = {"action": "auth", "token": AUTH_TOKEN}
            await ws.send(json.dumps(auth_msg))
            response = await ws.recv()
            print(f"[{datetime.now()}] Auth response: {response}")

            auth_data = json.loads(response)
            if auth_data.get("status") != "authenticated":
                print("Authentication failed!")
                return

            # Subscribe to firehose
            sub_msg = {"action": "subscribe"}
            await ws.send(json.dumps(sub_msg))
            response = await ws.recv()
            print(f"[{datetime.now()}] Subscribe response: {response}")

            # Receive messages for 5 seconds
            message_count = 0
            print(f"\n[{datetime.now()}] Listening for messages (5 seconds)...\n")

            try:
                async with asyncio.timeout(5):
                    async for message in ws:
                        message_count += 1

                        # Parse and display
                        try:
                            data = json.loads(message)
                            print(f"Message {message_count}: {json.dumps(data, indent=2)}")

                        except json.JSONDecodeError:
                            print(f"Failed to parse: {message[:100]}")
            except asyncio.TimeoutError:
                print(f"\n[{datetime.now()}] Timeout after 5 seconds")

            print(f"[{datetime.now()}] Total messages received: {message_count}")

    except Exception as e:
        print(f"[{datetime.now()}] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 60)
    print("Polygon Firehose Proxy - Quick Test Client")
    print("=" * 60)
    print()

    asyncio.run(test_firehose())
