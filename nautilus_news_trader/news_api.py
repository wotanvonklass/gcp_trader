#!/usr/bin/env python3
"""
News API - REST API + SSE streaming for Pako Web dashboard.

Endpoints:
    # Read-only (existing)
    GET /health                  - Health check (no auth)
    GET /news                    - List news events
    GET /news/{symbol}           - News events for a ticker
    GET /news/{news_id}/strategies - Strategies for a news event

    # Event Ingestion (from News Trader)
    POST /events/news-received   - News received from Pub/Sub
    POST /events/news-decision   - Trading decision made
    POST /events/strategy-spawned - Strategy spawned
    POST /events/order-placed    - Order submitted
    POST /events/order-filled    - Order filled
    POST /events/order-cancelled - Order cancelled
    POST /events/strategy-stopped - Strategy stopped

    # SSE Streaming (to Web App)
    GET /stream                  - Real-time event stream

    # Active Strategies
    GET /strategies/active       - Currently running strategies
    POST /strategies/{id}/exit   - Manual early exit
    POST /strategies/{id}/extend - Extend exit timer
    POST /strategies/{id}/cancel - Cancel pending order

    # System Health & Stats
    GET /health/detailed         - Component status
    GET /stats/latency           - Latency percentiles
    GET /stats/skips             - Skip reason breakdown
    GET /stats/performance       - Performance by hour/strategy

Authentication:
    Header: X-API-Key: <key>
    Set via NEWS_API_KEY environment variable

Usage:
    NEWS_API_KEY=your-secret-key python news_api.py
"""

import os
import json
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from collections import deque
from dataclasses import dataclass, field, asdict

from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import requests

from shared.trade_db import get_trade_db
from utils.alpaca_health import check_trade_updates_proxy


# ==============================================================================
# Configuration
# ==============================================================================

API_KEY = os.environ.get("NEWS_API_KEY", "")
PORT = int(os.environ.get("NEWS_API_PORT", "8100"))
DB_PATH = os.environ.get("NEWS_API_DB_PATH")
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")

# Event buffer settings
MAX_EVENTS = 1000  # Keep last 1000 events in memory
HEARTBEAT_INTERVAL = 30  # SSE heartbeat every 30 seconds


# ==============================================================================
# Event Storage (In-Memory)
# ==============================================================================

@dataclass
class PipelineEvent:
    """Base event structure for all pipeline events."""
    id: str
    type: str
    timestamp: str
    news_id: str
    data: Dict[str, Any] = field(default_factory=dict)


class EventStore:
    """In-memory store for pipeline events with SSE broadcasting."""

    def __init__(self, max_events: int = MAX_EVENTS):
        self.events: deque = deque(maxlen=max_events)
        self.subscribers: List[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        self.start_time = datetime.now(timezone.utc)
        self.event_counts: Dict[str, int] = {}

        # Active strategies tracking
        self.active_strategies: Dict[str, Dict[str, Any]] = {}

        # Latency tracking
        self.latency_samples: Dict[str, List[float]] = {
            "news_to_decision": [],
            "decision_to_order": [],
            "order_to_fill": [],
            "total_news_to_fill": [],
        }

    async def add_event(self, event: PipelineEvent):
        """Add event to store and broadcast to all subscribers."""
        async with self._lock:
            self.events.append(event)

            # Track event counts
            self.event_counts[event.type] = self.event_counts.get(event.type, 0) + 1

            # Update active strategies
            self._update_active_strategies(event)

            # Broadcast to all SSE subscribers
            dead_subscribers = []
            for queue in self.subscribers:
                try:
                    await queue.put(event)
                except asyncio.QueueFull:
                    dead_subscribers.append(queue)

            # Clean up dead subscribers
            for queue in dead_subscribers:
                self.subscribers.remove(queue)

    def _update_active_strategies(self, event: PipelineEvent):
        """Update active strategies based on event type."""
        if event.type == "strategy_spawned":
            strategy_id = event.data.get("strategy_id")
            if strategy_id:
                self.active_strategies[strategy_id] = {
                    "id": strategy_id,
                    "news_id": event.news_id,
                    "ticker": event.data.get("ticker"),
                    "strategy_type": event.data.get("strategy_type"),
                    "side": event.data.get("side", "long"),
                    "position_size_usd": event.data.get("position_size_usd"),
                    "entry_limit_price": event.data.get("entry_price"),
                    "exit_delay_seconds": event.data.get("exit_delay_seconds"),
                    "status": "pending_entry",
                    "spawned_at": event.timestamp,
                    "headline": event.data.get("headline", ""),
                }

        elif event.type == "order_filled":
            strategy_id = event.data.get("strategy_id")
            order_role = event.data.get("order_role")
            if strategy_id and strategy_id in self.active_strategies:
                if order_role == "entry":
                    self.active_strategies[strategy_id]["status"] = "in_position"
                    self.active_strategies[strategy_id]["entry_fill_price"] = event.data.get("fill_price")
                    self.active_strategies[strategy_id]["qty"] = event.data.get("qty")
                    self.active_strategies[strategy_id]["entry_filled_at"] = event.timestamp
                elif order_role == "exit":
                    self.active_strategies[strategy_id]["status"] = "pending_close"
                    self.active_strategies[strategy_id]["exit_fill_price"] = event.data.get("fill_price")

        elif event.type == "order_placed":
            strategy_id = event.data.get("strategy_id")
            order_role = event.data.get("order_role")
            if strategy_id and strategy_id in self.active_strategies:
                if order_role == "exit":
                    self.active_strategies[strategy_id]["status"] = "pending_exit"
                    self.active_strategies[strategy_id]["exit_order_id"] = event.data.get("order_id")

        elif event.type == "strategy_stopped":
            strategy_id = event.data.get("strategy_id")
            if strategy_id and strategy_id in self.active_strategies:
                del self.active_strategies[strategy_id]

    async def subscribe(self) -> asyncio.Queue:
        """Create a new SSE subscriber queue."""
        queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self.subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """Remove an SSE subscriber."""
        async with self._lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)

    def get_recent_events(self, limit: int = 100, event_type: str = None) -> List[Dict]:
        """Get recent events, optionally filtered by type."""
        events = list(self.events)
        if event_type:
            events = [e for e in events if e.type == event_type]
        return [asdict(e) for e in events[-limit:]]

    def get_events_for_news(self, news_id: str) -> List[Dict]:
        """Get all events for a specific news item."""
        return [asdict(e) for e in self.events if e.news_id == news_id]


