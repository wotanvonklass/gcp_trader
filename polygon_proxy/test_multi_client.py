#!/usr/bin/env python3
"""
Test multiple clients with different subscription patterns:
1. Client 1: Specific ticker (T.AAPL)
2. Client 2: Wildcard (*)
3. Client 3: Multiple tickers (T.GOOGL, A.GOOGL)
4. Test unsubscribe functionality
"""

import asyncio
import websockets
import json
import sys
from datetime import datetime
from typing import Set

class TestClient:
    def __init__(self, name: str, port: int = 8765):
        self.name = name
        self.url = f"ws://localhost:{port}"
        self.messages_received = 0
        self.symbols_seen: Set[str] = set()
        self.types_seen: Set[str] = set()

    async def run(self, subscriptions: list, duration: int = 10, unsubscribe_after: int = None):
        """
        Run client with given subscriptions for specified duration

        Args:
            subscriptions: List of subscription strings (e.g., ["T.AAPL", "Q.GOOGL"])
            duration: How long to run in seconds
            unsubscribe_after: If set, unsubscribe after this many seconds
        """
        print(f"\n[{self.name}] Connecting to {self.url}...")

        try:
            async with websockets.connect(self.url) as ws:
                # Authenticate
                auth_msg = {"action": "auth", "params": "MdHapjkP8r7K6y30JH_WCxwVW19eMh3Y"}
                await ws.send(json.dumps(auth_msg))
                response = await ws.recv()
                print(f"[{self.name}] Auth response: {response}")

                # Subscribe
                sub_params = ",".join(subscriptions)
                sub_msg = {"action": "subscribe", "params": sub_params}
                await ws.send(json.dumps(sub_msg))
                print(f"[{self.name}] Subscribed to: {sub_params}")

                # Receive messages
                start_time = asyncio.get_event_loop().time()
                unsubscribed = False

                while asyncio.get_event_loop().time() - start_time < duration:
                    try:
                        # Check if we should unsubscribe
                        elapsed = asyncio.get_event_loop().time() - start_time
                        if unsubscribe_after and elapsed >= unsubscribe_after and not unsubscribed:
                            unsub_msg = {"action": "unsubscribe", "params": sub_params}
                            await ws.send(json.dumps(unsub_msg))
                            print(f"[{self.name}] ⚠️  UNSUBSCRIBED from: {sub_params}")
                            unsubscribed = True

                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        self.messages_received += 1

                        # Parse and track what we're seeing
                        try:
                            data = json.loads(msg)
                            if isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict):
                                        if 'sym' in item:
                                            self.symbols_seen.add(item['sym'])
                                        if 'ev' in item:
                                            self.types_seen.add(item['ev'])

                                        # Print sample messages
                                        if self.messages_received % 50 == 0:
                                            print(f"[{self.name}] Sample: {item}")
                        except:
                            pass

                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"[{self.name}] Error receiving: {e}")
                        break

                print(f"\n[{self.name}] ===== SUMMARY =====")
                print(f"[{self.name}] Total messages: {self.messages_received}")
                print(f"[{self.name}] Symbols seen: {sorted(self.symbols_seen)}")
                print(f"[{self.name}] Event types seen: {sorted(self.types_seen)}")
                print(f"[{self.name}] Unsubscribed: {unsubscribed}")

        except Exception as e:
            print(f"[{self.name}] Connection error: {e}")

async def test_scenario_1():
    """Test specific ticker subscription"""
    print("\n" + "="*60)
    print("SCENARIO 1: Single client with specific ticker (T.AAPL)")
    print("="*60)

    client = TestClient("Client-Specific")
    await client.run(subscriptions=["T.AAPL"], duration=15)

async def test_scenario_2():
    """Test wildcard subscription"""
    print("\n" + "="*60)
    print("SCENARIO 2: Single client with wildcard (*)")
    print("="*60)

    client = TestClient("Client-Wildcard")
    await client.run(subscriptions=["*"], duration=15)

async def test_scenario_3():
    """Test multiple tickers"""
    print("\n" + "="*60)
    print("SCENARIO 3: Single client with multiple tickers")
    print("="*60)

    client = TestClient("Client-Multi")
    await client.run(subscriptions=["T.GOOGL", "A.GOOGL", "T.MSFT"], duration=15)

async def test_scenario_4():
    """Test multiple clients simultaneously with different subscriptions"""
    print("\n" + "="*60)
    print("SCENARIO 4: Multiple clients with different subscriptions")
    print("="*60)

    client1 = TestClient("Client1-AAPL")
    client2 = TestClient("Client2-Wildcard")
    client3 = TestClient("Client3-GOOGL")

    # Run all clients concurrently
    await asyncio.gather(
        client1.run(subscriptions=["T.AAPL"], duration=20),
        client2.run(subscriptions=["*"], duration=20),
        client3.run(subscriptions=["T.GOOGL", "Q.GOOGL"], duration=20)
    )

async def test_scenario_5():
    """Test unsubscribe functionality"""
    print("\n" + "="*60)
    print("SCENARIO 5: Subscribe then unsubscribe")
    print("="*60)

    client = TestClient("Client-Unsub")
    # Subscribe for 20 seconds, unsubscribe after 10 seconds
    await client.run(subscriptions=["T.AAPL", "T.GOOGL"], duration=20, unsubscribe_after=10)

async def test_scenario_6():
    """Test wildcard vs specific - verify filtering"""
    print("\n" + "="*60)
    print("SCENARIO 6: Wildcard vs Specific (verify filtering)")
    print("Expected: Client1 gets only AAPL, Client2 gets everything")
    print("="*60)

    client1 = TestClient("Client1-OnlyAAPL")
    client2 = TestClient("Client2-Everything")

    # Run both concurrently
    await asyncio.gather(
        client1.run(subscriptions=["T.AAPL"], duration=15),
        client2.run(subscriptions=["*"], duration=15)
    )

    print("\n🔍 VERIFICATION:")
    print(f"Client1 should only see AAPL: {client1.symbols_seen}")
    print(f"Client2 should see multiple symbols: {client2.symbols_seen}")

async def main():
    if len(sys.argv) > 1:
        scenario = sys.argv[1]
        if scenario == "1":
            await test_scenario_1()
        elif scenario == "2":
            await test_scenario_2()
        elif scenario == "3":
            await test_scenario_3()
        elif scenario == "4":
            await test_scenario_4()
        elif scenario == "5":
            await test_scenario_5()
        elif scenario == "6":
            await test_scenario_6()
        else:
            print("Invalid scenario. Use 1-6")
    else:
        # Run all scenarios
        print("🧪 Running all test scenarios...")
        print("="*60)

        await test_scenario_1()
        await asyncio.sleep(2)

        await test_scenario_2()
        await asyncio.sleep(2)

        await test_scenario_3()
        await asyncio.sleep(2)

        await test_scenario_4()
        await asyncio.sleep(2)

        await test_scenario_5()
        await asyncio.sleep(2)

        await test_scenario_6()

if __name__ == "__main__":
    print("Multi-Client Test Suite for Filtered Proxy")
    print("=" * 60)
    print("Usage:")
    print("  python test_multi_client.py     # Run all scenarios")
    print("  python test_multi_client.py 1   # Run scenario 1 only")
    print("  python test_multi_client.py 2   # Run scenario 2 only")
    print("  ... etc")
    print("=" * 60)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
