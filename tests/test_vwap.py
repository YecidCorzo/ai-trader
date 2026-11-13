import unittest

from indicators.vwap import calculate_vwap, utc_day_key


class VwapTests(unittest.TestCase):
    def test_empty_candles_return_unavailable(self):
        self.assertIsNone(calculate_vwap([]))

    def test_zero_total_volume_returns_unavailable(self):
        candles = [
            {"time": "2026-01-02T00:00:00Z", "high": 101, "low": 99, "close": 100, "volume": 0},
            {"time": "2026-01-02T00:05:00Z", "high": 102, "low": 98, "close": 100, "volume": 0},
        ]
        self.assertIsNone(calculate_vwap(candles))

    def test_positive_volume_returns_current_utc_day_weighted_price(self):
        candles = [
            {"time": "2026-01-02T00:00:00Z", "high": 101, "low": 99, "close": 100, "volume": 2},
            {"time": "2026-01-02T00:05:00Z", "high": 102, "low": 100, "close": 101, "volume": 1},
        ]
        self.assertAlmostEqual(calculate_vwap(candles), 100.3333333333)

    def test_previous_utc_days_are_excluded_after_midnight(self):
        candles = [
            {"time": "2026-01-01T23:55:00Z", "high": 101, "low": 99, "close": 100, "volume": 100},
            {"time": "2026-01-02T00:00:00Z", "high": 201, "low": 199, "close": 200, "volume": 1},
            {"time": "2026-01-02T00:05:00Z", "high": 221, "low": 219, "close": 220, "volume": 3},
        ]
        self.assertAlmostEqual(calculate_vwap(candles), 215.0)

    def test_timezone_offsets_are_normalized_to_utc(self):
        candles = [
            {"time": "2026-01-02T00:00:00Z", "high": 101, "low": 99, "close": 100, "volume": 1},
            {"time": "2026-01-02T01:05:00+01:00", "high": 201, "low": 199, "close": 200, "volume": 1},
        ]
        self.assertAlmostEqual(calculate_vwap(candles), 150.0)
        self.assertEqual(utc_day_key(1767312000000), utc_day_key("2026-01-02T00:00:00Z"))

    def test_timestamp_is_required_and_must_be_timezone_aware(self):
        with self.assertRaisesRegex(ValueError, "timestamp UTC"):
            calculate_vwap([{"high": 101, "low": 99, "close": 100, "volume": 1}])
        with self.assertRaisesRegex(ValueError, "zona horaria"):
            utc_day_key("2026-01-02T00:00:00")


if __name__ == "__main__":
    unittest.main()
