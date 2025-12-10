# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

GCP-Trader is a news-driven trading system that reacts to market news in real-time. The system consists of three main components:

1. **Benzinga News Scraper** (benzinga_scraper) - Captures news from Benzinga Pro and publishes to GCP Pub/Sub
2. **Polygon WebSocket Proxy** (polygon_proxy) - Three-tier Rust proxy system providing real-time market data with millisecond bars
3. **News Trading System** (news-trader) - NautilusTrader-based system that subscribes to news and executes trades via Alpaca

## Timezone Information

**IMPORTANT:** The developer is in **Central European Time (CET/CEST)**

- **Local timezone:** CET (UTC+1) / CEST (UTC+2 during summer)
- **GCP VMs:** All run in UTC (no timezone conversion)
- **Logs:** All timestamps are in UTC
- **Market hours in CET:**
  - 🇺🇸 **US Pre-market:** 10:00-15:30 CET ✅ **Trading enabled**
  - 🇺🇸 **US Regular hours:** 15:30-22:00 CET ✅ **Trading enabled**
  - 🇺🇸 **US After-hours:** 22:00-02:00 CET (next day) ✅ **Trading enabled**

**Trading configuration:** The news-trader system has `extended_hours: True`, which means:
- ✅ Trades can be executed during pre-market (10:00-15:30 CET)
- ✅ Trades can be executed during regular hours (15:30-22:00 CET)
- ✅ Trades can be executed during after-hours (22:00-02:00 CET)
- ❌ No trading on weekends or market holidays

**When reporting timestamps:** Always convert UTC to CET for the user (CET = UTC+1 in winter, UTC+2 in summer)

## Architecture

```
Benzinga Pro → Scraper → GCP Pub/Sub → News Trader
                                            ↓
Polygon.io → Firehose → Ms-Aggregator → Filtered Proxy → Trading System
                                            ↓
                                      Alpaca API (execution)
```

### Data Flow
- News events flow through Pub/Sub subscription `benzinga-news-trader`
- Market data flows through Polygon proxy on port 8765 (client connection point)
- Trading execution happens via Alpaca paper trading API

## Key Commands

### Polygon Proxy (Rust)

The proxy has three components that must run in order:

```bash
# Start firehose (connects to Polygon.io)
cd polygon_proxy/firehose-proxy
cargo run --release

# Start millisecond aggregator (generates sub-second bars)
cd polygon_proxy/ms-aggregator
cargo run --release

# Start filtered proxy (client connection point on port 8765)
cd polygon_proxy/filtered-proxy
cargo run --release
```

**Testing:**
```bash
# Test client connections
cd polygon_proxy
python test_polygon_proxy.py
python test_500ms_active_symbol.py
python quick_test.py

# Test filtered proxy with pytest
cd polygon_proxy/filtered-proxy
cargo test
pytest tests/test_filtered_proxy.py -v
pytest tests/test_500ms_e2e.py -v
```

**Deploy to GCP:**
```bash
cd polygon_proxy
source .env
./deploy-gcp.sh
```

### News Trader (Python)

**Setup:**
```bash
cd news-trader
pip install -r requirements.txt
```

**Run trading system:**
```bash
cd news-trader
python run_news_trader.py
```

This starts a NautilusTrader node that:
- Subscribes to GCP Pub/Sub `benzinga-news-trader`
- Spawns `NewsVolumeStrategy` for each qualifying news event
- Executes trades via Alpaca API

