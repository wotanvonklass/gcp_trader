#!/usr/bin/env python3
"""
Test script for trade notifications via GCP Cloud Monitoring

This script sends a test trade notification to Pub/Sub which triggers
an email alert via GCP Cloud Monitoring.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.trade_notifier import get_trade_notifier

def test_trade_notification():
    """Send a test trade notification"""
    print("=" * 60)
    print("Testing Trade Notification via GCP Cloud Monitoring")
    print("=" * 60)
    print()

    # Get trade notifier
    notifier = get_trade_notifier()

    if not notifier.enabled:
        print("❌ Trade notifier is disabled")
        print("   Check that ENABLE_TRADE_NOTIFICATIONS=true in .env")
        return False

    print(f"✓ Trade notifier enabled")
    print(f"✓ Publishing to: {notifier.topic_path}")
    print()

    # Send test BUY notification
    print("Sending TEST BUY notification...")
    notifier.notify_trade(
        side='BUY',
        ticker='TSLA',
        quantity=100,
        price=389.50,
        order_id='test-order-12345-buy',
        news_headline='TEST: This is a test trade notification from news-trader',
        strategy_id='test-strategy-001'
    )

    print()
    print("✅ Test BUY notification sent!")
    print()

    # Send test SELL notification
    print("Sending TEST SELL notification...")
    notifier.notify_trade(
        side='SELL',
        ticker='TSLA',
        quantity=100,
        price=392.75,
        order_id='test-order-12345-sell',
        news_headline='TEST: This is a test trade notification from news-trader',
        strategy_id='test-strategy-001'
    )

    print()
    print("✅ Test SELL notification sent!")
    print()
    print("=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print()
    print("1. Check your email (v.onklass@gmail.com)")
    print("   You should receive 2 alerts from GCP Cloud Monitoring")
    print()
    print("2. View alerts in GCP Console:")
    print("   https://console.cloud.google.com/monitoring/alerting?project=gnw-trader")
    print()
    print("3. View Pub/Sub messages:")
    print("   https://console.cloud.google.com/cloudpubsub/topic/detail/alpaca-trades?project=gnw-trader")
    print()

    return True

if __name__ == "__main__":
    success = test_trade_notification()
    sys.exit(0 if success else 1)
