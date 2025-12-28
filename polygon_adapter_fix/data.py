# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2025 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Data client implementation for the Polygon.io adapter.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Set

import aiohttp
import msgspec

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import LogColor
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import Bar, BarType, QuoteTick, TradeTick, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import ClientId, InstrumentId, Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.data.messages import (
    SubscribeTradeTicks,
    SubscribeQuoteTicks,
    SubscribeBars,
    UnsubscribeTradeTicks,
    UnsubscribeQuoteTicks,
    UnsubscribeBars,
)

from nautilus_trader.adapters.polygon.config import PolygonDataClientConfig
from nautilus_trader.adapters.polygon.constants import (
    FIELD_EVENT,
    FIELD_MESSAGE,
    FIELD_STATUS,
    FIELD_SYMBOL,
    PolygonAction,
    PolygonChannel,
    PolygonConnectionStatus,
    PolygonEventType,
)
from nautilus_trader.adapters.polygon.parsing import (
    determine_event_type,
    is_extended_hours_trade,
    parse_instrument_id_to_symbol,
    parse_polygon_bar,
    parse_polygon_quote,
    parse_polygon_trade,
    parse_symbol_to_instrument_id,
)


class PolygonDataClient(LiveMarketDataClient):
    """
    Provides a data client for Polygon.io real-time market data.

    Parameters
    ----------
    config : PolygonDataClientConfig
        The client configuration.
    cache : Cache
        The cache instance.
    clock : LiveClock
        The clock instance.
    logger : Logger
        The logger instance.
    msgbus : MessageBus
        The message bus instance.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        config: PolygonDataClientConfig,
        cache: Cache,
        clock: LiveClock,
        msgbus: MessageBus,
        instrument_provider: Optional[Any] = None,
        client_id: Optional[ClientId] = None,
    ) -> None:
        venue = Venue("POLYGON")
        client_id = client_id or ClientId(f"{venue.value}-DATA-{UUID4()}")

        # Use a dummy instrument provider if none provided
        if instrument_provider is None:
            from nautilus_trader.common.providers import InstrumentProvider
            instrument_provider = InstrumentProvider()

        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
        )

        self._config = config
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_session: Optional[aiohttp.ClientSession] = None
        self._rest_session: Optional[aiohttp.ClientSession] = None

        # Subscription tracking
        self._subscribed_trades: Set[InstrumentId] = set()
        self._subscribed_quotes: Set[InstrumentId] = set()
        self._subscribed_bars: Dict[InstrumentId, List[BarType]] = {}

        # WebSocket state
        self._ws_connected = False
        self._ws_authenticated = False
        self._reconnect_task: Optional[asyncio.Task] = None

        # Rate limiting
        self._rate_limiter = asyncio.Semaphore(config.rate_limit_per_minute)

    async def _connect(self) -> None:
        """Connect to Polygon WebSocket."""
        self._log.info("Connecting to Polygon WebSocket...")

        try:
            # Create session if needed
            if not self._ws_session:
                self._ws_session = aiohttp.ClientSession()

            # Connect to WebSocket
            self._ws = await self._ws_session.ws_connect(
                self._config.base_url_ws,
                heartbeat=self._config.websocket_heartbeat,
            )

            self._ws_connected = True

            # Start message handler
            asyncio.create_task(self._handle_messages())

            # Wait for connection message
            await asyncio.sleep(0.1)

            # Send authentication
            await self._authenticate()

        except Exception as e:
            self._log.error(f"Failed to connect to Polygon WebSocket: {e}")
            await self._reconnect()

    async def _disconnect(self) -> None:
        """Disconnect from Polygon WebSocket."""
        self._log.info("Disconnecting from Polygon WebSocket...")

        self._ws_connected = False
        self._ws_authenticated = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._ws_session:
            await self._ws_session.close()
            self._ws_session = None

    async def _authenticate(self) -> None:
        """Authenticate with Polygon WebSocket."""
        if not self._ws:
            return

        auth_msg = {
            "action": PolygonAction.AUTH.value,
            "params": self._config.api_key,
        }

        await self._ws.send_str(json.dumps(auth_msg))
        self._log.info("Sent authentication message")

    async def _handle_messages(self) -> None:
        """Handle incoming WebSocket messages."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_message(json.loads(msg.data))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._log.error(f"WebSocket error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    self._log.warning("WebSocket connection closed")
                    break
        except Exception as e:
            self._log.error(f"Error handling WebSocket messages: {e}")
        finally:
            await self._reconnect()

    async def _process_message(self, data: Any) -> None:
        """Process a single WebSocket message."""
        # Handle single message or array of messages
        messages = data if isinstance(data, list) else [data]

        for msg in messages:
            event_type = determine_event_type(msg)

            if event_type == PolygonEventType.STATUS:
                await self._handle_status_message(msg)
            elif event_type == PolygonEventType.TRADE:
                await self._handle_trade_message(msg)
            elif event_type == PolygonEventType.QUOTE:
                await self._handle_quote_message(msg)
            elif event_type in [PolygonEventType.AGGREGATE_MINUTE, PolygonEventType.AGGREGATE_SECOND]:
                await self._handle_aggregate_message(msg)
            else:
                self._log.debug(f"Unknown message type: {msg}")

    async def _handle_status_message(self, msg: dict) -> None:
        """Handle status messages."""
        status = msg.get(FIELD_STATUS)
        message = msg.get(FIELD_MESSAGE)

        self._log.info(f"Status: {status} - {message}", LogColor.BLUE)

        if status == PolygonConnectionStatus.AUTH_SUCCESS.value:
            self._ws_authenticated = True
            self._log.info("Successfully authenticated with Polygon", LogColor.GREEN)

            # Resubscribe to all instruments
            await self._resubscribe_all()
        elif status == PolygonConnectionStatus.AUTH_FAILED.value:
            self._log.error(f"Authentication failed: {message}")
            self._ws_authenticated = False

    async def _handle_trade_message(self, msg: dict) -> None:
        """Handle trade tick messages."""
        symbol = msg.get(FIELD_SYMBOL)
        if not symbol:
            return

        instrument_id = parse_symbol_to_instrument_id(symbol, self.venue.value)

        # Check if we're subscribed to this instrument
        if instrument_id not in self._subscribed_trades:
            return

        # Check if we should filter extended hours
        if not self._config.include_extended_hours:
            timestamp_ms = msg.get("t")
            if timestamp_ms and is_extended_hours_trade(timestamp_ms):
                return

        trade = parse_polygon_trade(msg, instrument_id)
        if trade:
            self._handle_data(trade)
            self._log.debug(f"Processed trade for {instrument_id}: {trade.price}")

    async def _handle_quote_message(self, msg: dict) -> None:
        """Handle quote tick messages."""
        symbol = msg.get(FIELD_SYMBOL)
        if not symbol:
            return

        instrument_id = parse_symbol_to_instrument_id(symbol, self.venue.value)

        if instrument_id not in self._subscribed_quotes:
            return

        # Check if we should filter extended hours
        if not self._config.include_extended_hours:
            timestamp_ms = msg.get("t")
            if timestamp_ms and is_extended_hours_trade(timestamp_ms):
                return

        quote = parse_polygon_quote(msg, instrument_id)
        if quote:
            self._handle_data(quote)
            self._log.debug(f"Processed quote for {instrument_id}: {quote.bid_price}/{quote.ask_price}")

    async def _handle_aggregate_message(self, msg: dict) -> None:
        """Handle aggregate bar messages."""
        symbol = msg.get(FIELD_SYMBOL)
        if not symbol:
            return

        instrument_id = parse_symbol_to_instrument_id(symbol, self.venue.value)

        # Check if we should filter extended hours
        if not self._config.include_extended_hours:
            timestamp_ms = msg.get("t")
            if timestamp_ms and is_extended_hours_trade(timestamp_ms):
                return

        bar_types = self._subscribed_bars.get(instrument_id, [])
        for bar_type in bar_types:
            # Determine aggregation type from event
            event_type = msg.get(FIELD_EVENT)
            if event_type == PolygonEventType.AGGREGATE_MINUTE.value:
                # Only process if bar type is 1-minute
                if bar_type.spec.aggregation == BarAggregation.MINUTE and bar_type.spec.step == 1:
                    bar = parse_polygon_bar(msg, bar_type, instrument_id)
                    if bar:
                        self._handle_data(bar)
                        self._log.debug(f"Processed 1-min bar for {instrument_id}: O={bar.open} H={bar.high} L={bar.low} C={bar.close}")
            elif event_type == PolygonEventType.AGGREGATE_SECOND.value:
                # Only process if bar type is 1-second
                if bar_type.spec.aggregation == BarAggregation.SECOND and bar_type.spec.step == 1:
                    bar = parse_polygon_bar(msg, bar_type, instrument_id)
                    if bar:
                        self._handle_data(bar)
                        self._log.debug(f"Processed 1-sec bar for {instrument_id}")

    async def _reconnect(self) -> None:
        """Reconnect to WebSocket with backoff."""
        if self._reconnect_task and not self._reconnect_task.done():
            return

        self._reconnect_task = asyncio.create_task(self._reconnect_with_backoff())

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff."""
        for attempt in range(self._config.websocket_reconnect_attempts):
            delay = self._config.websocket_reconnect_delay * (2 ** attempt)
            self._log.info(f"Reconnecting in {delay} seconds... (attempt {attempt + 1})")
            await asyncio.sleep(delay)

            try:
                await self._connect()
                if self._ws_connected:
                    return
            except Exception as e:
                self._log.error(f"Reconnection attempt {attempt + 1} failed: {e}")

        self._log.error("Failed to reconnect after all attempts")

    async def _resubscribe_all(self) -> None:
        """Resubscribe to all instruments after reconnection."""
        symbols = set()

        # Collect all subscribed symbols
        for instrument_id in self._subscribed_trades:
            symbols.add(parse_instrument_id_to_symbol(instrument_id))
        for instrument_id in self._subscribed_quotes:
            symbols.add(parse_instrument_id_to_symbol(instrument_id))
        for instrument_id in self._subscribed_bars.keys():
            symbols.add(parse_instrument_id_to_symbol(instrument_id))

        if symbols:
            await self._send_subscription(list(symbols))

    async def _send_subscription(
        self,
        symbols: List[str],
        action: str = "subscribe",
    ) -> None:
        """Send subscription message to WebSocket."""
        if not self._ws or not self._ws_authenticated:
            self._log.warning("Cannot subscribe - not connected or authenticated")
            return

        channels = []

        if self._config.subscribe_trades:
            channels.extend([f"{PolygonChannel.TRADES.value}.{sym}" for sym in symbols])

        if self._config.subscribe_quotes:
            channels.extend([f"{PolygonChannel.QUOTES.value}.{sym}" for sym in symbols])

        if self._config.subscribe_bars:
            channels.extend([f"{PolygonChannel.AGGREGATE_MINUTE.value}.{sym}" for sym in symbols])

        if self._config.subscribe_second_aggregates:
            channels.extend([f"{PolygonChannel.AGGREGATE_SECOND.value}.{sym}" for sym in symbols])

        if channels:
            msg = {
                "action": action,
                "params": ",".join(channels),
            }

            await self._ws.send_str(json.dumps(msg))
            self._log.info(f"{action} to {len(channels)} channels")

    # LiveMarketDataClient interface implementation
    # FIXED: Methods now accept command objects instead of instrument_id directly

    async def _subscribe_trade_ticks(self, command: SubscribeTradeTicks) -> None:
        """Subscribe to trade ticks."""
        instrument_id = command.instrument_id
        self._subscribed_trades.add(instrument_id)
        symbol = parse_instrument_id_to_symbol(instrument_id)
        await self._send_subscription([symbol])

    async def _subscribe_quote_ticks(self, command: SubscribeQuoteTicks) -> None:
        """Subscribe to quote ticks."""
        instrument_id = command.instrument_id
        self._subscribed_quotes.add(instrument_id)
        symbol = parse_instrument_id_to_symbol(instrument_id)
        await self._send_subscription([symbol])

    async def _subscribe_bars(self, command: SubscribeBars) -> None:
        """Subscribe to bars."""
        bar_type = command.bar_type
        instrument_id = bar_type.instrument_id

        if instrument_id not in self._subscribed_bars:
            self._subscribed_bars[instrument_id] = []

        self._subscribed_bars[instrument_id].append(bar_type)
        symbol = parse_instrument_id_to_symbol(instrument_id)
        await self._send_subscription([symbol])

    async def _unsubscribe_trade_ticks(self, command: UnsubscribeTradeTicks) -> None:
        """Unsubscribe from trade ticks."""
        instrument_id = command.instrument_id
        self._subscribed_trades.discard(instrument_id)
        symbol = parse_instrument_id_to_symbol(instrument_id)
        await self._send_subscription([symbol], action="unsubscribe")

    async def _unsubscribe_quote_ticks(self, command: UnsubscribeQuoteTicks) -> None:
        """Unsubscribe from quote ticks."""
        instrument_id = command.instrument_id
        self._subscribed_quotes.discard(instrument_id)
        symbol = parse_instrument_id_to_symbol(instrument_id)
        await self._send_subscription([symbol], action="unsubscribe")

    async def _unsubscribe_bars(self, command: UnsubscribeBars) -> None:
        """Unsubscribe from bars."""
        bar_type = command.bar_type
        instrument_id = bar_type.instrument_id

        if instrument_id in self._subscribed_bars:
            bar_types = self._subscribed_bars[instrument_id]
            if bar_type in bar_types:
                bar_types.remove(bar_type)

            if not bar_types:
                del self._subscribed_bars[instrument_id]
                symbol = parse_instrument_id_to_symbol(instrument_id)
                await self._send_subscription([symbol], action="unsubscribe")

    async def _request_instrument(self, instrument_id: InstrumentId) -> None:
        """Request instrument information."""
        # Implement REST API call to get instrument details
        pass

    async def _request_instruments(self, venue: Venue) -> None:
        """Request all instruments for venue."""
        # Implement REST API call to get all instruments
        pass

    async def _request_quote_ticks(
        self,
        instrument_id: InstrumentId,
        limit: int,
        correlation_id: UUID4,
        from_datetime: Optional[Any] = None,
        to_datetime: Optional[Any] = None,
    ) -> None:
        """Request historical quote ticks."""
        # Implement REST API call for historical quotes
        pass

    async def _request_trade_ticks(
        self,
        instrument_id: InstrumentId,
        limit: int,
        correlation_id: UUID4,
        from_datetime: Optional[Any] = None,
        to_datetime: Optional[Any] = None,
    ) -> None:
        """Request historical trade ticks."""
        # Implement REST API call for historical trades
        pass

    async def _request_bars(
        self,
        bar_type: BarType,
        limit: int,
        correlation_id: UUID4,
        from_datetime: Optional[Any] = None,
        to_datetime: Optional[Any] = None,
    ) -> None:
        """Request historical bars."""
        # Implement REST API call for historical bars
        pass