# Global event store
event_store = EventStore()


# ==============================================================================
# Pydantic Models - Requests
# ==============================================================================

class NewsReceivedRequest(BaseModel):
    news_id: str
    headline: str
    tickers: List[str]
    source: str
    pub_time: str
    news_age_ms: int


class NewsDecisionRequest(BaseModel):
    news_id: str
    decision: str  # "trade" or "skip"
    skip_reason: Optional[str] = None
    volume_check_ms: Optional[int] = None
    volume_found: Optional[float] = None
    volume_threshold: Optional[float] = None


class StrategySpawnedRequest(BaseModel):
    news_id: str
    strategy_id: str
    strategy_type: str
    ticker: str
    side: str = "long"
    position_size_usd: float
    entry_price: float
    exit_delay_seconds: int
    headline: Optional[str] = None


class OrderPlacedRequest(BaseModel):
    news_id: str
    strategy_id: str
    order_id: str
    alpaca_order_id: Optional[str] = None
    order_role: str  # "entry" or "exit"
    side: str  # "buy" or "sell"
    order_type: str  # "market" or "limit"
    qty: float
    limit_price: Optional[float] = None


class OrderFilledRequest(BaseModel):
    news_id: str
    strategy_id: str
    order_id: str
    order_role: str  # "entry" or "exit"
    fill_price: float
    qty: float
    slippage: Optional[float] = None


class OrderCancelledRequest(BaseModel):
    news_id: str
    strategy_id: str
    order_id: str
    reason: str


class StrategyStoppedRequest(BaseModel):
    news_id: str
    strategy_id: str
    reason: str  # "scheduled_exit", "manual", "error", "cancelled"
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    duration_ms: Optional[int] = None


# ==============================================================================
# Pydantic Models - Responses
# ==============================================================================

class NewsEvent(BaseModel):
    id: str
    headline: str
    tickers: List[str]
    pub_time: Optional[str]
    source: Optional[str] = None
    decision: Optional[str]
    skip_reason: Optional[str]
    strategies_spawned: int
    news_age_ms: Optional[int] = None


class CompletedTrade(BaseModel):
    """A completed trade with entry and exit fills."""
    id: str
    news_id: Optional[str]
    ticker: str
    strategy_type: Optional[str]
    strategy_name: Optional[str]
    position_size_usd: Optional[float]
    entry_price: float
    exit_price: float
    entry_time: Optional[str]
    exit_time: Optional[str]
    qty: float
    pnl: float
    pnl_percent: Optional[float]
    started_at: Optional[str]
    stopped_at: Optional[str]
    stop_reason: Optional[str]
    headline: Optional[str]
    pub_time: Optional[str]
    source: Optional[str]


