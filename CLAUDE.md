# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

GCP-Trader is a news-driven trading system that reacts to market news in real-time. The system consists of five main components:

1. **Benzinga News Scraper** (`benzinga_scraper/`) - Captures news from Benzinga Pro and publishes to GCP Pub/Sub
2. **Polygon WebSocket Proxy** (`polygon_proxy/`) - Three-tier Rust proxy system providing real-time market data with millisecond bars
3. **Alpaca Trade Updates Proxy** (`alpaca_trade_updates_proxy/`) - Rust WebSocket proxy multiplexing Alpaca trade updates to multiple clients
4. **News Trading System** (`nautilus_news_trader/`) - NautilusTrader-based system that subscribes to news and executes trades via Alpaca
5. **Web Dashboard** (`web/`) - React real-time monitoring dashboard for the trading pipeline

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
                                                        Alpaca API
                                                              ↓
                              Trade Updates Proxy ← Alpaca WebSocket
                                      ↓
                                Web Dashboard (React) ← News API (SSE)
```

### Data Flow
- News events flow through Pub/Sub subscription `benzinga-news-trader`
- Market data flows through Polygon proxy on port 8765 (client connection point)
- Trade updates flow through Alpaca proxy on port 8099
- Trading execution happens via Alpaca paper trading API
- News API provides SSE stream for real-time dashboard updates

---

## 1. Benzinga News Scraper

**Location:** `benzinga_scraper/`
**Language:** Node.js (JavaScript)
**Purpose:** Real-time news scraping from Benzinga Pro using headless Chrome

### Key Files
- `index.js` - Main scraper with MutationObserver, Puppeteer, GCP Pub/Sub integration
- `benzinga-addon/` - Chrome extension for DOM manipulation
- `package.json` - Dependencies: puppeteer-extra, @google-cloud/pubsub, express

### How It Works
1. **Login** - Authenticates to Benzinga Pro at `https://www.benzinga.com/pro/login`
2. **Dashboard** - Loads `https://pro.benzinga.com/dashboard` with newsfeed
3. **DOM Monitoring** - MutationObserver watches for new `.NewsfeedStory` elements
4. **Extraction** - Parses headline, tickers, source, timestamp via React fiber
5. **Publishing** - Publishes to GCP Pub/Sub topic `benzinga-news`

### Key Features
- Zero polling - event-driven with MutationObserver
- Puppeteer Extra + Stealth plugin (anti-detection)
- Heartbeat publishing every 5 minutes
- Auto-restart on failure via systemd
- GCP Cloud Monitoring alerts

### Output Data
```json
{
  "storyId": "12345",
  "headline": "Apple beats Q4 earnings...",
  "tickers": ["AAPL"],
  "source": "Benzinga",
  "channels": ["News", "Earnings"],
  "createdAt": "2024-01-15T14:30:00Z",
  "capturedAt": "2024-01-15T14:30:01Z"
}
```

### Commands
```bash
# Local development
cd benzinga_scraper
npm install
npm start

# Deploy to GCP VM
./deploy-vm-native.sh

# Check production status
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl status benzinga_scraper"

# View production logs
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo tail -f /var/log/benzinga_scraper.log"
```

### Configuration
- `.env` - Benzinga credentials (`BENZINGA_EMAIL`, `BENZINGA_PASSWORD`), `PUBSUB_TOPIC`
- Credentials: `v.onklass@gmail.com`
- GCP Project: `gnw-trader`
- Pub/Sub Topic: `benzinga-news`

### Deployment
- VM: `benzinga_scraper` (e2-medium, us-east4-a)
- Service: `benzinga_scraper.service` via systemd
- Logs: `/var/log/benzinga_scraper.log`

---

## 2. Polygon WebSocket Proxy

**Location:** `polygon_proxy/`
**Language:** Rust
**Purpose:** Three-tier WebSocket proxy for Polygon.io market data with sub-second bar support

