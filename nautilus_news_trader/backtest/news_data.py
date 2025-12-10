#!/usr/bin/env python3
"""
Custom news data type for NautilusTrader backtesting.

Extends nautilus_trader.core.data.Data to enable news events
to flow through the backtest engine's event loop.
"""

from datetime import datetime, timezone
from typing import List, Optional

from nautilus_trader.core.data import Data
from nautilus_trader.model.data import DataType


class BenzingaNewsData(Data):
    """
    Represents a Benzinga news event for backtesting.

    This mirrors the JSON structure from Pub/Sub but as a NautilusTrader Data object.

    Parameters
    ----------
    news_id : str
        Unique news identifier.
    headline : str
        News headline text.
    tickers : list[str]
        List of ticker symbols (e.g., ["KALA", "AAPL"]).
    url : str
        URL to the full article.
    source : str
        News source (e.g., "Benzinga").
    tags : list[str]
        News tags/categories.
    ts_event : int
        UNIX timestamp (nanoseconds) when the news was published.
    ts_init : int
        UNIX timestamp (nanoseconds) when this object was created.

    """

    def __init__(
        self,
        news_id: str,
        headline: str,
        tickers: List[str],
        url: str,
        source: str,
        tags: List[str],
        ts_event: int,
        ts_init: int,
    ):
        self._news_id = news_id
        self._headline = headline
        self._tickers = tickers
        self._url = url
        self._source = source
        self._tags = tags
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def news_id(self) -> str:
        return self._news_id

    @property
    def headline(self) -> str:
        return self._headline

    @property
    def tickers(self) -> List[str]:
        return self._tickers

    @property
    def url(self) -> str:
        return self._url

    @property
    def source(self) -> str:
        return self._source

    @property
    def tags(self) -> List[str]:
        return self._tags

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def to_dict(self) -> dict:
        """Convert to dict matching Pub/Sub message format."""
        return {
            "id": self._news_id,
            "headline": self._headline,
            "tickers": self._tickers,
            "url": self._url,
            "source": self._source,
            "tags": self._tags,
            "createdAt": datetime.fromtimestamp(
                self._ts_event / 1e9, tz=timezone.utc
            ).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict, ts_init: Optional[int] = None) -> "BenzingaNewsData":
        """
        Create from Pub/Sub message dict.

        Parameters
        ----------
        data : dict
            News event dict with keys: id, headline, tickers, url, source, tags, createdAt
        ts_init : int, optional
            Override initialization timestamp (nanoseconds)

        """
        # Parse publication time
        pub_time_str = data.get("createdAt") or data.get("updatedAt") or data.get("capturedAt")
        if pub_time_str:
            pub_time = datetime.fromisoformat(pub_time_str.replace("Z", "+00:00"))
            ts_event = int(pub_time.timestamp() * 1e9)
        else:
            ts_event = 0

        if ts_init is None:
            ts_init = ts_event

        return cls(
            news_id=str(data.get("id", "")),
            headline=data.get("headline", ""),
            tickers=data.get("tickers", []),
            url=data.get("url", ""),
            source=data.get("source", ""),
            tags=data.get("tags", []),
            ts_event=ts_event,
            ts_init=ts_init,
        )

    def __repr__(self) -> str:
        return (
            f"BenzingaNewsData("
            f"news_id={self._news_id}, "
            f"headline='{self._headline[:50]}...', "
            f"tickers={self._tickers}, "
            f"ts_event={self._ts_event})"
        )


# DataType for subscription
BENZINGA_NEWS_DATA_TYPE = DataType(BenzingaNewsData)
