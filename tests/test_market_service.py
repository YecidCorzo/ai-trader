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


if __name__ == "__main__":
    unittest.main()
