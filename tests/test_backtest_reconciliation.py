import copy
import json
from decimal import Decimal
from pathlib import Path
import unittest

from backend.services.backtest_reconciliation import (
    BacktestReconciliationError,
    reconcile_walk_forward_ledger,
)
from backend.services.backtest_research import run_advanced_strategy_walk_forward_backtests

ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "docs" / "research" / "advanced-strategy-acceptance-SOLUSDT-1h-run-788.json"
)


class EveryFifthCandleStrategy:
    """Deterministic LONG signals so folds contain winners and losers."""

    def evaluate(self, *, candles, **kwargs):
        last = candles[-1]
        if last["time"] % 5 != 4:
            return {"signal": "NEUTRAL"}
        close = last["close"]
        return {
            "signal": "LONG", "score": 80, "reasons": ["synthetic"],
            "entry": close, "stop_loss": close * 0.97,
            "take_profit_1": close * 1.03, "take_profit_2": close * 1.06,
            "risk_reward": 2.0,
        }


def synthetic_candles():
    rows = []
    for index in range(160):
        base = 100.0 + (index % 7) * 0.37
        # Alternate strong up and down bars after each signal candle.
        if index % 10 == 5:
            rows.append([index, base, base * 1.08, base * 0.999, base * 1.07, 10.0])
        elif index % 10 == 0 and index:
            rows.append([index, base, base * 1.001, base * 0.95, base * 0.96, 10.0])
        else:
            rows.append([index, base, base * 1.004, base * 0.996, base, 10.0])
    return rows


def synthetic_walk_forward():
    return run_advanced_strategy_walk_forward_backtests(
        synthetic_candles(),
        train_size=50,
        validation_size=10,
        test_size=20,
        step_size=20,
        backtest_kwargs={
            "strategy": EveryFifthCandleStrategy(),
            "initial_balance": 10000.0,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
            "risk_per_trade": 0.01,
        },
    )


class BacktestReconciliationTests(unittest.TestCase):
    def test_engine_output_reconciles_with_winners_and_losers(self):
        walk_forward = synthetic_walk_forward()
        self.assertGreaterEqual(walk_forward["total_trades"], 4)
        self.assertTrue(any(trade["net_pnl"] > 0 for trade in walk_forward["trades"]))
        self.assertTrue(any(trade["net_pnl"] < 0 for trade in walk_forward["trades"]))

        summary = reconcile_walk_forward_ledger(walk_forward)

        self.assertEqual(summary["status"], "RECONCILED")
        self.assertEqual(summary["trade_count"], walk_forward["total_trades"])
        self.assertEqual(summary["fold_count"], walk_forward["fold_count"])

    def test_published_run_788_artifact_reconciles(self):
        report = json.loads(ARTIFACT.read_text(encoding="utf-8"), parse_float=Decimal)
        summary = reconcile_walk_forward_ledger(report["walk_forward"])
        self.assertEqual(summary["trade_count"], 40)
        self.assertEqual(Decimal(summary["recomputed_net_pnl"]), Decimal("-292.05318018"))
        self.assertEqual(Decimal(summary["recomputed_total_fees"]), Decimal("313.29244217"))

    def test_tampered_trade_net_pnl_fails_closed(self):
        walk_forward = synthetic_walk_forward()
        walk_forward["trades"][0]["net_pnl"] += 0.01
        with self.assertRaisesRegex(BacktestReconciliationError, "net_pnl no reconcilia"):
            reconcile_walk_forward_ledger(walk_forward)

    def test_hidden_fee_reduction_fails_closed(self):
        walk_forward = synthetic_walk_forward()
        trade = walk_forward["trades"][0]
        trade["exit_fee"] -= 0.5
        trade["net_pnl"] += 0.5
        with self.assertRaisesRegex(BacktestReconciliationError, "balance no reconcilia"):
            reconcile_walk_forward_ledger(walk_forward)

    def test_aggregate_net_pnl_must_match_trades(self):
        walk_forward = synthetic_walk_forward()
        walk_forward["net_pnl"] += 1.0
        with self.assertRaisesRegex(BacktestReconciliationError, "net_pnl agregado"):
            reconcile_walk_forward_ledger(walk_forward)

    def test_aggregate_fees_must_match_trades(self):
        walk_forward = synthetic_walk_forward()
        walk_forward["total_fees"] -= 0.01
        with self.assertRaisesRegex(BacktestReconciliationError, "total_fees agregado"):
            reconcile_walk_forward_ledger(walk_forward)

    def test_dropped_trade_fails_closed(self):
        walk_forward = synthetic_walk_forward()
        walk_forward["trades"].pop()
        with self.assertRaisesRegex(BacktestReconciliationError, "no coincide"):
            reconcile_walk_forward_ledger(walk_forward)

    def test_non_finite_and_missing_values_fail_closed(self):
        base = synthetic_walk_forward()
        for field, value in (("gross_pnl", float("nan")), ("entry_fee", None), ("balance", "x")):
            walk_forward = copy.deepcopy(base)
            walk_forward["trades"][0][field] = value
            with self.assertRaises(BacktestReconciliationError):
                reconcile_walk_forward_ledger(walk_forward)

    def test_negative_fee_and_fractional_count_fail_closed(self):
        walk_forward = synthetic_walk_forward()
        walk_forward["trades"][0]["entry_fee"] = -1.0
        with self.assertRaisesRegex(BacktestReconciliationError, "negativas"):
            reconcile_walk_forward_ledger(walk_forward)
        walk_forward = synthetic_walk_forward()
        walk_forward["folds"][0]["trade_count"] = 1.5
        with self.assertRaisesRegex(BacktestReconciliationError, "entero"):
            reconcile_walk_forward_ledger(walk_forward)



class AcceptanceScriptReconciliationTests(unittest.TestCase):
    def _run_script(self, walk_forward):
        import sys
        import tempfile
        from unittest.mock import patch

        from scripts import run_advanced_strategy_acceptance as script

        class FakeMarket:
            def __init__(self, symbol):
                pass

            def get_candles(self, **kwargs):
                return [[index, 1, 1, 1, 1, 1] for index in range(10000)]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch.object(script, "MarketService", FakeMarket), patch.object(
                script, "run_advanced_strategy_walk_forward_backtests",
                return_value=walk_forward,
            ), patch.object(sys, "argv", ["acceptance", "--output", str(output)]), patch(
                "builtins.print"
            ):
                exit_code = script.main()
            return exit_code, json.loads(output.read_text(encoding="utf-8"))

    def test_report_includes_reconciliation_and_keeps_no_go_exit_zero(self):
        exit_code, report = self._run_script(synthetic_walk_forward())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["ledger_reconciliation"]["status"], "RECONCILED")
        self.assertIn("decision", report)

    def test_unreconciled_ledger_publishes_report_but_fails_job(self):
        walk_forward = synthetic_walk_forward()
        walk_forward["net_pnl"] += 5.0
        exit_code, report = self._run_script(walk_forward)
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["ledger_reconciliation"]["status"], "FAILED")
        self.assertIn("net_pnl agregado", report["ledger_reconciliation"]["error"])


if __name__ == "__main__":
    unittest.main()
