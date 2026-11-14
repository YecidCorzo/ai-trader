"""Read-only Binance public market-data client with explicit upstream errors."""
from __future__ import annotations

import requests


class MarketDataError(RuntimeError):
    """A Binance/public-market-data failure safe to expose as HTTP 502/503."""

    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class MarketService:
    def __init__(self, symbol="SOLUSDT"):
        self.symbol = symbol
        self.base_url = "https://data-api.binance.vision/api/v3"

    def _request_json(self, endpoint, params):
        try:
            response = requests.get(
                f"{self.base_url}/{endpoint}",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError) as error:
            raise MarketDataError(
                "Binance public market-data service is unavailable",
                status_code=503,
            ) from error
        except requests.HTTPError as error:
            upstream_status = getattr(error.response, "status_code", None)
            status_code = (
                503 if upstream_status == 429
                or (upstream_status is not None and upstream_status >= 500)
                else 502
            )
            raise MarketDataError(
                "Binance rejected or failed the public market-data request",
                status_code=status_code,
            ) from error
        except requests.RequestException as error:
            raise MarketDataError(
                "Binance public market-data request failed",
                status_code=502,
            ) from error
        except (TypeError, ValueError) as error:
            raise MarketDataError(
                "Binance returned an invalid public market-data response",
                status_code=502,
            ) from error

    def get_price(self):
        data = self._request_json("ticker/price", {"symbol": self.symbol})
        try:
            price = float(data["price"])
            if not price > 0:
                raise ValueError("non-positive price")
            return price
        except (KeyError, TypeError, ValueError) as error:
            raise MarketDataError(
                "Binance returned an invalid ticker price",
                status_code=502,
            ) from error

    @staticmethod
    def _filter_closed_candles(candles, now_ms):
        from services.candle_utils import filter_closed_candles
        return filter_closed_candles(candles, now_ms)

    def get_candles(self, interval="5m", limit=100, closed_only=False):
        """Download historical candles in batches of up to 1,000."""
        limit = int(limit)
        if limit < 1:
            raise ValueError("El límite de velas debe ser mayor que cero")

        fetch_limit = limit + 1 if closed_only else limit
        candles = []
        end_time = None

        while len(candles) < fetch_limit:
            batch_limit = min(1000, fetch_limit - len(candles))
            params = {
                "symbol": self.symbol,
                "interval": interval,
                "limit": batch_limit,
            }
            if end_time is not None:
                params["endTime"] = end_time

            batch = self._request_json("klines", params)
            if not isinstance(batch, list):
                raise MarketDataError(
                    "Binance returned an invalid candle payload",
                    status_code=502,
                )
            if not batch:
                break

            try:
                # Avoid duplicates when paging backwards.
                existing_times = {int(candle[0]) for candle in candles}
                batch = [
                    candle for candle in batch
                    if int(candle[0]) not in existing_times
                ]
                if not batch:
                    break

                # Binance returns each batch in chronological order.
                candles = batch + candles
                end_time = int(batch[0][0]) - 1
            except (TypeError, ValueError, IndexError, KeyError) as error:
                raise MarketDataError(
                    "Binance returned malformed candle data",
                    status_code=502,
                ) from error

            if len(candles) >= fetch_limit:
                break

        if closed_only:
            import time
            try:
                candles = self._filter_closed_candles(
                    candles, int(time.time() * 1000)
                )
            except (TypeError, ValueError, IndexError, KeyError) as error:
                raise MarketDataError(
                    "Binance candle data could not be validated",
                    status_code=502,
                ) from error

        return candles[-limit:]
