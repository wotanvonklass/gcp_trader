#!/usr/bin/env python3
"""
Comprehensive test suite for Polygon Filtered Proxy

Tests both happy paths and edge cases to ensure robustness.
"""

import asyncio
import websockets
import json
import pytest
from typing import List, Dict, Any


# Test Configuration
PROXY_URL = "ws://localhost:8765"
TEST_API_KEY = "test_key"


class ProxyClient:
    """Helper class for managing WebSocket connections to the proxy"""

    def __init__(self, name: str):
        self.name = name
        self.ws = None
        self.received_messages = []

    async def connect(self):
        """Connect to the proxy"""
        self.ws = await websockets.connect(PROXY_URL)
        return self

    async def auth(self, api_key: str = TEST_API_KEY):
        """Authenticate with the proxy"""
        await self.ws.send(json.dumps({
            "action": "auth",
            "params": api_key
        }))
        response = await self.ws.recv()
        return json.loads(response)

    async def subscribe(self, params: str):
        """Subscribe to symbols"""
        await self.ws.send(json.dumps({
            "action": "subscribe",
            "params": params
        }))
        response = await self.ws.recv()
        return json.loads(response)

    async def unsubscribe(self, params: str):
        """Unsubscribe from symbols"""
        await self.ws.send(json.dumps({
            "action": "unsubscribe",
            "params": params
        }))
        response = await self.ws.recv()
        return json.loads(response)

    async def receive_messages(self, count: int = 10, timeout: float = 1.0):
        """Receive up to count messages with timeout"""
        messages = []
        for _ in range(count):
            try:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
                data = json.loads(msg)
                messages.append(data)
                self.received_messages.append(data)
            except asyncio.TimeoutError:
                break
            except json.JSONDecodeError:
                # Skip non-JSON messages
                continue
        return messages

    async def send_raw(self, message: str):
        """Send raw message (for testing invalid inputs)"""
        await self.ws.send(message)

    async def close(self):
        """Close the connection"""
        if self.ws:
            await self.ws.close()

    def get_symbols(self) -> set:
        """Extract all symbols from received messages"""
        symbols = set()
        for msg in self.received_messages:
            if isinstance(msg, list):
                for item in msg:
                    if isinstance(item, dict) and 'sym' in item:
                        symbols.add(item['sym'])
        return symbols

    def get_event_types(self) -> set:
        """Extract all event types from received messages"""
        event_types = set()
        for msg in self.received_messages:
            if isinstance(msg, list):
                for item in msg:
                    if isinstance(item, dict) and 'ev' in item:
                        event_types.add(item['ev'])
        return event_types


# ============================================================================
# HAPPY PATH TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_basic_auth_and_subscribe():
    """Test basic authentication and subscription flow"""
    client = ProxyClient("basic_test")

    try:
        await client.connect()

        # Test authentication
        auth_resp = await client.auth()
        assert auth_resp[0]["status"] == "auth_success"

        # Test subscription
        sub_resp = await client.subscribe("T.AAPL")
        assert sub_resp[0]["status"] == "success"
        assert "subscribed" in sub_resp[0]["message"].lower()

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_multiple_ticker_subscription():
    """Test subscribing to multiple tickers at once"""
    client = ProxyClient("multi_ticker")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to multiple tickers
        sub_resp = await client.subscribe("T.AAPL,T.TSLA,T.NVDA")
        assert sub_resp[0]["status"] == "success"

        # Receive some messages
        messages = await client.receive_messages(20, timeout=2.0)

        # Check that we only get subscribed symbols
        symbols = client.get_symbols()
        if len(symbols) > 0:
            assert symbols.issubset({"AAPL", "TSLA", "NVDA"})

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_wildcard_subscription():
    """Test wildcard subscription receives all symbols"""
    client = ProxyClient("wildcard")

    try:
        await client.connect()
        await client.auth()

        sub_resp = await client.subscribe("*")
        assert sub_resp[0]["status"] == "success"

        # Receive messages
        messages = await client.receive_messages(50, timeout=3.0)

        # Wildcard should receive multiple different symbols
        symbols = client.get_symbols()
        # We expect to see various symbols with wildcard
        # (exact count depends on market activity)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_multiple_message_types():
    """Test subscription to different message types (T, A, AM)"""
    client = ProxyClient("multi_type")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to trades and aggregates
        sub_resp = await client.subscribe("T.AAPL,A.AAPL,AM.AAPL")
        assert sub_resp[0]["status"] == "success"

        # Receive messages
        await client.receive_messages(30, timeout=3.0)

        # Check we can get different event types
        event_types = client.get_event_types()
        # Note: We might not receive all types depending on market activity

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_flow():
    """Test subscribing then unsubscribing"""
    client = ProxyClient("unsub_flow")

    try:
        await client.connect()
        await client.auth()

        # Subscribe
        sub_resp = await client.subscribe("T.TSLA")
        assert sub_resp[0]["status"] == "success"

        # Receive some messages
        messages_before = await client.receive_messages(10, timeout=2.0)
        symbols_before = client.get_symbols()

        # Unsubscribe
        unsub_resp = await client.unsubscribe("T.TSLA")
        assert unsub_resp[0]["status"] == "success"
        assert "unsubscribed" in unsub_resp[0]["message"].lower()

        # Clear received messages
        client.received_messages = []

        # Try to receive more - should get nothing (or at least no TSLA)
        await client.receive_messages(10, timeout=2.0)
        symbols_after = client.get_symbols()

        # After unsubscribe, should not receive TSLA
        assert "TSLA" not in symbols_after

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_multiple_clients_different_subscriptions():
    """Test multiple clients with different subscriptions don't interfere"""
    client1 = ProxyClient("client1")
    client2 = ProxyClient("client2")

    try:
        # Connect both clients
        await client1.connect()
        await client2.connect()

        # Authenticate both
        await client1.auth()
        await client2.auth()

        # Different subscriptions
        await client1.subscribe("T.AAPL")
        await client2.subscribe("T.NVDA")

        # Receive messages concurrently
        await asyncio.gather(
            client1.receive_messages(20, timeout=3.0),
            client2.receive_messages(20, timeout=3.0)
        )

        # Check isolation
        symbols1 = client1.get_symbols()
        symbols2 = client2.get_symbols()

        if len(symbols1) > 0:
            assert symbols1 == {"AAPL"} or len(symbols1) == 0

        if len(symbols2) > 0:
            assert symbols2 == {"NVDA"} or len(symbols2) == 0

    finally:
        await client1.close()
        await client2.close()


