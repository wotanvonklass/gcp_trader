#!/usr/bin/env python3
"""
V16 Filters for news trading.

Filters:
- Price filter (<$5.00)
- Session filter (Extended + Closing hours)
- Momentum filter (ret_3s > 0)
- Market cap filter (<$50M)
"""

from datetime import datetime, timezone
from typing import Optional, Dict
import pytz


# Session definitions (US Eastern Time)
SESSIONS = {
    'pre_market_early': (4, 0, 7, 0),      # 4:00-7:00 AM ET
    'pre_market_late': (7, 0, 9, 30),      # 7:00-9:30 AM ET
    'regular_open': (9, 30, 10, 0),        # 9:30-10:00 AM ET
    'regular_morning': (10, 0, 12, 0),     # 10:00 AM-12:00 PM ET
    'regular_afternoon': (12, 0, 15, 30),  # 12:00-3:30 PM ET
    'regular_closing': (15, 30, 16, 0),    # 3:30-4:00 PM ET
    'post_market': (16, 0, 20, 0),         # 4:00-8:00 PM ET
}

# Allowed sessions for trading (Extended + Closing)
ALLOWED_SESSIONS = ['pre_market_early', 'pre_market_late', 'post_market', 'regular_closing']


class V16Filters:
    """V16 filter implementation for news trading."""

    def __init__(
        self,
        max_price: float = 5.00,
        max_market_cap: float = 50_000_000,
        require_positive_momentum: bool = True,
        session_filter_enabled: bool = True,
        allowed_sessions: list = None,
        log_func=None,
    ):
        self.max_price = max_price
        self.max_market_cap = max_market_cap
        self.require_positive_momentum = require_positive_momentum
        self.session_filter_enabled = session_filter_enabled
        self.allowed_sessions = allowed_sessions or ALLOWED_SESSIONS
        self.log = log_func or print

        # Cache for market cap lookups
        self.market_cap_cache: Dict[str, Optional[float]] = {}

    def get_current_session(self, now: datetime = None) -> str:
        """Determine current trading session based on US Eastern time."""
        if now is None:
            now = datetime.now(timezone.utc)

        eastern = pytz.timezone('US/Eastern')
        now_et = now.astimezone(eastern)

        hour = now_et.hour
        minute = now_et.minute
        time_decimal = hour + minute / 60.0

        for session_name, (start_h, start_m, end_h, end_m) in SESSIONS.items():
            start = start_h + start_m / 60.0
            end = end_h + end_m / 60.0
            if start <= time_decimal < end:
                return session_name

        return 'outside_hours'

    def check_session(self, now: datetime = None, trace_id: str = "") -> tuple[bool, str]:
        """
        Check if current session is allowed for trading.
        Returns (passed, message).
        """
        if not self.session_filter_enabled:
            return True, "Session filter disabled"

        current_session = self.get_current_session(now)
        if current_session in self.allowed_sessions:
            return True, f"Session OK: {current_session}"
        else:
            return False, f"Session {current_session} not in {self.allowed_sessions}"

    def check_price(self, price: float, trace_id: str = "") -> tuple[bool, str]:
        """
        Check if price is below maximum.
        Returns (passed, message).
        """
        if price < self.max_price:
            return True, f"Price OK: ${price:.2f} < ${self.max_price:.2f}"
        else:
            return False, f"Price ${price:.2f} >= ${self.max_price:.2f}"

    def check_momentum(self, price_now: float, price_3s_ago: float, trace_id: str = "") -> tuple[bool, str]:
        """
        Check if momentum is positive (price moved up in last 3s).
        Returns (passed, message).
        """
        if not self.require_positive_momentum:
            return True, "Momentum filter disabled"

        if price_3s_ago <= 0:
            return True, "No price history, skipping momentum check"

        ret_3s = (price_now - price_3s_ago) / price_3s_ago

        if ret_3s > 0:
            return True, f"Momentum OK: ret_3s={ret_3s*100:.2f}%"
        else:
            return False, f"Momentum ret_3s={ret_3s*100:.2f}% <= 0"

    def check_market_cap(self, market_cap: Optional[float], trace_id: str = "") -> tuple[bool, str]:
        """
        Check if market cap is below maximum.
        Returns (passed, message).
        """
        if market_cap is None:
            return True, "Market cap unknown, proceeding"

        if market_cap < self.max_market_cap:
            return True, f"Market cap OK: ${market_cap/1e6:.1f}M < ${self.max_market_cap/1e6:.0f}M"
        else:
            return False, f"Market cap ${market_cap/1e6:.1f}M >= ${self.max_market_cap/1e6:.0f}M"

    def check_all(
        self,
        price: float,
        price_3s_ago: float,
        market_cap: Optional[float],
        now: datetime = None,
        trace_id: str = "",
    ) -> tuple[bool, list[str]]:
        """
        Run all filters.
        Returns (all_passed, list of messages).
        """
        messages = []
        all_passed = True

        # Session filter
        passed, msg = self.check_session(now, trace_id)
        messages.append(f"Session: {msg}")
        if not passed:
            all_passed = False

        # Price filter
        passed, msg = self.check_price(price, trace_id)
        messages.append(f"Price: {msg}")
        if not passed:
            all_passed = False

        # Momentum filter
        passed, msg = self.check_momentum(price, price_3s_ago, trace_id)
        messages.append(f"Momentum: {msg}")
        if not passed:
            all_passed = False

        # Market cap filter
        passed, msg = self.check_market_cap(market_cap, trace_id)
        messages.append(f"MarketCap: {msg}")
        if not passed:
            all_passed = False

        return all_passed, messages
