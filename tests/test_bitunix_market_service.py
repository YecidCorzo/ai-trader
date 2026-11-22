import unittest
from unittest.mock import Mock, patch
import requests

from services.bitunix_market_service import (
    BitunixMarketDataError, BitunixMarketService,
)


BASE_TIME = 1_700_000_000_000


def candle(timestamp=BASE_TIME, **changes):
    row = {
        "time": timestamp, "open": "10", "high": "12",
        "low": "9", "close": "11", "baseVol": "123",
    }
    row.update(changes)
    return row


def service(symbol="SOLUSDT", **kwargs):
    # Avoid real sleeps in tests while retaining the rate-limiter path.
    return BitunixMarketService(
        symbol, monotonic=lambda: 10.0, sleep=lambda _: None, **kwargs
    )


class BitunixMarketServiceTests(unittest.TestCase):
    @patch("services.bitunix_market_service.requests.get")
    def test_get_price_uses_last_price_and_mark_price_is_separate(self, get):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {
            "code": 0,
            "data": [{"symbol": "SOLUSDT", "lastPrice": "150.25", "markPrice": "150.10"}],
        }
        get.return_value = response
        market = service("SOLUSDT")
        self.assertEqual(market.get_price(), 150.25)
        self.assertEqual(market.get_mark_price(), 150.10)
        self.assertEqual(get.call_count, 1)  # same short-lived ticker cache
        self.assertEqual(get.call_args.kwargs["timeout"], 10)

    @patch("services.bitunix_market_service.requests.get")
    def test_get_candles_normalizes_and_returns_metadata(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"code": 0, "data": [candle()]}
        get.return_value = response
        result = service(clock_ms=lambda: BASE_TIME + 900_000).get_candles(
            "5m", 1, include_metadata=True
        )
        self.assertEqual(result["candles"], [[BASE_TIME, 10.0, 12.0, 9.0, 11.0, 123.0]])
        self.assertTrue(result["complete"])
        self.assertEqual(get.call_args.kwargs["params"]["type"], "LAST_PRICE")

    @patch("services.bitunix_market_service.requests.get")
    def test_forming_candle_is_filtered_locally_and_extra_history_is_requested(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "code": 0,
            "data": [
                candle(BASE_TIME),
                candle(BASE_TIME + 300_000),
                candle(BASE_TIME + 600_000),
            ],
        }
        get.return_value = response
        result = service(clock_ms=lambda: BASE_TIME + 720_000).get_candles(
            "5m", 2, include_metadata=True
        )
        self.assertEqual([row[0] for row in result["candles"]], [BASE_TIME, BASE_TIME + 300_000])
        self.assertTrue(result["complete"])

    @patch("services.bitunix_market_service.requests.get")
    def test_gap_or_interval_mismatch_is_rejected(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "code": 0,
            "data": [candle(BASE_TIME), candle(BASE_TIME + 600_000)],
        }
        get.return_value = response
        with self.assertRaises(BitunixMarketDataError):
            service(clock_ms=lambda: BASE_TIME + 2_000_000).get_candles("5m", 2)

    @patch("services.bitunix_market_service.requests.get")
    def test_pagination_collects_contiguous_pages_without_silent_truncation(self, get):
        response_newer = Mock()
        response_newer.status_code = 200
        response_older = Mock()
        response_older.status_code = 200
        older = [candle(BASE_TIME + index * 300_000) for index in range(2)]
        newer = [candle(BASE_TIME + index * 300_000) for index in range(2, 202)]
        response_newer.json.return_value = {"code": 0, "data": newer}
        response_older.json.return_value = {"code": 0, "data": older}
        get.side_effect = [response_newer, response_older]
        result = service(clock_ms=lambda: BASE_TIME + 100_000_000).get_candles(
            "5m", 201, include_metadata=True
        )
        self.assertTrue(result["complete"])
        self.assertEqual(result["returned"], 201)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["endTime"], BASE_TIME + 600_000)

    @patch("services.bitunix_market_service.requests.get")
    def test_one_hour_request_rejects_five_minute_spacing(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "code": 0,
            "data": [candle(BASE_TIME), candle(BASE_TIME + 300_000), candle(BASE_TIME + 600_000)],
        }
        get.return_value = response
        with self.assertRaises(BitunixMarketDataError):
            service(clock_ms=lambda: BASE_TIME + 100_000_000).get_candles("1h", 2)

    @patch("services.bitunix_market_service.requests.get")
    def test_short_provider_page_is_explicitly_marked_incomplete(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"code": 0, "data": [candle()]}
        get.return_value = response
        result = service(clock_ms=lambda: BASE_TIME + 900_000).get_candles(
            "5m", 2, include_metadata=True
        )
        self.assertFalse(result["complete"])
        self.assertFalse(result["history_exhausted"])
        self.assertTrue(result["provider_page_short"])
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["requested"], 2)
        with self.assertRaises(BitunixMarketDataError):
            service(clock_ms=lambda: BASE_TIME + 900_000).get_candles("5m", 2)

    def test_monthly_interval_is_excluded_and_limit_is_bounded(self):
        market = service()
        with self.assertRaises(ValueError):
            market.get_candles("1M", 10)
        with self.assertRaises(ValueError):
            market.get_candles("5m", 1001)

    @patch("services.bitunix_market_service.requests.get")
    def test_non_finite_ticker_prices_are_rejected(self, get):
        response = Mock()
        response.status_code = 200
        get.return_value = response
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                market = service()
                response.json.return_value = {
                    "code": 0, "data": [{"symbol": "SOLUSDT", "lastPrice": value}],
                }
                with self.assertRaises(BitunixMarketDataError):
                    market.get_price()

    @patch("services.bitunix_market_service.requests.get")
    def test_non_finite_candle_values_are_rejected(self, get):
        response = Mock()
        response.status_code = 200
        get.return_value = response
        for field in ("open", "high", "low", "close", "baseVol"):
            for value in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(field=field, value=value):
                    response.json.return_value = {
                        "code": 0, "data": [candle(**{field: value})],
                    }
                    with self.assertRaises(BitunixMarketDataError):
                        service(clock_ms=lambda: BASE_TIME + 900_000).get_candles("5m", 1)

    @patch("services.bitunix_market_service.requests.get")
    def test_invalid_ohlcv_candles_and_duplicate_timestamps_are_rejected(self, get):
        response = Mock()
        response.status_code = 200
        get.return_value = response
        invalid_values = [
            {"high": "9.5"}, {"low": "11.5"}, {"baseVol": "-1"},
            {"time": "0"}, {"open": "0"},
        ]
        for changes in invalid_values:
            with self.subTest(changes=changes):
                response.json.return_value = {"code": 0, "data": [candle(**changes)]}
                with self.assertRaises(BitunixMarketDataError):
                    service(clock_ms=lambda: BASE_TIME + 900_000).get_candles("5m", 1)
        response.json.return_value = {"code": 0, "data": [candle(), candle()]}
        with self.assertRaises(BitunixMarketDataError):
            service(clock_ms=lambda: BASE_TIME + 900_000).get_candles("5m", 2)

    @patch("services.bitunix_market_service.requests.get")
    def test_418_and_429_are_retried_with_backoff_then_mapped_to_503(self, get):
        ok = Mock()
        ok.status_code = 200
        ok.json.return_value = {"code": 0, "data": [{"symbol": "SOLUSDT", "lastPrice": "10"}]}
        for status in (418, 429):
            limited = Mock()
            limited.status_code = status
            limited.headers = {"Retry-After": "0.25"}
            get.side_effect = [limited, ok]
            market = service()
            self.assertEqual(market.get_price(), 10.0)
            self.assertEqual(get.call_count, 2)
            get.reset_mock()

        limited = Mock()
        limited.status_code = 418
        limited.headers = {}
        get.side_effect = [limited, limited, limited]
        market = service()
        with self.assertRaises(BitunixMarketDataError) as caught:
            market.get_price()
        self.assertEqual(caught.exception.status_code, 503)

    @patch("services.bitunix_market_service.requests.get")
    def test_nonzero_api_code_is_error(self, get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"code": 10001, "data": None}
        get.return_value = response
        with self.assertRaises(BitunixMarketDataError):
            service().get_price()

    @patch("services.bitunix_market_service.requests.get")
    def test_timeout_is_provider_unavailable(self, get):
        get.side_effect = requests.Timeout()
        with self.assertRaises(BitunixMarketDataError) as caught:
            service().get_price()
        self.assertEqual(caught.exception.status_code, 503)

    def test_invalid_interval_and_zero_limit_are_rejected(self):
        with self.assertRaises(ValueError):
            service().get_candles("7m", 10)
        with self.assertRaises(ValueError):
            service().get_candles("5m", 0)


    @patch("services.bitunix_market_service.requests.get")
    def test_price_snapshot_preserves_original_cached_retrieval_time(self, get):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {
            "code": 0,
            "data": [{"symbol": "SOLUSDT", "lastPrice": "150.25"}],
        }
        get.return_value = response
        clock = [10.0]
        market = BitunixMarketService(
            "SOLUSDT", monotonic=lambda: clock[0], sleep=lambda _: None
        )
        first = market.get_price_snapshot()
        clock[0] = 12.0
        second = market.get_price_snapshot()
        self.assertEqual(first["price"], 150.25)
        self.assertEqual(second["price"], 150.25)
        self.assertAlmostEqual(
            (first["retrieved_at"] - second["retrieved_at"]).total_seconds(),
            2.0,
            delta=0.05,
        )
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
