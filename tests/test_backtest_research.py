import unittest

from services.backtest_research import (
    buy_and_hold_baseline,
    chronological_walk_forward_splits,
    monte_carlo_trade_resampling,
)


class WalkForwardResearchTests(unittest.TestCase):
    def test_splits_are_chronological_and_do_not_overlap(self):
        candles = list(range(20))
        splits = chronological_walk_forward_splits(
            candles, train_size=8, validation_size=3, test_size=3, step_size=3
        )
        self.assertEqual(len(splits), 3)
        first = splits[0]
        self.assertEqual(first["train"], list(range(8)))
        self.assertEqual(first["validation"], [8, 9, 10])
        self.assertEqual(first["test"], [11, 12, 13])
        self.assertLess(max(first["train"]), min(first["validation"]))
        self.assertLess(max(first["validation"]), min(first["test"]))
        self.assertEqual(splits[1]["train"], list(range(11)))

    def test_rejects_too_short_history(self):
        with self.assertRaises(ValueError):
            chronological_walk_forward_splits([1, 2, 3], 2, 2, 2)

    def test_rejects_invalid_window_sizes(self):
        with self.assertRaises(ValueError):
            chronological_walk_forward_splits(list(range(20)), 0, 2, 2)


class MonteCarloResearchTests(unittest.TestCase):
    def test_seed_makes_results_reproducible(self):
        trades = [{"net_pnl": 12.0}, {"net_pnl": -8.0}, {"net_pnl": 3.0}]
        first = monte_carlo_trade_resampling(
            trades, 1000, simulations=250, seed=7
        )
        second = monte_carlo_trade_resampling(
            trades, 1000, simulations=250, seed=7
        )
        self.assertEqual(first, second)
        self.assertEqual(first["method"], "iid_trade_pnl_bootstrap")

    def test_empty_or_non_finite_trade_sample_is_rejected(self):
        with self.assertRaises(ValueError):
            monte_carlo_trade_resampling([], 1000)
        with self.assertRaises(ValueError):
            monte_carlo_trade_resampling([{"net_pnl": float("nan")}], 1000)


class BuyAndHoldResearchTests(unittest.TestCase):
    def test_benchmark_charges_costs_and_returns_traceable_assumptions(self):
        candles = [
            {"open": 100.0, "close": 100.0},
            {"open": 110.0, "close": 120.0},
        ]
        result = buy_and_hold_baseline(candles, 1000.0, 0.001, 0.001)
        self.assertGreater(result["fees"], 0)
        self.assertGreater(result["return_percent"], 0)
        self.assertEqual(result["benchmark"], "buy_and_hold_long")


if __name__ == "__main__":
    unittest.main()
