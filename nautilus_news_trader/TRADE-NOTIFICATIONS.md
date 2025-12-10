# Trade Notifications via GCP Cloud Monitoring

## Overview

This system sends email notifications to **v.onklass@gmail.com** for every Alpaca trade executed by the news-trader bot using GCP Cloud Monitoring infrastructure.

## Architecture (KISS)

```
NewsVolumeStrategy (BUY/SELL order)
          ↓
   trade_notifier.py
          ↓
   Pub/Sub Topic: alpaca-trades
          ↓
   GCP Cloud Monitoring Alert Policy
          ↓
   Email: v.onklass@gmail.com
```

**Why This is Simple:**
- Uses existing GCP infrastructure (already configured for benzinga-scraper)
- No Gmail SMTP passwords needed
- No external dependencies
- Centralized alert management in GCP Console
- Easy to add SMS, Slack, PagerDuty later

---

## What Was Implemented

### 1. Pub/Sub Topic
**Topic:** `alpaca-trades`
- Receives JSON trade events
- Project: gnw-trader

### 2. Trade Notifier Utility
**File:** `/news-trader/utils/trade_notifier.py`
- Publishes trade events to Pub/Sub
- Auto-initialized in NewsVolumeStrategy
- Can be disabled via environment variable

### 3. Strategy Integration
**File:** `/news-trader/strategies/news_volume_strategy.py`
- Sends notification after BUY order (line ~140)
- Sends notification after SELL order (line ~217)
- Includes: ticker, quantity, price, order ID, news headline

### 4. GCP Alert Policy
**Name:** "Alpaca Trade Executed"
- Triggers on ANY message to alpaca-trades topic
- Sends email immediately
- Auto-closes alert after 5 minutes

### 5. Setup Script
**File:** `/news-trader/setup-trade-monitoring.sh`
- Creates Pub/Sub topic
- Creates/reuses notification channel
- Creates alert policy
- Run once to set up

---

## Email Format

You'll receive emails like:

```
Subject: Alpaca Trade Executed

Trade published to Pub/Sub

🤖 Alpaca trade executed!

Check Pub/Sub topic 'alpaca-trades' for trade details.

View in console:
https://console.cloud.google.com/cloudpubsub/topic/detail/alpaca-trades?project=gnw-trader
```

---

## Configuration

### Environment Variables

Add to `/news-trader/.env`:

```bash
# Trade Notifications (defaults to enabled)
ENABLE_TRADE_NOTIFICATIONS=true
```

**Note:** No Gmail credentials needed! Uses GCP service account automatically.

---

## Testing

### Manual Test (Using gcloud CLI)

```bash
gcloud pubsub topics publish alpaca-trades --project=gnw-trader \
  --message='{"side":"BUY","ticker":"TSLA","quantity":100,"price":389.50,"order_id":"test-12345"}'
```

Expected: Email arrives within 1-2 minutes

### Test with News-Trader

The trade notifier is automatically called when:
1. BUY order is placed (entry)
2. SELL order is placed (exit after 7 minutes)

---

## Monitoring & Management

### View Alerts in GCP Console

https://console.cloud.google.com/monitoring/alerting?project=gnw-trader

### View Pub/Sub Messages

https://console.cloud.google.com/cloudpubsub/topic/detail/alpaca-trades?project=gnw-trader

### View Notification Channels

https://console.cloud.google.com/monitoring/alerting/notifications?project=gnw-trader

### Disable Notifications

**Temporarily:** Set `ENABLE_TRADE_NOTIFICATIONS=false` in `.env`

**Permanently:** Delete alert policy:
```bash
gcloud alpha monitoring policies list --project=gnw-trader --filter="displayName='Alpaca Trade Executed'"
gcloud alpha monitoring policies delete POLICY_NAME --project=gnw-trader
```

---

## Trade Event Schema

Each Pub/Sub message contains:

