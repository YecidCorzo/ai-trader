import unittest

from indicators.vwap import calculate_vwap


class VwapTests(unittest.TestCase):
    def test_empty_candles_return_unavailable(self):
        self.assertIsNone(calculate_vwap([]))

    def test_zero_total_volume_returns_unavailable(self):
        candles = [
            {"high": 101, "low": 99, "close": 100, "volume": 0},
            {"high": 102, "low": 98, "close": 100, "volume": 0},
        ]
        self.assertIsNone(calculate_vwap(candles))

    def test_positive_volume_returns_volume_weighted_price(self):
        candles = [
            {"high": 101, "low": 99, "close": 100, "volume": 2},
            {"high": 102, "low": 100, "close": 101, "volume": 1},
        ]
        self.assertAlmostEqual(calculate_vwap(candles), 100.5)


if __name__ == "__main__":
    unittest.main()
