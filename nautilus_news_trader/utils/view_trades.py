#!/usr/bin/env python3
"""
CLI tool to view trade P&L and news summary from the SQLite database.

Usage:
    python view_trades.py              # Show today's trades
    python view_trades.py --days 7     # Show last 7 days
    python view_trades.py --news       # Show news summary
    python view_trades.py --all        # Show all data
"""

import argparse
import sys
import importlib.util
from pathlib import Path

# Load trade_db directly to avoid importing shared/__init__.py
# which pulls in nautilus_trader and other heavy dependencies
_trade_db_path = Path(__file__).parent.parent / "shared" / "trade_db.py"
_spec = importlib.util.spec_from_file_location("trade_db", _trade_db_path)
_trade_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_trade_db)
get_trade_db = _trade_db.get_trade_db


def print_pnl_summary(db, days: int = 1):
    """Print P&L summary."""
    summary = db.get_pnl_summary(days)

    print("=" * 80)
    print(f"P&L SUMMARY (Last {days} day{'s' if days > 1 else ''})")
    print("=" * 80)

    if not summary or summary.get('trade_count', 0) == 0:
        print("No completed trades found.")
        if summary.get('open_trades', 0) > 0:
            print(f"Open trades: {summary['open_trades']}")
        print()
        return

    total_pnl = summary.get('total_pnl', 0)
    emoji = "PROFIT" if total_pnl >= 0 else "LOSS"

    print(f"Total Realized P&L: ${total_pnl:+,.2f}")
    print(f"Completed Trades: {summary.get('trade_count', 0)}")
    print(f"Win Rate: {summary.get('win_rate', 0):.1f}%")
    print(f"Biggest Win: ${summary.get('biggest_win', 0):+,.2f}")
    print(f"Biggest Loss: ${summary.get('biggest_loss', 0):+,.2f}")
    if summary.get('open_trades', 0) > 0:
        print(f"Open Trades: {summary['open_trades']}")
    print()


def print_trade_details(db, days: int = 1):
    """Print detailed trade P&L."""
    trades = db.get_trade_pnl(days)

    print("=" * 80)
    print(f"TRADE DETAILS (Last {days} day{'s' if days > 1 else ''})")
    print("=" * 80)

    if not trades:
        print("No trades found.")
        print()
        return

    # Sort by P&L descending (completed trades first)
    completed = [t for t in trades if t.get('exit_price')]
    open_trades = [t for t in trades if not t.get('exit_price')]

    completed.sort(key=lambda x: x.get('pnl', 0) or 0, reverse=True)

    for trade in completed:
        pnl = trade.get('pnl', 0) or 0
        pnl_pct = trade.get('pnl_pct', 0) or 0
        emoji = "WIN " if pnl >= 0 else "LOSS"

        print(f"{emoji} {trade['ticker']} ({trade['strategy_name']})")
        print(f"   Entry: {trade.get('qty', 0):.0f} shares @ ${trade.get('entry_price', 0):.2f}")
        print(f"   Exit:  @ ${trade.get('exit_price', 0):.2f}")
        print(f"   P&L:   ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
        print(f"   News:  {trade.get('headline', '')[:60]}...")
        print()

    for trade in open_trades:
        print(f"OPEN {trade['ticker']} ({trade['strategy_name']})")
        print(f"   Entry: {trade.get('qty', 0):.0f} shares @ ${trade.get('entry_price', 0):.2f}")
        print(f"   Exit:  (pending)")
        print(f"   News:  {trade.get('headline', '')[:60]}...")
        print()


def print_news_summary(db, days: int = 1):
    """Print news processing summary."""
    summary = db.get_news_summary(days)

    print("=" * 80)
    print(f"NEWS SUMMARY (Last {days} day{'s' if days > 1 else ''})")
    print("=" * 80)

    if not summary or summary.get('total_news', 0) == 0:
        print("No news events found.")
        print()
        return

    total = summary.get('total_news', 0)
    traded = summary.get('traded', 0)

    print(f"Total News Received: {total}")
    print(f"Traded: {traded} ({traded/total*100:.1f}%)" if total > 0 else "Traded: 0")
    print(f"Total Strategies Spawned: {summary.get('total_strategies', 0)}")
    print()
    print("Skip Reasons:")
    print(f"   No Volume: {summary.get('skip_no_volume', 0)}")
    print(f"   Too Old: {summary.get('skip_too_old', 0)}")
    print(f"   No Tickers: {summary.get('skip_no_tickers', 0)}")
    print(f"   Position Exists: {summary.get('skip_position_exists', 0)}")
    print()


def main():
    parser = argparse.ArgumentParser(description='View trade P&L and news summary')
    parser.add_argument('--days', type=int, default=1, help='Number of days to look back (default: 1)')
    parser.add_argument('--news', action='store_true', help='Show news summary')
    parser.add_argument('--all', action='store_true', help='Show all data')
    parser.add_argument('--db', type=str, help='Path to database file')

    args = parser.parse_args()

    try:
        db = get_trade_db(args.db)
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

    if args.all:
        print_pnl_summary(db, args.days)
        print_trade_details(db, args.days)
        print_news_summary(db, args.days)
    elif args.news:
        print_news_summary(db, args.days)
    else:
        print_pnl_summary(db, args.days)
        print_trade_details(db, args.days)


if __name__ == '__main__':
    main()