### Architecture
```
┌─────────────────────────────────────────────┐
│              POLYGON.IO                     │
└────────────────┬────────────────────────────┘
                 │ (1 connection)
                 ▼
┌─────────────────────────────────────────────┐
│       Firehose Proxy (8767)                 │
│       - Single Polygon connection           │
└────────┬────────────────────────┬───────────┘
         │                        │
         ▼                        ▼
┌──────────────────┐    ┌──────────────────────┐
│ Ms-Aggregator    │    │ Filtered Proxy       │
│ (8768)           │───>│ (8765)               │
│ - Generates      │    │ - Per-client filter  │
│   ms bars        │    │ - Smart routing      │
│ - Forwards       │    │ - CLIENT ENDPOINT    │
│   A.*, AM.*      │    └──────────┬───────────┘
└──────────────────┘               │
                                   ▼
                            ┌──────────────┐
                            │   CLIENTS    │
                            │ Port 8765    │
                            └──────────────┘
```

### Components

| Component | Port | Purpose |
|-----------|------|---------|
| **Firehose Proxy** | 8767 | Single connection to Polygon.io |
| **Ms-Aggregator** | 8768 | Generates millisecond bars (100Ms, 250Ms, 500Ms) + forwards native bars |
| **Filtered Proxy** | 8765 | **Client connection point** - smart routing + per-client filtering |

**Clients connect ONLY to port 8765** - everything else is internal infrastructure.

### Subscription Format
```python
# Trades only
{"action": "subscribe", "params": "T.AAPL"}

# 1-second bars (Polygon native)
{"action": "subscribe", "params": "A.AAPL"}

# Millisecond bars (generated from trades)
{"action": "subscribe", "params": "100Ms.AAPL"}   # 100ms bars
{"action": "subscribe", "params": "250Ms.AAPL"}   # 250ms bars
{"action": "subscribe", "params": "500Ms.AAPL"}   # 500ms bars

# Everything for AAPL
{"action": "subscribe", "params": "T.AAPL,A.AAPL,100Ms.AAPL"}

# Wildcard (gets T.*, Q.*, A.*, AM.* but NOT millisecond bars)
{"action": "subscribe", "params": "*"}
```

**Important:** Wildcard subscriptions (`*`) do NOT include millisecond bars - must explicitly subscribe.

### Message Formats
```json
// Trade
{"ev": "T", "sym": "AAPL", "p": 150.25, "s": 100, "t": 1633024800000}

// Millisecond Bar
{"ev": "MB", "sym": "AAPL", "interval": 500, "o": 150.20, "h": 150.30, "l": 150.15, "c": 150.25, "v": 1000, "s": 1633024800000, "e": 1633024800500, "n": 42}
```

### Commands
```bash
# Start all services locally (3 terminals)
cd polygon_proxy/firehose-proxy && cargo run --release
cd polygon_proxy/ms-aggregator && cargo run --release
cd polygon_proxy/filtered-proxy && cargo run --release

# Test connections
cd polygon_proxy
python test_polygon_proxy.py
python test_500ms_active_symbol.py

# Deploy to GCP
cd polygon_proxy
source .env
./deploy-gcp.sh
```

### Configuration
- `.env` - `POLYGON_API_KEY`, `GCP_PROJECT_ID`, `VM_NAME`, `ZONE`
- Default ports: 8767 (firehose), 8768 (aggregator), 8765 (filtered)

### Deployment
- VM: `polygon-proxy` (e2-small Spot, us-east4-a)
- All three Rust services via systemd
- Firewall: Port 8765 open for clients

---

## 3. Alpaca Trade Updates Proxy

**Location:** `alpaca_trade_updates_proxy/`
**Language:** Rust
**Purpose:** Lightweight WebSocket proxy multiplexing Alpaca's trading updates stream to unlimited clients

### Why This Exists
Alpaca allows only **one WebSocket connection per account** for trading updates. This proxy:
1. Maintains a single upstream connection to Alpaca
2. Accepts unlimited client connections
3. Broadcasts all trading events to all connected clients
4. Handles reconnection automatically