**Environment variables required:**
- `GCP_PROJECT_ID` - GCP project for Pub/Sub
- `PUBSUB_SUBSCRIPTION` - Pub/Sub subscription name
- `POLYGON_API_KEY` - For market data verification
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` - For trade execution

**Single instance lock:** The trading system uses PID file locking at `/opt/news-trader/runner/default/process.pid` to prevent multiple instances.

### Benzinga Scraper

**Production scraper (benzinga_scraper/index.js):**
```bash
cd benzinga_scraper
npm install
npm start  # Runs headless Chrome with extension + real-time DOM monitoring
```

**Deploy to GCP VM:**
```bash
cd benzinga_scraper
./deploy-vm-native.sh  # Deploys to benzinga_scraper VM in us-east4-a
```

**Active scraper:**
- VM: `benzinga_scraper` (e2-medium, us-east4-a)
- Running: `benzinga_scraper/index.js` via systemd service
- Monitoring: Real-time DOM monitoring with MutationObserver
- Publishing: GCP Pub/Sub topic `benzinga-news`
- Logs: `/var/log/benzinga_scraper.log` and `/var/log/benzinga_scraper-error.log`

**Archived scrapers** (see `arrchive/` folder):
- Python/Playwright scraper (benzinga_scraper.py)
- Development scrapers (scraper-dev.js, scraper-dev-simple.js)

## Component Details

### Polygon Proxy Architecture

Three-tier system providing sub-second market data:

1. **Firehose Proxy (port 8767)** - Single connection to Polygon.io, broadcasts all data
2. **Ms-Aggregator (port 8768)** - Generates millisecond bars (100ms, 250ms, 500ms, etc.) from trades and forwards native bars (A.*, AM.*)
3. **Filtered Proxy (port 8765)** - **Client connection point** with smart routing:
   - Routes bar requests (A.*, AM.*, *Ms.*) to Ms-Aggregator
   - Routes tick/quote requests (T.*, Q.*) to Firehose
   - Per-client filtering - only sends subscribed symbols

**Client subscription format:**
```python
# Subscribe to trades, 1-second bars, and 100ms bars for AAPL
{"action": "subscribe", "params": "T.AAPL,A.AAPL,100Ms.AAPL"}

# Millisecond bars: 100Ms.*, 250Ms.*, 500Ms.*, or any interval 1-60000ms
{"action": "subscribe", "params": "500Ms.SPY"}
```

**Important:** Wildcard subscriptions (`*`) do NOT include millisecond bars - must explicitly subscribe.

### News Trading System

Built on NautilusTrader with custom actor architecture:

- **PubSubNewsController** (`news-trader/actors/pubsub_news_controller.py`) - Subscribes to Pub/Sub, filters news by age (2-10 seconds default), verifies trading volume via Polygon, spawns strategies
- **NewsVolumeStrategy** (`news-trader/strategies/news_volume_strategy.py`) - Enters position with limit order (1% offset), exits after configured delay (7 minutes default)

**Trading flow:**
1. News arrives via Pub/Sub
2. Controller checks news age (must be 0-10 seconds old)
3. Controller queries Polygon for recent volume
4. If volume exists, spawn strategy with position size based on volume percentage
5. Strategy places entry limit order via Alpaca API
6. Strategy schedules exit timer
7. Strategy exits position and stops

**Uses direct Alpaca API calls** (not NautilusTrader execution engine) for simplicity.

### Benzinga Scraper Implementation

**Active production scraper:** `benzinga_scraper/index.js`

The scraper runs in continuous mode with real-time DOM monitoring:

1. **Login** - Authenticates to Benzinga Pro at `https://www.benzinga.com/pro/login`
2. **Dashboard** - Loads `https://pro.benzinga.com/dashboard` with newsfeed
3. **DOM Monitoring** - MutationObserver watches for new `.NewsfeedStory` elements
4. **Extraction** - Parses headline, tickers, source, timestamp from each story
5. **Publishing** - Publishes to GCP Pub/Sub topic `benzinga-news`

**Key features:**
- Zero polling - event-driven with MutationObserver
- Runs headless with Puppeteer Extra + Stealth plugin (anti-detection)
- Heartbeat publishing every 5 minutes to Pub/Sub
- Auto-restart on failure via systemd
- GCP Cloud Monitoring alerts for downtime/issues

**Extracted data:** headline, tickers, source, url, tags, raw, time, capturedAt

**Credentials:** Benzinga Pro login uses `v.onklass@gmail.com`

**Alternative scrapers archived** in `arrchive/` folder (Python/Playwright version, dev versions)

## Configuration Files

- **polygon_proxy/.env** - Polygon API key, GCP project, VM config
- **news-trader/.env** - Pub/Sub config, Alpaca credentials, Polygon key, trading parameters
- **benzinga_scraper/.env** - Benzinga credentials (`v.onklass@gmail.com`), Pub/Sub topic
- **Project root .env** - Contains all credentials including Benzinga, Alpaca, Polygon

## GCP Deployment

**Polygon Proxy:**
- Deploys to e2-small Spot VM (~$4/month)
- Zone: us-east4-a
- All three Rust services run via systemd
- Firewall: Port 8765 must be open for client connections

**News Trader:**
- Typically runs on dedicated VM in `/opt/news-trader`
- Requires Google Cloud credentials for Pub/Sub

