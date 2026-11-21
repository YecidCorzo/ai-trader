"""Read-only Bitunix USDT-margined futures market-data client.

Only public market-data endpoints are implemented. No authentication,
account, position, or order functionality exists in this adapter.
"""
from __future__ import annotations

import math

import requests


class BitunixMarketDataError(RuntimeError):
    """A Bitunix public market-data failure safe to expose as HTTP 502/503."""

    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class BitunixMarketService:
    BASE_URL = "https://fapi.bitunix.com/api/v1/futures/market"
    SUPPORTED_INTERVALS = {
        "1m", "5m", "15m", "30m", "1h", "2h", "4h",
        "6h", "8h", "12h", "1d", "3d", "1w", "1M",
    }

    def __init__(self, symbol: str = "SOLUSDT", *, timeout: float = 10):
        self.symbol = symbol.upper()
        self.timeout = timeout

    def _request_data(self, endpoint: str, params: dict) -> object:
        try:
            response = requests.get(
                f"{self.BASE_URL}/{endpoint}", params=params, timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.Timeout, requests.ConnectionError) as error:
            raise BitunixMarketDataError(
                "Bitunix public market-data service is unavailable", status_code=503
            ) from error
        except requests.HTTPError as error:
            upstream_status = getattr(error.response, "status_code", None)
            status_code = (
                503 if upstream_status == 429
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
                "Bitunix returned invalid public market-data JSON", status_code=502
            ) from error

        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise BitunixMarketDataError(
                "Bitunix returned an unsuccessful market-data response",
                status_code=502,
            )
        return payload.get("data")

    def get_price(self) -> float:
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
        try:
            price = float(ticker["lastPrice"])
            if not math.isfinite(price) or price <= 0:
                raise ValueError("non-finite or non-positive price")
            return price
        except (TypeError, ValueError, KeyError):
            raise BitunixMarketDataError(
                "Bitunix returned an invalid futures ticker price", status_code=502
            ) from None

    def get_candles(self, interval: str = "5m", limit: int = 100,
                    *, closed_only: bool = True) -> list[list[float | int]]:
        """Return [open_time_ms, open, high, low, close, base_volume] rows.

        Bitunix documents that this REST endpoint returns completed candles.
        closed_only is accepted for provider-interface parity.
        """
        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported Bitunix futures interval: {interval}")
        limit = int(limit)
        if limit < 1:
            raise ValueError("El límite de velas debe ser mayor que cero")

        candles = []
        end_time = None
        while len(candles) < limit:
            batch_limit = min(200, limit - len(candles))
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
                    normalized.append(candle)

                normalized.sort(key=lambda candle: candle[0])
                if any(
                    normalized[index][0] == normalized[index + 1][0]
                    for index in range(len(normalized) - 1)
                ):
                    raise ValueError("duplicate candle timestamp")
                existing = {int(candle[0]) for candle in candles}
                normalized = [
                    candle for candle in normalized
                    if int(candle[0]) not in existing
                ]
                if not normalized:
                    break
                candles = normalized + candles
                end_time = int(normalized[0][0])
            except (TypeError, ValueError, KeyError, IndexError, OverflowError):
                raise BitunixMarketDataError(
                    "Bitunix returned malformed candle data", status_code=502
                ) from None
            if len(batch) < batch_limit:
                break

        candles.sort(key=lambda candle: candle[0])
        return candles[-limit:]
