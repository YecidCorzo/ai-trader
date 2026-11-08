import unittest

from backend.services.backtest_review import review_backtest


class BacktestReviewTests(unittest.TestCase):
    def setUp(self):
        self.candles = [
            {"time": 1_700_000_000_000},
            {"time": 1_700_000_300_000},
        ]

    def test_negative_profit_factor_is_rejected(self):
        result = {
            "trades": [{"net_pnl": -10}, {"net_pnl": 5}],
            "profit_factor": 0.5,
            "max_drawdown_percent": 20,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
        }
        review = review_backtest(result, self.candles)
        self.assertEqual(review["decision"], "NOT_EVALUABLE")
        self.assertFalse(review["live_trading_authorized"])

    def test_insufficient_trades_are_not_evaluable(self):
        result = {
            "trades": [{"net_pnl": 10}] * 29,
            "profit_factor": 2.0,
            "max_drawdown_percent": 5,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
        }
        self.assertEqual(
            review_backtest(result, self.candles)["decision"],
            "NOT_EVALUABLE",
        )

    def test_short_history_requires_validation_when_not_rejected(self):
        result = {
            "trades": [{"net_pnl": 10}] * 30,
            "profit_factor": 1.2,
            "max_drawdown_percent": 10,
            "fee_rate": 0.001,
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
            "trades": [{"net_pnl": 10}] * 30,
            "profit_factor": 1.2,
            "max_drawdown_percent": 10,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
        }
        self.assertEqual(review_backtest(result, candles)["decision"], "REFINE")


if __name__ == "__main__":
    unittest.main()
