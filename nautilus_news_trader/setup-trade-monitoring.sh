#!/bin/bash

# Setup GCP Cloud Monitoring for Alpaca Trade Notifications
set -e

PROJECT_ID="gnw-trader"
TRADE_TOPIC="alpaca-trades"
EMAIL="v.onklass@gmail.com"

echo "🔔 Setting up trade notifications via GCP Cloud Monitoring"
echo "Project: $PROJECT_ID"
echo "Topic: $TRADE_TOPIC"
echo ""

# Create Pub/Sub topic for trade events
echo "Creating Pub/Sub topic: $TRADE_TOPIC..."
gcloud pubsub topics create $TRADE_TOPIC --project=$PROJECT_ID 2>/dev/null || echo "✓ Topic already exists"

# Get or create notification channel
echo ""
echo "Getting notification channel..."
CHANNEL_ID=$(gcloud alpha monitoring channels list \
    --project=$PROJECT_ID \
    --filter="labels.email_address='$EMAIL'" \
    --format="value(name)" | head -1)

if [ -z "$CHANNEL_ID" ]; then
    echo "Creating notification channel for $EMAIL..."
    cat > /tmp/notification-channel.json <<EOF
{
  "type": "email",
  "displayName": "Trade Alerts",
  "labels": {
    "email_address": "$EMAIL"
  }
}
EOF

    CHANNEL_ID=$(gcloud alpha monitoring channels create \
      --channel-content-from-file=/tmp/notification-channel.json \
      --project=$PROJECT_ID \
      --format="value(name)")

    rm -f /tmp/notification-channel.json
fi

echo "✓ Notification channel: $CHANNEL_ID"

# Alert: Email on EVERY trade execution
echo ""
echo "Creating alert: Email on every trade..."
cat > /tmp/alert-trade-executed.json <<EOF
{
  "displayName": "Alpaca Trade Executed",
  "conditions": [{
    "displayName": "Trade published to Pub/Sub",
    "conditionThreshold": {
      "filter": "resource.type=\"pubsub_topic\" AND resource.labels.topic_id=\"$TRADE_TOPIC\" AND metric.type=\"pubsub.googleapis.com/topic/send_message_operation_count\"",
      "aggregations": [{
        "alignmentPeriod": "60s",
        "perSeriesAligner": "ALIGN_RATE"
      }],
      "comparison": "COMPARISON_GT",
      "thresholdValue": 0,
      "duration": "0s"
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$CHANNEL_ID"],
  "alertStrategy": {
    "autoClose": "300s",
    "notificationRateLimit": {
      "period": "60s"
    }
  },
  "documentation": {
    "content": "🤖 Alpaca trade executed!\n\nCheck Pub/Sub topic '$TRADE_TOPIC' for trade details.\n\nView in console:\nhttps://console.cloud.google.com/cloudpubsub/topic/detail/$TRADE_TOPIC?project=$PROJECT_ID"
  }
}
EOF

gcloud alpha monitoring policies create \
  --policy-from-file=/tmp/alert-trade-executed.json \
  --project=$PROJECT_ID 2>/dev/null || echo "✓ Alert policy may already exist"

echo "✓ Created: Trade execution alert"

# Cleanup
rm -f /tmp/alert-trade-executed.json

echo ""
echo "✅ Trade monitoring configured!"
echo ""
echo "View alerts:"
echo "  https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo ""
echo "View trade events:"
echo "  https://console.cloud.google.com/cloudpubsub/topic/detail/$TRADE_TOPIC?project=$PROJECT_ID"
echo ""
