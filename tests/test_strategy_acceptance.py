import unittest
from unittest.mock import patch

from backend.main import app, get_advanced_strategy_acceptance
from backend.services.strategy_acceptance import (
    evaluate_advanced_strategy_go_no_go,
    ADVANCED_STRATEGY_ACCEPTANCE_CONFIG,
)


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
    def test_acceptance_config_is_frozen_to_solusdt_hourly_windows(self):
        self.assertEqual(ADVANCED_STRATEGY_ACCEPTANCE_CONFIG, {
            "config_id": "SOLUSDT-1H-10000-5000-1000-1000-1000-v1",
            "symbol": "SOL/USDT",
            "market_symbol": "SOLUSDT",
            "interval": "1h",
            "limit": 10000,
            "train_size": 5000,
            "validation_size": 1000,
            "test_size": 1000,
            "step_size": 1000,
            "required_bars": 7000,
            "expected_folds_at_full_history": 4,
        })

    def test_acceptance_endpoint_has_no_user_overridable_window_parameters(self):
        parameters = app.openapi()["paths"]["/api/backtest/advanced/acceptance"]["get"].get("parameters", [])
        self.assertEqual(parameters, [])

    @patch("backend.main.run_advanced_strategy_walk_forward_backtests")
    @patch("backend.main.market_service")
    def test_acceptance_uses_exact_preregistered_market_and_windows(self, market, run_walk_forward):
        rows = [[index, 100.0, 101.0, 99.0, 100.0, 10.0] for index in range(10000)]
        market.get_candles.return_value = rows
        run_walk_forward.return_value = walk_forward_fixture()

        result = get_advanced_strategy_acceptance()

        market.get_candles.assert_called_once_with(
            interval="1h", limit=10000, closed_only=True,
        )
        run_walk_forward.assert_called_once()
        args, kwargs = run_walk_forward.call_args
        self.assertEqual(len(args[0]), 10000)
        self.assertEqual(kwargs["train_size"], 5000)
        self.assertEqual(kwargs["validation_size"], 1000)
        self.assertEqual(kwargs["test_size"], 1000)
        self.assertEqual(kwargs["step_size"], 1000)
        self.assertEqual(result["acceptance_config"]["config_id"], "SOLUSDT-1H-10000-5000-1000-1000-1000-v1")
        self.assertTrue(result["history_complete"])
        self.assertEqual(result["decision"]["decision"], "GO")

    @patch("backend.main.run_advanced_strategy_walk_forward_backtests")
    @patch("backend.main.market_service")
    def test_insufficient_real_history_returns_no_go_not_server_error(self, market, run_walk_forward):
        market.get_candles.return_value = [
            [index, 100.0, 101.0, 99.0, 100.0, 10.0] for index in range(6999)
        ]

        result = get_advanced_strategy_acceptance()

        run_walk_forward.assert_not_called()
        self.assertFalse(result["history_complete"])
        self.assertEqual(result["decision"]["decision"], "NO_GO")
        self.assertEqual(result["decision"]["criteria_passed"], 0)
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
