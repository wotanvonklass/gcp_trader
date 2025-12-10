# NautilusTrader Adapter Migration

## Summary

Successfully migrated the News Trading System from direct API calls to using proper NautilusTrader adapters with custom proxy infrastructure.

## Changes Made

### 1. Updated `run_news_trader.py`

**Added Imports:**
```python
from nautilus_trader.adapters.alpaca.config import AlpacaExecClientConfig
from nautilus_trader.adapters.alpaca.factories import AlpacaLiveExecClientFactory
from nautilus_trader.adapters.polygon.config import PolygonDataClientConfig
from nautilus_trader.adapters.polygon.factories import PolygonLiveDataClientFactory
```

**Configured Data Client (Polygon):**
```python
data_clients={
    "POLYGON": PolygonDataClientConfig(
        api_key=polygon_api_key,
        base_url_ws=polygon_proxy_url,  # ws://localhost:8765
        subscribe_trades=True,
        subscribe_quotes=True,
        subscribe_bars=True,
        subscribe_second_aggregates=True,
        include_extended_hours=True,
    ),
}
```

**Configured Execution Client (Alpaca):**
```python
exec_clients={
    "ALPACA": AlpacaExecClientConfig(
        api_key=alpaca_api_key,
        secret_key=alpaca_secret_key,
        paper_trading=True,
        validate_orders=True,
        trade_updates_ws_url=trade_updates_ws_url,  # ws://localhost:8099/trade-updates-paper
        trade_updates_auth_key="nautilus",
        trade_updates_auth_secret="nautilus",
    ),
}
```

**Registered Adapter Factories:**
```python
trading_node.add_data_client_factory("POLYGON", PolygonLiveDataClientFactory)
trading_node.add_exec_client_factory("ALPACA", AlpacaLiveExecClientFactory)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    News Trading System                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  GCP Pub/Sub (benzinga-news-trader)                         │
│         │                                                     │
│         ▼                                                     │
│  PubSubNewsController                                        │
│         │                                                     │
│         ├──────────────────┬─────────────────┐              │
│         ▼                  ▼                 ▼              │
│  NewsVolumeStrategy   NewsVolumeStrategy   ...              │
│    (Direct Alpaca API)                                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              │
        ┌─────────────────────┴────────────────────┐
        │                                           │
        ▼                                           ▼
┌──────────────────┐                     ┌──────────────────┐
│  Polygon Proxy   │                     │  Alpaca Proxy    │
│  (port 8765)     │                     │  (port 8099)     │
├──────────────────┤                     ├──────────────────┤
│ • Filtered Proxy │                     │ • Trade Updates  │
│ • Ms-Aggregator  │                     │ • Multi-client   │
│ • Firehose       │                     │ • Broadcast      │
└────────┬─────────┘                     └────────┬─────────┘
         │                                         │
         ▼                                         ▼
   Polygon.io                              Alpaca Trading API
```

## Data Flow

### Market Data (Polygon)
1. **Polygon.io** → Firehose Proxy (8767)
2. Firehose → Ms-Aggregator (8768) generates millisecond bars
3. Ms-Aggregator → Filtered Proxy (8765) with per-client filtering
4. **Clients connect to port 8765** (Polygon data client)

### Trade Updates (Alpaca)
1. **Alpaca Trading API** ← Trade Updates Proxy (8099)
2. Proxy maintains single connection to Alpaca
3. Proxy broadcasts to all connected clients
4. **Clients connect to port 8099** (Alpaca execution client)

### Order Execution
Strategies still use **direct Alpaca REST API** for order placement (intentional design for simplicity)

## Environment Variables

Required in `.env`:

```bash
# GCP Pub/Sub
GCP_PROJECT_ID=your-project-id
PUBSUB_SUBSCRIPTION=benzinga-news-trader

# Alpaca
ALPACA_API_KEY=your-alpaca-api-key
ALPACA_SECRET_KEY=your-alpaca-secret-key

# Polygon
POLYGON_API_KEY=your-polygon-api-key

# Trading Parameters
MIN_NEWS_AGE_SECONDS=2
MAX_NEWS_AGE_SECONDS=10
VOLUME_PERCENTAGE=0.05
MIN_POSITION_SIZE=100
MAX_POSITION_SIZE=20000
LIMIT_ORDER_OFFSET_PCT=0.01
EXIT_DELAY_MINUTES=7
EXTENDED_HOURS=true

# Optional: Proxy URLs (defaults shown)
TRADE_UPDATES_WS_URL=ws://localhost:8099/trade-updates-paper
POLYGON_PROXY_URL=ws://localhost:8765
```

## Testing

### Prerequisites

1. **Start Polygon Proxy** (3 components):
   ```bash
   # Terminal 1: Firehose
   cd polygon_proxy/firehose-proxy
   cargo run --release

   # Terminal 2: Ms-Aggregator
   cd polygon_proxy/ms-aggregator
   cargo run --release

   # Terminal 3: Filtered Proxy
   cd polygon_proxy/filtered-proxy
   cargo run --release
   ```

