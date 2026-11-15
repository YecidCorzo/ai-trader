import unittest
from scripts.run_multi_symbol_advanced_strategy_acceptance import (
    CONFIG, aggregate_symbol_results, histories_are_aligned,
)


class MultiSymbolAcceptanceTests(unittest.TestCase):
    def _fixture(self, trades_per_fold=1):
        candles = [[i * 3600000, "1", "1", "1", "1", "1"] for i in range(10000)]
        by_symbol, runs = {}, {}
        for symbol in CONFIG["symbols"]:
            by_symbol[symbol] = candles
            trades, folds = [], []
            for fold in range(1, 5):
                start = 6000 + (fold - 1) * 1000
                for offset in range(trades_per_fold):
                    trades.append({"entry_time": (start + offset) * 3600000,
                                   "net_pnl": 10.0, "cost_in_r": 0.1})
                folds.append({"fold": fold, "test_range": [start, start + 1000],
                              "trade_count": trades_per_fold, "net_pnl": 10.0 * trades_per_fold,
                              "max_drawdown_percent": 2.0})
            runs[symbol] = {"folds": folds, "trades": trades,
                            "total_trades": len(trades), "net_pnl": 40.0 * trades_per_fold,
                            "expectancy_per_trade": 10.0, "profit_factor": None,
                            "max_fold_drawdown_percent": 2.0, "total_fees": 1.0,
                            "average_cost_in_r": 0.1}
        return runs, by_symbol

    def test_pools_outcomes_and_preserves_independent_simulation_semantics(self):
        runs, candles = self._fixture()
        result = aggregate_symbol_results(runs, candles)
        self.assertEqual(result["total_trades"], len(CONFIG["symbols"]) * 4)
        self.assertEqual(result["net_pnl"], len(CONFIG["symbols"]) * 40.0)
        self.assertEqual([f["trade_count"] for f in result["folds"]], [len(CONFIG["symbols"])] * 4)
        self.assertIn("not a portfolio equity curve", result["aggregation"])
        self.assertTrue(all("symbol" in trade and "fold" in trade for trade in result["trades"]))

    def test_requires_identical_contiguous_hourly_timestamps(self):
        candles = [[i * 3600000, "1", "1", "1", "1", "1"] for i in range(10000)]
        aligned = {symbol: candles for symbol in CONFIG["symbols"]}
        self.assertTrue(histories_are_aligned(aligned))
        broken = dict(aligned)
        broken[CONFIG["symbols"][0]] = candles[:-1] + [[9999 * 3600000 + 1, "1", "1", "1", "1", "1"]]
        self.assertFalse(histories_are_aligned(broken))
        missing_pair = dict(aligned)
        missing_pair.pop(CONFIG["symbols"][-1])
        self.assertFalse(histories_are_aligned(missing_pair))

    def test_rejects_changed_symbol_universe(self):
        with self.assertRaises(ValueError):
            aggregate_symbol_results({}, {})

    def test_rejects_trade_count_mismatch(self):
        runs, candles = self._fixture()
        runs[CONFIG["symbols"][0]]["total_trades"] += 1
        with self.assertRaises(ValueError):
            aggregate_symbol_results(runs, candles)

    def test_rejects_unattributed_trade_outside_oos_folds(self):
        runs, candles = self._fixture()
        symbol = CONFIG["symbols"][0]
        runs[symbol]["trades"].append({
            "entry_time": 5000 * 3600000, "net_pnl": 999.0, "cost_in_r": 0.1,
        })
        runs[symbol]["total_trades"] += 1
        with self.assertRaisesRegex(ValueError, "outside the frozen OOS folds"):
            aggregate_symbol_results(runs, candles)

    def test_rejects_duplicate_fold_number(self):
        runs, candles = self._fixture()
        symbol = CONFIG["symbols"][0]
        runs[symbol]["folds"][3]["fold"] = 1
        with self.assertRaisesRegex(ValueError, "invalid or duplicate fold number"):
            aggregate_symbol_results(runs, candles)

    def test_rejects_fold_pnl_that_does_not_match_trade_ledger(self):
        runs, candles = self._fixture()
        symbol = CONFIG["symbols"][0]
        runs[symbol]["folds"][0]["net_pnl"] += 500.0
        with self.assertRaisesRegex(ValueError, "ledger PnL does not reconcile"):
            aggregate_symbol_results(runs, candles)

    def test_rejects_symbol_pnl_that_does_not_match_trade_ledger(self):
        runs, candles = self._fixture()
        symbol = CONFIG["symbols"][0]
        runs[symbol]["net_pnl"] += 500.0
        with self.assertRaisesRegex(ValueError, "symbol ledger PnL does not reconcile"):
            aggregate_symbol_results(runs, candles)


if __name__ == "__main__":
    unittest.main()
