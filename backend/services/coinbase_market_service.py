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
    MAX_4H_CANDLE_LIMIT = 250
    MAX_RAW_4H_CANDLES = MAX_4H_CANDLE_LIMIT * 4 + 4
    MAX_CONSECUTIVE_SYNTHETIC = 6
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
        max_consecutive_synthetic: int = MAX_CONSECUTIVE_SYNTHETIC,
    ):
        normalized_product = str(product_id).upper()
        if normalized_product not in self.ALLOWED_PRODUCTS:
            raise ValueError("Coinbase product is not enabled for this adapter")
        self.product_id = normalized_product
        self.timeout = timeout
        if int(max_consecutive_synthetic) < 1:
            raise ValueError("max_consecutive_synthetic must be at least 1")
        self.max_consecutive_synthetic = int(max_consecutive_synthetic)
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

        # Sparse trading is valid at the provider level. Do not validate gaps
        # across the whole fetched page: continuity is checked only after the
        # exact requested output window has been built.
        candles.sort(key=lambda row: row[0])
        return candles

    def _verify_latest_synthetic_with_ticker(self, candle_start_ms: int) -> None:
        """A synthetic final candle is valid only when ticker confirms no trade in it.

        Coinbase candle endpoints omit no-trade intervals. If the ticker's last
        trade timestamp falls inside the synthetic interval, the omission is
        inconsistent and the series fails closed with 503.
        """
        payload, _ = self._request_json(f"/products/{self.product_id}/ticker")
        if not isinstance(payload, dict):
            raise CoinbaseMarketDataError(
                "Coinbase ticker cannot validate the latest synthetic candle",
                status_code=503,
            )
        try:
            ticker_time = datetime.fromisoformat(
                str(payload.get("time", "")).replace("Z", "+00:00")
            )
            if ticker_time.tzinfo is None:
                raise ValueError("ticker timestamp must be timezone-aware")
            ticker_ms = int(ticker_time.timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            raise CoinbaseMarketDataError(
                "Coinbase ticker timestamp is unavailable for synthetic-candle validation",
                status_code=503,
            ) from None
        if ticker_ms >= candle_start_ms:
            raise CoinbaseMarketDataError(
                "Coinbase ticker shows activity in the latest synthetic candle",
                status_code=503,
            )

    def _fill_missing_candles(
        self,
        candles: list[list[float | int]],
        *,
        start_ms: int,
        end_ms: int,
        interval_ms: int,
        verify_latest: bool,
    ) -> tuple[list[list[float | int]], set[int]]:
        """Fill only the requested output window, carrying forward prior close."""
        real_by_time = {
            int(row[0]): row for row in candles
            if start_ms <= int(row[0]) <= end_ms
        }
        prior_rows = [
            row for row in candles if int(row[0]) < start_ms
        ]
        previous_close = float(max(prior_rows, key=lambda row: row[0])[4]) if prior_rows else None
        output: list[list[float | int]] = []
        synthetic: set[int] = set()
        consecutive = 0
        real_count = 0

        for timestamp in range(start_ms, end_ms + 1, interval_ms):
            row = real_by_time.get(timestamp)
            if row is not None:
                output.append(row)
                previous_close = float(row[4])
                consecutive = 0
                real_count += 1
                continue
            if previous_close is None:
                # No prior close exists yet; do not invent leading history.
                continue
            consecutive += 1
            if consecutive > self.max_consecutive_synthetic:
                raise CoinbaseMarketDataError(
                    "Coinbase candle history exceeds the consecutive synthetic-candle limit",
                    status_code=503,
                )
            synthetic.add(timestamp)
            output.append([
                timestamp, previous_close, previous_close,
                previous_close, previous_close, 0.0,
            ])

        if real_count == 0:
            raise CoinbaseMarketDataError(
                "Coinbase returned no real candles in the requested interval",
                status_code=503,
            )
        if not output:
            raise CoinbaseMarketDataError(
                "Coinbase returned no usable candles in the requested interval",
                status_code=503,
            )
        if any(
            int(output[index + 1][0]) - int(output[index][0]) != interval_ms
            for index in range(len(output) - 1)
        ):
            raise CoinbaseMarketDataError(
                "Coinbase returned an incomplete candle window", status_code=503
            )
        if verify_latest and int(output[-1][0]) in synthetic:
            self._verify_latest_synthetic_with_ticker(int(output[-1][0]))
        return output, synthetic

    def _get_native_candles(
        self,
        interval: str,
        limit: int,
        *,
        closed_only: bool,
    ) -> tuple[list[list[float | int]], set[int]]:
        granularity = self.GRANULARITY_SECONDS[interval]
        target_count = limit + (1 if closed_only else 0)
        fetched = self._fetch_normalized_candles(
            granularity, target_count, max_count=self.MAX_CANDLE_LIMIT + 1
        )
        interval_ms = granularity * 1000
        now_ms = int(self.clock_ms())
        expected_latest = (
            (now_ms // interval_ms) * interval_ms - interval_ms
            if closed_only else (now_ms // interval_ms) * interval_ms
        )
        start_ms = expected_latest - (limit - 1) * interval_ms
        return self._fill_missing_candles(
            fetched,
            start_ms=start_ms,
            end_ms=expected_latest,
            interval_ms=interval_ms,
            verify_latest=closed_only,
        )

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
        max_limit = self.MAX_4H_CANDLE_LIMIT if interval == "4h" else self.MAX_CANDLE_LIMIT
        if limit < 1 or limit > max_limit:
            raise ValueError(f"Candle limit must be between 1 and {max_limit} for {interval}")

        self._ensure_product_active()
        if interval == "4h":
            # Cap at 250 output bars (<=1004 hourly rows), avoiding ~17 page
            # requests for a 1000-bar request while retaining closed-hour checks.
            hourly_interval_ms = 3_600_000
            four_hour_ms = self.FOUR_HOURS_SECONDS * 1000
            now_ms = int(self.clock_ms())
            latest_hour = (
                (now_ms // hourly_interval_ms) * hourly_interval_ms - hourly_interval_ms
                if closed_only else (now_ms // hourly_interval_ms) * hourly_interval_ms
            )
            latest_bucket = (latest_hour // four_hour_ms) * four_hour_ms
            start_bucket = latest_bucket - (limit - 1) * four_hour_ms
            raw_limit = limit * 4 + (4 if closed_only else 0)
            hourly_fetched = self._fetch_normalized_candles(
                3600, raw_limit, max_count=self.MAX_RAW_4H_CANDLES
            )
            hourly, hourly_synthetic = self._fill_missing_candles(
                hourly_fetched,
                start_ms=start_bucket,
                end_ms=latest_hour,
                interval_ms=hourly_interval_ms,
                verify_latest=False,
            )
            candles = self._aggregate_four_hour(hourly, now_ms=now_ms)[-limit:]
            synthetic_timestamps = set()
            for row in candles:
                bucket = int(row[0])
                if any(bucket + offset * hourly_interval_ms in hourly_synthetic for offset in range(4)):
                    synthetic_timestamps.add(bucket)
            if not candles or int(candles[-1][0]) != latest_bucket:
                raise CoinbaseMarketDataError(
                    "Coinbase could not build the latest complete 4h candle",
                    status_code=503,
                )
            if closed_only and int(candles[-1][0]) in synthetic_timestamps:
                self._verify_latest_synthetic_with_ticker(int(candles[-1][0]))
        else:
            candles, synthetic_timestamps = self._get_native_candles(
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
            "synthetic_count": len(synthetic_timestamps),
            "synthetic_timestamps": sorted(synthetic_timestamps),
        }
        if include_metadata:
            return metadata
        if not complete:
            raise CoinbaseMarketDataError(
                "Coinbase returned incomplete candle history", status_code=503
            )
        return candles
