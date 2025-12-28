#!/usr/bin/env python3
"""
Alpaca Health Check Utility.

Simple utility to validate Alpaca authentication and account access.
Can be used both on startup and as a periodic health check.
"""

import logging
import os
import json
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


def check_trade_updates_proxy(
    proxy_url: Optional[str] = None,
    timeout_seconds: float = 5.0
) -> Dict[str, Any]:
    """
    Check if the Alpaca trade updates proxy is reachable and responding.

    Args:
        proxy_url: WebSocket URL for the proxy. Defaults to TRADE_UPDATES_WS_URL env var.
        timeout_seconds: Connection timeout in seconds.

    Returns:
        Dict with health check results:
        {
            'healthy': bool,
            'error': str (if not healthy),
            'proxy_url': str,
            'response_time_ms': float (if healthy),
            'checked_at': str (ISO timestamp)
        }
    """
    result = {
        'healthy': False,
        'error': None,
        'proxy_url': proxy_url or os.environ.get('TRADE_UPDATES_WS_URL', 'ws://localhost:8099/trade-updates-paper'),
        'response_time_ms': None,
        'checked_at': datetime.utcnow().isoformat() + 'Z'
    }

    proxy_url = result['proxy_url']

    try:
        import websockets
        import time

        async def _check_connection():
            start_time = time.time()

            # Connect to proxy
            async with websockets.connect(
                proxy_url,
                open_timeout=timeout_seconds,
                close_timeout=2.0,
            ) as ws:
                # Send auth message (proxy accepts any credentials)
                auth_msg = json.dumps({
                    "action": "auth",
                    "key": "health_check",
                    "secret": "health_check"
                })
                await ws.send(auth_msg)

                # Wait for auth response
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=timeout_seconds)
                    response_data = json.loads(response)

                    # Check for success response
                    if isinstance(response_data, list) and len(response_data) > 0:
                        if response_data[0].get('T') == 'success':
                            elapsed_ms = (time.time() - start_time) * 1000
                            return True, elapsed_ms, None
                        else:
                            return False, None, f"Unexpected response: {response}"
                    else:
                        return False, None, f"Unexpected response format: {response}"
                except asyncio.TimeoutError:
                    return False, None, "Timeout waiting for auth response"

        # Run the async check
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # If we're in an async context, create a new task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _check_connection())
                healthy, response_time_ms, error = future.result(timeout=timeout_seconds + 2)
        else:
            healthy, response_time_ms, error = loop.run_until_complete(_check_connection())

        result['healthy'] = healthy
        result['response_time_ms'] = response_time_ms
        result['error'] = error

    except ImportError:
        result['error'] = "websockets library not installed"
    except asyncio.TimeoutError:
        result['error'] = f"Connection timeout after {timeout_seconds}s"
    except ConnectionRefusedError:
        result['error'] = "Connection refused - proxy not running"
    except Exception as e:
        result['error'] = f"Connection failed: {str(e)}"

    return result


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
