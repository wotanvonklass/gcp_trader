---
name: check-pipeline
description: Check news pipeline health. First checks market status via Polygon API, then fetches the last 3 NYSE/NASDAQ news from GLN Atom feed and cross-checks against our Pub/Sub. Adjusts expectations based on market hours (weekend/holiday = less activity).
---

# Check Pipeline Skill

## Purpose

This skill checks the health of the news ingestion pipeline by:
1. Checking current date/time and market status (via Polygon API)
2. Fetching the last 3 NYSE/NASDAQ news from the GLN Atom feed
3. Cross-checking if these news appear in our GCP Pub/Sub
4. Reporting results with context based on market hours

## Cross-Check Process

### Step 0: Check Market Status

Before checking the pipeline, get current date/time and market status:

```bash
# Get current date, day of week, and time in UTC and ET
date -u "+%Y-%m-%d %H:%M:%S UTC (%A)" && TZ=America/New_York date "+%Y-%m-%d %H:%M:%S ET (%A)"
```

Then check Polygon market status:

```bash
curl -s "https://api.polygon.io/v1/marketstatus/now?apiKey=${POLYGON_API_KEY}" | jq '{market: .market, exchanges: .exchanges, serverTime: .serverTime}'
```

**Use this info to set expectations:**
- **Market open**: Expect frequent news, pipeline should show recent activity
- **Market closed (after hours)**: Less news volume, older timestamps acceptable
- **Weekend/Holiday**: Minimal news, stale feed timestamps are normal
- **Pre-market (4am-9:30am ET)**: Some news activity expected

### Step 1: Fetch Latest GLN News (NYSE/NASDAQ only)

Use WebFetch to get the GLN Atom feed for US news:

**URL**: `https://www.globenewswire.com/AtomFeed/country/United%20States/feedTitle/GlobeNewswire%20-%20News%20from%20United%20States`

**Prompt**: "Extract the 15 most recent news entries that have NYSE or NASDAQ stock tickers. Skip entries without tickers or with other exchanges (TSX, OTC, Paris, etc). For each provide: 1) Title/headline, 2) Published timestamp, 3) Stock ticker."

From the results, identify the **last 3 NYSE or NASDAQ news** with their:
- Headline (or key words)
- Ticker symbol
- Published timestamp

### Step 2: Check Pub/Sub for These News

Pull recent GLN messages from our monitor subscription and search for matches:

```bash
gcloud pubsub subscriptions pull benzinga-news-monitor \
  --project=gnw-trader \
  --limit=50 \
  --format=json 2>/dev/null | jq -r '
    .[].message.data | @base64d | fromjson |
    select(.source == "GLN") |
    "\(.capturedAt) | \(.tickers | join(",")) | \(.headline[0:80])"'
```

### Step 3: Report Results

For each of the 3 GLN news items:
- **FOUND**: News appears in Pub/Sub with acceptable latency (< 2 min)
- **DELAYED**: News appears but with high latency (> 2 min)
- **MISSING**: News not found in Pub/Sub (investigate scraper)

## Quick Check Commands

### Check Latest News from Pub/Sub

```bash
gcloud pubsub subscriptions pull benzinga-news-monitor \
  --project=gnw-trader \
  --limit=10 \
  --format=json 2>/dev/null | jq -r '.[] |
    .message.data | @base64d | fromjson |
    "\(.capturedAt) | \(.source) | \(.tickers | join(",")) | \(.headline[0:60])..."'
```

### Check GLN News Only

```bash
gcloud pubsub subscriptions pull benzinga-news-monitor \
  --project=gnw-trader \
  --limit=20 \
  --format=json 2>/dev/null | jq -r '.[] |
    .message.data | @base64d | fromjson |
    select(.source == "GLN") |
    "\(.capturedAt) | \(.tickers | join(",")) | \(.headline[0:80])..."'
```

### Check Scraper Health

SSH to the scraper VM and check service status:

```bash
gcloud compute ssh benzinga-scraper --zone=us-east4-a --project=gnw-trader \
  --command="sudo systemctl status benzinga-scraper"
```

View recent logs:

```bash
gcloud compute ssh benzinga-scraper --zone=us-east4-a --project=gnw-trader \
  --command="tail -50 /var/log/benzinga-scraper.log"
```

Check for recent GLN news in logs:

```bash
gcloud compute ssh benzinga-scraper --zone=us-east4-a --project=gnw-trader \
  --command="grep -i 'GLN' /var/log/benzinga-scraper.log | tail -20"
```

Check for Pub/Sub publish activity:

```bash
gcloud compute ssh benzinga-scraper --zone=us-east4-a --project=gnw-trader \
  --command="grep 'Heartbeat published' /var/log/benzinga-scraper.log | tail -5"
```

