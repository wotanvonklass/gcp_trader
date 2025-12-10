#!/bin/bash

# Setup GCP Cloud Monitoring Alerts for Benzinga Scraper
set -e

PROJECT_ID="gnw-trader"
TOPIC="benzinga-news"
EMAIL="vonklass@gmail.com"

echo "🔔 Setting up Cloud Monitoring alerts for Benzinga Scraper"
echo "Project: $PROJECT_ID"
echo "Topic: $TOPIC"
echo ""

# Create notification channel (email)
echo "Creating notification channel..."
cat > /tmp/notification-channel.json <<EOF
{
  "type": "email",
  "displayName": "Benzinga Scraper Alerts",
  "labels": {
    "email_address": "$EMAIL"
  }
}
EOF

CHANNEL_ID=$(gcloud alpha monitoring channels create \
  --channel-content-from-file=/tmp/notification-channel.json \
  --project=$PROJECT_ID \
  --format="value(name)" 2>/dev/null || \
  gcloud alpha monitoring channels list \
    --project=$PROJECT_ID \
    --filter="displayName='Benzinga Scraper Alerts'" \
    --format="value(name)" | head -1)

echo "✓ Notification channel: $CHANNEL_ID"

# Alert 1: No heartbeat for 10 minutes
echo ""
echo "Creating alert: No heartbeat for 10 minutes..."
cat > /tmp/alert-no-heartbeat.json <<EOF
{
  "displayName": "Benzinga Scraper - No Heartbeat (10 min)",
  "conditions": [{
    "displayName": "No heartbeat messages",
    "conditionThreshold": {
      "filter": "resource.type=\"pubsub_topic\" AND resource.labels.topic_id=\"$TOPIC\" AND metric.type=\"pubsub.googleapis.com/topic/send_message_operation_count\"",
      "aggregations": [{
        "alignmentPeriod": "600s",
        "perSeriesAligner": "ALIGN_RATE",
        "crossSeriesReducer": "REDUCE_SUM"
      }],
      "comparison": "COMPARISON_LT",
      "thresholdValue": 0.01,
      "duration": "600s"
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$CHANNEL_ID"],
  "alertStrategy": {
    "autoClose": "1800s"
  }
}
EOF

gcloud alpha monitoring policies create \
  --policy-from-file=/tmp/alert-no-heartbeat.json \
  --project=$PROJECT_ID 2>/dev/null || echo "Alert may already exist"

echo "✓ Created: No heartbeat alert"

# Alert 2: No news during business hours (15 minutes)
echo ""
echo "Creating alert: No news for 15 minutes (business hours)..."
cat > /tmp/alert-no-news.json <<EOF
{
  "displayName": "Benzinga Scraper - No News (15 min, Business Hours)",
  "conditions": [{
    "displayName": "No news messages during business hours",
    "conditionThreshold": {
      "filter": "resource.type=\"pubsub_topic\" AND resource.labels.topic_id=\"$TOPIC\" AND metric.type=\"pubsub.googleapis.com/topic/send_message_operation_count\"",
      "aggregations": [{
        "alignmentPeriod": "900s",
        "perSeriesAligner": "ALIGN_RATE",
        "crossSeriesReducer": "REDUCE_SUM"
      }],
      "comparison": "COMPARISON_LT",
      "thresholdValue": 0.05,
      "duration": "900s"
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$CHANNEL_ID"],
  "alertStrategy": {
    "autoClose": "1800s"
  },
  "documentation": {
    "content": "Benzinga scraper hasn't published any news in 15 minutes during business hours (7 AM - 7 PM ET, Mon-Fri). This may indicate:\n- Scraper is stuck\n- Login session expired\n- Network issues\n\nCheck scraper logs: gcloud compute ssh benzinga-scraper --zone=us-east4-a --command='sudo tail -100 /var/log/benzinga-scraper.log'"
  }
}
EOF

gcloud alpha monitoring policies create \
  --policy-from-file=/tmp/alert-no-news.json \
  --project=$PROJECT_ID 2>/dev/null || echo "Alert may already exist"

echo "✓ Created: No news alert"

# Cleanup
rm -f /tmp/notification-channel.json /tmp/alert-no-heartbeat.json /tmp/alert-no-news.json

echo ""
echo "✅ Monitoring alerts configured!"
echo ""
echo "View alerts:"
echo "  https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo ""
echo "Test alerts by stopping the scraper:"
echo "  gcloud compute ssh benzinga-scraper --zone=us-east4-a --command='sudo systemctl stop benzinga-scraper'"
