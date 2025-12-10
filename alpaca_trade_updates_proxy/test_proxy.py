#!/usr/bin/env python3
"""Test script for trading updates proxy."""

import asyncio
import json
import websockets
from datetime import datetime

async def test_connection():
    """Test connection to the trading updates proxy."""
    url = "ws://localhost:8099/trade-updates-paper"

    print(f"╔════════════════════════════════════════════════════╗")
    print(f"║  Trading Updates Proxy Test                       ║")
    print(f"╚════════════════════════════════════════════════════╝")
    print()
    print(f"Connecting to: {url}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        async with websockets.connect(url) as ws:
            print("✓ Connected successfully")

            # Authenticate
            auth_msg = {"action": "auth", "key": "test", "secret": "test"}
            await ws.send(json.dumps(auth_msg))
            print("→ Sent authentication")

            # Receive auth response
            auth_response = await ws.recv()
            auth_data = json.loads(auth_response)
            print(f"← Auth response: {auth_data}")

            if isinstance(auth_data, list) and auth_data[0].get("T") == "success":
                print("✓ Authentication successful")
            else:
                print("✗ Authentication failed")
                return

            print()
            print("Listening for trading updates...")
            print("(Updates will appear when orders are placed/filled/cancelled)")
            print("Press Ctrl+C to stop")
            print()

            # Listen for messages
            message_count = 0
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    message_count += 1
                    data = json.loads(message)

                    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"[{timestamp}] Message #{message_count}:")
                    print(json.dumps(data, indent=2))
                    print()

                except asyncio.TimeoutError:
                    # Just a timeout, continue waiting
                    continue

    except websockets.exceptions.ConnectionRefused:
        print("✗ Connection refused")
        print("  Make sure the proxy is running: cargo run --release")
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
