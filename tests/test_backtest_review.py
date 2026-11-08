import unittest

from backend.services.backtest_review import review_backtest


class BacktestReviewTests(unittest.TestCase):
    def setUp(self):
        self.candles = [
            {"time": 1_700_000_000_000},
            {"time": 1_700_000_300_000},
        ]

    @staticmethod
    def profitable_trades(count):
        return [
            {"net_pnl": 10.0, "entry": 100.0, "quantity": 1.0}
            for _ in range(count)
        ]

    def test_negative_profit_factor_is_not_evaluable_with_small_sample(self):
        result = {
            "trades": [
                {"net_pnl": -10, "entry": 100, "quantity": 1},
                {"net_pnl": 5, "entry": 100, "quantity": 1},
            ],
            "max_drawdown_percent": 20,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, self.candles)
        self.assertEqual(review["decision"], "NOT_EVALUABLE")
        self.assertFalse(review["live_trading_authorized"])

    def test_insufficient_trades_are_not_evaluable(self):
        result = {
            "trades": self.profitable_trades(29),
            "max_drawdown_percent": 5,
            "slippage_rate": 0.0005,
        }
        self.assertEqual(
            review_backtest(result, self.candles)["decision"],
            "NOT_EVALUABLE",
        )

    def test_short_history_requires_validation(self):
        result = {
            "trades": self.profitable_trades(30),
            "max_drawdown_percent": 10,
            "slippage_rate": 0.0005,
        }
        self.assertEqual(
            review_backtest(result, self.candles)["decision"],
            "VALIDATION_REQUIRED",
        )

    def test_long_history_positive_edge_scores_deploy_but_never_authorizes_live(self):
        candles = [
            {"time": 1_500_000_000_000},
            {"time": 1_700_000_000_000},
        ]
        result = {
            "trades": self.profitable_trades(30),
            "max_drawdown_percent": 10,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, candles)
        self.assertEqual(review["decision"], "DEPLOY")
        self.assertGreaterEqual(review["years_tested_exact"], 6.0)
        self.assertFalse(review["live_trading_authorized"])

    def test_binance_array_candles_are_supported(self):
        candles = [
            [1_500_000_000_000, "100", "101", "99", "100", "10"],
            [1_700_000_000_000, "100", "101", "99", "100", "10"],
        ]
        result = {
            "trades": self.profitable_trades(30),
            "max_drawdown_percent": 10,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, candles)
        self.assertGreaterEqual(review["years_tested_exact"], 6.0)
        self.assertEqual(review["decision"], "DEPLOY")
        self.assertFalse(review["live_trading_authorized"])


class ClaudeBacktestExpertIntegrationTests(unittest.TestCase):
    def test_realistic_losing_sample_is_rejected(self):
        candles = [
            [1_790_000_000_000, "100", "101", "99", "100", "10"],
            [1_791_000_000_000, "100", "101", "99", "100", "10"],
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


if __name__ == "__main__":
    unittest.main()
