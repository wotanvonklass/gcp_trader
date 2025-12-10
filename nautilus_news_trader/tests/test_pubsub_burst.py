#!/usr/bin/env python3
"""
Test script to reproduce Pub/Sub message loss issue.

Publishes N messages in rapid succession and checks if all strategies receive them.

Usage:
    python tests/test_pubsub_burst.py -n 30    # Publish 30 messages
    python tests/test_pubsub_burst.py --check  # Check logs for received messages
"""

import os
import sys
import json
import argparse
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gnw-trader")
PUBSUB_TOPIC = "benzinga-news"

# Test batch ID to correlate messages
BATCH_ID = datetime.now(timezone.utc).strftime("%H%M%S")


def publish_burst(n_messages: int, delay_ms: int = 0):
    """Publish N messages in rapid succession."""
    now = datetime.now(timezone.utc)
    published_ids = []

    print(f"Publishing {n_messages} messages (batch: {BATCH_ID})...")
    print(f"Delay between messages: {delay_ms}ms")
    print()

    for i in range(n_messages):
        # Generate unique test ID
        msg_id = f"BURST_{BATCH_ID}_{i:03d}"
        ticker = f"TST{i:02d}"  # Fake tickers TST00, TST01, etc.

        news = {
            "id": msg_id,
            "headline": f"[TEST] Burst test message {i+1}/{n_messages} - {msg_id}",
            "tickers": [ticker],
            "source": "BurstTest",
            "url": f"https://test.example.com/burst/{msg_id}",
            "tags": ["Test", "Burst"],
            "time": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "capturedAt": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }

        # Publish via gcloud
        message_json = json.dumps(news)
        cmd = [
            "gcloud", "pubsub", "topics", "publish", PUBSUB_TOPIC,
            f"--project={GCP_PROJECT_ID}",
            f"--message={message_json}"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  [{i+1:3d}/{n_messages}] Published {msg_id}")
            published_ids.append(msg_id)
        else:
            print(f"  [{i+1:3d}/{n_messages}] FAILED: {result.stderr}")

        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    print()
    print(f"Published {len(published_ids)}/{n_messages} messages")
    print(f"Batch ID: {BATCH_ID}")
    print()
    print("Wait 10-15 seconds, then run with --check to verify reception:")
    print(f"  python tests/test_pubsub_burst.py --check --batch {BATCH_ID}")

    return published_ids


def check_reception(batch_id: str):
    """Check which strategies received the burst messages."""
    print(f"Checking reception for batch: {batch_id}")
    print()

    strategies = ["volume_5pct", "volume_10pct", "trend"]

    for strategy in strategies:
        cmd = f'grep "BURST_{batch_id}" /opt/news-trader/runner/{strategy}/logs/*.log 2>/dev/null | grep Processing | wc -l'
        result = subprocess.run(
            ["gcloud", "compute", "ssh", "news-trader", "--zone=us-east4-a", "--", cmd],
            capture_output=True, text=True
        )
        count = result.stdout.strip().split()[-1] if result.stdout else "0"
        print(f"  {strategy}: {count} messages received")

    print()

    # Get detailed breakdown
    print("Detailed message IDs per strategy:")
    for strategy in strategies:
        cmd = f'grep "BURST_{batch_id}" /opt/news-trader/runner/{strategy}/logs/*.log 2>/dev/null | grep Processing | sed "s/.*\\[/[/" | cut -d"]" -f1 | sort'
        result = subprocess.run(
            ["gcloud", "compute", "ssh", "news-trader", "--zone=us-east4-a", "--", cmd],
            capture_output=True, text=True
        )
        ids = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        print(f"\n  {strategy} ({len(ids)} messages):")
        for msg_id in ids[:10]:
            print(f"    {msg_id}")
        if len(ids) > 10:
            print(f"    ... and {len(ids) - 10} more")


def main():
    parser = argparse.ArgumentParser(description="Test Pub/Sub burst message handling")
    parser.add_argument("-n", "--count", type=int, default=30, help="Number of messages to publish")
    parser.add_argument("--delay", type=int, default=0, help="Delay between messages in milliseconds")
    parser.add_argument("--check", action="store_true", help="Check reception instead of publishing")
    parser.add_argument("--batch", type=str, help="Batch ID to check (required with --check)")
    args = parser.parse_args()

    print("=" * 60)
    print("PUB/SUB BURST TEST")
    print("=" * 60)
    print()

    if args.check:
        if not args.batch:
            print("ERROR: --batch required with --check")
            sys.exit(1)
        check_reception(args.batch)
    else:
        publish_burst(args.count, args.delay)


if __name__ == "__main__":
    main()
