# GCP-Trader Docker Deployment

Consolidated Docker deployment for all trading services.

## Services

| Service | Image Size | Port | Description |
|---------|------------|------|-------------|
| firehose-proxy | ~25 MB | 8767 (internal) | Connects to Polygon.io WebSocket |
| ms-aggregator | ~25 MB | 8768 (internal) | Generates millisecond bars |
| filtered-proxy | ~25 MB | 8765 | Client connection point for market data |
| alpaca-proxy | ~25 MB | 8099 | Trade updates WebSocket proxy |
| benzinga-ws | ~50 MB | - | Benzinga WebSocket news client |
| benzinga-scraper | ~800 MB | - | Benzinga Pro browser scraper |
| news-trader | ~500 MB | - | NautilusTrader news trading system |

**Total estimated image size: ~1.5 GB**

## Quick Start

1. Copy environment file and fill in credentials:
```bash
cp .env.example .env
# Edit .env with your API keys
```

2. Build and start all services:
```bash
docker-compose up -d --build
```

3. View logs:
```bash
docker-compose logs -f
```

4. Stop all services:
```bash
docker-compose down
```

## Building Individual Services

```bash
# Rust services (small images)
docker-compose build firehose-proxy ms-aggregator filtered-proxy alpaca-proxy

# Node.js scraper (large due to Chrome)
docker-compose build benzinga-scraper

# Python services
docker-compose build benzinga-ws news-trader
```

## GCP Credentials

Services that need GCP access (benzinga-ws, benzinga-scraper, news-trader) require credentials.

Mount your credentials file:
```bash
export GCP_CREDENTIALS_PATH=~/.config/gcloud/application_default_credentials.json
docker-compose up -d
```

Or on a GCP VM, the default service account is used automatically.

## Service Dependencies

```
                    Polygon.io
                        │
                firehose-proxy (8767)
                   /         \
          ms-aggregator    filtered-proxy
              (8768)           │
                   \          /
                filtered-proxy (8765) ◄─── news-trader
                                              │
Benzinga Pro ─► benzinga-scraper              │
                        │                     │
                    Pub/Sub ──────────────────┘
                        │
                  benzinga-ws
```

## Cost Comparison

| Deployment | Monthly Cost |
|------------|--------------|
| 4 GCP VMs (current) | ~$55-60/month |
| 1 e2-medium VM + Docker | ~$25/month |
| 1 e2-standard-2 VM + Docker | ~$50/month |

## Notes

- **benzinga-scraper** requires `shm_size: 2gb` for Chrome
- **news-trader** uses public NautilusTrader; for private fork, build wheel separately
- All Rust services use multi-stage builds for minimal image size
