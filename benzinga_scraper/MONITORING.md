# Monitoring Benzinga News

This guide shows you how to view news that has been processed and published to Pub/Sub.

## Quick Start

### View Recent News Messages

```bash
# View last 10 messages
./monitor-news.sh

# View last 20 messages
./monitor-news.sh 20

# Continuous monitoring (updates every 5 seconds)
./monitor-news.sh --continuous
```

### View Scraper Logs

```bash
# View recent logs
./view-logs.sh

# View only news-related logs
./view-logs.sh --news

# View errors only
./view-logs.sh --errors

# Tail logs in real-time
./view-logs.sh --tail
```

## Method 1: Pull from Pub/Sub Subscription

Your topic `benzinga-news` has 3 subscriptions:
- `benzinga-news-trader` - Main trading subscription
- `benzinga-news-monitor` - Monitoring subscription (safe to pull from)
- `benzinga-news-sub` - General subscription

### Manual Pull (Command Line)

```bash
# Pull 10 messages
gcloud pubsub subscriptions pull benzinga-news-monitor \
    --project=gnw-trader \
    --limit=10 \
    --format=json | jq -r '.[] | .message.data' | base64 --decode | jq '.'
```

### Example Output

```json
{
  "id": "test-tsla-002",
  "headline": "Tesla Reports Strong Earnings Beat, Upgrades Full-Year Guidance",
  "tickers": ["TSLA"],
  "source": "test",
  "capturedAt": "2025-11-21T19:17:34Z"
}
```

## Method 2: Cloud Logging (GCP Console)

### Via Web Console

1. Go to [Cloud Logging](https://console.cloud.google.com/logs/query?project=gnw-trader)
2. Use this query:
   ```
   resource.type="gce_instance"
   textPayload:"NEWS"
   ```
3. Adjust time range as needed

### Via gcloud CLI

```bash
# View logs with news
gcloud logging read 'resource.type="gce_instance" AND textPayload:"NEWS"' \
    --project=gnw-trader \
    --limit=20 \
    --format=json | jq -r '.[].textPayload'

# View all scraper logs
gcloud logging read 'resource.type="gce_instance"' \
    --project=gnw-trader \
    --limit=50

# Tail logs in real-time
gcloud logging tail --project=gnw-trader
```

## Method 3: Check Running Scraper

If your scraper is running on a VM:

```bash
# SSH into the VM
gcloud compute ssh benzinga-scraper --zone=us-east4-a --project=gnw-trader

# View Docker logs (if using Docker deployment)
sudo docker logs -f benzinga-scraper

# View systemd logs (if using native deployment)
sudo journalctl -u benzinga-scraper -f
```

## Method 4: Export to BigQuery (For Historical Analysis)

To keep a permanent record of all news, set up a BigQuery export:

```bash
# Create BigQuery dataset
bq --project=gnw-trader mk benzinga_data

# Create table
bq --project=gnw-trader mk \
    --table benzinga_data.news \
    id:STRING,headline:STRING,tickers:STRING,source:STRING,capturedAt:TIMESTAMP

# Create Pub/Sub subscription with BigQuery sink
gcloud pubsub subscriptions create benzinga-news-bigquery \
    --topic=benzinga-news \
    --project=gnw-trader \
    --bigquery-table=gnw-trader:benzinga_data.news
```

Then query historical data:

```sql
SELECT *
FROM `gnw-trader.benzinga_data.news`
WHERE capturedAt > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
ORDER BY capturedAt DESC
LIMIT 100;
```

## Method 5: View in Pub/Sub Console

1. Go to [Pub/Sub Topics](https://console.cloud.google.com/cloudpubsub/topic/list?project=gnw-trader)
2. Click on `benzinga-news` topic
3. Go to "Messages" tab
4. Click "Pull" to manually pull messages

## Important Notes

### Message Retention

- **Pub/Sub**: Messages are retained for 7 days by default (configurable up to 31 days)
- **Cloud Logging**: Logs are retained for 30 days by default (configurable)
- **Once a message is acknowledged**, it's deleted from Pub/Sub

### Subscriptions

- `benzinga-news-monitor` is safe to pull from for monitoring
- Be careful with `benzinga-news-trader` - pulling from it may consume messages needed by your trading system
- Messages pulled without `--auto-ack` remain in the subscription

### Best Practices

1. **For Real-Time Monitoring**: Use `./monitor-news.sh --continuous`
2. **For Historical Analysis**: Use Cloud Logging or set up BigQuery export
3. **For Production**: Don't rely on pulling messages - use push subscriptions or Cloud Functions
4. **For Debugging**: Use `./view-logs.sh --tail` to see what the scraper is doing

## Troubleshooting

### No Messages Appearing

1. Check if scraper is running:
   ```bash
   gcloud compute instances list --project=gnw-trader
   ```

2. Check scraper logs:
   ```bash
   ./view-logs.sh --tail
   ```

3. Check if messages are being published:
   ```bash
   gcloud pubsub topics describe benzinga-news --project=gnw-trader
   ```

### Messages Already Consumed

If you're not seeing messages, they may have already been acknowledged by another subscriber. Check:

```bash
# See subscription metrics
gcloud pubsub subscriptions describe benzinga-news-monitor --project=gnw-trader
```

## Monitoring Dashboard

For a full monitoring dashboard, consider setting up Cloud Monitoring with metrics like:
- Message publish rate
- Message backlog
- Scraper uptime
- Error rate

See [GCP Monitoring](https://console.cloud.google.com/monitoring?project=gnw-trader) for more details.
