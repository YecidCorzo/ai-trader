import unittest
from unittest.mock import patch

from backend.services.backtest_service import BacktestService


class BacktestEndOfDataTests(unittest.TestCase):
    @staticmethod
    def make_candles():
        return [
            {
                "time": index,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 if index < 39 else 100.5,
                "volume": 10.0,
            }
            for index in range(40)
        ]

    def test_open_long_position_is_closed_at_last_close_with_costs(self):
        candles = self.make_candles()
        fast_ema = [99.0] * 40
        slow_ema = [100.0] * 40
        fast_ema[15] = 101.0
        rsi = [60.0] * 40
        atr = [1.0] * 40
        service = BacktestService(
            initial_balance=10000.0, fee_rate=0.001,
            slippage_rate=0.0005, risk_per_trade=0.01,
            atr_multiplier=1.5, reward_risk=2.0,
        )
        with (
            patch.object(BacktestService, "_ema_series", side_effect=[fast_ema, slow_ema]),
            patch.object(BacktestService, "_rsi_series", return_value=rsi),
            patch.object(BacktestService, "_atr_series", return_value=atr),
        ):
            result = service.run(candles, fast_period=2, slow_period=3,
                                 rsi_period=2, rsi_long_min=50, rsi_short_max=50)
        self.assertEqual(result["total_trades"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["direction"], "LONG")
        self.assertEqual(trade["reason"], "end_of_data")
        self.assertEqual(trade["exit_time"], 39)
        self.assertAlmostEqual(trade["exit"], 100.5 * (1 - 0.0005), places=6)
        self.assertGreater(trade["fees"], 0)
        self.assertAlmostEqual(result["final_balance"],
                               result["initial_balance"] + trade["net_pnl"], places=2)

    def test_open_short_position_is_closed_at_last_close_with_costs(self):
        candles = self.make_candles()
        fast_ema = [101.0] * 40
        slow_ema = [100.0] * 40
        fast_ema[15] = 99.0
        rsi = [40.0] * 40
        atr = [1.0] * 40
        service = BacktestService(
            initial_balance=10000.0, fee_rate=0.001,
            slippage_rate=0.0005, risk_per_trade=0.01,
            atr_multiplier=1.5, reward_risk=2.0,
        )
        with (
            patch.object(BacktestService, "_ema_series", side_effect=[fast_ema, slow_ema]),
            patch.object(BacktestService, "_rsi_series", return_value=rsi),
            patch.object(BacktestService, "_atr_series", return_value=atr),
        ):
            result = service.run(candles, fast_period=2, slow_period=3,
                                 rsi_period=2, rsi_long_min=50, rsi_short_max=50)
        self.assertEqual(result["total_trades"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["direction"], "SHORT")
        self.assertEqual(trade["reason"], "end_of_data")
        self.assertEqual(trade["exit_time"], 39)
        self.assertAlmostEqual(trade["exit"], 100.5 * (1 + 0.0005), places=6)
        self.assertGreater(trade["fees"], 0)
        self.assertAlmostEqual(result["final_balance"],
                               result["initial_balance"] + trade["net_pnl"], places=2)


if __name__ == "__main__":
    unittest.main()
