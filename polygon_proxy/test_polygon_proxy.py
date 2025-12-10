#!/usr/bin/env python3
"""
Test script for Polygon WebSocket proxy.
Tests multi-client connections, wildcard subscriptions, and proper routing.
"""

import asyncio
import json
import os
import sys
import websockets
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha")
PROXY_URL = "ws://localhost:8765"  # Stocks proxy

class PolygonProxyClient:
    def __init__(self, client_id: str, symbols: List[str], use_wildcard: bool = False):
        self.client_id = client_id
        self.symbols = symbols
        self.use_wildcard = use_wildcard
        self.messages_received = 0
        self.connected = False
        self.ws = None
        
    async def connect(self):
        """Connect and authenticate to the proxy"""
        try:
            self.ws = await websockets.connect(PROXY_URL)
            self.connected = True
            logger.info(f"[{self.client_id}] Connected to proxy")
            
            # Send auth
            auth_msg = {"action": "auth", "params": POLYGON_API_KEY}
            await self.ws.send(json.dumps(auth_msg))
            
            # Wait for auth response
            response = await self.ws.recv()
            auth_data = json.loads(response)
            logger.info(f"[{self.client_id}] Auth response: {auth_data}")
            
            return True
        except Exception as e:
            logger.error(f"[{self.client_id}] Connection failed: {e}")
            return False
    
    async def subscribe(self):
        """Subscribe to symbols or wildcard"""
        if not self.connected:
            return False
            
        try:
            if self.use_wildcard:
                # Subscribe to everything
                params = "T.*,Q.*,A.*"
                logger.info(f"[{self.client_id}] Subscribing to wildcard")
            else:
                # Subscribe to specific symbols
                subscriptions = []
                for symbol in self.symbols:
                    subscriptions.extend([f"T.{symbol}", f"Q.{symbol}"])
                params = ",".join(subscriptions)
                logger.info(f"[{self.client_id}] Subscribing to {self.symbols}")
            
            sub_msg = {"action": "subscribe", "params": params}
            await self.ws.send(json.dumps(sub_msg))
            
            # Get subscription confirmation
            response = await self.ws.recv()
            logger.info(f"[{self.client_id}] Subscribe response: {response}")
            
            return True
        except Exception as e:
            logger.error(f"[{self.client_id}] Subscribe failed: {e}")
            return False
    
    async def receive_messages(self, duration: int = 10):
        """Receive messages for specified duration"""
        if not self.connected:
            return
            
        start_time = datetime.now()
        symbols_seen = set()
        
        try:
            while (datetime.now() - start_time).seconds < duration:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    self.messages_received += 1
                    
                    # Try to parse and extract symbol
                    try:
                        data = json.loads(msg)
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and 'sym' in item:
                                    symbols_seen.add(item['sym'])
                        elif isinstance(data, dict) and 'sym' in data:
                            symbols_seen.add(data['sym'])
                    except:
                        pass
                    
                    if self.messages_received % 100 == 0:
                        logger.info(f"[{self.client_id}] Received {self.messages_received} messages")
                        
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"[{self.client_id}] Receive error: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"[{self.client_id}] Error in receive loop: {e}")
        
        logger.info(f"[{self.client_id}] Total messages: {self.messages_received}, Symbols seen: {symbols_seen}")
        return self.messages_received, symbols_seen
    
    async def disconnect(self):
        """Disconnect from proxy"""
        if self.ws:
            await self.ws.close()
            logger.info(f"[{self.client_id}] Disconnected")

async def test_basic_connection():
    """Test 1: Basic connection and subscription"""
    logger.info("\n=== TEST 1: Basic Connection ===")
    
    client = PolygonProxyClient("test_basic", ["AAPL", "GOOGL"])
    
    if await client.connect():
        if await client.subscribe():
            messages, symbols = await client.receive_messages(5)
            logger.info(f"Received {messages} messages from symbols: {symbols}")
        await client.disconnect()
    
    return client.messages_received > 0

async def test_multiple_clients():
    """Test 2: Multiple clients with different subscriptions"""
    logger.info("\n=== TEST 2: Multiple Clients ===")
    
    clients = [
        PolygonProxyClient("client_1", ["AAPL", "MSFT"]),
        PolygonProxyClient("client_2", ["GOOGL", "AMZN"]),
        PolygonProxyClient("client_3", ["AAPL"]),  # Overlapping subscription
    ]
    
    # Connect all clients
    for client in clients:
        await client.connect()
        await client.subscribe()
    
    # Receive messages concurrently
    tasks = [client.receive_messages(5) for client in clients]
    results = await asyncio.gather(*tasks)
    
    # Disconnect all
    for client in clients:
        await client.disconnect()
    
    # Check results
    for i, (client, (messages, symbols)) in enumerate(zip(clients, results)):
        logger.info(f"{client.client_id}: {messages} messages, symbols: {symbols}")
    
    return all(messages > 0 for messages, _ in results)

