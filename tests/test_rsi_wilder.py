import unittest

from indicators.rsi import calculate_rsi, calculate_rsi_series


class WilderRsiTests(unittest.TestCase):
    def test_initial_value_uses_first_complete_period(self):
        values = calculate_rsi_series([1, 2, 3, 2, 3], period=3)
        self.assertEqual(values[:3], [None, None, None])
        self.assertAlmostEqual(values[3], 66.6666667, places=5)

    def test_wilder_smoothing_differs_from_recomputing_simple_window(self):
        closes = [10, 11, 10, 12, 11, 13, 12]
        values = calculate_rsi_series(closes, period=3)
        # After the initial 3-period average, Wilder recursively smooths
        # the next loss instead of recalculating a simple rolling window.
        self.assertAlmostEqual(values[3], 75.0, places=5)
        self.assertAlmostEqual(values[4], 54.5454545, places=5)
        self.assertAlmostEqual(values[5], 75.0, places=5)
        self.assertAlmostEqual(calculate_rsi(closes, period=3), values[-1])

    def test_flat_series_returns_neutral(self):
        self.assertEqual(calculate_rsi([5, 5, 5, 5], period=3), 50.0)

    def test_no_losses_returns_one_hundred(self):
        self.assertEqual(calculate_rsi([1, 2, 3, 4], period=3), 100.0)

    def test_invalid_period_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_rsi_series([1, 2], period=0)


if __name__ == "__main__":
    unittest.main()