```json
{
  "side": "BUY" | "SELL",
  "ticker": "TSLA",
  "quantity": 100,
  "price": 389.50,
  "total_value": 38950.00,
  "order_id": "a8f3d9e1-...",
  "timestamp": "2025-11-23T12:00:00",
  "strategy_id": "news-tsla-123",
  "news_headline": "Tesla announces new battery technology..."
}
```

---

## Extending Notifications

### Add Slack Alerts

1. Create Slack webhook: https://api.slack.com/messaging/webhooks
2. Add notification channel:
```bash
gcloud alpha monitoring channels create \
  --display-name="Trade Alerts Slack" \
  --type=slack \
  --channel-labels=url=YOUR_WEBHOOK_URL \
  --project=gnw-trader
```
3. Add channel to alert policy in GCP Console

### Add SMS Alerts

1. Get notification channel ID:
```bash
gcloud alpha monitoring channels list --project=gnw-trader
```
2. Update alert policy to include SMS channel

### Rate Limiting

Current settings:
- **Alert Rate Limit:** 1 alert per 60 seconds
- **Auto-Close:** 5 minutes

To change, edit alert policy in GCP Console.

---

## Costs

**Current:** $0/month (within free tier)

**Free Tier Limits:**
- Pub/Sub: First 10 GB/month free
- Cloud Monitoring: First 150 MB metrics/month free
- Email notifications: Unlimited

**With Heavy Trading (1000 trades/day):**
- Pub/Sub: ~$0.01/month
- Still within free tier

---

## Troubleshooting

### No Emails Arriving

1. **Check alert policy is enabled:**
```bash
gcloud alpha monitoring policies list --project=gnw-trader \
  --filter="displayName='Alpaca Trade Executed'"
```

2. **Verify notification channel:**
```bash
gcloud alpha monitoring channels list --project=gnw-trader
```

3. **Check spam folder** for v.onklass@gmail.com

4. **Test Pub/Sub directly:**
```bash
gcloud pubsub topics publish alpaca-trades --project=gnw-trader \
  --message='{"side":"TEST","ticker":"TSLA","order_id":"manual-test"}'
```

### Trade Notifier Not Working

1. **Check logs:**
```python
# In news-trader code, notifier logs:
# "✓ Trade notifier initialized: projects/gnw-trader/topics/alpaca-trades"
# "✅ Trade notification sent: BUY 100 TSLA @ $389.50"
```

2. **Verify environment variable:**
```bash
echo $ENABLE_TRADE_NOTIFICATIONS  # Should be 'true'
```

3. **Check Pub/Sub permissions:**
```bash
gcloud pubsub topics get-iam-policy alpaca-trades --project=gnw-trader
```

### Messages Published But No Alerts

1. **Check alert policy condition:** Must be set to `> 0` for immediate alerts
2. **Check alert rate limiting:** May be suppressing frequent alerts
3. **View alert history:** GCP Console → Monitoring → Alerting → Incidents

---

## Files Created/Modified

### Created:
- `/news-trader/utils/trade_notifier.py` - Pub/Sub publisher
- `/news-trader/setup-trade-monitoring.sh` - GCP setup script
- `/news-trader/test_trade_notification.py` - Test script (optional)
- `/news-trader/TRADE-NOTIFICATIONS.md` - This file

### Modified:
- `/news-trader/strategies/news_volume_strategy.py` - Added notifications

---

## Next Steps

1. ✅ Trade notifications are configured
2. ⏭️ Deploy news-trader to GCP VM (if not already)
3. ⏭️ Wait for next news event to trigger a trade
4. ⏭️ Verify email arrives for both BUY and SELL orders
5. ⏭️ (Optional) Add Slack/SMS notifications

---

## Support

**View GCP Monitoring Docs:**
https://cloud.google.com/monitoring/docs

**View Pub/Sub Docs:**
https://cloud.google.com/pubsub/docs

**Contact:**
Notifications go to v.onklass@gmail.com
