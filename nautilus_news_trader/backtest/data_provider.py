#!/usr/bin/env python3
"""
Abstract data provider interface for backtesting.

Allows swapping live Polygon API calls with historical data lookups.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Protocol
import pandas as pd


class MarketDataProvider(Protocol):
    """Protocol for market data providers (live or historical)."""

    def check_trading_activity(self, symbol: str, at_time: datetime, trace_id: str = "") -> Optional[dict]:
        """Get trading activity around a specific time."""
        ...

    def get_market_cap(self, symbol: str) -> Optional[float]:
        """Get market cap for symbol."""
        ...

    def get_price_at_time(self, symbol: str, at_time: datetime) -> Optional[float]:
        """Get price at specific time (for backtest exit pricing)."""
        ...


class HistoricalDataProvider:
    """
    Historical data provider for backtesting.

    Loads bar data from Polygon or CSV and provides lookups by timestamp.
    """

    def __init__(
        self,
        bars_data: Dict[str, pd.DataFrame],  # symbol -> DataFrame with timestamp index
        market_caps: Dict[str, float],
        log_func=None,
    ):
        """
        Args:
            bars_data: Dict mapping symbol to DataFrame with columns:
                       [timestamp, open, high, low, close, volume]
                       timestamp should be datetime index or column
            market_caps: Dict mapping symbol to market cap value
        """
        self.bars_data = bars_data
        self.market_caps = market_caps
        self.log = log_func or print

        # Ensure timestamp index for fast lookups
        for symbol, df in self.bars_data.items():
            if not isinstance(df.index, pd.DatetimeIndex):
                if 'timestamp' in df.columns:
                    df.set_index('timestamp', inplace=True)
                elif 't' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['t'], unit='ms', utc=True)
                    df.set_index('timestamp', inplace=True)

    def check_trading_activity(
        self,
        symbol: str,
        at_time: datetime,
        trace_id: str = ""
    ) -> Optional[dict]:
        """
        Get trading activity in 3-second window before at_time.
        Mirrors PolygonClient.check_trading_activity() interface.
        """
        if symbol not in self.bars_data:
            return None

        df = self.bars_data[symbol]

        # Get 3-second window
        window_start = at_time - timedelta(seconds=3)
        window_end = at_time

        # Filter bars in window
        mask = (df.index >= window_start) & (df.index <= window_end)
        window_bars = df[mask]

        if window_bars.empty:
            return None

        # Calculate aggregates (same as PolygonClient)
        total_volume = window_bars['volume'].sum()
        if total_volume == 0:
            return None

        total_value = (window_bars['volume'] * window_bars['close']).sum()
        avg_price = total_value / total_volume

        first_bar = window_bars.iloc[0]
        last_bar = window_bars.iloc[-1]

        return {
            'symbol': symbol,
            'volume': int(total_volume),
            'avg_price': float(avg_price),
            'last_price': float(last_bar['close']),
            'price_3s_ago': float(first_bar['open']),
            'bars_count': len(window_bars),
        }

    def get_market_cap(self, symbol: str) -> Optional[float]:
        """Get market cap for symbol."""
        return self.market_caps.get(symbol)

    def get_price_at_time(self, symbol: str, at_time: datetime) -> Optional[float]:
        """Get closest price at or before specified time."""
        if symbol not in self.bars_data:
            return None

        df = self.bars_data[symbol]

        # Find closest bar at or before the time
        mask = df.index <= at_time
        if not mask.any():
            return None

        closest = df[mask].iloc[-1]
        return float(closest['close'])

    def get_bars_for_period(
        self,
        symbol: str,
        start: datetime,
        end: datetime
    ) -> Optional[pd.DataFrame]:
        """Get all bars in a time period (for strategy simulation)."""
        if symbol not in self.bars_data:
            return None

        df = self.bars_data[symbol]
        mask = (df.index >= start) & (df.index <= end)
        return df[mask].copy()

    @classmethod
    def from_polygon_csv(
        cls,
        csv_paths: Dict[str, str],  # symbol -> path to CSV
        market_caps: Dict[str, float],
        log_func=None,
    ) -> "HistoricalDataProvider":
        """
        Load from Polygon-format CSV files.

        Expected columns: t (timestamp ms), o, h, l, c, v, vw, n
        """
        bars_data = {}
        for symbol, path in csv_paths.items():
            df = pd.read_csv(path)
            df['timestamp'] = pd.to_datetime(df['t'], unit='ms', utc=True)
            df = df.rename(columns={
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
            })
            df.set_index('timestamp', inplace=True)
            bars_data[symbol] = df

        return cls(bars_data, market_caps, log_func)

    @classmethod
    def from_polygon_api(
        cls,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        api_key: str,
        log_func=None,
    ) -> "HistoricalDataProvider":
        """
        Fetch historical data directly from Polygon API.
        """
        import requests

        bars_data = {}
        market_caps = {}
        log = log_func or print

        for symbol in symbols:
            log(f"Fetching {symbol} data from Polygon...")

            # Fetch bars
            from_ms = int(start_date.timestamp() * 1000)
            to_ms = int(end_date.timestamp() * 1000)

            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/second/{from_ms}/{to_ms}"
            params = {
                'adjusted': 'true',
                'sort': 'asc',
                'limit': 50000,
                'apiKey': api_key
            }

            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                if results:
                    df = pd.DataFrame(results)
                    df['timestamp'] = pd.to_datetime(df['t'], unit='ms', utc=True)
                    df = df.rename(columns={
                        'o': 'open',
                        'h': 'high',
                        'l': 'low',
                        'c': 'close',
                        'v': 'volume',
                    })
                    df.set_index('timestamp', inplace=True)
                    bars_data[symbol] = df
                    log(f"  Loaded {len(df)} bars for {symbol}")

            # Fetch market cap
            url = f"https://api.polygon.io/v3/reference/tickers/{symbol}"
            params = {'apiKey': api_key}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                market_caps[symbol] = data.get('results', {}).get('market_cap')

        return cls(bars_data, market_caps, log_func)
