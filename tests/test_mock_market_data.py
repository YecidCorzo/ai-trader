import unittest

from services.backtest_service import BacktestService
from indicators.ema import calculate_ema
from indicators.rsi import calculate_rsi_series
from tests.helpers.mock_market_data import (
    SCENARIOS,
    generate_ohlcv,
    make_invalid_ohlcv,
)


class MockMarketDataHarnessTests(unittest.TestCase):
    def test_generation_is_reproducible_for_same_seed(self):
        first = generate_ohlcv(count=80, scenario="volatile", seed=42)
        second = generate_ohlcv(count=80, scenario="volatile", seed=42)
        self.assertEqual(first, second)

    def test_all_scenarios_generate_valid_ordered_ohlcv(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                candles = generate_ohlcv(count=80, scenario=scenario)
                self.assertEqual(len(candles), 80)
                self.assertEqual(
                    [row[0] for row in candles],
                    sorted(row[0] for row in candles),
                )
                for timestamp, open_price, high, low, close, volume in candles:
                    self.assertGreater(timestamp, 0)
                    self.assertGreater(low, 0)
                    self.assertGreaterEqual(high, max(open_price, close, low))
                    self.assertLessEqual(low, min(open_price, close, high))
                    self.assertGreaterEqual(volume, 0)

    def test_trend_scenarios_have_expected_direction(self):
        rising = generate_ohlcv(count=120, scenario="uptrend", seed=11)
        falling = generate_ohlcv(count=120, scenario="downtrend", seed=11)
        self.assertGreater(rising[-1][4], rising[0][1])
        self.assertLess(falling[-1][4], falling[0][1])

    def test_sideways_scenario_mean_reverts_near_starting_price(self):
        candles = generate_ohlcv(count=500, scenario="sideways", seed=19)
        closes = [row[4] for row in candles]
        self.assertLess(max(closes), 115.0)
        self.assertGreater(min(closes), 85.0)

    def test_zero_volume_scenario_is_supported(self):
        candles = generate_ohlcv(count=60, scenario="zero_volume")
        self.assertTrue(all(row[5] == 0 for row in candles))

    def test_gap_scenario_contains_opening_gap(self):
        candles = generate_ohlcv(count=60, scenario="gap")
        gap_index = len(candles) // 2
        self.assertGreater(candles[gap_index][1], candles[gap_index - 1][4])

    def test_invalid_scenarios_are_rejected(self):
        with self.assertRaises(ValueError):
            generate_ohlcv(scenario="unknown")
        with self.assertRaises(ValueError):
            generate_ohlcv(count=0)

    def test_ema_and_rsi_indicators_have_deterministic_edge_values(self):
        self.assertAlmostEqual(calculate_ema([10.0, 12.0, 14.0], 2), 13.1111111111)
        flat_rsi = calculate_rsi_series([100.0] * 16, period=14)
        rising_rsi = calculate_rsi_series([float(i) for i in range(16)], period=14)
        self.assertEqual(flat_rsi[-1], 50.0)
        self.assertEqual(rising_rsi[-1], 100.0)
        self.assertIsNone(rising_rsi[13])

    def test_backtester_accepts_synthetic_market_history_in_paper_mode(self):
        candles = generate_ohlcv(count=240, scenario="uptrend", seed=21)
        result = BacktestService().run(candles)
        self.assertEqual(result["mode"], "paper")
        self.assertEqual(result["initial_balance"], 10000.0)
        self.assertIsInstance(result["trades"], list)

    def test_invalid_candles_are_rejected_by_backtester(self):
        for kind in ("negative_volume", "inconsistent_ohlc", "non_finite_close"):
            with self.subTest(kind=kind):
                candles = generate_ohlcv(count=60)
                invalid = make_invalid_ohlcv(kind)
                invalid[0] = candles[10][0]
                candles[10] = invalid
                with self.assertRaises(ValueError):
                    BacktestService().run(candles)


if __name__ == "__main__":
    unittest.main()
