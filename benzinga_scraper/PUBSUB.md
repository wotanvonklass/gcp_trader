# Pub/Sub Integration

The scraper now publishes news to Google Cloud Pub/Sub automatically.

## Quick Setup

```bash
# 1. Create Pub/Sub topic and subscription
./setup-pubsub-simple.sh

# 2. Deploy (Pub/Sub is enabled by default)
./deploy-vm.sh
```

Done! News will be published to `benzinga-news` topic.

## How It Works

```
Extension captures news → Node.js reads it → Publishes to Pub/Sub
```

Each news item is published as a separate message with:
- `id` - Unique identifier
- `headline` - News headline
- `tickers` - Array of stock symbols
- `source` - News source (BZ Wire, SEC, etc.)
- `publishedDateTime` - When published (ISO format)
- `capturedAt` - When captured (ISO format)
- `description` - News description
- `captureDelay` - Delay between publish and capture

## Configuration

Set these in `.env` or deployment:

```bash
# Enable/disable Pub/Sub (enabled by default)
ENABLE_PUBSUB=true

# Topic name (default: benzinga-news)
PUBSUB_TOPIC=benzinga-news
```

## Subscribe to News

### Option 1: Pull Messages (Simple)

```bash
# Pull 10 messages
gcloud pubsub subscriptions pull benzinga-news-sub \
    --limit=10 \
    --auto-ack

# Pull continuously
while true; do
  gcloud pubsub subscriptions pull benzinga-news-sub \
    --limit=5 \
    --auto-ack
  sleep 1
done
```

### Option 2: Node.js Subscriber

```javascript
const { PubSub } = require('@google-cloud/pubsub');
const pubsub = new PubSub();

const subscription = pubsub.subscription('benzinga-news-sub');

subscription.on('message', (message) => {
  const news = JSON.parse(message.data.toString());

  console.log('New news:', {
    headline: news.headline,
    tickers: news.tickers,
    source: news.source
  });

  // Process the news here
  // e.g., trigger trades, send alerts, store in DB

  message.ack();
});

subscription.on('error', (error) => {
  console.error('Subscription error:', error);
});

console.log('Listening for news...');
```

### Option 3: Python Subscriber

```python
from google.cloud import pubsub_v1
import json

project_id = "your-project-id"
subscription_id = "benzinga-news-sub"

subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(project_id, subscription_id)

def callback(message):
    news = json.loads(message.data.decode('utf-8'))

    print(f"New news: {news['headline']}")
    print(f"Tickers: {news['tickers']}")
    print(f"Source: {news['source']}")

    # Process the news here

    message.ack()

streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
print("Listening for news...")

try:
    streaming_pull_future.result()
except KeyboardInterrupt:
    streaming_pull_future.cancel()
```

## Testing

```bash
# Publish test message
gcloud pubsub topics publish benzinga-news \
    --message='{"headline":"Test","tickers":["AAPL"]}'

# Pull it
gcloud pubsub subscriptions pull benzinga-news-sub \
    --auto-ack
```

## Disable Pub/Sub

```bash
# In .env or deployment
ENABLE_PUBSUB=false
```

Or remove the environment variable entirely (it's enabled by default).

## Message Format

```json
{
  "id": "03_04_20PM_AAPL_Apple_announces_earnings_BZ_Wire",
  "headline": "Apple announces Q4 earnings beat",
  "tickers": ["AAPL"],
  "source": "BZ Wire",
  "publishedDateTime": "2025-01-21T15:04:20.000Z",
  "capturedAt": "2025-01-21T15:04:23.456Z",
  "description": "Apple Inc. reported stronger-than-expected...",
  "captureDelay": {
    "milliseconds": 3456,
    "seconds": 3,
    "minutes": 0,
    "formatted": "3s"
  }
}
```

## Monitoring

```bash
# View recent messages
gcloud pubsub subscriptions seek benzinga-news-sub \
    --time=$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)

gcloud pubsub subscriptions pull benzinga-news-sub \
    --limit=100

# Check subscription backlog
gcloud pubsub subscriptions describe benzinga-news-sub
```

## Cost

Pub/Sub pricing:
- First 10GB/month: **FREE**
- After that: $0.40/GB

Typical usage:
- ~1KB per message
- ~1000 messages/day = 1MB/day = 30MB/month
- Cost: **$0** (within free tier)

## Troubleshooting

### No messages appearing?

```bash
# Check if Pub/Sub is enabled
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker logs benzinga-scraper 2>&1 | grep Pub'

# Should see: "📬 Pub/Sub: Enabled (topic: benzinga-news)"
```

### Permission denied?

```bash
# Grant yourself subscriber access
gcloud pubsub subscriptions add-iam-policy-binding benzinga-news-sub \
    --member="user:your-email@example.com" \
    --role="roles/pubsub.subscriber"
```

### Messages piling up?

```bash
# Check subscriber count
gcloud pubsub subscriptions describe benzinga-news-sub

# Create another subscription if needed
gcloud pubsub subscriptions create benzinga-news-sub-2 \
    --topic=benzinga-news
```