### Features
- ✅ Paper & Live Trading endpoints
- ✅ Multi-client support
- ✅ Auto-reconnection with exponential backoff
- ✅ Lightweight (~300 lines, ~5MB binary)

### Endpoints
| Endpoint | Description |
|----------|-------------|
| `ws://localhost:8099/trade-updates-paper` | Paper trading updates |
| `ws://localhost:8099/trade-updates-live` | Live trading updates |

### Usage
```python
import asyncio
import websockets
import json

async def stream_trading_updates():
    url = "ws://localhost:8099/trade-updates-paper"
    async with websockets.connect(url) as ws:
        # Authenticate
        await ws.send(json.dumps({"action": "auth", "key": "any", "secret": "any"}))

        # Receive trading updates
        while True:
            message = await ws.recv()
            data = json.loads(message)
            print(f"Update: {data}")
```

### Trading Update Events
- Order Placed, Filled, Cancelled, Expired, Rejected

### Commands
```bash
# Build and run
cd alpaca_trade_updates_proxy
cargo build --release
cargo run --release

# Test
python test_proxy.py
```

### Configuration
- `.env` - `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `PROXY_PORT=8099`
- Optional: `ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY` for live trading

---

## 4. News Trading System (Nautilus News Trader)

**Location:** `nautilus_news_trader/`
**Language:** Python (NautilusTrader)
**Purpose:** Real-time news-driven trading system subscribing to Benzinga news via Pub/Sub

### Key Files
| File | Purpose |
|------|---------|
| `run_news_trader.py` | Main entry point - starts TradingNode |
| `news_api.py` | FastAPI server for monitoring/control (port 8100) |
| `actors/pubsub_news_controller.py` | Subscribes to Pub/Sub, filters news, spawns strategies |
| `strategies/news_volume_strategy.py` | Volume-based strategy with fixed-time exit |
| `strategies/news_trend_strategy.py` | Trend-based strategy with EMA indicators |
| `shared/trade_db.py` | SQLite trade database |
| `config/strategies.yaml` | Multi-strategy configuration |

### Trading Flow
1. News arrives via Pub/Sub subscription `benzinga-news-trader`
2. Controller checks news age (must be 2-10 seconds old by default)
3. Controller verifies tickers exist and trading is allowed
4. Strategy spawned with position size based on volume percentage
5. Entry limit order placed via Alpaca API
6. Exit timer scheduled (default 7 minutes)
7. Position closed, strategy stops

### Strategies

**Volume Strategy (`news_volume_strategy.py`):**
- Entry: Limit order at last trade price + offset
- Exit: Fixed time delay (configurable, default 7 min)
- Position size: Based on 3-second volume percentage

**Trend Strategy (`news_trend_strategy.py`):**
- Entry: Same as volume strategy
- Exit: When trend_strength indicator < 64
- Uses EMA-based trend strength calculation

### News API (FastAPI)
Provides REST API and SSE streaming for the web dashboard:
- `GET /health` - Health check
- `GET /news` - List news events
- `GET /stream` - SSE endpoint for real-time events
- `GET /strategies/active` - Active strategies
- `POST /strategies/{id}/exit` - Manual early exit

### Commands
```bash
# Local development
cd nautilus_news_trader
pip install -r requirements.txt
python run_news_trader.py

# Start API server
python news_api.py

# Deploy to GCP
./deploy.sh

# Check production status
gcloud compute ssh news-trader --zone=us-east4-a --command="sudo systemctl status news-trader"
```

### Configuration (`.env`)
```bash
# GCP
GCP_PROJECT_ID=gnw-trader
PUBSUB_SUBSCRIPTION=benzinga-news-trader

# Alpaca (Paper)
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...

# Polygon
POLYGON_API_KEY=...

# Proxy URLs
POLYGON_PROXY_URL=ws://10.150.0.11:8765
TRADE_UPDATES_WS_URL=ws://10.150.0.11:8099/trade-updates-paper

