#!/usr/bin/env python3
"""
Alpaca Health Check Utility.

Simple utility to validate Alpaca authentication and account access.
Can be used both on startup and as a periodic health check.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


def check_alpaca_health(api_key: str, secret_key: str) -> Dict[str, Any]:
    """
    Check Alpaca authentication and account status.

    Args:
        api_key: Alpaca API key
        secret_key: Alpaca secret key

    Returns:
        Dict with health check results:
        {
            'healthy': bool,
            'error': str (if not healthy),
            'account': dict (if healthy),
            'checked_at': str (ISO timestamp)
        }
    """
    result = {
        'healthy': False,
        'error': None,
        'account': None,
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    }

    try:
        # Import Alpaca API
        import alpaca_trade_api as tradeapi

        # Validate credentials are provided
        if not api_key or not secret_key:
            result['error'] = "Missing API credentials"
            return result

        # Initialize Alpaca client
        alpaca = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url="https://paper-api.alpaca.markets",
            api_version='v2'
        )

        # Test authentication by fetching account info
        account = alpaca.get_account()

        # Extract key account details
        account_info = {
            'account_number': account.account_number,
            'status': account.status,
            'currency': account.currency,
            'cash': float(account.cash),
            'buying_power': float(account.buying_power),
            'portfolio_value': float(account.portfolio_value),
            'pattern_day_trader': account.pattern_day_trader,
            'trading_blocked': account.trading_blocked,
            'transfers_blocked': account.transfers_blocked,
            'account_blocked': account.account_blocked,
        }

        # Check for account issues
        if account.account_blocked:
            result['error'] = "Account is blocked"
            result['account'] = account_info
            return result

        if account.trading_blocked:
            result['error'] = "Trading is blocked"
            result['account'] = account_info
            return result

        if account.status != 'ACTIVE':
            result['error'] = f"Account status is {account.status}, expected ACTIVE"
            result['account'] = account_info
            return result

        # All checks passed
        result['healthy'] = True
        result['account'] = account_info

        return result

    except Exception as e:
        result['error'] = f"Health check failed: {str(e)}"
        return result


def log_health_check(result: Dict[str, Any], log_level: str = "INFO") -> None:
    """
    Log health check results in a readable format.

    Args:
        result: Health check result dict from check_alpaca_health()
        log_level: Log level for healthy status (ERROR used for unhealthy)
    """
    if result['healthy']:
        account = result['account']
        logger.log(
            getattr(logging, log_level),
            f"✅ Alpaca Health Check PASSED"
        )
        logger.log(
            getattr(logging, log_level),
            f"   Account: {account['account_number']} ({account['status']})"
        )
        logger.log(
            getattr(logging, log_level),
            f"   Buying Power: ${account['buying_power']:,.2f}"
        )
        logger.log(
            getattr(logging, log_level),
            f"   Portfolio Value: ${account['portfolio_value']:,.2f}"
        )
        if account['trading_blocked'] or account['account_blocked']:
            logger.warning(f"   ⚠️ Account has restrictions!")
    else:
        logger.error(f"❌ Alpaca Health Check FAILED: {result['error']}")
        if result['account']:
            logger.error(f"   Account Status: {result['account']['status']}")


def require_healthy_alpaca(api_key: str, secret_key: str) -> Dict[str, Any]:
    """
    Check Alpaca health and raise exception if not healthy.
    Use this on startup to fail fast.

    Args:
        api_key: Alpaca API key
        secret_key: Alpaca secret key

    Returns:
        Account info dict if healthy

    Raises:
        RuntimeError: If health check fails
    """
    result = check_alpaca_health(api_key, secret_key)
    log_health_check(result)

    if not result['healthy']:
        raise RuntimeError(f"Alpaca health check failed: {result['error']}")

    return result['account']
