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

    def test_rejects_single_candle_test_window(self):
        with self.assertRaisesRegex(ValueError, "al menos 2"):
            chronological_walk_forward_splits(list(range(20)), 8, 3, 1)

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


class WalkForwardExecutionTests(unittest.TestCase):
    def test_runner_executes_only_chronological_test_windows(self):
        from unittest.mock import patch
        from services.backtest_research import run_walk_forward_backtests

        candles = [
            {"time": i, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
            for i in range(50)
        ]
        calls = []

        class FakeBacktestService:
            def __init__(self, **kwargs):
                pass

            def run(self, raw, start_index=None, end_index=None):
                calls.append((start_index, end_index))
                return {
                    "trades": [{"net_pnl": 2.0}],
                    "total_trades": 1,
                    "net_profit": 2.0,
                    "return_percent": 0.02,
                    "win_rate_percent": 100.0,
                    "profit_factor": None,
                    "max_drawdown_percent": 0.0,
                    "long_net_pnl": 2.0,
                    "short_net_pnl": 0.0,
                    "total_fees": 0.1,
                }

        with patch("services.backtest_service.BacktestService", FakeBacktestService):
            result = run_walk_forward_backtests(
                candles,
                train_size=30,
                validation_size=5,
                test_size=5,
                step_size=5,
            )

        self.assertEqual(calls, [(34, 39), (39, 44), (44, 49)])
        self.assertEqual(result["fold_count"], 3)
        self.assertEqual(result["total_trades"], 3)
        self.assertEqual(result["net_pnl"], 6.0)
        self.assertFalse(result["parameter_optimization_performed"])
        self.assertEqual(result["mode"], "paper")

    def test_splits_reject_overlapping_test_windows(self):
        with self.assertRaisesRegex(ValueError, "solapamiento"):
            chronological_walk_forward_splits(
                list(range(40)),
                train_size=20,
                validation_size=5,
                test_size=10,
                step_size=5,
            )

    def test_runner_rejects_insufficient_indicator_warmup(self):
        from services.backtest_research import run_walk_forward_backtests

        candles = [
            {"time": i, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
            for i in range(20)
        ]
        with self.assertRaises(ValueError):
            run_walk_forward_backtests(
                candles,
                train_size=5,
                validation_size=5,
                test_size=5,
            )


if __name__ == "__main__":
    unittest.main()