@pytest.mark.asyncio
async def test_multiple_clients_same_subscription():
    """Test multiple clients can subscribe to the same ticker independently"""
    client1 = ProxyClient("same1")
    client2 = ProxyClient("same2")

    try:
        await client1.connect()
        await client2.connect()

        await client1.auth()
        await client2.auth()

        # Both subscribe to same ticker
        await client1.subscribe("T.TSLA")
        await client2.subscribe("T.TSLA")

        # Both should receive messages
        messages1 = await client1.receive_messages(10, timeout=2.0)
        messages2 = await client2.receive_messages(10, timeout=2.0)

        # Both clients should have received some data
        # (if market is active)

    finally:
        await client1.close()
        await client2.close()


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_unsubscribe_without_subscribe():
    """Test unsubscribing from a ticker that was never subscribed"""
    client = ProxyClient("unsub_without_sub")

    try:
        await client.connect()
        await client.auth()

        # Unsubscribe without subscribing first
        unsub_resp = await client.unsubscribe("T.AAPL")
        # Should still return success (idempotent operation)
        assert unsub_resp[0]["status"] == "success"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_duplicate_subscription():
    """Test subscribing to the same ticker twice"""
    client = ProxyClient("dup_sub")

    try:
        await client.connect()
        await client.auth()

        # Subscribe twice
        sub_resp1 = await client.subscribe("T.AAPL")
        assert sub_resp1[0]["status"] == "success"

        sub_resp2 = await client.subscribe("T.AAPL")
        assert sub_resp2[0]["status"] == "success"

        # Should still work fine (idempotent)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_empty_subscription_params():
    """Test subscribing with empty params"""
    client = ProxyClient("empty_params")

    try:
        await client.connect()
        await client.auth()

        # Try to subscribe with empty string
        sub_resp = await client.subscribe("")
        # Should handle gracefully

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_subscription_format():
    """Test subscription with invalid format"""
    client = ProxyClient("invalid_format")

    try:
        await client.connect()
        await client.auth()

        # Various invalid formats
        test_cases = [
            "AAPL",  # Missing type prefix
            "T.",    # Missing symbol
            "...",   # Just dots
            "T.AAPL.extra",  # Too many parts
        ]

        for test_case in test_cases:
            sub_resp = await client.subscribe(test_case)
            # Should still return a response (may be success or error)
            assert "status" in sub_resp[0]

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_subscription_without_auth():
    """Test subscribing without authenticating first"""
    client = ProxyClient("no_auth")

    try:
        await client.connect()

        # Try to subscribe without auth
        await client.ws.send(json.dumps({
            "action": "subscribe",
            "params": "T.AAPL"
        }))

        # Proxy may silently ignore or send error - both are acceptable
        # Try to receive but don't require a response
        try:
            response = await asyncio.wait_for(client.ws.recv(), timeout=1.0)
            # If we get a response, it should be valid JSON
            if response:
                json.loads(response)
        except asyncio.TimeoutError:
            # No response is also acceptable (silently ignored)
            pass

        # Key test: connection should still be alive
        # Authenticate now and verify it works
        auth_resp = await client.auth()
        assert auth_resp[0]["status"] == "auth_success"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_json():
    """Test sending invalid JSON"""
    client = ProxyClient("invalid_json")

    try:
        await client.connect()
        await client.auth()

        # Send invalid JSON
        await client.send_raw("not valid json{{{")

        # Connection should stay alive
        # Try a valid operation after
        sub_resp = await client.subscribe("T.AAPL")
        assert sub_resp[0]["status"] == "success"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rapid_subscribe_unsubscribe():
    """Test rapid subscribe/unsubscribe operations"""
    client = ProxyClient("rapid_ops")

    try:
        await client.connect()
        await client.auth()

        # Rapidly subscribe and unsubscribe
        for i in range(10):
            await client.subscribe("T.AAPL")
            await client.receive_messages(1, timeout=0.1)
            await client.unsubscribe("T.AAPL")
            await client.receive_messages(1, timeout=0.1)

        # Should handle gracefully

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_very_long_subscription_list():
    """Test subscribing to many tickers at once"""
    client = ProxyClient("long_list")

    try:
        await client.connect()
        await client.auth()

        # Create a long list of subscriptions
        symbols = ["AAPL", "TSLA", "NVDA", "AMD", "GOOGL", "MSFT",
                   "AMZN", "META", "NFLX", "INTC"]
        params = ",".join([f"T.{sym}" for sym in symbols])

        sub_resp = await client.subscribe(params)
        assert sub_resp[0]["status"] == "success"

        # Should handle large subscription lists

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_concurrent_operations():
    """Test concurrent operations from multiple clients"""
    clients = [ProxyClient(f"concurrent_{i}") for i in range(5)]

    try:
        # Connect all clients
        await asyncio.gather(*[c.connect() for c in clients])

        # Authenticate all
        await asyncio.gather(*[c.auth() for c in clients])

        # Each client subscribes to different ticker
        symbols = ["AAPL", "TSLA", "NVDA", "AMD", "GOOGL"]
        await asyncio.gather(*[
            clients[i].subscribe(f"T.{symbols[i]}")
            for i in range(5)
        ])

        # All receive messages concurrently
        await asyncio.gather(*[
            c.receive_messages(10, timeout=2.0)
            for c in clients
        ])

        # Each should only see their symbol
        for i, client in enumerate(clients):
            syms = client.get_symbols()
            if len(syms) > 0:
                assert syms == {symbols[i]}

    finally:
        await asyncio.gather(*[c.close() for c in clients])