class StrategyExecution(BaseModel):
    id: str
    ticker: str
    strategy_type: Optional[str]
    strategy_name: Optional[str]
    position_size_usd: Optional[float]
    entry_price: Optional[float]
    exit_price: Optional[float]
    qty: Optional[float]
    pnl: Optional[float]
    status: str
    started_at: Optional[str]
    stopped_at: Optional[str]
    stop_reason: Optional[str]


class StrategiesResponse(BaseModel):
    strategies: List[StrategyExecution]


class HealthResponse(BaseModel):
    status: str


class DetailedHealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    sse_clients: int
    events_in_buffer: int
    active_strategies: int
    event_counts: Dict[str, int]
    components: Dict[str, Dict[str, Any]]


class ActiveStrategyResponse(BaseModel):
    id: str
    news_id: str
    ticker: str
    strategy_type: Optional[str]
    side: str
    position_size_usd: Optional[float]
    status: str
    entry_limit_price: Optional[float]
    entry_fill_price: Optional[float]
    qty: Optional[float]
    current_price: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pnl_percent: Optional[float]
    exit_countdown_seconds: Optional[int]
    spawned_at: str
    headline: str


class LatencyStats(BaseModel):
    avg: float
    p50: float
    p99: float
    max: float
    sample_count: int


class LatencyResponse(BaseModel):
    news_to_decision: LatencyStats
    decision_to_order: LatencyStats
    order_to_fill: LatencyStats
    total_news_to_fill: LatencyStats


class SkipAnalysis(BaseModel):
    period: str
    total: int
    triggered: int
    skipped: int
    by_reason: List[Dict[str, Any]]
    near_misses: List[Dict[str, Any]]


class PerformanceStats(BaseModel):
    period: str
    total_trades: int
    total_pnl: float
    win_rate: float
    avg_pnl: float
    by_hour: List[Dict[str, Any]]
    by_strategy: List[Dict[str, Any]]


# ==============================================================================
# FastAPI App
# ==============================================================================

app = FastAPI(
    title="Pako News API",
    description="REST API + SSE streaming for news trading monitoring",
    version="2.0.0",
)

# CORS middleware for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Static files directory (for serving built frontend)
STATIC_DIR = Path(__file__).parent / "static"


def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """Verify the API key from request header.

    If NEWS_API_KEY is not set, authentication is skipped (local dev mode).
    """
    if not API_KEY:
        # No API key configured - skip auth (local dev mode)
        return
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key"
        )


# ==============================================================================
# Health Endpoints
# ==============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint (no authentication required)."""
    uptime = (datetime.now(timezone.utc) - event_store.start_time).total_seconds()
    return {
        "status": "ok",
        "uptime": int(uptime),
        "started_at": event_store.start_time.isoformat(),
        "news_count": len([e for e in event_store.events if e.type == "news_received"]),
        "event_count": len(event_store.events),
        "active_strategies": len(event_store.active_strategies),
        "trading_active": False,  # News trader not connected in standalone mode
        "sse_subscribers": len(event_store.subscribers),
        "environment": os.environ.get("ENVIRONMENT", "development"),
    }


@app.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """Detailed health check with component status."""
    verify_api_key(x_api_key)

    uptime = (datetime.now(timezone.utc) - event_store.start_time).total_seconds()

    # Check database connectivity
    db_status = "healthy"
    try:
        db = get_trade_db(DB_PATH)
        db.get_news_summary(days=1)
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check trade updates proxy connectivity
    trade_proxy_result = check_trade_updates_proxy()
    trade_proxy_status = {
        "status": "healthy" if trade_proxy_result['healthy'] else "error",
        "url": trade_proxy_result['proxy_url'],
    }
    if trade_proxy_result['healthy']:
        trade_proxy_status["response_time_ms"] = trade_proxy_result['response_time_ms']
    else:
        trade_proxy_status["error"] = trade_proxy_result['error']

    return {
        "status": "ok",
        "uptime_seconds": uptime,
        "sse_clients": len(event_store.subscribers),
        "events_in_buffer": len(event_store.events),
        "active_strategies": len(event_store.active_strategies),
        "event_counts": event_store.event_counts,
        "components": {
            "news_api": {"status": "healthy", "uptime": uptime},
            "database": {"status": db_status},
            "event_store": {
                "status": "healthy",
                "buffer_size": len(event_store.events),
                "max_size": MAX_EVENTS,
            },
            "trade_updates_proxy": trade_proxy_status,
        },
    }


# ==============================================================================
# News Endpoints (Existing)
# ==============================================================================

