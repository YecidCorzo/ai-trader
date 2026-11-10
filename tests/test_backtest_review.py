import unittest

from backend.services.backtest_review import review_backtest


class BacktestReviewTests(unittest.TestCase):
    def setUp(self):
        self.candles = [
            {"time": 1_700_000_000_000},
            {"time": 1_700_000_300_000},
        ]

    @staticmethod
    def make_trades(count, net_pnl=0.01):
        return [
            {"net_pnl": net_pnl, "entry": 100.0, "quantity": 1.0}
            for _ in range(count)
        ]

    def test_negative_expectancy_is_rejected(self):
        trades = self.make_trades(10, 0.40) + self.make_trades(20, -0.55)
        result = {
            "trades": trades,
            "win_rate_percent": 100 / 3,
            "max_drawdown_percent": 20,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, self.candles)
        self.assertEqual(review["decision"], "REJECT")
        self.assertIn("negative_expectancy", review["blocking_reasons"])
        self.assertFalse(review["live_trading_authorized"])

    def test_insufficient_trades_are_not_evaluable(self):
        result = {
            "trades": self.make_trades(29),
            "win_rate_percent": 100.0,
            "max_drawdown_percent": 5,
            "slippage_rate": 0.0005,
        }
        self.assertEqual(
            review_backtest(result, self.candles)["decision"],
            "NOT_EVALUABLE",
        )

    def test_short_history_requires_validation_when_not_rejected(self):
        result = {
            "trades": self.make_trades(30),
            "win_rate_percent": 100.0,
            "max_drawdown_percent": 10,
            "slippage_rate": 0.0005,
        }
        self.assertEqual(
            review_backtest(result, self.candles)["decision"],
            "VALIDATION_REQUIRED",
        )

    def test_five_years_and_positive_edge_can_only_refine(self):
        candles = [
            {"time": 1_500_000_000_000},
            {"time": 1_700_000_000_000},
        ]
        result = {
            "trades": self.make_trades(30),
            "win_rate_percent": 100.0,
            "max_drawdown_percent": 10,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, candles)
        self.assertEqual(review["decision"], "REFINE")
        self.assertFalse(review["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()


class ClaudeBacktestExpertIntegrationTests(unittest.TestCase):
    def test_realistic_losing_sample_is_rejected(self):
        from backend.services.backtest_review import review_backtest

        candles = [
            {"time": 1_790_000_000_000},
            {"time": 1_791_000_000_000},
        ]
        trades = (
            [{"net_pnl": 0.40, "entry": 100.0, "quantity": 1.0}] * 32
            + [{"net_pnl": -0.55, "entry": 100.0, "quantity": 1.0}] * 96
        )
        result = {
            "trades": trades,
            "win_rate_percent": 25.0,
            "max_drawdown_percent": 33.24,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, candles, parameter_count=8)
        self.assertEqual(review["decision"], "REJECT")
        self.assertFalse(review["live_trading_authorized"])
        self.assertEqual(review["quality_score"], 42)
        self.assertIn("negative_expectancy", review["blocking_reasons"])
        self.assertIn("short_test_period", review["blocking_reasons"])