2. **Start Alpaca Trade Updates Proxy**:
   ```bash
   cd alpaca_trade_updates_proxy
   cargo run --release
   ```

3. **Verify Proxies Running**:
   ```bash
   # Test Polygon proxy
   cd polygon_proxy
   python test_polygon_proxy.py

   # Test Alpaca proxy
   cd alpaca_trade_updates_proxy
   python test_proxy.py
   ```

### Run News Trading System

```bash
cd nautilus_news_trader
python run_news_trader.py
```

### Expected Startup Logs

```
🚀 NEWS TRADING SYSTEM WITH NAUTILUS & PUB/SUB
============================================================
📦 Using custom Nautilus installation from: /opt/nautilus_trader
📊 Alpaca credentials found: PKxxxxxxxx...
🏥 Running Alpaca health check...
✅ Alpaca account validated - Ready to trade
📡 Pub/Sub: gnw-trader/benzinga-news-trader
📊 Data: Polygon WebSocket proxy (ws://localhost:8765)
⚡ Execution: Alpaca via trade updates proxy (ws://localhost:8099)

🔌 Trade updates proxy: ws://localhost:8099/trade-updates-paper
🔌 Polygon proxy: ws://localhost:8765

📋 Controller configured
🔧 Initializing TradingNode...
📦 Registering Polygon data client factory...
📦 Registering Alpaca execution client factory...
🔧 Building TradingNode...
✅ TradingNode built successfully
✅ News trading system operational!
```

## Benefits of Adapter Architecture

### Before (Direct API)
- ❌ No centralized data client
- ❌ No real-time market data subscriptions
- ❌ No trade update notifications
- ❌ Strategies isolated from market data

### After (Adapters + Proxies)
- ✅ Centralized Polygon data client (trades, quotes, bars, millisecond bars)
- ✅ Real-time WebSocket data through local proxy
- ✅ Trade update notifications to all strategies
- ✅ Share one Polygon connection across unlimited clients
- ✅ Share one Alpaca WebSocket across unlimited clients
- ✅ Per-client filtering (only receive subscribed symbols)
- ✅ Future strategies can subscribe to market data
- ✅ Proper NautilusTrader event-driven architecture

## Strategy Execution

Current strategies use **direct Alpaca REST API** for simplicity:
- Order placement: `alpaca.submit_order()`
- Position queries: `alpaca.get_position()`
- Order status: `alpaca.get_order()`

This is **intentional** and works alongside the adapters:
- Adapters provide data and notifications
- Strategies control execution timing directly
- Simpler than using NautilusTrader execution callbacks

## Future Enhancements

Optionally migrate strategies to use NautilusTrader execution engine:

```python
# Instead of:
order = self.alpaca.submit_order(...)

# Use:
order = self.order_factory.limit(
    instrument_id=self.instrument_id,
    order_side=OrderSide.BUY,
    quantity=self.instrument.make_qty(qty),
    price=self.instrument.make_price(limit_price),
)
self.submit_order(order)

# And handle via callbacks:
def on_order_filled(self, order):
    # React to fills automatically
    pass
```

## Troubleshooting

### Issue: "Failed to connect to Polygon proxy"
**Solution:** Ensure all 3 Polygon proxy components are running:
```bash
ps aux | grep -E "firehose|ms-aggregator|filtered-proxy"
```

### Issue: "Failed to connect to trade updates proxy"
**Solution:** Check trade updates proxy is running:
```bash
ps aux | grep trade-updates-proxy
```

### Issue: "No market data received"
**Solution:**
- Verify market is open (9:30 AM - 4:00 PM ET)
- Check Polygon API key is valid
- Test direct connection: `cd polygon_proxy && python test_polygon_proxy.py`

### Issue: "No trade updates"
**Solution:**
- Verify Alpaca credentials are valid
- Check proxy logs for errors
- Test direct connection: `cd alpaca_trade_updates_proxy && python test_proxy.py`

## Files Changed

- ✅ `/nautilus_news_trader/run_news_trader.py` - Added adapter configuration
- ✅ `/nautilus_news_trader/ADAPTER_MIGRATION.md` - This documentation

## Files Unchanged (Intentional)

- `/nautilus_news_trader/strategies/news_volume_strategy.py` - Still uses direct Alpaca API
- `/nautilus_news_trader/actors/pubsub_news_controller.py` - Controller logic unchanged

## Next Steps

1. **Test with proxies running** - Ensure data and execution work
2. **Monitor logs** - Verify adapter connections
3. **Optionally migrate strategy** - Convert to NautilusTrader execution if desired
4. **Deploy to production** - Copy to GCP VM and run

## Support

For issues:
- Check proxy status and logs
- Verify environment variables
- Review NautilusTrader adapter documentation
- See `/home/ubuntu/code/nautilus_trader_private/DEPLOYMENT_GUIDE.md`
