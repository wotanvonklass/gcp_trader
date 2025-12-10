#!/usr/bin/env python3
"""
Test filtered proxy filtering logic by injecting mock data through firehose
"""

import asyncio
import websockets
import json
from typing import List

# Simulated Polygon messages
MOCK_MESSAGES = [
    {"ev":"T","sym":"AAPL","p":150.25,"s":100,"t":1704067200000,"x":4,"c":[14,37]},
    {"ev":"T","sym":"GOOGL","p":2800.50,"s":250,"t":1704067201000,"x":4,"c":[14]},
    {"ev":"A","sym":"AAPL","v":5200,"av":125000,"o":150.30,"c":150.25,"h":150.50,"l":150.20,"t":1704067200000},
    {"ev":"T","sym":"MSFT","p":380.75,"s":150,"t":1704067202000,"x":4,"c":[37]},
    {"ev":"Q","sym":"AAPL","bp":150.20,"bs":100,"ap":150.30,"as":150,"t":1704067203000},
    {"ev":"T","sym":"AAPL","p":150.30,"s":200,"t":1704067204000,"x":4,"c":[14,37]},
    {"ev":"T","sym":"GOOGL","p":2801.00,"s":300,"t":1704067205000,"x":4,"c":[14]},
    {"ev":"AM","sym":"MSFT","v":150000,"av":2500000,"o":380.50,"c":380.75,"h":381.00,"l":380.25,"t":1704067260000},
]

class MockClient:
    def __init__(self, name: str, subscriptions: List[str], port: int = 8765):
        self.name = name
        self.subscriptions = subscriptions
        self.url = f"ws://localhost:{port}"
        self.received_symbols = set()
        self.received_types = set()
        self.message_count = 0

    async def run(self, duration: int = 10):
        print(f"\n[{self.name}] Connecting...")
        async with websockets.connect(self.url) as ws:
            # Auth
            await ws.send(json.dumps({"action": "auth", "params": "test_key"}))
            auth_resp = await ws.recv()
            print(f"[{self.name}] Auth: {auth_resp}")

            # Subscribe
            sub_params = ",".join(self.subscriptions)
            await ws.send(json.dumps({"action": "subscribe", "params": sub_params}))
            sub_resp = await ws.recv()
            print(f"[{self.name}] Subscribed to: {sub_params}")

            # Receive messages
            end_time = asyncio.get_event_loop().time() + duration
            while asyncio.get_event_loop().time() < end_time:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)

                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and 'sym' in item:
                                self.received_symbols.add(item['sym'])
                                self.received_types.add(item.get('ev', 'unknown'))
                                self.message_count += 1
                                print(f"[{self.name}] Got: {item['ev']}.{item['sym']}")
                except asyncio.TimeoutError:
                    continue

        print(f"\n[{self.name}] ===== SUMMARY =====")
        print(f"[{self.name}] Total messages: {self.message_count}")
        print(f"[{self.name}] Symbols seen: {sorted(self.received_symbols)}")
        print(f"[{self.name}] Types seen: {sorted(self.received_types)}")

async def inject_mock_data():
    """Connect to firehose and inject mock data"""
    await asyncio.sleep(2)  # Let clients connect first

    print("\n[INJECTOR] Connecting to firehose proxy...")
    try:
        async with websockets.connect("ws://localhost:8767") as ws:
            # Auth
            await ws.send(json.dumps({"action": "auth", "params": "test_key"}))
            auth_resp = await ws.recv()
            print(f"[INJECTOR] Auth response: {auth_resp}")

            # Inject mock messages
            for i, msg in enumerate(MOCK_MESSAGES):
                await asyncio.sleep(0.5)  # Space out messages
                wrapped_msg = [msg]  # Wrap in array like Polygon does
                await ws.send(json.dumps(wrapped_msg))
                print(f"[INJECTOR] Sent {i+1}/{len(MOCK_MESSAGES)}: {msg['ev']}.{msg['sym']}")

            print("[INJECTOR] All mock data sent!")
            await asyncio.sleep(2)  # Let clients receive

    except Exception as e:
        print(f"[INJECTOR] Error: {e}")

async def test_scenario_specific_ticker():
    """Test 1: Client subscribes to specific ticker (T.AAPL)"""
    print("\n" + "="*70)
    print("TEST 1: Specific Ticker Subscription (T.AAPL)")
    print("Expected: Should only receive AAPL trades, nothing else")
    print("="*70)

    client = MockClient("Client-AAPL-Only", ["T.AAPL"])

    await asyncio.gather(
        client.run(duration=8),
        inject_mock_data()
    )

    # Verify
    print("\n🔍 VERIFICATION:")
    assert "AAPL" in client.received_symbols, "Should receive AAPL"
    assert "GOOGL" not in client.received_symbols, "Should NOT receive GOOGL"
    assert "MSFT" not in client.received_symbols, "Should NOT receive MSFT"
    assert "T" in client.received_types, "Should receive Trade type"
    assert "A" not in client.received_types, "Should NOT receive Aggregate type"
    print("✅ PASS: Client received only T.AAPL as expected")

async def test_scenario_wildcard():
    """Test 2: Client subscribes to wildcard (*)"""
    print("\n" + "="*70)
    print("TEST 2: Wildcard Subscription (*)")
    print("Expected: Should receive ALL symbols and types")
    print("="*70)

    client = MockClient("Client-Wildcard", ["*"])

    await asyncio.gather(
        client.run(duration=8),
        inject_mock_data()
    )

    # Verify
    print("\n🔍 VERIFICATION:")
    assert "AAPL" in client.received_symbols, "Should receive AAPL"
    assert "GOOGL" in client.received_symbols, "Should receive GOOGL"
    assert "MSFT" in client.received_symbols, "Should receive MSFT"
    print("✅ PASS: Client received all symbols as expected")

async def test_scenario_multi_client():
    """Test 3: Multiple clients with different subscriptions"""
    print("\n" + "="*70)
    print("TEST 3: Multiple Clients with Different Subscriptions")
    print("Client 1: T.AAPL")
    print("Client 2: *")
    print("Client 3: T.GOOGL,A.GOOGL")
    print("="*70)

    client1 = MockClient("Client1-AAPL", ["T.AAPL"])
    client2 = MockClient("Client2-All", ["*"])
    client3 = MockClient("Client3-GOOGL", ["T.GOOGL", "A.GOOGL"])

    await asyncio.gather(
        client1.run(duration=8),
        client2.run(duration=8),
        client3.run(duration=8),
        inject_mock_data()
    )

    # Verify
    print("\n🔍 VERIFICATION:")
    print(f"Client 1 got: {client1.received_symbols} (expected: only AAPL)")
    print(f"Client 2 got: {client2.received_symbols} (expected: AAPL, GOOGL, MSFT)")
    print(f"Client 3 got: {client3.received_symbols} (expected: only GOOGL)")

    assert client1.received_symbols == {"AAPL"}, "Client 1 should only get AAPL"
    assert "AAPL" in client2.received_symbols and "GOOGL" in client2.received_symbols, "Client 2 should get all"
    assert client3.received_symbols == {"GOOGL"}, "Client 3 should only get GOOGL"
    print("✅ PASS: All clients received correct filtered data")

async def main():
    print("🧪 Testing Filtered Proxy Filtering Logic")
    print("=" * 70)

    try:
        await test_scenario_specific_ticker()
        await asyncio.sleep(2)

        await test_scenario_wildcard()
        await asyncio.sleep(2)

        await test_scenario_multi_client()

        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
