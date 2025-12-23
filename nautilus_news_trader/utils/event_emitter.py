#!/usr/bin/env python3
"""
Event Emitter - Sends pipeline events to the News API for real-time monitoring.

This module provides a simple, non-blocking way to emit events from the News Trader
to the News API. Events are sent asynchronously to avoid impacting trading latency.

Usage:
    from utils.event_emitter import emit_news_received, emit_news_decision, ...

    # In your trading code:
    emit_news_received(news_id, headline, tickers, source, pub_time, news_age_ms)
    emit_news_decision(news_id, decision="trade", volume_found=245.5)
    emit_strategy_spawned(news_id, strategy_id, "volume", "AAPL", 5000.0, 198.50, 420)
"""

import os
import logging
import threading
import queue
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

import requests

# Configuration from environment
NEWS_API_URL = os.environ.get("NEWS_API_URL", "http://localhost:8100")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")
EMIT_ENABLED = os.environ.get("NEWS_API_EMIT_ENABLED", "true").lower() == "true"

# Logger
logger = logging.getLogger(__name__)

# Event queue for async sending
_event_queue: queue.Queue = queue.Queue(maxsize=1000)
_worker_thread: Optional[threading.Thread] = None
_shutdown = threading.Event()


def _send_event(endpoint: str, data: Dict[str, Any]) -> bool:
    """Send an event to the News API."""
    if not EMIT_ENABLED:
        return True

    if not NEWS_API_KEY:
        logger.warning("[EventEmitter] NEWS_API_KEY not set, skipping event emission")
        return False

    try:
        url = f"{NEWS_API_URL}{endpoint}"
        headers = {
            "X-API-Key": NEWS_API_KEY,
            "Content-Type": "application/json",
        }

        response = requests.post(url, json=data, headers=headers, timeout=5)

        if response.status_code == 200:
            logger.debug(f"[EventEmitter] Event sent: {endpoint}")
            return True
        else:
            logger.warning(f"[EventEmitter] Failed to send event: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.Timeout:
        logger.warning(f"[EventEmitter] Timeout sending event to {endpoint}")
        return False
    except requests.exceptions.ConnectionError:
        logger.warning(f"[EventEmitter] Connection error sending event to {endpoint}")
        return False
    except Exception as e:
        logger.error(f"[EventEmitter] Error sending event: {e}")
        return False


def _worker():
    """Background worker that sends events from the queue."""
    logger.info("[EventEmitter] Worker thread started")

    while not _shutdown.is_set():
        try:
            # Wait for an event with timeout
            endpoint, data = _event_queue.get(timeout=1.0)
            _send_event(endpoint, data)
            _event_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"[EventEmitter] Worker error: {e}")

    logger.info("[EventEmitter] Worker thread stopped")


def _enqueue_event(endpoint: str, data: Dict[str, Any]):
    """Add an event to the queue for async sending."""
    global _worker_thread

    # Start worker thread if not running
    if _worker_thread is None or not _worker_thread.is_alive():
        _shutdown.clear()
        _worker_thread = threading.Thread(target=_worker, daemon=True)
        _worker_thread.start()

    try:
        _event_queue.put_nowait((endpoint, data))
    except queue.Full:
        logger.warning("[EventEmitter] Event queue full, dropping event")


def shutdown():
    """Shutdown the event emitter gracefully."""
    global _worker_thread
    _shutdown.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=5.0)
        _worker_thread = None


# ==============================================================================
# Event Emission Functions
# ==============================================================================

def emit_news_received(
    news_id: str,
    headline: str,
    tickers: List[str],
    source: str,
    pub_time: str,
    news_age_ms: int,
):
    """
    Emit event when news is received from Pub/Sub.

    Args:
        news_id: Unique identifier for the news item
        headline: News headline text
        tickers: List of ticker symbols mentioned
        source: News source (e.g., "Benzinga")
        pub_time: Publication timestamp (ISO format)
        news_age_ms: Age of the news in milliseconds when received
    """
    _enqueue_event("/events/news-received", {
        "news_id": news_id,
        "headline": headline,
        "tickers": tickers,
        "source": source,
        "pub_time": pub_time,
        "news_age_ms": news_age_ms,
    })


def emit_news_decision(
    news_id: str,
    decision: str,
    skip_reason: Optional[str] = None,
    volume_check_ms: Optional[int] = None,
    volume_found: Optional[float] = None,
    volume_threshold: Optional[float] = None,
):
    """
    Emit event when a trading decision is made for news.

    Args:
        news_id: News item ID
        decision: "trade" or "skip"
        skip_reason: If skipped, reason (no_tickers, no_volume, too_old, etc.)
        volume_check_ms: Time spent checking volume (milliseconds)
        volume_found: Volume percentage found (if checked)
        volume_threshold: Volume threshold used
    """
    _enqueue_event("/events/news-decision", {
        "news_id": news_id,
        "decision": decision,
        "skip_reason": skip_reason,
        "volume_check_ms": volume_check_ms,
        "volume_found": volume_found,
        "volume_threshold": volume_threshold,
    })