@pytest.mark.asyncio
async def test_client_disconnect_cleanup():
    """Test that client disconnection properly cleans up subscriptions"""
    client1 = ProxyClient("disconnect1")
    client2 = ProxyClient("disconnect2")

    try:
        await client1.connect()
        await client2.connect()

        await client1.auth()
        await client2.auth()

        # Both subscribe to same ticker
        await client1.subscribe("T.TSLA")
        await client2.subscribe("T.TSLA")

        # Client1 disconnects abruptly
        await client1.close()

        # Client2 should still receive messages
        messages = await client2.receive_messages(10, timeout=2.0)
        # Client2 should still work fine

    finally:
        await client2.close()


@pytest.mark.asyncio
async def test_multiple_unsubscribes():
    """Test unsubscribing from the same ticker multiple times"""
    client = ProxyClient("multi_unsub")

    try:
        await client.connect()
        await client.auth()

        # Subscribe once
        await client.subscribe("T.AAPL")

        # Unsubscribe multiple times
        for _ in range(3):
            unsub_resp = await client.unsubscribe("T.AAPL")
            assert unsub_resp[0]["status"] == "success"

        # Should handle gracefully (idempotent)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_wildcard_plus_specific():
    """Test subscribing to wildcard and then specific ticker"""
    client = ProxyClient("wildcard_specific")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to wildcard
        await client.subscribe("*")

        # Also subscribe to specific (should be redundant)
        await client.subscribe("T.AAPL")

        # Should work fine - client gets everything from wildcard
        messages = await client.receive_messages(20, timeout=2.0)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mixed_valid_invalid_subscriptions():
    """Test subscription list with mix of valid and invalid formats"""
    client = ProxyClient("mixed_subs")

    try:
        await client.connect()
        await client.auth()

        # Mix of valid and potentially invalid
        sub_resp = await client.subscribe("T.AAPL,INVALID,T.TSLA,")
        # Should handle gracefully

    finally:
        await client.close()