# Trading Parameters
MIN_NEWS_AGE_SECONDS=2
MAX_NEWS_AGE_SECONDS=10
VOLUME_PERCENTAGE=0.05
EXIT_DELAY_MINUTES=7
EXTENDED_HOURS=true
```

### Single Instance Lock
Uses PID file locking at `/opt/news-trader/runner/default/process.pid` to prevent multiple instances.

### Dependencies
- NautilusTrader (private fork with Alpaca/Polygon adapters)
- google-cloud-pubsub
- fastapi, uvicorn
- websockets

---

## 5. Web Dashboard

**Location:** `web/`
**Language:** TypeScript/React
**Purpose:** Real-time monitoring dashboard for the news trading pipeline

### Tech Stack
- React + TypeScript + Vite
- TailwindCSS
- Lightweight Charts (for trading charts)

### Main Views
| View | Purpose |
|------|---------|
| **Live Feed** | Real-time news stream with decisions |
| **Pipeline** | Drill into a specific news event's journey |
| **Active** | Running strategies with live P&L |
| **Trades** | Completed trades history |
| **News History** | Historical news events with filters |
| **Stats** | Performance analytics |
| **System Health** | Component status, latency metrics |

### Key Files
- `src/App.tsx` - Main app component
- `src/api.ts` - API client code
- `src/types.ts` - TypeScript type definitions
- `src/components/` - View components (TradesView, NewsView, etc.)

### Data Sources
- **News API (SSE)** - Real-time events via `/stream` endpoint
- **News API (REST)** - Historical data, active strategies
- **Polygon API** - OHLC bars for charts

### Commands
```bash
cd web
npm install
npm run dev    # Start development server
npm run build  # Production build
```

### Configuration
- `.env.local` - Development environment
- `.env.production` - Production environment

---

## GCP Deployment Summary

| Service | VM | Machine Type | Zone |
|---------|-----|--------------|------|
| Benzinga Scraper | `benzinga_scraper` | e2-medium | us-east4-a |
| Polygon Proxy | `polygon-proxy` | e2-small (Spot) | us-east4-a |
| News Trader | `news-trader` | e2-medium | us-east4-a |

### Internal IPs (GCP VPC)
- Polygon Proxy: `10.150.0.11:8765` (market data), `:8099` (trade updates)
- News API: `:8100` (monitoring)

---

## Configuration Files Summary

| File | Location | Purpose |
|------|----------|---------|
| `.env` (root) | `/` | All credentials (Benzinga, Alpaca, Polygon) |
| `benzinga_scraper/.env` | `benzinga_scraper/` | Benzinga credentials, Pub/Sub topic |
| `polygon_proxy/.env` | `polygon_proxy/` | Polygon API key, GCP config |
| `nautilus_news_trader/.env` | `nautilus_news_trader/` | Trading parameters, proxy URLs |
| `config/strategies.yaml` | `nautilus_news_trader/` | Multi-strategy definitions |

---

## Monitoring

### GCP Cloud Monitoring Alerts
- **"Benzinga Scraper - No Heartbeat (10 min)"** - Scraper down
- **"Benzinga Scraper - No News (15 min)"** - Scraper stuck

### Manual Checks
```bash
# Scraper status
gcloud compute ssh benzinga_scraper --zone=us-east4-a --command="sudo systemctl status benzinga_scraper"

# Pub/Sub messages
gcloud pubsub subscriptions pull benzinga-news-monitor --limit=5 --project=gnw-trader

# News Trader logs
gcloud compute ssh news-trader --zone=us-east4-a --command="sudo journalctl -u news-trader -f"
```

---

## Building NautilusTrader Private Fork

The news-trader uses a private fork of NautilusTrader with custom Alpaca and Polygon adapters. Source code is at `/Users/wotanvonklass/Development/nautilus_trader_private`.

### Build and Deploy Process

Building requires ~2 hours on an e2-medium VM (Rust + Cython compilation). Use a dedicated spot VM to avoid blocking the news-trader.

**Step 1: Create spot build VM**
```bash
gcloud compute instances create nautilus-builder \
  --zone=us-east4-a \
  --machine-type=e2-medium \
  --provisioning-model=SPOT \
  --instance-termination-action=DELETE \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --project=gnw-trader