## GLN Atom Feed Reference

### Feed URL
The GLN Atom feed for US news (includes company announcements + legal/investor notices):
- **URL**: `https://www.globenewswire.com/AtomFeed/country/United%20States/feedTitle/GlobeNewswire%20-%20News%20from%20United%20States`

### Expected Latency

- **Normal**: GLN news appears in Pub/Sub within 2 minutes of GLN publish time
- **Warning**: Latency > 2 minutes but < 5 minutes
- **Alert**: Latency > 5 minutes or news missing entirely

### Notes
- Focus on NYSE and NASDAQ tickers (these are tradeable)
- Skip TSX, Paris, OTC Markets tickers
- Weekend/off-hours will have less news activity

## Example Cross-Check

### Step 0: Market Status

```
Current Time: 2025-12-28 09:00:00 UTC (Sunday)
             2025-12-28 04:00:00 ET (Sunday)

Polygon Market Status:
  market: "closed"
  exchanges: { nasdaq: "closed", nyse: "closed" }

Expectation: Weekend - minimal news activity, stale timestamps normal
```

### Step 1: GLN Feed Results (last 3 with tickers)

From the US Atom feed, extract entries with tickers:

| # | Ticker | Headline | Published (UTC) |
|---|--------|----------|-----------------|
| 1 | FFIV | ROSEN Encourages F5, Inc. Investors... | 2025-12-27T23:29:49Z |
| 2 | TLX | TLX DEADLINE NOTICE: ROSEN... | 2025-12-27T23:02:00Z |
| 3 | NUAI | NUAI Announcement: Suffered Losses... | 2025-12-27T23:36:40Z |

### Step 2: Search Pub/Sub

Match by ticker + headline keywords in our GLN messages.

### Step 3: Report

```
Pipeline Health Check - 2025-12-28 00:00 UTC
============================================

1. FFIV - "ROSEN Encourages F5..."
   GLN:    23:29:49 UTC
   PubSub: 23:30:15 UTC
   Latency: 26s
   Status: FOUND

2. TLX  - "TLX DEADLINE NOTICE..."
   GLN:    23:02:00 UTC
   PubSub: 23:02:45 UTC
   Latency: 45s
   Status: FOUND

3. NUAI - "NUAI Announcement..."
   GLN:    23:36:40 UTC
   PubSub: 23:37:02 UTC
   Latency: 22s
   Status: FOUND

Summary: 3/3 captured - PIPELINE HEALTHY
```

## Pipeline Architecture

```
Benzinga Pro Dashboard (pro.benzinga.com)
       |
       | MutationObserver watches .NewsfeedStory elements
       v
benzinga_scraper VM (GCP us-east4-a)
       |
       | Extracts: headline, tickers, source, createdAt, capturedAt
       | source="GLN" indicates Globe Newswire articles
       v
Pub/Sub topic: benzinga-news
       |
       +---> benzinga-news-monitor (for health checks - use this)
       +---> benzinga-news-trader (for trading system)
       +---> benzinga-news-vol5, vol10, trend (other consumers)
```

## News Message Format

Each Pub/Sub message contains:

```json
{
  "id": "unique-id",
  "storyId": "benzinga-story-id",
  "headline": "Company Announces Q4 Results...",
  "tickers": ["AAPL", "MSFT"],
  "source": "GLN",           // "GLN" = Globe Newswire
  "sourceGroup": "Press Releases",
  "sourceFull": "GlobeNewswire",
  "createdAt": "2025-12-27T10:00:00Z",  // Benzinga timestamp
  "capturedAt": "2025-12-27T10:00:01Z"  // When we scraped it
}
```

## Important Notes

**NEVER use `--auto-ack` when pulling from `benzinga-news-monitor`!**
- `--auto-ack` permanently removes messages after pulling
- The monitor subscription is for health checks - messages should remain available
- Only the actual consumers (news-trader, etc.) should ack messages

**To reset the monitor subscription if messages were accidentally acked:**
```bash
gcloud pubsub subscriptions seek benzinga-news-monitor \
  --project=gnw-trader \
  --time="$(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ)"
```

## Troubleshooting

### No Recent News
1. Check if scraper service is running
2. Check scraper logs for errors
3. Verify Benzinga Pro login is still valid
4. Check if market is open (less news on weekends/holidays)

### Missing GLN News
1. GLN news appears on Benzinga with slight delay (typically 30-60 sec)
2. Some GLN articles may not have tickers and get filtered
3. Check if the specific article appeared on Benzinga Pro at all

### High Latency
1. Check scraper VM CPU/memory usage
2. Check Pub/Sub backlog
3. Verify MutationObserver is still active (check for heartbeat logs)