@app.get("/news/detail/{news_id}")
async def get_news_detail(
    news_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get a single news event by ID."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    news = db.get_news_event_by_id(news_id)
    if not news:
        raise HTTPException(status_code=404, detail="News event not found")
    return news


@app.get("/news/{news_id}/strategies", response_model=StrategiesResponse)
async def get_news_strategies(
    news_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get all strategy executions for a specific news event."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    strategies = db.get_strategies_for_news(news_id)
    return {"strategies": strategies}


@app.get("/news/{news_id}/events")
async def get_news_events(
    news_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get all pipeline events for a specific news item."""
    verify_api_key(x_api_key)
    events = event_store.get_events_for_news(news_id)
    return {"events": events}


@app.get("/news", response_model=List[NewsEvent])
async def list_news(
    limit: int = Query(default=100, ge=1, le=1000),
    triggered_only: bool = Query(default=False),
    from_date: Optional[str] = Query(default=None, description="Start date (ISO format or 'today')"),
    to_date: Optional[str] = Query(default=None, description="End date (ISO format)"),
    symbol: Optional[str] = Query(default=None, description="Filter by ticker symbol"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """List news events with optional filters."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    events = db.fetch_news_events_json(
        limit=limit,
        triggered_only=triggered_only,
        from_date=from_date,
        to_date=to_date,
        symbol=symbol,
    )
    return events


@app.get("/news/{symbol}", response_model=List[NewsEvent])
async def get_news_by_symbol(
    symbol: str,
    limit: int = Query(default=20, ge=1, le=500),
    from_date: Optional[str] = Query(default=None, description="Start date (ISO format or 'today')"),
    to_date: Optional[str] = Query(default=None, description="End date (ISO format)"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get news events for a specific ticker symbol."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    events = db.fetch_news_events_json(
        limit=limit,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
    )
    return events


@app.get("/trades", response_model=List[CompletedTrade])
async def list_trades(
    limit: int = Query(default=100, ge=1, le=1000),
    from_date: Optional[str] = Query(default=None, description="Start date (ISO format or 'today')"),
    to_date: Optional[str] = Query(default=None, description="End date (ISO format)"),
    ticker: Optional[str] = Query(default=None, description="Filter by ticker symbol"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """List completed trades with actual fills and P&L (for Journal)."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    trades = db.fetch_completed_trades(
        limit=limit,
        from_date=from_date,
        to_date=to_date,
        ticker=ticker,
    )
    return trades


# ==============================================================================
# Event Ingestion Endpoints (from News Trader)
# ==============================================================================

@app.post("/events/news-received")
async def event_news_received(
    req: NewsReceivedRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """News received from Pub/Sub."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="news_received",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "headline": req.headline,
            "tickers": req.tickers,
            "source": req.source,
            "pub_time": req.pub_time,
            "news_age_ms": req.news_age_ms,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


@app.post("/events/news-decision")
async def event_news_decision(
    req: NewsDecisionRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Trading decision made for news."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="news_decision",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "decision": req.decision,
            "skip_reason": req.skip_reason,
            "volume_check_ms": req.volume_check_ms,
            "volume_found": req.volume_found,
            "volume_threshold": req.volume_threshold,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


@app.post("/events/strategy-spawned")
async def event_strategy_spawned(
    req: StrategySpawnedRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Strategy spawned for a ticker."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="strategy_spawned",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "strategy_id": req.strategy_id,
            "strategy_type": req.strategy_type,
            "ticker": req.ticker,
            "side": req.side,
            "position_size_usd": req.position_size_usd,
            "entry_price": req.entry_price,
            "exit_delay_seconds": req.exit_delay_seconds,
            "headline": req.headline,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


@app.post("/events/order-placed")
async def event_order_placed(
    req: OrderPlacedRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Order submitted to Alpaca."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="order_placed",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "strategy_id": req.strategy_id,
            "order_id": req.order_id,
            "alpaca_order_id": req.alpaca_order_id,
            "order_role": req.order_role,
            "side": req.side,
            "order_type": req.order_type,
            "qty": req.qty,
            "limit_price": req.limit_price,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


@app.post("/events/order-filled")
async def event_order_filled(
    req: OrderFilledRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Order filled."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="order_filled",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "strategy_id": req.strategy_id,
            "order_id": req.order_id,
            "order_role": req.order_role,
            "fill_price": req.fill_price,
            "qty": req.qty,
            "slippage": req.slippage,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


@app.post("/events/order-cancelled")
async def event_order_cancelled(
    req: OrderCancelledRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Order cancelled."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="order_cancelled",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "strategy_id": req.strategy_id,
            "order_id": req.order_id,
            "reason": req.reason,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


@app.post("/events/strategy-stopped")
async def event_strategy_stopped(
    req: StrategyStoppedRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Strategy completed/stopped."""
    verify_api_key(x_api_key)

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="strategy_stopped",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=req.news_id,
        data={
            "strategy_id": req.strategy_id,
            "reason": req.reason,
            "pnl": req.pnl,
            "pnl_percent": req.pnl_percent,
            "duration_ms": req.duration_ms,
        },
    )

    await event_store.add_event(event)
    return {"status": "ok", "event_id": event.id}


# ==============================================================================
# SSE Streaming Endpoint
# ==============================================================================

@app.get("/stream")
async def event_stream(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key (alternative to header for SSE)"),
):
    """Server-Sent Events stream for real-time updates.

    Note: EventSource browsers API doesn't support custom headers,
    so we accept API key via query param as well.
    """
    # Accept API key from either header or query param
    key_to_verify = x_api_key or api_key
    verify_api_key(key_to_verify)

    async def generate():
        queue = await event_store.subscribe()

        try:
            # Send initial connection message
            yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

            # Send recent events as initial state
            # First try in-memory events, then fall back to database
            recent = event_store.get_recent_events(limit=50)

            if not recent and DB_PATH:
                # Load from database if in-memory is empty (e.g., after restart)
                try:
                    db = get_trade_db(DB_PATH)
                    db_news = db.fetch_news_events_json(limit=50, triggered_only=False)
                    # Convert database news to PipelineEvent format
                    for news in reversed(db_news):  # Oldest first
                        event = {
                            'id': f"db_{news['id']}",
                            'type': 'news_received',
                            'timestamp': news.get('pub_time', datetime.now(timezone.utc).isoformat()),
                            'news_id': news['id'],
                            'data': {
                                'headline': news.get('headline', ''),
                                'tickers': news.get('tickers', []),
                                'source': news.get('source'),
                                'news_age_ms': news.get('news_age_ms'),
                                'pub_time': news.get('pub_time'),
                            }
                        }
                        recent.append(event)

                        # Add decision event if available
                        if news.get('decision'):
                            db_decision = news.get('decision')
                            db_skip_reason = news.get('skip_reason')

                            # Normalize decision format: DB stores 'skip_no_tickers' but
                            # real-time events send 'skip' + skip_reason='no_tickers'
                            if db_decision.startswith('skip_') and not db_skip_reason:
                                # Extract reason from combined decision field
                                normalized_decision = 'skip'
                                normalized_skip_reason = db_decision.replace('skip_', '').replace('_', ' ')
                            else:
                                normalized_decision = db_decision
                                normalized_skip_reason = db_skip_reason

                            decision_event = {
                                'id': f"db_{news['id']}_decision",
                                'type': 'news_decision',
                                'timestamp': news.get('pub_time', datetime.now(timezone.utc).isoformat()),
                                'news_id': news['id'],
                                'data': {
                                    'decision': normalized_decision,
                                    'skip_reason': normalized_skip_reason,
                                    'strategies_spawned': news.get('strategies_spawned', 0),
                                }
                            }
                            recent.append(decision_event)
                except Exception as e:
                    print(f"[SSE] Error loading from DB: {e}")

            yield f"event: initial_state\ndata: {json.dumps({'events': recent})}\n\n"

            # Send active strategies
            active = list(event_store.active_strategies.values())
            yield f"event: active_strategies\ndata: {json.dumps({'strategies': active})}\n\n"

            last_heartbeat = datetime.now(timezone.utc)

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    # Wait for events with timeout for heartbeat
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=HEARTBEAT_INTERVAL
                    )

                    # Send event
                    yield f"event: {event.type}\ndata: {json.dumps(asdict(event))}\n\n"

                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                    last_heartbeat = datetime.now(timezone.utc)

        finally:
            await event_store.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ==============================================================================
# Active Strategies Endpoints
# ==============================================================================

@app.get("/strategies/active")
async def get_active_strategies(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get currently running strategies."""
    verify_api_key(x_api_key)

    strategies = list(event_store.active_strategies.values())
    return {"strategies": strategies, "count": len(strategies)}


@app.post("/strategies/{strategy_id}/exit")
async def manual_exit_strategy(
    strategy_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Request manual early exit for a strategy."""
    verify_api_key(x_api_key)

    if strategy_id not in event_store.active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found or already closed")

    # Note: This would need to communicate with the actual trading system
    # For now, we just emit an event
    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="manual_exit_requested",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=event_store.active_strategies[strategy_id].get("news_id", ""),
        data={"strategy_id": strategy_id},
    )
    await event_store.add_event(event)

    return {"status": "exit_requested", "strategy_id": strategy_id}


@app.post("/strategies/{strategy_id}/extend")
async def extend_strategy_timer(
    strategy_id: str,
    minutes: int = Query(default=2, ge=1, le=30),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Extend the exit timer for a strategy."""
    verify_api_key(x_api_key)

    if strategy_id not in event_store.active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found or already closed")

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="timer_extend_requested",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=event_store.active_strategies[strategy_id].get("news_id", ""),
        data={"strategy_id": strategy_id, "extend_minutes": minutes},
    )
    await event_store.add_event(event)

    return {"status": "extend_requested", "strategy_id": strategy_id, "minutes": minutes}


@app.post("/strategies/{strategy_id}/cancel")
async def cancel_strategy_order(
    strategy_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Cancel pending order for a strategy."""
    verify_api_key(x_api_key)

    if strategy_id not in event_store.active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found or already closed")

    strategy = event_store.active_strategies[strategy_id]
    if strategy.get("status") != "pending_entry":
        raise HTTPException(status_code=400, detail="Strategy not in pending_entry status")

    event = PipelineEvent(
        id=str(uuid.uuid4()),
        type="cancel_order_requested",
        timestamp=datetime.now(timezone.utc).isoformat(),
        news_id=strategy.get("news_id", ""),
        data={"strategy_id": strategy_id},
    )
    await event_store.add_event(event)

    return {"status": "cancel_requested", "strategy_id": strategy_id}


# ==============================================================================
# Strategy Detail & Market Data Endpoints
# ==============================================================================

@app.get("/strategies/{strategy_id}")
async def get_strategy_by_id(
    strategy_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get a specific strategy execution by ID."""
    verify_api_key(x_api_key)
    db = get_trade_db(DB_PATH)
    strategy = db.get_strategy_by_id(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@app.get("/market/bars/{ticker}")
async def get_market_bars(
    ticker: str,
    from_ts: int = Query(..., description="Start timestamp in milliseconds"),
    to_ts: int = Query(..., description="End timestamp in milliseconds"),
    timeframe: str = Query(default="1", description="Bar multiplier: 1, 5, 15"),
    timespan: str = Query(default="second", description="Bar unit: second, minute"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Proxy to Polygon.io aggregates endpoint for OHLCV data."""
    verify_api_key(x_api_key)

    if not POLYGON_API_KEY:
        raise HTTPException(status_code=500, detail="Polygon API key not configured")

    # Validate timespan
    if timespan not in ("second", "minute"):
        raise HTTPException(status_code=400, detail="timespan must be 'second' or 'minute'")

    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{timeframe}/{timespan}/{from_ts}/{to_ts}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Polygon API error: {response.text}"
            )
        return response.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from Polygon: {str(e)}")


@app.get("/market/bars/{ticker}/ms")
async def get_market_bars_ms(
    ticker: str,
    from_ts: int = Query(..., description="Start timestamp in milliseconds"),
    to_ts: int = Query(..., description="End timestamp in milliseconds"),
    interval_ms: int = Query(default=100, description="Bar interval: 100, 250, or 500 ms"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Fetch trades from Polygon and aggregate into millisecond OHLCV bars."""
    verify_api_key(x_api_key)

    if not POLYGON_API_KEY:
        raise HTTPException(status_code=500, detail="Polygon API key not configured")

    # Validate interval
    if interval_ms not in (100, 250, 500):
        raise HTTPException(status_code=400, detail="interval_ms must be 100, 250, or 500")

    # Convert ms timestamps to nanoseconds for Polygon API
    from_ns = from_ts * 1_000_000
    to_ns = to_ts * 1_000_000

    # Fetch all trades in the time range (with pagination)
    all_trades = []
    next_url = None
    base_url = f"https://api.polygon.io/v3/trades/{ticker}"

    while True:
        if next_url:
            url = next_url
            params = {"apiKey": POLYGON_API_KEY}
        else:
            url = base_url
            params = {
                "timestamp.gte": from_ns,
                "timestamp.lte": to_ns,
                "order": "asc",
                "limit": 50000,
                "apiKey": POLYGON_API_KEY,
            }

        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Polygon API error: {response.text}"
                )
            data = response.json()
            trades = data.get("results", [])
            all_trades.extend(trades)

            # Check for pagination
            next_url = data.get("next_url")
            if not next_url or len(trades) == 0:
                break

        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch from Polygon: {str(e)}")

    if not all_trades:
        return {"results": [], "resultsCount": 0, "ticker": ticker, "status": "OK"}

    # Aggregate trades into millisecond bars
    bars = []
    current_bar = None
    current_bucket_start = None

    for trade in all_trades:
        # Use sip_timestamp (nanoseconds) -> convert to milliseconds
        trade_ts_ns = trade.get("sip_timestamp") or trade.get("participant_timestamp")
        if not trade_ts_ns:
            continue
        trade_ts_ms = trade_ts_ns // 1_000_000
        price = trade.get("price")
        size = trade.get("size", 0)

        if price is None:
            continue

        # Calculate which bucket this trade belongs to
        bucket_start = (trade_ts_ms // interval_ms) * interval_ms

        if current_bucket_start != bucket_start:
            # Save previous bar if exists
            if current_bar:
                bars.append(current_bar)

            # Start new bar
            current_bucket_start = bucket_start
            current_bar = {
                "t": bucket_start,  # timestamp in ms
                "o": price,         # open
                "h": price,         # high
                "l": price,         # low
                "c": price,         # close
                "v": size,          # volume
                "vw": price * size, # volume-weighted sum (will divide later)
                "n": 1,             # trade count
            }
        else:
            # Update current bar
            current_bar["h"] = max(current_bar["h"], price)
            current_bar["l"] = min(current_bar["l"], price)
            current_bar["c"] = price
            current_bar["v"] += size
            current_bar["vw"] += price * size
            current_bar["n"] += 1

    # Don't forget the last bar
    if current_bar:
        bars.append(current_bar)

    # Calculate VWAP for each bar
    for bar in bars:
        if bar["v"] > 0:
            bar["vw"] = bar["vw"] / bar["v"]
        else:
            bar["vw"] = bar["c"]

    return {
        "results": bars,
        "resultsCount": len(bars),
        "ticker": ticker,
        "status": "OK",
        "interval_ms": interval_ms,
    }


# ==============================================================================
# Stats Endpoints
# ==============================================================================

@app.get("/stats/latency")
async def get_latency_stats(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get latency percentiles for pipeline stages."""
    verify_api_key(x_api_key)

    def calc_stats(samples: List[float]) -> Dict[str, float]:
        if not samples:
            return {"avg": 0, "p50": 0, "p99": 0, "max": 0, "sample_count": 0}

        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        return {
            "avg": sum(sorted_samples) / n,
            "p50": sorted_samples[n // 2],
            "p99": sorted_samples[int(n * 0.99)] if n > 1 else sorted_samples[-1],
            "max": sorted_samples[-1],
            "sample_count": n,
        }

    return {
        "news_to_decision": calc_stats(event_store.latency_samples.get("news_to_decision", [])),
        "decision_to_order": calc_stats(event_store.latency_samples.get("decision_to_order", [])),
        "order_to_fill": calc_stats(event_store.latency_samples.get("order_to_fill", [])),
        "total_news_to_fill": calc_stats(event_store.latency_samples.get("total_news_to_fill", [])),
    }


@app.get("/stats/skips")
async def get_skip_analysis(
    days: int = Query(default=1, ge=1, le=30),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get skip reason breakdown."""
    verify_api_key(x_api_key)

    db = get_trade_db(DB_PATH)
    summary = db.get_news_summary(days=days)

    total = summary.get("total_news", 0)
    triggered = summary.get("triggered", 0)
    skipped = total - triggered

    by_reason = []
    for reason in ["skip_no_tickers", "skip_no_volume", "skip_too_old", "skip_position_exists"]:
        count = summary.get(reason, 0)
        if count > 0:
            by_reason.append({
                "reason": reason.replace("skip_", ""),
                "count": count,
                "percentage": (count / skipped * 100) if skipped > 0 else 0,
            })

    return {
        "period": f"{days} day(s)",
        "total": total,
        "triggered": triggered,
        "skipped": skipped,
        "by_reason": by_reason,
        "near_misses": [],  # Would need additional query to find near misses
    }


@app.get("/stats/performance")
async def get_performance_stats(
    days: int = Query(default=1, ge=1, le=30),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get performance statistics."""
    verify_api_key(x_api_key)

    db = get_trade_db(DB_PATH)
    pnl_summary = db.get_pnl_summary(days=days)
    trades = db.get_trade_pnl(days=days)

    # Group by hour
    by_hour = {}
    for trade in trades:
        if trade.get("entry_time"):
            try:
                dt = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
                hour = dt.hour
                if hour not in by_hour:
                    by_hour[hour] = {"trades": 0, "pnl": 0, "wins": 0}
                by_hour[hour]["trades"] += 1
                by_hour[hour]["pnl"] += trade.get("pnl") or 0
                if (trade.get("pnl") or 0) > 0:
                    by_hour[hour]["wins"] += 1
            except:
                pass

    hourly_stats = []
    for hour in sorted(by_hour.keys()):
        h = by_hour[hour]
        hourly_stats.append({
            "hour": hour,
            "trades": h["trades"],
            "pnl": h["pnl"],
            "win_rate": (h["wins"] / h["trades"] * 100) if h["trades"] > 0 else 0,
        })

    # Group by strategy
    by_strategy = {}
    for trade in trades:
        name = trade.get("strategy_name", "unknown")
        if name not in by_strategy:
            by_strategy[name] = {"trades": 0, "pnl": 0, "wins": 0}
        by_strategy[name]["trades"] += 1
        by_strategy[name]["pnl"] += trade.get("pnl") or 0
        if (trade.get("pnl") or 0) > 0:
            by_strategy[name]["wins"] += 1

    strategy_stats = []
    for name, s in by_strategy.items():
        strategy_stats.append({
            "strategy": name,
            "trades": s["trades"],
            "pnl": s["pnl"],
            "win_rate": (s["wins"] / s["trades"] * 100) if s["trades"] > 0 else 0,
        })

    return {
        "period": f"{days} day(s)",
        "total_trades": pnl_summary.get("trade_count", 0),
        "total_pnl": pnl_summary.get("total_pnl", 0),
        "win_rate": pnl_summary.get("win_rate", 0),
        "avg_pnl": (pnl_summary.get("total_pnl", 0) / pnl_summary.get("trade_count", 1)) if pnl_summary.get("trade_count", 0) > 0 else 0,
        "by_hour": hourly_stats,
        "by_strategy": strategy_stats,
    }


@app.get("/stats/summary")
async def get_summary_stats(
    days: int = Query(default=1, ge=1, le=30),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get summary statistics for dashboard."""
    verify_api_key(x_api_key)

    db = get_trade_db(DB_PATH)
    news_summary = db.get_news_summary(days=days)
    pnl_summary = db.get_pnl_summary(days=days)

    total_news = news_summary.get("total_news", 0) or 0
    triggered = news_summary.get("triggered", 0) or 0
    total_strategies = news_summary.get("total_strategies", 0) or 0
    active_count = len(event_store.active_strategies)
    closed = max(0, total_strategies - active_count)

    total_pnl = pnl_summary.get("total_pnl", 0) or 0
    trade_count = pnl_summary.get("trade_count", 0) or 0
    winners = pnl_summary.get("winners", 0) or 0
    losers = pnl_summary.get("losers", 0) or 0
    gross_profit = pnl_summary.get("gross_profit", 0) or 0
    gross_loss = pnl_summary.get("gross_loss", 0) or 0

    return {
        "period": f"{days} day(s)",
        "news": {
            "total": total_news,
            "triggered": triggered,
            "triggered_percent": (triggered / total_news * 100) if total_news > 0 else 0,
            "skipped": total_news - triggered,
            "pending": 0,
            "skip_reasons": news_summary.get("skip_reasons", {}),
        },
        "strategies": {
            "total_spawned": total_strategies,
            "total": total_strategies,
            "active": active_count,
            "closed": closed,
        },
        "pnl": {
            "total": total_pnl,
            "trade_count": trade_count,
            "win_rate": pnl_summary.get("win_rate", 0) or 0,
            "open_trades": pnl_summary.get("open_trades", 0) or 0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "winners": winners,
            "losers": losers,
        },
    }


# ==============================================================================
# Recent Events Endpoint
# ==============================================================================

@app.get("/events/recent")
async def get_recent_events(
    limit: int = Query(default=50, ge=1, le=500),
    event_type: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get recent pipeline events."""
    verify_api_key(x_api_key)

    events = event_store.get_recent_events(limit=limit, event_type=event_type)
    return {"events": events, "count": len(events)}


# ==============================================================================
# Static File Serving (SPA Frontend)
# ==============================================================================

# Mount static assets if the directory exists
if STATIC_DIR.exists():
    # Serve static assets (js, css, images)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    async def serve_index():
        """Serve the SPA index.html."""
        return FileResponse(STATIC_DIR / "index.html")

    # Catch-all route for SPA client-side routing
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve index.html for all non-API routes (SPA routing)."""
        # Check if it's a static file
        file_path = STATIC_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html for client-side routing
        return FileResponse(STATIC_DIR / "index.html")


# ==============================================================================
# Main
# ==============================================================================

if __name__ == "__main__":
    if not API_KEY:
        print("WARNING: NEWS_API_KEY not set. API authentication will fail.")
        print("Set it with: export NEWS_API_KEY=your-secret-key")

    print(f"Starting Pako News API v2.0 on port {PORT}")
    print(f"Database: {DB_PATH or 'auto-detect'}")
    print(f"SSE streaming enabled on /stream")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