# Install build dependencies
gcloud compute ssh nautilus-builder --zone=us-east4-a --project=gnw-trader --command="
  sudo apt-get update && sudo apt-get install -y python3-venv python3-dev build-essential clang libssl-dev pkg-config
"
```

**Step 2: Copy source and build wheel**
```bash
# Create tarball
cd /Users/wotanvonklass/Development/nautilus_trader_private
tar --exclude='target' --exclude='build' --exclude='.git' --exclude='*.whl' --exclude='__pycache__' -czf /tmp/nautilus_trader_private.tar.gz .

# Upload and build (~2 hours)
gcloud compute scp /tmp/nautilus_trader_private.tar.gz nautilus-builder:/tmp/ --zone=us-east4-a --project=gnw-trader
gcloud compute ssh nautilus-builder --zone=us-east4-a --project=gnw-trader --command="
  cd /tmp && mkdir -p nautilus_trader_private && cd nautilus_trader_private
  tar -xzf /tmp/nautilus_trader_private.tar.gz
  python3 -m venv .venv && source .venv/bin/activate
  pip install --upgrade pip wheel setuptools build cython numpy maturin
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source ~/.cargo/env
  pip wheel . --no-deps -w dist/
"
```

**Step 3: Transfer and install**
```bash
# Transfer via HTTP
gcloud compute ssh nautilus-builder --zone=us-east4-a --project=gnw-trader --command="cd /tmp/nautilus_trader_private/dist && python3 -m http.server 8888 &"

BUILDER_IP=$(gcloud compute instances describe nautilus-builder --zone=us-east4-a --project=gnw-trader --format='get(networkInterfaces[0].networkIP)')
gcloud compute ssh news-trader --zone=us-east4-a --project=gnw-trader --command="
  wget -q http://${BUILDER_IP}:8888/nautilus_trader-*.whl -O /tmp/nautilus_trader.whl
  sudo systemctl stop news-trader
  source /opt/news-trader/.venv/bin/activate
  pip install --force-reinstall /tmp/nautilus_trader-*.whl
  sudo systemctl start news-trader
"
```

**Step 4: Cleanup**
```bash
gcloud compute instances delete nautilus-builder --zone=us-east4-a --project=gnw-trader --quiet
```

### Quick Reference
- **Build time:** ~2 hours on e2-medium
- **Wheel size:** ~100 MB
- **Python version:** 3.11 (must match news-trader VM)
- **Key changes location:** `nautilus_trader/adapters/polygon/` and `nautilus_trader/adapters/alpaca/`

---

## Development Workflow

1. **Testing Polygon Proxy locally:** Start all three components in separate terminals, then run test scripts
2. **Testing News Trader:** Ensure Pub/Sub subscription exists and has messages, then run `run_news_trader.py`
3. **Testing Scraper:** Production scraper runs on GCP VM. For local testing, use `npm start` with local Chrome
4. **Testing Web Dashboard:** Run `npm run dev` in `web/` directory

---

## Important Notes

### Polygon Proxy
- Clients connect ONLY to port 8765 (filtered proxy)
- Ports 8767 and 8768 are internal infrastructure
- Millisecond bars are generated from trades, not native Polygon data
- During off-hours, no trades = no bars

### News Trading
- System enforces single instance via PID file lock
- Strategies are spawned dynamically per news event
- Uses custom NautilusTrader installation (private fork)
- Trading parameters passed through controller config to strategy

### Scraper
- **Benzinga Pro subscription required** - Login: `v.onklass@gmail.com`
- **Runs on dedicated VM** `benzinga_scraper` (e2-medium, us-east4-a)
- Uses Puppeteer Extra + Stealth plugin (anti-detection)
- Heartbeat monitoring every 5 minutes
- GCP Cloud Monitoring alerts (email: `vonklass@gmail.com`)