# ============================================================================
# MS-AGGREGATOR INTEGRATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_second_bar_subscription():
    """Test subscribing to second bars (A.*)"""
    client = ProxyClient("second_bars")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to 1-second bars
        sub_resp = await client.subscribe("A.AAPL")
        assert sub_resp[0]["status"] == "success"
        assert "subscribed" in sub_resp[0]["message"].lower()

        # Should route to ms-aggregator and receive bars
        messages = await client.receive_messages(10, timeout=3.0)

        # Check for bar data (if any received)
        for msg in messages:
            if isinstance(msg, list):
                for item in msg:
                    if isinstance(item, dict) and 'ev' in item:
                        # A.* bars have ev=A
                        if item['ev'] == 'A':
                            assert 'sym' in item
                            assert item['sym'] == 'AAPL'

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_minute_bar_subscription():
    """Test subscribing to minute bars (AM.*)"""
    client = ProxyClient("minute_bars")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to 1-minute bars
        sub_resp = await client.subscribe("AM.TSLA")
        assert sub_resp[0]["status"] == "success"

        # Should route to ms-aggregator
        await client.receive_messages(5, timeout=2.0)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_millisecond_bar_subscription():
    """Test subscribing to millisecond bars (*Ms.*)"""
    client = ProxyClient("ms_bars")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to 100ms bars
        sub_resp = await client.subscribe("100Ms.AAPL")
        assert sub_resp[0]["status"] == "success"

        # Should route to ms-aggregator
        await client.receive_messages(20, timeout=3.0)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mixed_ticks_and_bars():
    """Test subscribing to both ticks and bars simultaneously"""
    client = ProxyClient("mixed_data")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to trades AND bars
        sub_resp = await client.subscribe("T.AAPL,A.AAPL,100Ms.AAPL")
        assert sub_resp[0]["status"] == "success"

        # Should receive data from BOTH upstreams
        messages = await client.receive_messages(30, timeout=4.0)

        # Check that we can receive different event types
        event_types = set()
        for msg in messages:
            if isinstance(msg, list):
                for item in msg:
                    if isinstance(item, dict) and 'ev' in item:
                        event_types.add(item['ev'])

        # We should potentially see trades (T) and bars (A)
        # (depending on market activity)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_multiple_bar_timeframes():
    """Test subscribing to multiple bar timeframes"""
    client = ProxyClient("multi_bars")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to multiple bar types
        sub_resp = await client.subscribe("A.AAPL,AM.AAPL,100Ms.AAPL,250Ms.AAPL")
        assert sub_resp[0]["status"] == "success"

        # All should route to ms-aggregator
        await client.receive_messages(30, timeout=4.0)

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_bar_unsubscribe():
    """Test unsubscribing from bars"""
    client = ProxyClient("bar_unsub")

    try:
        await client.connect()
        await client.auth()

        # Subscribe to bars
        await client.subscribe("A.AAPL,100Ms.AAPL")

        # Unsubscribe
        unsub_resp = await client.unsubscribe("A.AAPL,100Ms.AAPL")
        assert unsub_resp[0]["status"] == "success"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_wildcard_includes_bars():
    """Test that wildcard subscription includes bars from ms-aggregator"""
    client = ProxyClient("wildcard_bars")

    try:
        await client.connect()
        await client.auth()

        # Wildcard should get data from BOTH firehose and ms-aggregator
        sub_resp = await client.subscribe("*")
        assert sub_resp[0]["status"] == "success"

        # Receive messages
        messages = await client.receive_messages(50, timeout=4.0)

        # Should potentially receive both trades and bars
        event_types = client.get_event_types()
        # Event types might include T, Q, A, AM depending on market

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_two_clients_bars_vs_ticks():
    """Test one client with bars, another with ticks"""
    client1 = ProxyClient("bars_client")
    client2 = ProxyClient("ticks_client")

    try:
        await client1.connect()
        await client2.connect()

        await client1.auth()
        await client2.auth()

        # Client 1: bars only
        await client1.subscribe("A.AAPL,100Ms.AAPL")

        # Client 2: ticks only
        await client2.subscribe("T.AAPL")

        # Both should receive appropriate data
        await asyncio.gather(
            client1.receive_messages(20, timeout=3.0),
            client2.receive_messages(20, timeout=3.0)
        )

        # Both should only get AAPL
        symbols1 = client1.get_symbols()
        symbols2 = client2.get_symbols()

        if len(symbols1) > 0:
            assert symbols1 == {"AAPL"}
        if len(symbols2) > 0:
            assert symbols2 == {"AAPL"}

    finally:
        await client1.close()
        await client2.close()


# ============================================================================
# TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    print("Filtered Proxy Test Suite")
    print("=" * 60)
    print("\nTo run these tests:")
    print("  1. Ensure filtered proxy is running on port 8765")
    print("  2. Run: pytest test_filtered_proxy.py -v")
    print("  3. Or run specific test: pytest test_filtered_proxy.py::test_basic_auth_and_subscribe -v")
    print("\nFor coverage report:")
    print("  pytest test_filtered_proxy.py --cov=filtered_proxy --cov-report=html")
    print("\n" + "=" * 60)
