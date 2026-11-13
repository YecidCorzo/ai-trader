import unittest

from backend.services.backtest_research import run_advanced_strategy_walk_forward_backtests


class NeutralStrategy:
    def evaluate(self, **kwargs):
        return {"signal": "NEUTRAL"}


class OnePreTestSignalStrategy:
    def evaluate(self, *, candles, **kwargs):
        if candles[-1]["time"] != 59:
            return {"signal": "NEUTRAL"}
        return {
            "signal": "LONG", "score": 80, "reasons": ["first test fold"],
            "entry": 100.0, "stop_loss": 95.0,
            "take_profit_1": 105.0, "take_profit_2": 110.0,
            "risk_reward": 2.0,
        }


def raw_candles():
    rows = []
    for index in range(140):
        rows.append([index, 100.0, 101.0, 99.0, 100.0, 10.0])
    rows[60] = [60, 100.0, 106.0, 100.0, 100.0, 10.0]
    rows[61] = [61, 101.0, 111.0, 101.0, 101.0, 10.0]
    return rows


class AdvancedStrategyWalkForwardTests(unittest.TestCase):
    def test_walk_forward_folds_are_chronological_non_overlapping_and_advanced(self):
        result = run_advanced_strategy_walk_forward_backtests(
            raw_candles(),
            train_size=50,
            validation_size=10,
            test_size=10,
            step_size=10,
            backtest_kwargs={"strategy": NeutralStrategy()},
        )
        self.assertEqual(result["strategy"], "AdvancedStrategy")
        self.assertEqual(result["framework"], "fixed_parameter_advanced_strategy_chronological_walk_forward")
        self.assertFalse(result["parameter_optimization_performed"])
        self.assertEqual(result["fold_count"], 8)
        self.assertEqual(result["total_trades"], 0)
        for index, fold in enumerate(result["folds"]):
            start, end = fold["test_range"]
            self.assertEqual(end - start, 10)
            self.assertGreaterEqual(start, 60)
            if index:
                self.assertGreaterEqual(start, result["folds"][index - 1]["test_range"][1])

    def test_signal_before_test_enters_at_first_test_candle_open(self):
        result = run_advanced_strategy_walk_forward_backtests(
            raw_candles(),
            train_size=50,
            validation_size=10,
            test_size=10,
            step_size=10,
            backtest_kwargs={"strategy": OnePreTestSignalStrategy()},
        )
        self.assertEqual(result["folds"][0]["trade_count"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["signal_time"], 59)
        self.assertEqual(trade["entry_time"], 60)
        self.assertGreaterEqual(trade["entry_time"], result["folds"][0]["test_range"][0])
        self.assertEqual(trade["exit_time"], 61)

    def test_insufficient_indicator_warmup_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "50 velas"):
            run_advanced_strategy_walk_forward_backtests(
                raw_candles(),
                train_size=30,
                validation_size=10,
                test_size=10,
                step_size=10,
                backtest_kwargs={"strategy": NeutralStrategy()},
            )


if __name__ == "__main__":
    unittest.main()
