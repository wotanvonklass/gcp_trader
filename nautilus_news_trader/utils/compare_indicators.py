#!/usr/bin/env python3
"""
Utility to compare live-calculated indicators with historical Polygon data.

Usage:
    python compare_indicators.py --ticker AAPL --start 2024-01-15T10:30:00 --stop 2024-01-15T10:37:00

This fetches 1-second bars from Polygon REST API for the given time range,
calculates EMAs and trend strength, and prints the results for comparison
with the live strategy logs.
"""

import argparse
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone


def fetch_bars_from_polygon(
    ticker: str,
    start_time: datetime,
    stop_time: datetime,
    interval_seconds: int = 1,
) -> pd.DataFrame:
    """Fetch historical bars from Polygon REST API."""
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("POLYGON_API_KEY environment variable not set")

    # Convert to milliseconds
    start_ms = int(start_time.timestamp() * 1000)
    stop_ms = int(stop_time.timestamp() * 1000)

    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{interval_seconds}/second/{start_ms}/{stop_ms}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": api_key,
    }

    print(f"Fetching bars from Polygon: {ticker} {start_time} → {stop_time}")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    results = data.get("results", [])

    if not results:
        print(f"No bars returned from Polygon")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.rename(columns={
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    })

    print(f"Fetched {len(df)} bars")
    return df


def calculate_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate EMAs from bar data."""
    df = df.copy()
    df["ema8"] = df["close"].ewm(span=8, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema55"] = df["close"].ewm(span=55, adjust=False).mean()
    return df


def calculate_trend_strength(df: pd.DataFrame) -> float:
    """
    Calculate trend strength (0-100) from EMA alignment and slope.
    Matches the simplified calculation used in NewsTrendStrategy.
    """
    if len(df) < 5:
        return 0.0

    # EMA alignment score (0-100)
    alignment = 0
    if df["ema8"].iloc[-1] > df["ema21"].iloc[-1]:
        alignment += 50
    if df["ema21"].iloc[-1] > df["ema55"].iloc[-1]:
        alignment += 50

    # EMA slope strength (0-100)
    if len(df) >= 5:
        slope_8 = (df["ema8"].iloc[-1] - df["ema8"].iloc[-5]) / df["ema8"].iloc[-5] * 100
        slope_21 = (df["ema21"].iloc[-1] - df["ema21"].iloc[-5]) / df["ema21"].iloc[-5] * 100
        slope_score = min(100, max(0, (slope_8 + slope_21) * 10 + 50))
    else:
        slope_score = 50

    # Final trend strength (60% alignment + 40% slope)
    trend_strength = 0.6 * alignment + 0.4 * slope_score
    return trend_strength


def calculate_vwap(df: pd.DataFrame) -> float:
    """Calculate VWAP from bar data."""
    if df["volume"].sum() == 0:
        return df["close"].iloc[-1] if len(df) > 0 else 0.0
    return (df["close"] * df["volume"]).sum() / df["volume"].sum()


def main():
    parser = argparse.ArgumentParser(description="Compare live vs historical indicators")
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol")
    parser.add_argument("--start", required=True, help="Start time (ISO format)")
    parser.add_argument("--stop", required=True, help="Stop time (ISO format)")
    parser.add_argument("--interval", type=int, default=1, help="Bar interval in seconds (default: 1)")

    args = parser.parse_args()

    # Parse times
    start_time = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    stop_time = datetime.fromisoformat(args.stop.replace("Z", "+00:00"))

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if stop_time.tzinfo is None:
        stop_time = stop_time.replace(tzinfo=timezone.utc)

    # Fetch bars
    df = fetch_bars_from_polygon(args.ticker, start_time, stop_time, args.interval)

    if df.empty:
        print("No data to analyze")
        return

    # Calculate indicators
    df = calculate_emas(df)
    trend_strength = calculate_trend_strength(df)
    vwap = calculate_vwap(df)
    total_volume = df["volume"].sum()

    # Print results
    print("\n" + "=" * 60)
    print(f"HISTORICAL INDICATORS for {args.ticker}")
    print(f"Period: {start_time} → {stop_time}")
    print("=" * 60)
    print(f"Bars:           {len(df)}")
    print(f"Total Volume:   {total_volume:,}")
    print(f"VWAP:           ${vwap:.4f}")
    print(f"Final Price:    ${df['close'].iloc[-1]:.4f}")
    print("-" * 60)
    print(f"EMA8:           ${df['ema8'].iloc[-1]:.4f}")
    print(f"EMA21:          ${df['ema21'].iloc[-1]:.4f}")
    print(f"EMA55:          ${df['ema55'].iloc[-1]:.4f}")
    print(f"Trend Strength: {trend_strength:.1f}")
    print("=" * 60)

    # Show first and last few bars for debugging
    print("\nFirst 5 bars:")
    print(df[["timestamp", "close", "volume", "ema8", "ema21"]].head().to_string(index=False))
    print("\nLast 5 bars:")
    print(df[["timestamp", "close", "volume", "ema8", "ema21"]].tail().to_string(index=False))


if __name__ == "__main__":
    main()
