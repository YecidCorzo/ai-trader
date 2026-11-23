"""Read-only public Coinbase market-data HTTP routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from services.coinbase_market_service import (
    CoinbaseMarketDataError,
    CoinbaseMarketService,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Keep one bounded cache/rate-limit state per explicitly supported product.
coinbase_market_services = {
    product_id: CoinbaseMarketService(product_id)
    for product_id in sorted(CoinbaseMarketService.ALLOWED_PRODUCTS)
}


def _coinbase_http_error(error: CoinbaseMarketDataError) -> HTTPException:
    logger.warning("Coinbase market-data upstream failure: %s", type(error).__name__)
    return HTTPException(
        status_code=error.status_code,
        detail="Proveedor Coinbase de datos de mercado no disponible",
    )


def _product_symbol(product_id: str) -> str:
    return product_id.replace("-", "/")


@router.get("/api/coinbase/price")
def get_coinbase_price(
    product_id: str = Query("SOL-EUR", pattern=r"^SOL-(EUR|USDC)$"),
):
    """Return a public Coinbase last-traded price snapshot."""
    service = coinbase_market_services[product_id]
    try:
        snapshot = service.get_price_snapshot()
    except CoinbaseMarketDataError as error:
        raise _coinbase_http_error(error) from None

    return {
        "symbol": _product_symbol(product_id),
        "product_id": product_id,
        "price": snapshot["price"],
        "retrieved_at": snapshot["retrieved_at"].isoformat(),
        "source": "Coinbase Exchange",
        "price_type": "last_traded_price",
        "data_type": "real_market_data",
        "mode": "paper",
    }


@router.get("/api/coinbase/candles")
def get_coinbase_candles(
    product_id: str = Query("SOL-EUR", pattern=r"^SOL-(EUR|USDC)$"),
    interval: str = Query("1h"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Return normalized closed Coinbase candles and explicit completeness metadata."""
    if interval == "4h" and limit > CoinbaseMarketService.MAX_4H_CANDLE_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"El límite máximo para velas 4h es {CoinbaseMarketService.MAX_4H_CANDLE_LIMIT}",
        )
    service = coinbase_market_services[product_id]
    try:
        result = service.get_candles(
            interval=interval,
            limit=limit,
            closed_only=True,
            include_metadata=True,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except CoinbaseMarketDataError as error:
        raise _coinbase_http_error(error) from None

    complete = bool(result["complete"])
    synthetic_timestamps = set(result.get("synthetic_timestamps", []))
    return {
        "symbol": _product_symbol(product_id),
        "product_id": product_id,
        "interval": interval,
        "source": "Coinbase Exchange",
        "candles": [
            {
                "time": int(row[0] / 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "synthetic": int(row[0]) in synthetic_timestamps,
            }
            for row in result["candles"]
        ],
        "candles_requested": result["requested"],
        "candles_returned": result["returned"],
        "synthetic_count": result.get("synthetic_count", 0),
        "complete": complete,
        "history_exhausted": result["history_exhausted"],
        "provider_page_short": result["provider_page_short"],
        "warning": (
            None if complete
            else "Histórico incompleto: Coinbase no devolvió todas las velas cerradas solicitadas o faltan velas iniciales sin cierre previo."
        ),
        "mode": "paper",
    }
