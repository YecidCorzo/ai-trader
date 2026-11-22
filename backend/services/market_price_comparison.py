"""Read-only shadow comparison between Binance Spot and Bitunix Futures."""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone

try:
    from backend.services.market_data_provider import MarketDataProvider
except ImportError:
    from services.market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class MarketPriceComparisonService:
    """Compare provider prices without selecting or changing a strategy source."""

    DEFAULT_MAX_ABS_BASIS_BPS = 50.0
    CACHE_TTL_SECONDS = 5.0
    MAX_PRICE_SKEW_SECONDS = 2.0

    def __init__(
        self,
        binance: MarketDataProvider,
        bitunix: MarketDataProvider,
        *,
        max_abs_basis_bps: float = DEFAULT_MAX_ABS_BASIS_BPS,
        max_price_skew_seconds: float = MAX_PRICE_SKEW_SECONDS,
        monotonic=time.monotonic,
    ):
        threshold = float(max_abs_basis_bps)
        skew_limit = float(max_price_skew_seconds)
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("max_abs_basis_bps debe ser positivo y finito")
        if not math.isfinite(skew_limit) or skew_limit <= 0:
            raise ValueError("max_price_skew_seconds debe ser positivo y finito")
        self.binance = binance
        self.bitunix = bitunix
        self.max_abs_basis_bps = threshold
        self.max_price_skew_seconds = skew_limit
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cached_result = None

    @staticmethod
    def _validated_price_snapshot(provider: MarketDataProvider) -> tuple[float, datetime]:
        snapshot = provider.get_price_snapshot()
        if not isinstance(snapshot, dict):
            raise ValueError("provider returned invalid price snapshot")
        price = float(snapshot["price"])
        retrieved_at = snapshot["retrieved_at"]
        if isinstance(retrieved_at, str):
            retrieved_at = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None:
            raise ValueError("provider returned a timestamp without timezone")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("provider returned invalid price")
        return price, retrieved_at.astimezone(timezone.utc)

    def compare(self) -> dict:
        with self._lock:
            now = self._monotonic()
            if (
                self._cached_result is not None
                and now - self._cached_at < self.CACHE_TTL_SECONDS
            ):
                return dict(self._cached_result)

            try:
                spot_price, spot_retrieved_at = self._validated_price_snapshot(self.binance)
                futures_last_price, futures_retrieved_at = self._validated_price_snapshot(self.bitunix)
                skew_seconds = abs((spot_retrieved_at - futures_retrieved_at).total_seconds())
            except Exception as error:
                logger.warning(
                    "Shadow price comparison unavailable: %s",
                    type(error).__name__,
                )
                result = {
                    "status": "unavailable",
                    "available": False,
                    "alert": False,
                    "binance_spot_price": None,
                    "bitunix_futures_last_price": None,
                    "binance_price_retrieved_at": None,
                    "bitunix_price_retrieved_at": None,
                    "price_skew_seconds": None,
                    "basis_bps": None,
                    "absolute_basis_bps": None,
                    "threshold_bps": self.max_abs_basis_bps,
                    "max_price_skew_seconds": self.max_price_skew_seconds,
                    "message": "No se puede comparar: uno de los proveedores no está disponible o devolvió un precio inválido.",
                }
            else:
                timestamps = {
                    "binance_price_retrieved_at": spot_retrieved_at.isoformat(),
                    "bitunix_price_retrieved_at": futures_retrieved_at.isoformat(),
                    "price_skew_seconds": skew_seconds,
                }
                if skew_seconds > self.max_price_skew_seconds:
                    result = {
                        "status": "unavailable",
                        "available": False,
                        "alert": False,
                        "binance_spot_price": spot_price,
                        "bitunix_futures_last_price": futures_last_price,
                        **timestamps,
                        "basis_bps": None,
                        "absolute_basis_bps": None,
                        "threshold_bps": self.max_abs_basis_bps,
                        "max_price_skew_seconds": self.max_price_skew_seconds,
                        "message": "No se calcula el diferencial: las cotizaciones no son suficientemente sincronizadas.",
                    }
                else:
                    basis_bps = (
                        (futures_last_price - spot_price) / spot_price * 10_000
                    )
                    alert = abs(basis_bps) > self.max_abs_basis_bps
                    result = {
                        "status": "alert" if alert else "ok",
                        "available": True,
                        "alert": alert,
                        "binance_spot_price": spot_price,
                        "bitunix_futures_last_price": futures_last_price,
                        **timestamps,
                        "basis_bps": basis_bps,
                        "absolute_basis_bps": abs(basis_bps),
                        "threshold_bps": self.max_abs_basis_bps,
                        "max_price_skew_seconds": self.max_price_skew_seconds,
                        "message": (
                            "Diferencial superior al umbral configurado."
                            if alert
                            else "Diferencial dentro del umbral configurado."
                        ),
                    }

            result.update({
                "symbol": "SOL/USDT",
                "binance_source": "Binance Spot",
                "bitunix_source": "Bitunix Futures LAST_PRICE",
                "mode": "paper",
                "shadow_mode": True,
                "strategy_source_changed": False,
                "orders_enabled": False,
                "compared_at": datetime.now(timezone.utc).isoformat(),
            })
            self._cached_at = self._monotonic()
            self._cached_result = dict(result)
            return result
