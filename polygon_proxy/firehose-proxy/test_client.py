#!/usr/bin/env python3
"""
Test client for Polygon Firehose Proxy

Usage:
    python3 test_client.py
"""

import asyncio
import websockets
import json
from datetime import datetime

PROXY_URL = "ws://localhost:8767"
AUTH_TOKEN = "firehose-token-12345"


async def test_firehose():
    """Connect to firehose proxy and receive all messages"""
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

            # Receive messages
            message_count = 0
            print(f"\n[{datetime.now()}] Listening for messages...\n")

            async for message in ws:
                message_count += 1

                # Parse and display
                try:
                    data = json.loads(message)

                    # Show first few messages in detail
                    if message_count <= 10:
                        print(f"Message {message_count}: {json.dumps(data, indent=2)}")
                    elif message_count % 100 == 0:
                        print(f"[{datetime.now()}] Received {message_count} messages...")

                except json.JSONDecodeError:
                    print(f"Failed to parse: {message[:100]}")

    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Stopped by user")
    except Exception as e:
        print(f"[{datetime.now()}] Error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Polygon Firehose Proxy - Test Client")
    print("=" * 60)
    print()

    asyncio.run(test_firehose())
