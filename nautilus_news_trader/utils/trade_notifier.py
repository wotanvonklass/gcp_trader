#!/usr/bin/env python3
"""
Trade Notification via GCP Cloud Monitoring
Publishes trade events to Pub/Sub which triggers email alerts
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional
from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)


class TradeNotifier:
    """Publishes trade events to GCP Pub/Sub for email alerting"""

    def __init__(self, project_id: str = "gnw-trader", topic_id: str = "alpaca-trades"):
        self.enabled = os.getenv('ENABLE_TRADE_NOTIFICATIONS', 'true').lower() == 'true'
        self.project_id = project_id
        self.topic_id = topic_id

        if self.enabled:
            try:
                self.publisher = pubsub_v1.PublisherClient()
                self.topic_path = self.publisher.topic_path(project_id, topic_id)
                logger.info(f"✓ Trade notifier initialized: {self.topic_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize trade notifier: {e}")
                self.enabled = False

    def notify_trade(
        self,
        side: str,  # 'BUY' or 'SELL'
        ticker: str,
        quantity: int,
        price: float,
        order_id: str,
        news_headline: Optional[str] = None,
        strategy_id: Optional[str] = None
    ):
        """
        Publish trade event to Pub/Sub
        This triggers a GCP alert which emails v.onklass@gmail.com
        """
        if not self.enabled:
            return

        try:
            # Create structured trade event
            trade_event = {
                "side": side,
                "ticker": ticker,
                "quantity": quantity,
                "price": round(price, 2),
                "total_value": round(quantity * price, 2),
                "order_id": order_id,
                "timestamp": datetime.now().isoformat(),
                "strategy_id": strategy_id or "unknown",
                "news_headline": news_headline[:100] if news_headline else None
            }

            # Publish to Pub/Sub
            message_data = json.dumps(trade_event).encode('utf-8')
            future = self.publisher.publish(self.topic_path, message_data)
            future.result()  # Wait for publish to complete

            logger.info(
                f"✅ Trade notification sent: {side} {quantity} {ticker} @ ${price:.2f} "
                f"(Order: {order_id[:8]}...)"
            )

        except Exception as e:
            logger.error(f"❌ Failed to send trade notification: {e}")


# Singleton instance
_notifier = None

def get_trade_notifier() -> TradeNotifier:
    """Get or create the global trade notifier instance"""
    global _notifier
    if _notifier is None:
        _notifier = TradeNotifier()
    return _notifier
