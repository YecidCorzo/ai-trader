import unittest
from unittest.mock import Mock, patch

import requests

from services.coinbase_market_service import (
    CoinbaseMarketDataError,
    CoinbaseMarketService,
)


HOUR = 3_600_000
BASE_TIME = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC


def raw_candle(timestamp_ms, *, low=9, high=12, open_price=10, close=11, volume=123):
    # Coinbase Exchange API fixture order: [time_seconds, low, high, open, close, volume].
    return [
        timestamp_ms // 1000,
        str(low),
        str(high),
        str(open_price),
        str(close),
        str(volume),
    ]


def response(payload, status=200, headers=None):
    result = Mock()
    result.status_code = status
    result.headers = headers or {}
    result.json.return_value = payload
    result.raise_for_status.return_value = None
    return result


def products_payload(product_id="SOL-EUR"):
    return [{
        "id": product_id,
        "status": "online",
        "trading_disabled": False,
    }]


def market(product_id="SOL-EUR", *, now_ms=None, sleep=None):
    return CoinbaseMarketService(
        product_id,
        clock_ms=lambda: now_ms if now_ms is not None else BASE_TIME + HOUR,
        monotonic=lambda: 10.0,
        sleep=sleep or (lambda _: None),
    )


class CoinbaseMarketServiceTests(unittest.TestCase):
    @patch("services.coinbase_market_service.requests.get")
    def test_exchange_candle_field_order_is_normalized_explicitly(self, get):
        get.side_effect = [
            response(products_payload()),
            response([raw_candle(BASE_TIME, low=9, high=12, open_price=10, close=11, volume=123)]),
            response([]),
        ]
        rows = market().get_candles("1h", 1)
        self.assertEqual(rows, [[BASE_TIME, 10.0, 12.0, 9.0, 11.0, 123.0]])

    @patch("services.coinbase_market_service.requests.get")
    def test_pagination_collects_more_than_300_candles(self, get):
        candles = [raw_candle(BASE_TIME + index * HOUR) for index in range(301)]
        get.side_effect = [
            response(products_payload()),
            response(candles[2:]),
            response(candles[:2]),
        ]
        result = market(now_ms=BASE_TIME + 301 * HOUR).get_candles(
            "1h", 301, closed_only=False, include_metadata=True
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["returned"], 301)
        self.assertEqual(result["candles"][0][0], BASE_TIME)
        self.assertEqual(result["candles"][-1][0], BASE_TIME + 300 * HOUR)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["granularity"], 3600)

    @patch("services.coinbase_market_service.requests.get")
    def test_complete_four_hour_candle_aggregates_four_closed_hourly_rows(self, get):
        hourly = [
            raw_candle(BASE_TIME + index * HOUR, open_price=10 + index,
                       high=12 + index, low=9 + index, close=11 + index,
                       volume=100 + index)
            for index in range(4)
        ]
        get.side_effect = [
            response(products_payload()),
            response(hourly),
            response([]),
        ]
        rows = market(now_ms=BASE_TIME + 4 * HOUR).get_candles("4h", 1)
        self.assertEqual(rows, [[
            BASE_TIME, 10.0, 15.0, 9.0, 14.0, 406.0
        ]])

    @patch("services.coinbase_market_service.requests.get")
    def test_incomplete_four_hour_bucket_is_rejected(self, get):
        hourly = [
            raw_candle(BASE_TIME),
            raw_candle(BASE_TIME + HOUR),
            raw_candle(BASE_TIME + 3 * HOUR),
        ]
        get.side_effect = [
            response(products_payload()),
            response(hourly),
            response([]),
        ]
        with self.assertRaises(CoinbaseMarketDataError):
            market(now_ms=BASE_TIME + 4 * HOUR).get_candles("4h", 1)

    @patch("services.coinbase_market_service.requests.get")
    def test_four_hour_aggregation_is_aligned_across_utc_midnight(self, get):
        utc_day_start = BASE_TIME + 20 * HOUR
        hourly = [raw_candle(utc_day_start + index * HOUR) for index in range(4)]
        get.side_effect = [
            response(products_payload()),
            response(hourly),
            response([]),
        ]
        rows = market(now_ms=utc_day_start + 4 * HOUR).get_candles("4h", 1)
        self.assertEqual(rows[0][0], utc_day_start)
        self.assertEqual(rows[0][1:], [10.0, 12.0, 9.0, 11.0, 492.0])

    @patch("services.coinbase_market_service.requests.get")
    def test_forming_native_candle_is_excluded_locally(self, get):
        get.side_effect = [
            response(products_payload()),
            response([
                raw_candle(BASE_TIME),
                raw_candle(BASE_TIME + HOUR),
            ]),
        ]
        rows = market(now_ms=BASE_TIME + HOUR + 10 * 60_000).get_candles("1h", 1)
        self.assertEqual([row[0] for row in rows], [BASE_TIME])

    @patch("services.coinbase_market_service.requests.get")
    def test_gap_in_native_candle_series_is_rejected(self, get):
        get.side_effect = [
            response(products_payload()),
            response([
                raw_candle(BASE_TIME),
                raw_candle(BASE_TIME + 2 * HOUR),
            ]),
        ]
        with self.assertRaises(CoinbaseMarketDataError):
            market(now_ms=BASE_TIME + 3 * HOUR).get_candles(
                "1h", 2, closed_only=False
            )

    @patch("services.coinbase_market_service.requests.get")
    def test_stale_closed_candle_returns_503(self, get):
        get.side_effect = [
            response(products_payload()),
            response([raw_candle(BASE_TIME)]),
            response([]),
        ]
        with self.assertRaises(CoinbaseMarketDataError) as caught:
            market(now_ms=BASE_TIME + 3 * HOUR).get_candles("1h", 1)
        self.assertEqual(caught.exception.status_code, 503)

    @patch("services.coinbase_market_service.requests.get")
    def test_429_respects_retry_after_before_one_retry(self, get):
        sleeps = []
        limited = response({}, status=429, headers={"Retry-After": "1.25"})
        get.side_effect = [
            response(products_payload()),
            limited,
            response({"price": "123.45"}),
        ]
        snapshot = market(sleep=sleeps.append).get_price_snapshot()
        self.assertEqual(snapshot["price"], 123.45)
        self.assertEqual(sleeps, [1.25])
        self.assertEqual(get.call_count, 3)

    @patch("services.coinbase_market_service.requests.get")
    def test_product_not_found_returns_404(self, get):
        get.return_value = response([])
        with self.assertRaises(CoinbaseMarketDataError) as caught:
            market().get_price()
        self.assertEqual(caught.exception.status_code, 404)

    @patch("services.coinbase_market_service.requests.get")
    def test_inactive_product_is_rejected(self, get):
        payload = products_payload()
        payload[0]["status"] = "offline"
        get.return_value = response(payload)
        with self.assertRaises(CoinbaseMarketDataError) as caught:
            market().get_price()
        self.assertEqual(caught.exception.status_code, 503)

    def test_only_approved_european_quote_products_are_accepted(self):
        with self.assertRaises(ValueError):
            CoinbaseMarketService("SOL-USDT")

    @patch("services.coinbase_market_service.requests.get")
    def test_non_finite_or_incoherent_ohlcv_is_rejected(self, get):
        for invalid in (
            raw_candle(BASE_TIME, high="NaN"),
            raw_candle(BASE_TIME, high=8),
            raw_candle(BASE_TIME, volume=-1),
        ):
            with self.subTest(invalid=invalid):
                get.side_effect = [
                    response(products_payload()),
                    response([invalid]),
                    response([]),
                ]
                with self.assertRaises(CoinbaseMarketDataError):
                    market().get_candles("1h", 1)


if __name__ == "__main__":
    unittest.main()