**Benzinga Scraper:**
- Runs on dedicated e2-medium VM (`benzinga_scraper` in us-east4-a)
- Managed by systemd service: `benzinga_scraper.service`
- Requires Benzinga Pro subscription
- Environment: `/opt/benzinga_scraper/.env`

## Testing

**Polygon Proxy:**
- `test_polygon_proxy.py` - Basic WebSocket connection test
- `test_500ms_active_symbol.py` - Test millisecond bars with active symbol
- `test_multi_client.py` - Test multiple simultaneous clients
- `filtered-proxy/tests/test_500ms_e2e.py` - End-to-end millisecond bar test

**News Trader:**
- No unit tests currently
- Manual testing via running `run_news_trader.py` and monitoring logs

## Important Notes

### Polygon Proxy
- Clients should ONLY connect to port 8765 (filtered proxy)
- Ports 8767 and 8768 are internal infrastructure
- Millisecond bars are generated from trades, not native Polygon data
- During off-hours, no trades = no bars

### News Trading
- System enforces single instance via PID file lock
- Strategies are spawned dynamically per news event (not pre-configured)
- Uses custom NautilusTrader installation at `/opt/nautilus_trader` (patched version)
- Trading parameters are passed through controller config to strategy

### Scraper
- **Benzinga Pro subscription required** - Login: `v.onklass@gmail.com`
- **Runs on dedicated VM** `benzinga_scraper` (e2-medium, us-east4-a)
- **Stable and publishing** to `benzinga-news` topic
- **Enhanced with:**
  - Puppeteer Extra + Stealth plugin (anti-detection)
  - React fiber URL extraction (article links)
  - Tag extraction (News, Press Releases, Earnings, FDA, M&A, etc.)
  - Raw text field for debugging
  - Heartbeat monitoring every 5 minutes
  - GCP Cloud Monitoring alerts (email: `vonklass@gmail.com`)
- **Check status:** `gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl status benzinga_scraper"`
- **View logs:** `sudo journalctl -u benzinga_scraper -f` or `/var/log/benzinga_scraper.log`
- **Alternative scrapers** archived in `arrchive/` folder

## Development Workflow

1. **Testing Polygon Proxy locally:** Start all three components in separate terminals, then run test scripts
2. **Testing News Trader:** Ensure Pub/Sub subscription exists and has messages, then run `run_news_trader.py`
3. **Testing Scraper:** Production scraper runs on GCP VM. For local testing, archived dev scrapers available in `arrchive/`

## Monitoring Production Systems

### Automated Monitoring (GCP Cloud Monitoring)

**Scraper publishes heartbeat every 5 minutes:**
- Heartbeat messages to `benzinga-news` topic with `type: "heartbeat"`
- Includes: uptime, news count/hour, time since last news, status

**GCP Alerts configured (send to `vonklass@gmail.com`):**
1. **"Benzinga Scraper - No Heartbeat (10 min)"** - Fires if no Pub/Sub messages for 10 minutes (scraper down)
2. **"Benzinga Scraper - No News (15 min)"** - Fires if message rate very low (< 0.001/sec, scraper stuck/issues)

**Setup alerts:**
```bash
cd benzinga_scraper
./setup-monitoring.sh
```

**View alerts dashboard:**
```
https://console.cloud.google.com/monitoring/alerting?project=gnw-trader
```

**Test alerts:**
```bash
# Stop scraper - should trigger alerts in 10-15 min
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl stop benzinga_scraper"

# Restart scraper - alerts auto-close after 30 min
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl start benzinga_scraper"
```

### Manual Monitoring

**Check scraper status:**
```bash
# Check if VM is running
gcloud compute instances list --project=gnw-trader | grep benzinga_scraper

# Check service status
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl status benzinga_scraper"

# View live logs
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo tail -f /var/log/benzinga_scraper.log"

# Check for heartbeats
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo grep 'Heartbeat published' /var/log/benzinga_scraper.log | tail -5"
```

**Check Pub/Sub messages:**
```bash
# Pull messages from monitoring subscription (safe, doesn't consume trader messages)
gcloud pubsub subscriptions pull benzinga-news-monitor --limit=5 --project=gnw-trader

# Check all benzinga subscriptions
gcloud pubsub subscriptions list --project=gnw-trader | grep benzinga
```

**Restart scraper if needed:**
```bash
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl restart benzinga_scraper"
```
- Nautilus trader is a private fork with custom alpaca and polygon adapter. Source code is here: /Users/wotanvonklass/Development/nautilus_trader_private/tests