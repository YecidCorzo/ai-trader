"""Read-only Coinbase Exchange public market-data adapter.

No authentication, account, order, or execution endpoints are implemented.
Candles are normalized to [open_time_ms, open, high, low, close, volume].
"""
from __future__ import annotations

import copy
import logging
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import requests

logger = logging.getLogger(__name__)


class CoinbaseMarketDataError(RuntimeError):
    """A safe-to-expose Coinbase public market-data failure."""

    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class CoinbaseMarketService:
    BASE_URL = "https://api.exchange.coinbase.com"
    ALLOWED_PRODUCTS = frozenset({"SOL-EUR", "SOL-USDC"})
    GRANULARITY_SECONDS = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400,
    }
    FOUR_HOURS_SECONDS = 14_400
    MAX_CANDLE_LIMIT = 1000
    MAX_RAW_4H_CANDLES = MAX_CANDLE_LIMIT * 4 + 4
    PAGE_SIZE = 300
    CACHE_TTL_SECONDS = 5.0
    CACHE_MAX_ENTRIES = 128
    MIN_REQUEST_INTERVAL_SECONDS = 0.15
    MAX_RETRY_AFTER_SECONDS = 2.0

    def __init__(
        self,
        product_id: str = "SOL-EUR",
        *,
        timeout: float = 10,
        clock_ms: Callable[[], int] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        normalized_product = str(product_id).upper()
        if normalized_product not in self.ALLOWED_PRODUCTS:
            raise ValueError("Coinbase product is not enabled for this adapter")
        self.product_id = normalized_product
        self.timeout = timeout
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._monotonic = monotonic
        self._sleep = sleep
        self._cache: OrderedDict[tuple, tuple[float, datetime, object]] = OrderedDict()
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    @staticmethod
    def _iso_utc(epoch_seconds: int) -> str:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")

    @staticmethod
    def _retry_after_seconds(value: object, now: datetime) -> float | None:
        if value is None:
            return None
        try:
            seconds = float(value)
            if math.isfinite(seconds) and seconds >= 0:
                return seconds
        except (TypeError, ValueError, OverflowError):
            pass
        try:
            retry_at = parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    def _request_json(self, path: str, params: dict | None = None) -> tuple[object, datetime]:
        params = params or {}
        cache_key = (path, tuple(sorted(params.items())))
        with self._request_lock:
            now_mono = self._monotonic()
            cached = self._cache.get(cache_key)
            if cached and now_mono - cached[0] < self.CACHE_TTL_SECONDS:
                self._cache.move_to_end(cache_key)
                return copy.deepcopy(cached[2]), cached[1]

            elapsed = self._monotonic() - self._last_request_at
            wait_for_slot = self.MIN_REQUEST_INTERVAL_SECONDS - elapsed
            if wait_for_slot > 0:
                self._sleep(wait_for_slot)
            self._last_request_at = self._monotonic()

            try:
                response = requests.get(
                    f"{self.BASE_URL}{path}",
                    params=params,
                    timeout=self.timeout,
                    headers={"Accept": "application/json"},
                )
                status = getattr(response, "status_code", None)
                if status == 429:
                    retry_after = self._retry_after_seconds(
                        getattr(response, "headers", {}).get("Retry-After"),
                        datetime.now(timezone.utc),
                    )
                    if retry_after is not None and retry_after <= self.MAX_RETRY_AFTER_SECONDS:
                        self._sleep(retry_after)
                        response = requests.get(
                            f"{self.BASE_URL}{path}",
                            params=params,
                            timeout=self.timeout,
                            headers={"Accept": "application/json"},
                        )
                        status = getattr(response, "status_code", None)
                    if status == 429:
                        logger.warning("Coinbase public API rate limited; request deferred")
                        raise CoinbaseMarketDataError(
                            "Coinbase public market-data service is rate limited",
                            status_code=503,
                        )
                if status == 418:
                    raise CoinbaseMarketDataError(
                        "Coinbase public market-data service is temporarily unavailable",
                        status_code=503,
                    )
                response.raise_for_status()
                payload = response.json()
            except CoinbaseMarketDataError:
                raise
            except (requests.Timeout, requests.ConnectionError):
                raise CoinbaseMarketDataError(
                    "Coinbase public market-data service is unavailable",
                    status_code=503,
                ) from None
            except requests.HTTPError as error:
                upstream_status = getattr(error.response, "status_code", None)
                mapped_status = 503 if upstream_status is None or upstream_status >= 500 else 502
                raise CoinbaseMarketDataError(
                    "Coinbase rejected or failed the public market-data request",
                    status_code=mapped_status,
                ) from None
            except requests.RequestException:
                raise CoinbaseMarketDataError(
                    "Coinbase public market-data request failed", status_code=502
                ) from None
            except (TypeError, ValueError):
                raise CoinbaseMarketDataError(
                    "Coinbase returned invalid public market-data JSON", status_code=502
                ) from None

            retrieved_at = datetime.now(timezone.utc)
            self._cache[cache_key] = (
                self._monotonic(), retrieved_at, copy.deepcopy(payload)
            )
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self.CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)
            return payload, retrieved_at

    def _ensure_product_active(self) -> dict:
        payload, _ = self._request_json("/products")
        if not isinstance(payload, list):
            raise CoinbaseMarketDataError(
                "Coinbase returned an invalid products response", status_code=502
            )
        product = next(
            (
                item for item in payload
                if isinstance(item, dict) and item.get("id") == self.product_id
            ),
            None,
        )
        if product is None:
            raise CoinbaseMarketDataError(
                "Requested Coinbase product does not exist", status_code=404
            )
        if product.get("status") != "online" or product.get("trading_disabled") is True:
            raise CoinbaseMarketDataError(
                "Requested Coinbase product is not active", status_code=503
            )
        return product

    @staticmethod
    def _positive_finite(value: object, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise CoinbaseMarketDataError(
                f"Coinbase returned an invalid {label}", status_code=502
            ) from None
        if not math.isfinite(number) or number <= 0:
            raise CoinbaseMarketDataError(
                f"Coinbase returned an invalid {label}", status_code=502
            )
        return number

    def get_price_snapshot(self) -> dict:
        self._ensure_product_active()
        payload, retrieved_at = self._request_json(
            f"/products/{self.product_id}/ticker"
        )
        if not isinstance(payload, dict):
            raise CoinbaseMarketDataError(
                "Coinbase returned an invalid ticker payload", status_code=502
            )
        price = self._positive_finite(payload.get("price"), "last traded price")
        return {"price": price, "retrieved_at": retrieved_at}

    def get_price(self) -> float:
        return self.get_price_snapshot()["price"]

    @classmethod
    def _normalize_candle(cls, item: object, interval_seconds: int) -> list[float | int]:
        # Coinbase Exchange candle order is [time, low, high, open, close, volume].
        if not isinstance(item, (list, tuple)) or len(item) != 6:
            raise ValueError("invalid candle shape")
        timestamp_seconds = int(item[0])
        low = float(item[1])
        high = float(item[2])
        open_price = float(item[3])
        close = float(item[4])
        volume = float(item[5])
        values = (low, high, open_price, close, volume)
        if (
            timestamp_seconds <= 0
            or timestamp_seconds % interval_seconds != 0
            or not all(math.isfinite(value) for value in values)
            or min(low, high, open_price, close) <= 0
            or volume < 0
            or high < max(open_price, close, low)
            or low > min(open_price, close, high)
        ):
            raise ValueError("invalid OHLCV values")
        return [
            timestamp_seconds * 1000,
            open_price,
            high,
            low,
            close,
            volume,
        ]

    def _fetch_normalized_candles(
        self,
        granularity: int,
        target_count: int,
        *,
        max_count: int,
    ) -> list[list[float | int]]:
        if target_count < 1 or target_count > max_count:
            raise ValueError("Requested Coinbase candle history exceeds the configured limit")
        interval_ms = granularity * 1000
        now_ms = int(self.clock_ms())
        end_seconds = (now_ms // interval_ms) * granularity
        candles: list[list[float | int]] = []
        seen: set[int] = set()
        max_pages = (target_count + self.PAGE_SIZE - 1) // self.PAGE_SIZE + 3

        for _ in range(max_pages):
            if len(candles) >= target_count:
                break
            page_end = end_seconds
            page_start = page_end - (self.PAGE_SIZE - 1) * granularity
            payload, _ = self._request_json(
                f"/products/{self.product_id}/candles",
                {
                    "granularity": granularity,
                    "start": self._iso_utc(page_start),
                    "end": self._iso_utc(page_end),
                },
            )
            if not isinstance(payload, list):
                raise CoinbaseMarketDataError(
                    "Coinbase returned an invalid candle payload", status_code=502
                )
            if not payload:
                break
            try:
                page = [self._normalize_candle(row, granularity) for row in payload]
                page.sort(key=lambda row: row[0])
                for row in page:
                    timestamp = int(row[0])
                    if timestamp in seen:
                        raise ValueError("duplicate candle timestamp")
                    seen.add(timestamp)
                if candles and page and page[-1][0] >= candles[0][0]:
                    raise ValueError("overlapping or unordered candle pages")
                candles = page + candles
                oldest_seconds = int(page[0][0] // 1000)
                end_seconds = oldest_seconds - granularity
            except (TypeError, ValueError, IndexError, OverflowError):
                raise CoinbaseMarketDataError(
                    "Coinbase returned malformed or duplicate candle data", status_code=502
                ) from None
            if len(payload) < self.PAGE_SIZE:
                # A short page can be caused by sparse trading. Continue paging
                # backwards; continuity is validated after all requested rows arrive.
                if end_seconds <= 0:
                    break

        candles.sort(key=lambda row: row[0])
        if any(
            candles[index + 1][0] - candles[index][0] != interval_ms
            for index in range(len(candles) - 1)
        ):
            raise CoinbaseMarketDataError(
                "Coinbase candle series has a gap or interval mismatch", status_code=502
            )
        return candles[-target_count:]

    def _get_native_candles(
        self,
        interval: str,
        limit: int,
        *,
        closed_only: bool,
    ) -> list[list[float | int]]:
        granularity = self.GRANULARITY_SECONDS[interval]
        target_count = limit + (1 if closed_only else 0)
        candles = self._fetch_normalized_candles(
            granularity, target_count, max_count=self.MAX_CANDLE_LIMIT + 1
        )
        interval_ms = granularity * 1000
        now_ms = int(self.clock_ms())
        if closed_only:
            candles = [
                row for row in candles
                if int(row[0]) + interval_ms <= now_ms
            ]
            expected_latest = (now_ms // interval_ms) * interval_ms - interval_ms
            if not candles or int(candles[-1][0]) != expected_latest:
                raise CoinbaseMarketDataError(
                    "Coinbase returned stale or incomplete closed candles",
                    status_code=503,
                )
        return candles[-limit:]

    @classmethod
    def _aggregate_four_hour(
        cls, hourly: list[list[float | int]], *, now_ms: int
    ) -> list[list[float | int]]:
        groups: dict[int, list[list[float | int]]] = {}
        for row in hourly:
            timestamp = int(row[0])
            bucket = (timestamp // (cls.FOUR_HOURS_SECONDS * 1000)) * (
                cls.FOUR_HOURS_SECONDS * 1000
            )
            groups.setdefault(bucket, []).append(row)

        aggregated = []
        for bucket, rows in sorted(groups.items()):
            rows.sort(key=lambda row: row[0])
            expected = [bucket + hour * 3_600_000 for hour in range(4)]
            if [int(row[0]) for row in rows] != expected:
                continue
            if bucket + cls.FOUR_HOURS_SECONDS * 1000 > now_ms:
                continue
            aggregated.append([
                bucket,
                float(rows[0][1]),
                max(float(row[2]) for row in rows),
                min(float(row[3]) for row in rows),
                float(rows[-1][4]),
                sum(float(row[5]) for row in rows),
            ])
        return aggregated

    def get_candles(
        self,
        interval: str = "1h",
        limit: int = 100,
        *,
        closed_only: bool = True,
        include_metadata: bool = False,
    ) -> list[list[float | int]] | dict:
        if interval not in {*self.GRANULARITY_SECONDS, "4h"}:
            raise ValueError("Unsupported Coinbase candle interval")
        try:
            limit = int(limit)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Candle limit must be an integer") from None
        if limit < 1 or limit > self.MAX_CANDLE_LIMIT:
            raise ValueError(
                f"Candle limit must be between 1 and {self.MAX_CANDLE_LIMIT}"
            )

        self._ensure_product_active()
        if interval == "4h":
            # Four hourly candles are required for every emitted 4h candle.
            raw_limit = min(
                self.MAX_RAW_4H_CANDLES,
                limit * 4 + (4 if closed_only else 0),
            )
            hourly = self._fetch_normalized_candles(
                3600, raw_limit, max_count=self.MAX_RAW_4H_CANDLES
            )
            hourly_interval_ms = 3_600_000
            now_ms = int(self.clock_ms())
            if closed_only:
                hourly = [
                    row for row in hourly
                    if int(row[0]) + hourly_interval_ms <= now_ms
                ]
                expected_hour = (now_ms // hourly_interval_ms) * hourly_interval_ms - hourly_interval_ms
                if not hourly or int(hourly[-1][0]) != expected_hour:
                    raise CoinbaseMarketDataError(
                        "Coinbase returned stale or incomplete hourly candles",
                        status_code=503,
                    )
            candles = self._aggregate_four_hour(hourly, now_ms=now_ms)[-limit:]
            if closed_only:
                expected_latest = (
                    (now_ms // (self.FOUR_HOURS_SECONDS * 1000))
                    * (self.FOUR_HOURS_SECONDS * 1000)
                    - self.FOUR_HOURS_SECONDS * 1000
                )
                if not candles or int(candles[-1][0]) != expected_latest:
                    raise CoinbaseMarketDataError(
                        "Coinbase could not build the latest complete 4h candle",
                        status_code=503,
                    )
        else:
            candles = self._get_native_candles(
                interval, limit, closed_only=closed_only
            )

        complete = len(candles) >= limit
        metadata = {
            "candles": candles,
            "complete": complete,
            "history_exhausted": len(candles) < limit,
            "provider_page_short": False,
            "requested": limit,
            "returned": len(candles),
            "interval": interval,
            "closed_only": closed_only,
        }
        if include_metadata:
            return metadata
        if not complete:
            raise CoinbaseMarketDataError(
                "Coinbase returned incomplete candle history", status_code=503
            )
        return candles
