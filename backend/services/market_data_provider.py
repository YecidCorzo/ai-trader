"""Structural interface for read-only public market-data providers."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypedDict


class PriceSnapshot(TypedDict):
    price: float
    retrieved_at: datetime


class MarketDataProvider(Protocol):
    """Read-only contract; no account, order, or execution methods.

    Price snapshots carry the local UTC retrieval time (or the original cache
    retrieval time), not an exchange event timestamp. Comparisons must reject
    snapshots whose retrieval times differ by more than the configured skew.

    Candle consumers must pass closed_only explicitly. When True, providers
    must return only completed candles in ascending order, with contiguous
    interval boundaries and fresh data; gaps, forming candles, malformed rows,
    or stale results must fail closed rather than be silently filled.
    """

    def get_price_snapshot(self) -> PriceSnapshot:
        ...

    def get_candles(
        self,
        interval: str,
        limit: int,
        *,
        closed_only: bool,
    ) -> list[list[float | int]]:
        ...