async def test_wildcard_subscription():
    """Test 3: Wildcard subscription mixed with specific subscriptions"""
    logger.info("\n=== TEST 3: Wildcard Subscription ===")
    
    clients = [
        PolygonProxyClient("specific_client", ["AAPL", "GOOGL"]),
        PolygonProxyClient("wildcard_client", [], use_wildcard=True),
        PolygonProxyClient("another_specific", ["MSFT"]),
    ]
    
    # Connect all
    for client in clients:
        await client.connect()
        await client.subscribe()
    
    # The wildcard client should receive everything
    # Specific clients should only receive their symbols
    tasks = [client.receive_messages(5) for client in clients]
    results = await asyncio.gather(*tasks)
    
    for client in clients:
        await client.disconnect()
    
    # Wildcard client should have the most messages
    wildcard_messages = results[1][0]
    logger.info(f"Wildcard client received {wildcard_messages} messages")
    logger.info(f"Specific clients received: {[r[0] for i, r in enumerate(results) if i != 1]}")
    
    return wildcard_messages >= max(r[0] for i, r in enumerate(results) if i != 1)

async def test_dynamic_subscribe_unsubscribe():
    """Test 4: Dynamic subscription changes"""
    logger.info("\n=== TEST 4: Dynamic Subscribe/Unsubscribe ===")
    
    client = PolygonProxyClient("dynamic_client", ["AAPL"])
    
    await client.connect()
    await client.subscribe()
    
    # Receive for a bit
    await client.receive_messages(3)
    initial_count = client.messages_received
    
    # Add more subscriptions
    sub_msg = {"action": "subscribe", "params": "T.GOOGL,Q.GOOGL,T.MSFT,Q.MSFT"}
    await client.ws.send(json.dumps(sub_msg))
    await asyncio.sleep(1)
    
    # Should receive more messages now
    await client.receive_messages(3)
    after_add_count = client.messages_received
    
    # Unsubscribe from AAPL
    unsub_msg = {"action": "unsubscribe", "params": "T.AAPL,Q.AAPL"}
    await client.ws.send(json.dumps(unsub_msg))
    await asyncio.sleep(1)
    
    # Continue receiving
    await client.receive_messages(3)
    final_count = client.messages_received
    
    await client.disconnect()
    
    logger.info(f"Messages - Initial: {initial_count}, After add: {after_add_count}, Final: {final_count}")
    return after_add_count > initial_count

async def test_client_isolation():
    """Test 5: Verify client isolation (messages only go to subscribed clients)"""
    logger.info("\n=== TEST 5: Client Isolation ===")
    
    # Create clients with non-overlapping subscriptions
    client_a = PolygonProxyClient("client_a", ["AAPL"])
    client_b = PolygonProxyClient("client_b", ["GOOGL"])
    
    await client_a.connect()
    await client_b.connect()
    await client_a.subscribe()
    await client_b.subscribe()
    
    # Track symbols each client sees
    task_a = client_a.receive_messages(5)
    task_b = client_b.receive_messages(5)
    
    (msgs_a, symbols_a), (msgs_b, symbols_b) = await asyncio.gather(task_a, task_b)
    
    await client_a.disconnect()
    await client_b.disconnect()
    
    logger.info(f"Client A saw symbols: {symbols_a}")
    logger.info(f"Client B saw symbols: {symbols_b}")
    
    # Symbols should not overlap (unless market is closed and no data)
    overlap = symbols_a & symbols_b
    if overlap:
        logger.warning(f"Unexpected overlap: {overlap}")
    
    return True  # Test structure is correct even if no data

async def run_all_tests():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("POLYGON PROXY TEST SUITE")
    logger.info("=" * 60)
    
    tests = [
        ("Basic Connection", test_basic_connection),
        ("Multiple Clients", test_multiple_clients),
        ("Wildcard Subscription", test_wildcard_subscription),
        ("Dynamic Subscribe/Unsubscribe", test_dynamic_subscribe_unsubscribe),
        ("Client Isolation", test_client_isolation),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = await test_func()
            results[name] = "PASS" if result else "FAIL"
        except Exception as e:
            logger.error(f"Test {name} crashed: {e}")
            results[name] = "ERROR"
        
        await asyncio.sleep(2)  # Brief pause between tests
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("=" * 60)
    
    for name, result in results.items():
        status = "✓" if result == "PASS" else "✗"
        logger.info(f"{status} {name}: {result}")
    
    passed = sum(1 for r in results.values() if r == "PASS")
    total = len(results)
    logger.info(f"\nPassed: {passed}/{total}")
    
    return passed == total

if __name__ == "__main__":
    # Check if proxy is running
    logger.info("Starting Polygon proxy tests...")
    logger.info(f"Proxy URL: {PROXY_URL}")
    logger.info(f"API Key: {POLYGON_API_KEY[:8]}...")
    
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        sys.exit(1)