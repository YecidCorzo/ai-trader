import unittest

from indicators.ema import calculate_ema, calculate_ema_series


class EmaSeriesTests(unittest.TestCase):
    def test_series_matches_single_value_calculation_for_each_prefix(self):
        values = [100.0, 101.0, 99.0, 102.0, 104.0, 103.0, 105.0]
        series = calculate_ema_series(values, 3)
        self.assertEqual(len(series), len(values))
        for index in range(len(values)):
            self.assertAlmostEqual(series[index], calculate_ema(values[:index + 1], 3), places=12)

    def test_empty_series_is_empty_and_single_value_is_seed(self):
        self.assertEqual(calculate_ema_series([], 9), [])
        self.assertEqual(calculate_ema_series([12.5], 9), [12.5])

    def test_invalid_period_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_ema_series([1, 2], 0)


if __name__ == "__main__":
    unittest.main()
