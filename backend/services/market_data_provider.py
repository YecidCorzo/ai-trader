"""Structural interface shared by read-only public market-data providers."""
from __future__ import annotations

from typing import Protocol


class MarketDataProvider(Protocol):
    """Read-only provider contract; intentionally contains no account/order API."""

    def get_price(self) -> float:
        ...

    def get_candles(
        self,
        interval: str = "5m",
        limit: int = 100,
        *,
        closed_only: bool = False,
    ) -> list[list[float | int]]:
        ...
