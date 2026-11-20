"""Public market-price snapshots for PAPER valuation; no exchange credentials."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import requests


class PaperPriceProviderError(RuntimeError):
    """Public market-price provider failed or returned an unusable quote."""



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
        try:
            response = requests.get(
                f"{self.BASE_URL}/ticker/price",
                params={"symbol": normalized},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            raise PaperPriceProviderError("Proveedor de precios no disponible") from None
        try:
            price = Decimal(str(payload["price"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            raise PaperPriceProviderError("Proveedor de precios no disponible") from None
        if not price.is_finite() or price <= 0:
            raise PaperPriceProviderError("Proveedor de precios no disponible") from None
        return PriceQuote(
            symbol=normalized,
            price=price,
            source="binance_public_ticker",
            retrieved_at=retrieved_at,
        )
