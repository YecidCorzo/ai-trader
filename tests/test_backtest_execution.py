import unittest

from backend.services.backtest_service import BacktestService


class BacktestExecutionTests(unittest.TestCase):
    def test_open_position_drawdown_includes_unrealized_loss(self):
        peak, drawdown = BacktestService._update_equity_drawdown(
            balance=10000.0,
            direction="LONG",
            entry=100.0,
            quantity=50.0,
            mark_price=90.0,
            entry_fee=5.0,
            fee_rate=0.001,
            peak_equity=10000.0,
            max_drawdown=0.0,
        )
        self.assertAlmostEqual(peak, 10000.0)
        self.assertAlmostEqual(drawdown * 100, 5.0, places=2)

    def test_long_stop_gap_fills_at_open_not_stop(self):
        price, reason = BacktestService._resolve_candle_exit(
            "LONG",
            {"open": 98.0, "high": 99.0, "low": 97.0, "close": 98.5},
            stop=99.0,
            target=103.0,
            slippage_rate=0.001,
        )
        self.assertEqual(reason, "stop_loss")
        self.assertAlmostEqual(price, 97.902)

    def test_short_stop_gap_fills_at_open_not_stop(self):
        price, reason = BacktestService._resolve_candle_exit(
            "SHORT",
            {"open": 102.0, "high": 103.0, "low": 101.0, "close": 102.5},
            stop=101.0,
            target=97.0,
            slippage_rate=0.001,
        )
        self.assertEqual(reason, "stop_loss")
        self.assertAlmostEqual(price, 102.102)

    def test_stop_wins_when_stop_and_target_hit_in_same_candle(self):
        price, reason = BacktestService._resolve_candle_exit(
            "LONG",
            {"open": 100.0, "high": 104.0, "low": 98.0, "close": 101.0},
            stop=99.0,
            target=103.0,
            slippage_rate=0.001,
        )
        self.assertEqual(reason, "stop_loss")
        self.assertAlmostEqual(price, 98.901)

    def test_target_fill_does_not_assume_gap_price_improvement(self):
        price, reason = BacktestService._resolve_candle_exit(
            "LONG",
            {"open": 104.0, "high": 105.0, "low": 103.5, "close": 104.5},
            stop=99.0,
            target=103.0,
            slippage_rate=0.001,
        )
        self.assertEqual(reason, "take_profit")
        self.assertAlmostEqual(price, 102.897)

    def test_no_level_touch_keeps_position_open(self):
        price, reason = BacktestService._resolve_candle_exit(
            "SHORT",
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
            stop=103.0,
            target=97.0,
            slippage_rate=0.001,
        )
        self.assertIsNone(price)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
