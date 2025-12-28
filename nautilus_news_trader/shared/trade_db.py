#!/usr/bin/env python3
"""
SQLite database for storing news events, strategies, and trade results.

This module provides persistent storage for:
- News events received from Benzinga
- Strategies spawned for each news event
- Orders placed and their fill status
- Trade P&L calculations

Database location: /opt/news-trader/data/trades.db (production)
                   ./data/trades.db (local development)
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import threading


class TradeDatabase:
    """SQLite database for trade storage and analysis."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None):
        """Singleton pattern - one database connection per process."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection and create tables if needed."""
        if self._initialized:
            return

        # Determine database path
        if db_path:
            self.db_path = db_path
        elif os.path.exists("/opt/news-trader"):
            self.db_path = "/opt/news-trader/data/trades.db"
        else:
            self.db_path = str(Path(__file__).parent.parent / "data" / "trades.db")

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # Create connection with thread safety
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Create tables
        self._create_tables()

        self._initialized = True
        print(f"[TradeDB] Initialized database at {self.db_path}")

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # News events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_events (
                id TEXT PRIMARY KEY,
                headline TEXT,
                tickers TEXT,
                url TEXT,
                source TEXT,
                tags TEXT,
                pub_time TEXT,
                captured_at TEXT,
                processed_at TEXT,
                age_seconds REAL,

                polygon_volume INTEGER,
                polygon_price REAL,
                polygon_bars INTEGER,

                decision TEXT,
                skip_reason TEXT,
                strategies_spawned INTEGER DEFAULT 0
            )
        """)

        # Strategies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                news_id TEXT,
                correlation_id TEXT,
                ticker TEXT,
                strategy_type TEXT,
                strategy_name TEXT,
                position_size_usd REAL,
                entry_price REAL,
                started_at TEXT,
                stopped_at TEXT,
                stop_reason TEXT,

                FOREIGN KEY (news_id) REFERENCES news_events(id)
            )
        """)

        # Orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                strategy_id TEXT,
                alpaca_order_id TEXT,
                side TEXT,
                qty REAL,
                limit_price REAL,
                filled_qty REAL,
                filled_price REAL,
                status TEXT,
                submitted_at TEXT,
                filled_at TEXT,
                cancelled_at TEXT,

                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        """)

        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_pub_time ON news_events(pub_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_decision ON news_events(decision)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategies_ticker ON strategies(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategies_news ON strategies(news_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id)")

        self.conn.commit()

    @contextmanager
    def _cursor(self):
        """Context manager for cursor with automatic commit/rollback."""
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e

    # ==================== NEWS EVENTS ====================

    def insert_news_event(
        self,
        news_id: str,
        headline: str,
        tickers: List[str],
        url: str = "",
        source: str = "",
        tags: List[str] = None,
        pub_time: datetime = None,
        captured_at: datetime = None,
        age_seconds: float = None,
        polygon_volume: int = None,
        polygon_price: float = None,
        polygon_bars: int = None,
        decision: str = None,
        skip_reason: str = None,
    ) -> bool:
        """Insert or update a news event."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO news_events
                    (id, headline, tickers, url, source, tags, pub_time, captured_at,
                     processed_at, age_seconds, polygon_volume, polygon_price, polygon_bars,
                     decision, skip_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news_id,
                    headline,
                    json.dumps(tickers) if tickers else "[]",
                    url,
                    source,
                    json.dumps(tags) if tags else "[]",
                    pub_time.isoformat() if pub_time else None,
                    captured_at.isoformat() if captured_at else None,
                    datetime.now(timezone.utc).isoformat(),
                    age_seconds,
                    polygon_volume,
                    polygon_price,
                    polygon_bars,
                    decision,
                    skip_reason,
                ))
            return True
        except Exception as e:
            print(f"[TradeDB] Error inserting news event: {e}")
            return False

    def update_news_decision(
        self,
        news_id: str,
        decision: str,
        skip_reason: str = None,
        polygon_volume: int = None,
        polygon_price: float = None,
        polygon_bars: int = None,
    ):
        """Update decision for a news event."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE news_events
                    SET decision = ?, skip_reason = ?,
                        polygon_volume = COALESCE(?, polygon_volume),
                        polygon_price = COALESCE(?, polygon_price),
                        polygon_bars = COALESCE(?, polygon_bars)
                    WHERE id = ?
                """, (decision, skip_reason, polygon_volume, polygon_price, polygon_bars, news_id))
        except Exception as e:
            print(f"[TradeDB] Error updating news decision: {e}")

    def increment_strategies_spawned(self, news_id: str):
        """Increment the count of strategies spawned for a news event."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE news_events
                    SET strategies_spawned = strategies_spawned + 1
                    WHERE id = ?
                """, (news_id,))
        except Exception as e:
            print(f"[TradeDB] Error incrementing strategies: {e}")

    # ==================== STRATEGIES ====================

    def insert_strategy(
        self,
        strategy_id: str,
        news_id: str,
        correlation_id: str,
        ticker: str,
        strategy_type: str,
        strategy_name: str,
        position_size_usd: float,
        entry_price: float,
    ) -> bool:
        """Insert a new strategy record."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO strategies
                    (id, news_id, correlation_id, ticker, strategy_type, strategy_name,
                     position_size_usd, entry_price, started_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    strategy_id,
                    news_id,
                    correlation_id,
                    ticker,
                    strategy_type,
                    strategy_name,
                    position_size_usd,
                    entry_price,
                    datetime.now(timezone.utc).isoformat(),
                ))

            # Increment strategies count on news event
            self.increment_strategies_spawned(news_id)
            return True
        except Exception as e:
            print(f"[TradeDB] Error inserting strategy: {e}")
            return False

    def update_strategy_stopped(self, strategy_id: str, stop_reason: str = None):
        """Mark strategy as stopped."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE strategies
                    SET stopped_at = ?, stop_reason = ?
                    WHERE id = ?
                """, (datetime.now(timezone.utc).isoformat(), stop_reason, strategy_id))
        except Exception as e:
            print(f"[TradeDB] Error updating strategy stopped: {e}")

    # ==================== ORDERS ====================

    def insert_order(
        self,
        order_id: str,
        strategy_id: str,
        side: str,
        qty: float,
        limit_price: float,
        alpaca_order_id: str = None,
    ) -> bool:
        """Insert a new order record."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO orders
                    (id, strategy_id, alpaca_order_id, side, qty, limit_price,
                     filled_qty, status, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 'submitted', ?)
                """, (
                    order_id,
                    strategy_id,
                    alpaca_order_id,
                    side,
                    qty,
                    limit_price,
                    datetime.now(timezone.utc).isoformat(),
                ))
            return True
        except Exception as e:
            print(f"[TradeDB] Error inserting order: {e}")
            return False

    def update_order_filled(
        self,
        order_id: str,
        filled_qty: float,
        filled_price: float,
        status: str = "filled",
    ):
        """Update order with fill information."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE orders
                    SET filled_qty = ?, filled_price = ?, status = ?, filled_at = ?
                    WHERE id = ?
                """, (filled_qty, filled_price, status, datetime.now(timezone.utc).isoformat(), order_id))
        except Exception as e:
            print(f"[TradeDB] Error updating order filled: {e}")

    def update_order_cancelled(self, order_id: str):
        """Mark order as cancelled."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    UPDATE orders
                    SET status = 'cancelled', cancelled_at = ?
                    WHERE id = ?
                """, (datetime.now(timezone.utc).isoformat(), order_id))
        except Exception as e:
            print(f"[TradeDB] Error updating order cancelled: {e}")

    # ==================== ANALYSIS QUERIES ====================

    def get_trade_pnl(self, days: int = 1) -> List[Dict[str, Any]]:
        """Get P&L for all completed trades in the last N days."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    SELECT
                        s.id as strategy_id,
                        s.ticker,
                        s.strategy_name,
                        n.headline,
                        n.pub_time,
                        buy.filled_price as entry_price,
                        sell.filled_price as exit_price,
                        buy.filled_qty as qty,
                        (sell.filled_price - buy.filled_price) * buy.filled_qty as pnl,
                        CASE WHEN buy.filled_price > 0
                            THEN ((sell.filled_price / buy.filled_price) - 1) * 100
                            ELSE 0 END as pnl_pct,
                        buy.filled_at as entry_time,
                        sell.filled_at as exit_time
                    FROM strategies s
                    JOIN news_events n ON s.news_id = n.id
                    JOIN orders buy ON buy.strategy_id = s.id AND buy.side = 'buy' AND buy.status = 'filled'
                    LEFT JOIN orders sell ON sell.strategy_id = s.id AND sell.side = 'sell' AND sell.status = 'filled'
                    WHERE s.started_at >= datetime('now', ?)
                    ORDER BY s.started_at DESC
                """, (f'-{days} days',))

                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[TradeDB] Error getting trade PnL: {e}")
            return []

    def get_news_summary(self, days: int = 1) -> Dict[str, Any]:
        """Get summary of news processing in the last N days."""
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_news,
                        SUM(CASE WHEN decision = 'trade' THEN 1 ELSE 0 END) as traded,
                        SUM(CASE WHEN decision = 'skip_no_volume' THEN 1 ELSE 0 END) as skip_no_volume,
                        SUM(CASE WHEN decision = 'skip_too_old' THEN 1 ELSE 0 END) as skip_too_old,
                        SUM(CASE WHEN decision = 'skip_no_tickers' THEN 1 ELSE 0 END) as skip_no_tickers,
                        SUM(CASE WHEN decision = 'skip_position_exists' THEN 1 ELSE 0 END) as skip_position_exists,
                        SUM(strategies_spawned) as total_strategies
                    FROM news_events
                    WHERE processed_at >= datetime('now', ?)
                """, (f'-{days} days',))

                row = cursor.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            print(f"[TradeDB] Error getting news summary: {e}")
            return {}

    def get_pnl_summary(self, days: int = 1) -> Dict[str, Any]:
        """Get P&L summary for completed trades."""
        trades = self.get_trade_pnl(days)

        if not trades:
            return {"total_pnl": 0, "trade_count": 0, "win_rate": 0}

        completed = [t for t in trades if t.get('exit_price')]

        if not completed:
            return {"total_pnl": 0, "trade_count": 0, "win_rate": 0, "open_trades": len(trades)}

        total_pnl = sum(t['pnl'] or 0 for t in completed)
        winners = sum(1 for t in completed if (t['pnl'] or 0) > 0)

        return {
            "total_pnl": total_pnl,
            "trade_count": len(completed),
            "win_rate": winners / len(completed) * 100 if completed else 0,
            "open_trades": len(trades) - len(completed),
            "biggest_win": max((t['pnl'] or 0) for t in completed),
            "biggest_loss": min((t['pnl'] or 0) for t in completed),
        }

    # ==================== API QUERIES ====================

    def fetch_news_events_json(
        self,
        limit: int = 100,
        traded_only: bool = False,
        symbol: str = None,
        from_date: str = None,
        to_date: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch news events formatted for JSON API response.

        Args:
            limit: Maximum number of events to return
            traded_only: If True, only return events with decision='trade'
            symbol: If provided, filter to events containing this ticker
            from_date: If provided, only return events from this date (ISO format or 'today')
            to_date: If provided, only return events until this date (ISO format)

        Returns:
            List of news event dicts ready for JSON serialization
        """
        try:
            with self._cursor() as cursor:
                query = """
                    SELECT
                        id,
                        headline,
                        tickers,
                        pub_time,
                        source,
                        decision,
                        skip_reason,
                        strategies_spawned,
                        age_seconds
                    FROM news_events
                    WHERE 1=1
                """
                params = []

                if traded_only:
                    query += " AND decision = 'trade'"

                if symbol:
                    # Search within JSON array of tickers
                    query += " AND tickers LIKE ?"
                    params.append(f'%"{symbol.upper()}"%')

                if from_date:
                    # Handle 'today' shortcut
                    if from_date == 'today':
                        from_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    query += " AND date(pub_time) >= date(?)"
                    params.append(from_date)

                if to_date:
                    query += " AND date(pub_time) <= date(?)"
                    params.append(to_date)

                query += " ORDER BY pub_time DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": row["id"],
                        "headline": row["headline"],
                        "tickers": json.loads(row["tickers"]) if row["tickers"] else [],
                        "pub_time": row["pub_time"],
                        "source": row["source"],
                        "decision": row["decision"],
                        "skip_reason": row["skip_reason"],
                        "strategies_spawned": row["strategies_spawned"] or 0,
                        "news_age_ms": int(row["age_seconds"] * 1000) if row["age_seconds"] else None,
                    })

                return results
        except Exception as e:
            print(f"[TradeDB] Error fetching news events: {e}")
            return []

    def get_news_event_by_id(self, news_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single news event by its ID.

        Args:
            news_id: The news event ID

        Returns:
            News event dict or None if not found
        """
        try:
            with self._cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        headline,
                        tickers,
                        source,
                        pub_time,
                        decision,
                        skip_reason,
                        strategies_spawned,
                        age_seconds
                    FROM news_events
                    WHERE id = ?
                    """,
                    (news_id,),
                )
                row = cursor.fetchone()
                if row:
                    # Convert age_seconds to age_ms for consistency
                    age_ms = int(row["age_seconds"] * 1000) if row["age_seconds"] else None
                    return {
                        "id": row["id"],
                        "headline": row["headline"],
                        "tickers": json.loads(row["tickers"]) if row["tickers"] else [],
                        "source": row["source"],
                        "pub_time": row["pub_time"],
                        "decision": row["decision"],
                        "skip_reason": row["skip_reason"],
                        "strategies_spawned": row["strategies_spawned"] or 0,
                        "news_age_ms": age_ms,
                    }
                return None
        except Exception as e:
            print(f"[TradeDB] Error fetching news by ID: {e}")
            return None

    def get_strategies_for_news(self, news_id: str) -> List[Dict[str, Any]]:
        """
        Get all strategies spawned for a specific news event, with P&L.

        Args:
            news_id: The news event ID

        Returns:
            List of strategy dicts with order/P&L info
        """
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    SELECT
                        s.id,
                        s.ticker,
                        s.strategy_type,
                        s.strategy_name,
                        s.position_size_usd,
                        s.entry_price,
                        s.started_at,
                        s.stopped_at,
                        s.stop_reason,
                        buy.filled_price as actual_entry_price,
                        buy.filled_qty as qty,
                        sell.filled_price as exit_price,
                        CASE
                            WHEN sell.filled_price IS NOT NULL AND buy.filled_qty > 0
                            THEN (sell.filled_price - buy.filled_price) * buy.filled_qty
                            ELSE NULL
                        END as pnl,
                        CASE
                            WHEN s.stopped_at IS NOT NULL THEN 'closed'
                            WHEN sell.status = 'filled' THEN 'closed'
                            WHEN buy.status = 'filled' THEN 'open'
                            ELSE 'pending'
                        END as status
                    FROM strategies s
                    LEFT JOIN orders buy ON buy.strategy_id = s.id AND buy.side = 'buy'
                    LEFT JOIN orders sell ON sell.strategy_id = s.id AND sell.side = 'sell'
                    WHERE s.news_id = ?
                    ORDER BY s.started_at DESC
                """, (news_id,))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": row["id"],
                        "ticker": row["ticker"],
                        "strategy_type": row["strategy_type"],
                        "strategy_name": row["strategy_name"],
                        "position_size_usd": row["position_size_usd"],
                        "entry_price": row["actual_entry_price"] or row["entry_price"],
                        "exit_price": row["exit_price"],
                        "qty": row["qty"],
                        "pnl": row["pnl"],
                        "status": row["status"],
                        "started_at": row["started_at"],
                        "stopped_at": row["stopped_at"],
                        "stop_reason": row["stop_reason"],
                    })

                return results
        except Exception as e:
            print(f"[TradeDB] Error getting strategies for news: {e}")
            return []

    def get_strategy_by_id(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single strategy by its ID with full details including news and orders.

        Args:
            strategy_id: The strategy ID

        Returns:
            Strategy dict with news and order info, or None if not found
        """
        try:
            with self._cursor() as cursor:
                cursor.execute("""
                    SELECT
                        s.id,
                        s.news_id,
                        s.ticker,
                        s.strategy_type,
                        s.strategy_name,
                        s.position_size_usd,
                        s.entry_price as limit_entry_price,
                        s.started_at,
                        s.stopped_at,
                        s.stop_reason,
                        n.headline,
                        n.pub_time,
                        n.source,
                        buy.filled_price as entry_price,
                        buy.filled_qty as qty,
                        buy.filled_at as entry_time,
                        sell.filled_price as exit_price,
                        sell.filled_at as exit_time,
                        CASE
                            WHEN sell.filled_price IS NOT NULL AND buy.filled_qty > 0
                            THEN (sell.filled_price - buy.filled_price) * buy.filled_qty
                            ELSE NULL
                        END as pnl,
                        CASE
                            WHEN buy.filled_price > 0 AND sell.filled_price IS NOT NULL
                            THEN ((sell.filled_price / buy.filled_price) - 1) * 100
                            ELSE NULL
                        END as pnl_percent,
                        CASE
                            WHEN s.stopped_at IS NOT NULL THEN 'closed'
                            WHEN sell.status = 'filled' THEN 'closed'
                            WHEN buy.status = 'filled' THEN 'open'
                            ELSE 'pending'
                        END as status
                    FROM strategies s
                    LEFT JOIN news_events n ON s.news_id = n.id
                    LEFT JOIN orders buy ON buy.strategy_id = s.id AND buy.side = 'buy'
                    LEFT JOIN orders sell ON sell.strategy_id = s.id AND sell.side = 'sell'
                    WHERE s.id = ?
                """, (strategy_id,))

                row = cursor.fetchone()
                if row:
                    return {
                        "id": row["id"],
                        "news_id": row["news_id"],
                        "ticker": row["ticker"],
                        "strategy_type": row["strategy_type"],
                        "strategy_name": row["strategy_name"],
                        "position_size_usd": row["position_size_usd"],
                        "limit_entry_price": row["limit_entry_price"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "entry_time": row["entry_time"],
                        "exit_time": row["exit_time"],
                        "qty": row["qty"],
                        "pnl": row["pnl"],
                        "pnl_percent": row["pnl_percent"],
                        "status": row["status"],
                        "started_at": row["started_at"],
                        "stopped_at": row["stopped_at"],
                        "stop_reason": row["stop_reason"],
                        "headline": row["headline"],
                        "pub_time": row["pub_time"],
                        "source": row["source"],
                    }
                return None
        except Exception as e:
            print(f"[TradeDB] Error getting strategy by ID: {e}")
            return None

    def fetch_completed_trades(
        self,
        limit: int = 100,
        from_date: str = None,
        to_date: str = None,
        ticker: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch completed trades (strategies with both entry and exit fills) for Journal.

        Only returns trades where:
        - Entry order was filled
        - Exit order was filled
        - Has real P&L

        Args:
            limit: Maximum number of trades to return
            from_date: If provided, only return trades from this date (ISO format or 'today')
            to_date: If provided, only return trades until this date (ISO format)
            ticker: If provided, filter to trades for this ticker

        Returns:
            List of completed trade dicts ready for JSON serialization
        """
        try:
            with self._cursor() as cursor:
                query = """
                    SELECT
                        s.id,
                        s.news_id,
                        s.ticker,
                        s.strategy_type,
                        s.strategy_name,
                        s.position_size_usd,
                        s.started_at,
                        s.stopped_at,
                        s.stop_reason,
                        buy.filled_price as entry_price,
                        buy.filled_qty as qty,
                        buy.filled_at as entry_time,
                        sell.filled_price as exit_price,
                        sell.filled_at as exit_time,
                        (sell.filled_price - buy.filled_price) * buy.filled_qty as pnl,
                        CASE
                            WHEN buy.filled_price > 0
                            THEN ((sell.filled_price - buy.filled_price) / buy.filled_price) * 100
                            ELSE 0
                        END as pnl_percent,
                        n.headline,
                        n.pub_time,
                        n.source
                    FROM strategies s
                    INNER JOIN orders buy ON buy.strategy_id = s.id
                        AND buy.side = 'buy'
                        AND buy.status = 'filled'
                        AND buy.filled_price IS NOT NULL
                    INNER JOIN orders sell ON sell.strategy_id = s.id
                        AND sell.side = 'sell'
                        AND sell.status = 'filled'
                        AND sell.filled_price IS NOT NULL
                    LEFT JOIN news_events n ON n.id = s.news_id
                    WHERE 1=1
                """
                params = []

                if ticker:
                    query += " AND UPPER(s.ticker) = UPPER(?)"
                    params.append(ticker)

                if from_date:
                    if from_date == 'today':
                        from_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    query += " AND date(s.stopped_at) >= date(?)"
                    params.append(from_date)

                if to_date:
                    query += " AND date(s.stopped_at) <= date(?)"
                    params.append(to_date)

                query += " ORDER BY s.stopped_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": row["id"],
                        "news_id": row["news_id"],
                        "ticker": row["ticker"],
                        "strategy_type": row["strategy_type"],
                        "strategy_name": row["strategy_name"],
                        "position_size_usd": row["position_size_usd"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "entry_time": row["entry_time"],
                        "exit_time": row["exit_time"],
                        "qty": row["qty"],
                        "pnl": row["pnl"],
                        "pnl_percent": row["pnl_percent"],
                        "started_at": row["started_at"],
                        "stopped_at": row["stopped_at"],
                        "stop_reason": row["stop_reason"],
                        "headline": row["headline"],
                        "pub_time": row["pub_time"],
                        "source": row["source"],
                    })

                return results
        except Exception as e:
            print(f"[TradeDB] Error fetching completed trades: {e}")
            return []

    def close(self):
        """Close database connection."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            self._initialized = False
            TradeDatabase._instance = None


# Convenience function to get database instance
def get_trade_db(db_path: Optional[str] = None) -> TradeDatabase:
    """Get the singleton database instance."""
    return TradeDatabase(db_path)
