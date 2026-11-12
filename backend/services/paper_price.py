"""Public market-price snapshots for PAPER valuation; no exchange credentials."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import requests


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    price: Decimal
    source: str
    retrieved_at: datetime


class BinancePublicPriceProvider:
    """Read-only Binance public ticker. The timestamp is local retrieval time."""

    BASE_URL = "https://data-api.binance.vision/api/v3"

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds

    def get_price(self, symbol: str) -> PriceQuote:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol es obligatorio")
        retrieved_at = datetime.now(timezone.utc)
        response = requests.get(
            f"{self.BASE_URL}/ticker/price",
            params={"symbol": normalized},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            price = Decimal(str(payload["price"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            raise ValueError("Binance devolvió un precio inválido") from None
        if not price.is_finite() or price <= 0:
            raise ValueError("Binance devolvió un precio no positivo")
        return PriceQuote(
            symbol=normalized,
            price=price,
            source="binance_public_ticker",
            retrieved_at=retrieved_at,
        )
