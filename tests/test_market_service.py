import unittest

from services.candle_utils import filter_closed_candles


class ClosedCandleTests(unittest.TestCase):
    def test_excludes_current_forming_kline(self):
        candles = [
            [1, "100", "102", "99", "101", "10", 999],
            [2, "101", "103", "100", "102", "11", 1000],
            [3, "102", "104", "101", "103", "12", 1100],
        ]
        closed = filter_closed_candles(candles, now_ms=1001)
        self.assertEqual([row[0] for row in closed], [1, 2])

    def test_close_time_equal_to_now_is_included(self):
        candle = [2, "101", "103", "100", "102", "11", 1000]
        self.assertEqual(filter_closed_candles([candle], now_ms=1000), [candle])

    def test_close_time_one_millisecond_after_now_is_excluded(self):
        candle = [3, "102", "104", "101", "103", "12", 1001]
        self.assertEqual(filter_closed_candles([candle], now_ms=1000), [])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(filter_closed_candles([], now_ms=1000), [])

    def test_missing_close_time_is_not_treated_as_closed(self):
        candles = [[1, "100", "102", "99", "101", "10"]]
        self.assertEqual(filter_closed_candles(candles, now_ms=1000), [])


class MarketServicePaginationTests(unittest.TestCase):
    @staticmethod
    def make_rows(start, count):
        return [
            [timestamp, "100", "102", "99", "101", "10", timestamp + 299999]
            for timestamp in range(start, start + count)
        ]

    def test_get_candles_fetches_multiple_pages_and_returns_chronological_limit(self):
        from unittest.mock import Mock, patch
        from services.market_services import MarketService

        recent = self.make_rows(1000, 1000)
        older = self.make_rows(500, 500)
        first_response = Mock()
        first_response.json.return_value = recent
        first_response.raise_for_status.return_value = None
        second_response = Mock()
        second_response.json.return_value = older
        second_response.raise_for_status.return_value = None

        with patch(
            "services.market_services.requests.get",
            side_effect=[first_response, second_response],
        ) as get:
            result = MarketService("SOLUSDT").get_candles(
                interval="5m", limit=1500
            )

        self.assertEqual(len(result), 1500)
        self.assertEqual(int(result[0][0]), 500)
        self.assertEqual(int(result[-1][0]), 1999)
        self.assertEqual(
            [int(row[0]) for row in result],
            sorted(int(row[0]) for row in result),
        )
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["limit"], 1000)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["limit"], 500)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["endTime"], 999)

    def test_get_candles_rejects_non_positive_limit(self):
        from services.market_services import MarketService

        with self.assertRaises(ValueError):
            MarketService().get_candles(limit=0)



if __name__ == "__main__":
    unittest.main()
