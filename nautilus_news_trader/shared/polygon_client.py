#!/usr/bin/env python3
"""
Polygon API client for news trading.

Provides:
- Trading activity check (3-second bars)
- Market cap lookup
- Historical bars for EMA calculation
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
import requests


class PolygonClient:
    """Polygon API client for market data."""

    def __init__(self, api_key: str, log_func=None):
        self.api_key = api_key
        self.log = log_func or print
        self.market_cap_cache: Dict[str, Optional[float]] = {}

    def check_trading_activity(self, symbol: str, trace_id: str = "") -> Optional[dict]:
        """
        Check trading activity on Polygon in last 3 seconds.
        Returns dict with volume, prices, or None if no activity.
        """
        try:
            now = datetime.now(timezone.utc)
            three_sec_ago = now - timedelta(seconds=3)

            from_ms = int(three_sec_ago.timestamp() * 1000)
            to_ms = int(now.timestamp() * 1000)

            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/second/{from_ms}/{to_ms}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'apiKey': self.api_key
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if not results:
                return None

            total_volume = sum(bar['v'] for bar in results)
            total_value = sum(bar['v'] * bar['c'] for bar in results)
            avg_price = total_value / total_volume if total_volume > 0 else 0

            first_bar = results[0]
            last_bar = results[-1]

            return {
                'symbol': symbol,
                'volume': total_volume,
                'avg_price': avg_price,
                'last_price': last_bar['c'],
                'price_3s_ago': first_bar['o'],
                'bars_count': len(results),
            }

        except Exception as e:
            self.log(f"Polygon error for {symbol}: {e}")
            return None

    def get_market_cap(self, symbol: str) -> Optional[float]:
        """Get market cap for a symbol from Polygon."""
        if symbol in self.market_cap_cache:
            return self.market_cap_cache[symbol]

        try:
            url = f"https://api.polygon.io/v3/reference/tickers/{symbol}"
            params = {'apiKey': self.api_key}

            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', {})
                market_cap = results.get('market_cap')
                self.market_cap_cache[symbol] = market_cap
                return market_cap

            self.market_cap_cache[symbol] = None
            return None

        except Exception as e:
            self.log(f"Market cap lookup failed for {symbol}: {e}")
            self.market_cap_cache[symbol] = None
            return None

    def get_historical_bars(
        self,
        symbol: str,
        bars_count: int = 300,
        trace_id: str = ""
    ) -> Optional[list]:
        """
        Fetch historical 1-second bars for EMA calculation.
        Returns list of bar dicts or None on error.
        """
        try:
            now = datetime.now(timezone.utc)
            from_time = now - timedelta(seconds=bars_count + 60)

            from_ms = int(from_time.timestamp() * 1000)
            to_ms = int(now.timestamp() * 1000)

            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/second/{from_ms}/{to_ms}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'limit': 50000,
                'apiKey': self.api_key
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if len(results) < 200:
                self.log(f"Insufficient bars for {symbol}: {len(results)} < 200")
                return None

            return results

        except Exception as e:
            self.log(f"Historical bars error for {symbol}: {e}")
            return None
