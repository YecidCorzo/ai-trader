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
        self.assertAlmostEqual(drawdown * 100, 5.095, places=3)

    def test_short_liquidation_price_includes_maintenance_and_fees(self):
        price = BacktestService._short_liquidation_price(
            entry=100.0,
            fee_rate=0.001,
            maintenance_margin_rate=0.25,
        )
        self.assertGreater(price, 150.0)
        self.assertLess(price, 161.0)

    def test_short_gap_beyond_liquidation_fills_at_open(self):
        liquidation = BacktestService._short_liquidation_price(100.0, 0.001, 0.25)
        price, reason = BacktestService._resolve_candle_exit(
            "SHORT",
            {"open": liquidation + 5, "high": liquidation + 8,
             "low": liquidation + 2, "close": liquidation + 6},
            stop=110.0,
            target=90.0,
            slippage_rate=0.001,
            liquidation_price=liquidation,
        )
        self.assertEqual(reason, "liquidation")
        self.assertAlmostEqual(price, (liquidation + 5) * 1.001)

    def test_short_stop_is_checked_before_intrabar_liquidation(self):
        liquidation = BacktestService._short_liquidation_price(100.0, 0.001, 0.25)
        price, reason = BacktestService._resolve_candle_exit(
            "SHORT",
            {"open": 100.0, "high": liquidation + 1,
             "low": 99.0, "close": 110.0},
            stop=105.0,
            target=90.0,
            slippage_rate=0.001,
            liquidation_price=liquidation,
        )
        self.assertEqual(reason, "stop_loss")
        self.assertAlmostEqual(price, 105.105)

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
