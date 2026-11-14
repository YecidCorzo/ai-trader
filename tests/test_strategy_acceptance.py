import unittest

from backend.services.strategy_acceptance import evaluate_advanced_strategy_go_no_go


def walk_forward_fixture():
    return {
        "total_trades": 100,
        "expectancy_per_trade": 1.25,
        "profit_factor": 1.3,
        "max_fold_drawdown_percent": 12.0,
        "fold_count": 4,
        "folds": [
            {"fold": 1, "trade_count": 25, "net_pnl": 31.25, "profit_factor": 1.25, "max_drawdown_percent": 10.0},
            {"fold": 2, "trade_count": 25, "net_pnl": 25.0, "profit_factor": 1.2, "max_drawdown_percent": 12.0},
            {"fold": 3, "trade_count": 25, "net_pnl": 37.5, "profit_factor": 1.4, "max_drawdown_percent": 8.0},
            {"fold": 4, "trade_count": 25, "net_pnl": 31.25, "profit_factor": 1.3, "max_drawdown_percent": 11.0},
        ],
    }


class AdvancedStrategyAcceptanceTests(unittest.TestCase):
    def test_go_requires_all_pre_registered_oos_gates(self):
        result = evaluate_advanced_strategy_go_no_go(walk_forward_fixture())
        self.assertEqual(result["decision"], "GO")
        self.assertEqual(result["criteria_passed"], result["criteria_total"])
        self.assertFalse(result["live_trading_authorized"])

    def test_no_go_when_oos_sample_is_below_100_trades(self):
        report = walk_forward_fixture()
        report["total_trades"] = 99
        result = evaluate_advanced_strategy_go_no_go(report)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertFalse(next(c for c in result["criteria"] if c["name"] == "oos_trade_count")["passed"])

    def test_no_go_when_expectancy_profit_factor_or_drawdown_fails(self):
        report = walk_forward_fixture()
        report["expectancy_per_trade"] = 0
        report["profit_factor"] = 1.19
        report["max_fold_drawdown_percent"] = 15.01
        result = evaluate_advanced_strategy_go_no_go(report)
        self.assertEqual(result["decision"], "NO_GO")
        failed = {item["name"] for item in result["criteria"] if not item["passed"]}
        self.assertTrue({
            "positive_oos_expectancy", "oos_profit_factor", "maximum_fold_drawdown"
        }.issubset(failed))

    def test_walk_forward_stability_requires_at_least_75_percent_positive_folds(self):
        report = walk_forward_fixture()
        report["folds"][2]["net_pnl"] = -1.0
        report["folds"][2]["profit_factor"] = 0.9
        report["folds"][3]["net_pnl"] = -1.0
        report["folds"][3]["profit_factor"] = 0.9
        result = evaluate_advanced_strategy_go_no_go(report)
        self.assertEqual(result["decision"], "NO_GO")
        stability = next(c for c in result["criteria"] if c["name"] == "walk_forward_stability")
        self.assertFalse(stability["passed"])
        self.assertEqual(stability["actual"]["positive_fold_ratio"], 0.5)

    def test_every_fold_needs_at_least_25_trades(self):
        report = walk_forward_fixture()
        report["folds"][0]["trade_count"] = 24
        result = evaluate_advanced_strategy_go_no_go(report)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertFalse(next(c for c in result["criteria"] if c["name"] == "minimum_trades_per_fold")["passed"])

    def test_missing_metrics_fail_closed(self):
        result = evaluate_advanced_strategy_go_no_go({"folds": []})
        self.assertEqual(result["decision"], "NO_GO")
        self.assertEqual(result["criteria_passed"], 0)

    def test_too_few_folds_fail_even_with_positive_aggregate_metrics(self):
        report = walk_forward_fixture()
        report["folds"] = report["folds"][:3]
        report["fold_count"] = 3
        result = evaluate_advanced_strategy_go_no_go(report)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertFalse(next(c for c in result["criteria"] if c["name"] == "walk_forward_fold_count")["passed"])


if __name__ == "__main__":
    unittest.main()
