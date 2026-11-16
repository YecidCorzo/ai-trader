import unittest

from scripts.run_advanced_strategy_diagnostics import summarize_trades


class FixedParameterDiagnosticsTests(unittest.TestCase):
    def test_summarizes_net_pnl_profit_factor_and_costs(self):
        trades = [
            {"net_pnl": 10.0, "entry_fee": 1.0, "exit_fee": 1.0,
             "direction": "LONG", "exit_reason": "take_profit_2", "score": 85,
             "mfe_r": 2.0, "mae_r": 0.2, "cost_in_r": 0.1,
             "tp1_hit": True, "tp2_hit": True},
            {"net_pnl": -5.0, "entry_fee": 0.5, "exit_fee": 0.5,
             "direction": "SHORT", "exit_reason": "stop_loss", "score": 70,
             "mfe_r": 0.4, "mae_r": 1.1, "cost_in_r": 0.12,
             "tp1_hit": False, "tp2_hit": False},
        ]
        result = summarize_trades(trades, 3.0)
        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["net_pnl"], 5.0)
        self.assertEqual(result["profit_factor"], 2.0)
        self.assertEqual(result["total_fees"], 3.0)
        self.assertEqual(result["win_rate_percent"], 50.0)
        self.assertEqual(result["by_exit_reason"]["stop_loss"]["trade_count"], 1)
        self.assertEqual(result["by_score"]["80-89"]["net_pnl"], 10.0)

    def test_empty_trade_set_fails_closed_without_fake_metrics(self):
        result = summarize_trades([])
        self.assertEqual(result["trade_count"], 0)
        self.assertIsNone(result["expectancy_per_trade"])
        self.assertIsNone(result["profit_factor"])
        self.assertIsNone(result["win_rate_percent"])

    def test_rejects_non_finite_trade_pnl(self):
        with self.assertRaises(ValueError):
            summarize_trades([{"net_pnl": float("nan")}])


if __name__ == "__main__":
    unittest.main()
