#!/usr/bin/env python3
"""
Test script for Alpaca health check.
Run this on the VM to verify health checks work correctly.
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

# Add news-trader to path
news_trader_path = "/opt/news-trader"
if os.path.exists(news_trader_path) and news_trader_path not in sys.path:
    sys.path.insert(0, news_trader_path)

from utils.alpaca_health import check_alpaca_health, log_health_check, require_healthy_alpaca

def main():
    print("=" * 60)
    print("ALPACA HEALTH CHECK TEST")
    print("=" * 60)
    print()

    # Get credentials from environment
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        print("❌ Error: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        print("   Load .env file or export them first")
        sys.exit(1)

    print(f"API Key: {api_key[:10]}...")
    print()

    # Test 1: check_alpaca_health() - non-blocking
    print("TEST 1: check_alpaca_health() - Non-blocking check")
    print("-" * 60)
    result = check_alpaca_health(api_key, secret_key)
    log_health_check(result)
    print()

    # Test 2: require_healthy_alpaca() - blocking (raises on failure)
    print("TEST 2: require_healthy_alpaca() - Startup check (fail-fast)")
    print("-" * 60)
    try:
        account_info = require_healthy_alpaca(api_key, secret_key)
        print(f"✅ Success - Account ready to trade")
        print()
    except RuntimeError as e:
        print(f"❌ Would fail startup: {e}")
        print()
        sys.exit(1)

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)

if __name__ == "__main__":
    main()
