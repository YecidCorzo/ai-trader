"""Read-only Bitunix USDT-margined futures market-data client.

Only public market-data endpoints are implemented. No authentication,
account, position, or order functionality exists in this adapter.
"""
from __future__ import annotations

import copy
import logging
import math
import threading
import time
from typing import Callable

import requests

logger = logging.getLogger(__name__)


class BitunixMarketDataError(RuntimeError):
    """A Bitunix public market-data failure safe to expose as HTTP 502/503."""

    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class BitunixMarketService:
    BASE_URL = "https://fapi.bitunix.com/api/v1/futures/market"
    SUPPORTED_INTERVALS = {
        "1m", "5m", "15m", "30m", "1h", "2h", "4h",
        "6h", "8h", "12h", "1d", "3d", "1w",
    }
    INTERVAL_MS = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
        "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
        "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000,
        "1w": 604_800_000,
    }
    MAX_CANDLE_LIMIT = 1000
    PAGE_SIZE = 200
    CACHE_TTL_SECONDS = 5.0
    MIN_REQUEST_INTERVAL_SECONDS = 0.15
    MAX_RATE_LIMIT_RETRIES = 2

    def __init__(
        self,
        symbol: str = "SOLUSDT",
        *,
        timeout: float = 10,
        clock_ms: Callable[[], int] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.symbol = symbol.upper()
        self.timeout = timeout
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._monotonic = monotonic
        self._sleep = sleep
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _request_data(self, endpoint: str, params: dict) -> object:
        cache_key = (endpoint, tuple(sorted(params.items())))
        with self._request_lock:
            now = self._monotonic()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.CACHE_TTL_SECONDS:
                return copy.deepcopy(cached[1])

            for attempt in range(self.MAX_RATE_LIMIT_RETRIES + 1):
                elapsed = self._monotonic() - self._last_request_at
                wait_for_slot = self.MIN_REQUEST_INTERVAL_SECONDS - elapsed
                if wait_for_slot > 0:
                    self._sleep(wait_for_slot)
                self._last_request_at = self._monotonic()

                try:
                    response = requests.get(
                        f"{self.BASE_URL}/{endpoint}",
                        params=params,
                        timeout=self.timeout,
                    )
                    status = getattr(response, "status_code", None)
                    if status in (418, 429):
                        retry_after = getattr(response, "headers", {}).get("Retry-After")
                        try:
                            retry_seconds = float(retry_after)
                        except (TypeError, ValueError):
                            retry_seconds = 0.5 * (2 ** attempt)
                        logger.warning(
                            "Bitunix rate limit response HTTP %s; retry %s/%s",
                            status, attempt + 1, self.MAX_RATE_LIMIT_RETRIES,
                        )
                        if attempt < self.MAX_RATE_LIMIT_RETRIES:
                            self._sleep(min(max(retry_seconds, 0.25), 2.0))
                            continue
                        raise BitunixMarketDataError(
                            "Bitunix rate limit or temporary ban; retry later",
                            status_code=503,
                        )

                    response.raise_for_status()
                    payload = response.json()
                except BitunixMarketDataError:
                    raise
                except (requests.Timeout, requests.ConnectionError) as error:
                    raise BitunixMarketDataError(
                        "Bitunix public market-data service is unavailable",
                        status_code=503,
                    ) from error
                except requests.HTTPError as error:
                    upstream_status = getattr(error.response, "status_code", None)
                    status_code = (
                        503 if upstream_status == 429 or upstream_status == 418
                        or (upstream_status is not None and upstream_status >= 500)
                        else 502
                    )
                    raise BitunixMarketDataError(
                        "Bitunix rejected or failed the public market-data request",
                        status_code=status_code,
                    ) from error
                except requests.RequestException as error:
                    raise BitunixMarketDataError(
                        "Bitunix public market-data request failed", status_code=502
                    ) from error
                except (TypeError, ValueError) as error:
                    raise BitunixMarketDataError(
                        "Bitunix returned invalid public market-data JSON",
                        status_code=502,
                    ) from error

                if not isinstance(payload, dict) or payload.get("code") != 0:
                    raise BitunixMarketDataError(
                        "Bitunix returned an unsuccessful market-data response",
                        status_code=502,
                    )
                data = payload.get("data")
                self._cache[cache_key] = (self._monotonic(), copy.deepcopy(data))
                return data

        raise BitunixMarketDataError("Bitunix market-data request failed", status_code=503)

    @staticmethod
    def _positive_finite(value: object, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise BitunixMarketDataError(f"Bitunix returned an invalid {label}", status_code=502) from None
        if not math.isfinite(number) or number <= 0:
            raise BitunixMarketDataError(f"Bitunix returned an invalid {label}", status_code=502)
        return number

    def _get_ticker(self) -> dict:
        data = self._request_data("tickers", {"symbols": self.symbol})
        if not isinstance(data, list):
            raise BitunixMarketDataError(
                "Bitunix returned an invalid ticker payload", status_code=502
            )
        ticker = next(
            (item for item in data
             if isinstance(item, dict) and item.get("symbol") == self.symbol),
            None,
        )
        if ticker is None:
            raise BitunixMarketDataError(
                "Bitunix did not return the requested ticker", status_code=502
            )
        return ticker

    def get_price(self) -> float:
        """Return last traded price; this is not the mark price."""
        return self._positive_finite(self._get_ticker().get("lastPrice"), "last traded price")

    def get_mark_price(self) -> float:
        """Return provider mark price; not yet wired into PAPER risk or stops."""
        return self._positive_finite(self._get_ticker().get("markPrice"), "mark price")

    def get_candles(
        self,
        interval: str = "5m",
        limit: int = 100,
        *,
        closed_only: bool = True,
        include_metadata: bool = False,
    ) -> list[list[float | int]] | dict:
        """Return normalized candles, optionally with explicit completeness metadata.

        Rows are [open_time_ms, open, high, low, close, base_volume].
        Monthly candles are excluded because their duration is calendar-based.
        """
        if interval not in self.SUPPORTED_INTERVALS:
            if interval == "1M":
                raise ValueError("El intervalo mensual se excluye: su duración es variable")
            raise ValueError(f"Unsupported Bitunix futures interval: {interval}")
        try:
            limit = int(limit)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("El límite de velas debe ser un entero") from None
        if limit < 1 or limit > self.MAX_CANDLE_LIMIT:
            raise ValueError(f"El límite de velas debe estar entre 1 y {self.MAX_CANDLE_LIMIT}")

        interval_ms = self.INTERVAL_MS[interval]
        # Ask for one extra row so a forming candle can be filtered without
        # silently returning fewer than the requested closed candles.
        target_rows = limit + (1 if closed_only else 0)
        candles: list[list[float | int]] = []
        seen_timestamps: set[int] = set()
        end_time = None
        history_exhausted = False
        short_page = False

        while len(candles) < target_rows:
            batch_limit = min(self.PAGE_SIZE, target_rows - len(candles))
            params = {
                "symbol": self.symbol, "interval": interval,
                "limit": batch_limit, "type": "LAST_PRICE",
            }
            if end_time is not None:
                params["endTime"] = end_time
            batch = self._request_data("kline", params)
            if not isinstance(batch, list):
                raise BitunixMarketDataError(
                    "Bitunix returned an invalid candle payload", status_code=502
                )
            if not batch:
                history_exhausted = True
                break

            try:
                normalized = []
                for item in batch:
                    candle = [
                        int(item["time"]), float(item["open"]), float(item["high"]),
                        float(item["low"]), float(item["close"]), float(item["baseVol"]),
                    ]
                    timestamp, open_price, high, low, close, volume = candle
                    if (
                        timestamp <= 0
                        or not all(math.isfinite(value) for value in candle[1:])
                        or min(open_price, high, low, close) <= 0
                        or volume < 0
                        or high < max(open_price, close, low)
                        or low > min(open_price, close, high)
                    ):
                        raise ValueError("invalid OHLCV candle")
                    if timestamp in seen_timestamps:
                        raise ValueError("duplicate candle timestamp")
                    seen_timestamps.add(timestamp)
                    normalized.append(candle)

                normalized.sort(key=lambda candle: candle[0])
                if any(
                    normalized[index][0] >= normalized[index + 1][0]
                    for index in range(len(normalized) - 1)
                ):
                    raise ValueError("duplicate or unordered candle timestamp")
                if candles and normalized and normalized[-1][0] >= candles[0][0]:
                    raise ValueError("overlapping or unordered candle pages")
                candles = normalized + candles
                end_time = int(normalized[0][0])
            except (TypeError, ValueError, KeyError, IndexError, OverflowError):
                raise BitunixMarketDataError(
                    "Bitunix returned malformed candle data", status_code=502
                ) from None

            if len(batch) < batch_limit:
                short_page = True
                break

        candles.sort(key=lambda candle: candle[0])
        if any(
            candles[index + 1][0] - candles[index][0] != interval_ms
            for index in range(len(candles) - 1)
        ):
            raise BitunixMarketDataError(
                "Bitunix candle series has a gap or interval mismatch", status_code=502
            )

        now_ms = int(self.clock_ms())
        if closed_only:
            candles = [
                candle for candle in candles
                if int(candle[0]) + interval_ms <= now_ms
            ]
        candles = candles[-limit:]

        complete = len(candles) >= limit
        metadata = {
            "candles": candles,
            "complete": complete,
            "history_exhausted": history_exhausted or short_page,
            "requested": limit,
            "returned": len(candles),
            "interval": interval,
            "closed_only": closed_only,
        }
        if include_metadata:
            return metadata
        return candles