def emit_strategy_spawned(
    news_id: str,
    strategy_id: str,
    strategy_type: str,
    ticker: str,
    position_size_usd: float,
    entry_price: float,
    exit_delay_seconds: int,
    side: str = "long",
    headline: Optional[str] = None,
):
    """
    Emit event when a strategy is spawned for a ticker.

    Args:
        news_id: News item ID that triggered the strategy
        strategy_id: Unique strategy identifier
        strategy_type: Type of strategy (e.g., "volume", "trend")
        ticker: Stock symbol
        position_size_usd: Target position size in USD
        entry_price: Target entry price
        exit_delay_seconds: Seconds until scheduled exit
        side: "long" or "short"
        headline: News headline for display
    """
    _enqueue_event("/events/strategy-spawned", {
        "news_id": news_id,
        "strategy_id": strategy_id,
        "strategy_type": strategy_type,
        "ticker": ticker,
        "side": side,
        "position_size_usd": position_size_usd,
        "entry_price": entry_price,
        "exit_delay_seconds": exit_delay_seconds,
        "headline": headline,
    })


def emit_order_placed(
    news_id: str,
    strategy_id: str,
    order_id: str,
    order_role: str,
    side: str,
    order_type: str,
    qty: float,
    limit_price: Optional[float] = None,
    alpaca_order_id: Optional[str] = None,
):
    """
    Emit event when an order is submitted to Alpaca.

    Args:
        news_id: News item ID
        strategy_id: Strategy identifier
        order_id: Local order ID
        order_role: "entry" or "exit"
        side: "buy" or "sell"
        order_type: "market" or "limit"
        qty: Order quantity
        limit_price: Limit price (if limit order)
        alpaca_order_id: Alpaca's order ID (if available)
    """
    _enqueue_event("/events/order-placed", {
        "news_id": news_id,
        "strategy_id": strategy_id,
        "order_id": order_id,
        "alpaca_order_id": alpaca_order_id,
        "order_role": order_role,
        "side": side,
        "order_type": order_type,
        "qty": qty,
        "limit_price": limit_price,
    })


def emit_order_filled(
    news_id: str,
    strategy_id: str,
    order_id: str,
    order_role: str,
    fill_price: float,
    qty: float,
    slippage: Optional[float] = None,
):
    """
    Emit event when an order is filled.

    Args:
        news_id: News item ID
        strategy_id: Strategy identifier
        order_id: Local order ID
        order_role: "entry" or "exit"
        fill_price: Actual fill price
        qty: Filled quantity
        slippage: Slippage vs limit price (if applicable)
    """
    _enqueue_event("/events/order-filled", {
        "news_id": news_id,
        "strategy_id": strategy_id,
        "order_id": order_id,
        "order_role": order_role,
        "fill_price": fill_price,
        "qty": qty,
        "slippage": slippage,
    })


def emit_order_cancelled(
    news_id: str,
    strategy_id: str,
    order_id: str,
    reason: str,
):
    """
    Emit event when an order is cancelled.

    Args:
        news_id: News item ID
        strategy_id: Strategy identifier
        order_id: Local order ID
        reason: Cancellation reason
    """
    _enqueue_event("/events/order-cancelled", {
        "news_id": news_id,
        "strategy_id": strategy_id,
        "order_id": order_id,
        "reason": reason,
    })


def emit_strategy_stopped(
    news_id: str,
    strategy_id: str,
    reason: str,
    pnl: Optional[float] = None,
    pnl_percent: Optional[float] = None,
    duration_ms: Optional[int] = None,
):
    """
    Emit event when a strategy is stopped/completed.

    Args:
        news_id: News item ID
        strategy_id: Strategy identifier
        reason: Stop reason (scheduled_exit, manual, error, cancelled)
        pnl: Realized P&L in dollars
        pnl_percent: Realized P&L as percentage
        duration_ms: Strategy duration in milliseconds
    """
    _enqueue_event("/events/strategy-stopped", {
        "news_id": news_id,
        "strategy_id": strategy_id,
        "reason": reason,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "duration_ms": duration_ms,
    })


# ==============================================================================
# Utility Functions
# ==============================================================================

def is_enabled() -> bool:
    """Check if event emission is enabled."""
    return EMIT_ENABLED and bool(NEWS_API_KEY)


def get_queue_size() -> int:
    """Get the number of pending events in the queue."""
    return _event_queue.qsize()


def configure(api_url: str = None, api_key: str = None, enabled: bool = None):
    """
    Configure the event emitter at runtime.

    Args:
        api_url: News API base URL
        api_key: API key for authentication
        enabled: Enable/disable event emission
    """
    global NEWS_API_URL, NEWS_API_KEY, EMIT_ENABLED

    if api_url is not None:
        NEWS_API_URL = api_url
    if api_key is not None:
        NEWS_API_KEY = api_key
    if enabled is not None:
        EMIT_ENABLED = enabled

    logger.info(f"[EventEmitter] Configured: URL={NEWS_API_URL}, enabled={EMIT_ENABLED}")
