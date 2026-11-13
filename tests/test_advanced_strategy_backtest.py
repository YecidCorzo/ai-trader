import unittest

from backend.indicators.atr import calculate_atr
from backend.indicators.ema import calculate_ema
from backend.indicators.macd import calculate_macd
from backend.indicators.rsi import calculate_rsi_series
from backend.indicators.vwap import calculate_vwap
from backend.services.advanced_strategy_backtest import AdvancedStrategyBacktestService


class StubAdvancedStrategy:
    def __init__(self, side):
        self.side = side

    def evaluate(self, *, candles, **kwargs):
        if candles[-1]["time"] != 50:
            return {"signal": "NEUTRAL"}
        if self.side == "LONG":
            return {
                "signal": "LONG", "score": 80, "reasons": ["fixture LONG"],
                "stop_loss": 95.0, "take_profit_1": 105.0, "take_profit_2": 110.0,
            }
        return {
            "signal": "SHORT", "score": 80, "reasons": ["fixture SHORT"],
            "stop_loss": 105.0, "take_profit_1": 95.0, "take_profit_2": 90.0,
        }


def candles_fixture(side="LONG"):
    rows = []
    for index in range(60):
        candle = {
            "time": index, "open": 100.0, "high": 101.0,
            "low": 99.0, "close": 100.0, "volume": 10.0,
        }
        if index == 51:
            if side == "LONG":
                candle.update({"high": 106.0, "low": 100.0})
            else:
                candle.update({"high": 100.0, "low": 94.0})
        if index == 52:
            if side == "LONG":
                candle.update({"open": 101.0, "high": 111.0, "low": 101.0})
            else:
                candle.update({"open": 99.8, "high": 99.9, "low": 89.0})
        rows.append(candle)
    return rows


class AdvancedStrategyBacktestTests(unittest.TestCase):
    def test_indicator_series_match_live_indicator_functions(self):
        rows = candles_fixture()
        for index, candle in enumerate(rows):
            candle["close"] = 100.0 + index * 0.15 + (index % 4) * 0.05
            candle["open"] = candle["close"] - 0.05
            candle["high"] = candle["close"] + 0.4
            candle["low"] = candle["close"] - 0.4
        service = AdvancedStrategyBacktestService()
        values = service._indicator_series(rows)
        closes = [row["close"] for row in rows]
        self.assertAlmostEqual(values["ema_fast"][-1], calculate_ema(closes, 9), places=10)
        self.assertAlmostEqual(values["ema_slow"][-1], calculate_ema(closes, 21), places=10)
        self.assertAlmostEqual(values["ema_trend"][-1], calculate_ema(closes, 50), places=10)
        expected_slope = (values["ema_trend"][-1] - values["ema_trend"][-6]) / values["ema_trend"][-6]
        self.assertAlmostEqual(values["ema_trend_slope"][-1], expected_slope, places=12)
        self.assertAlmostEqual(values["rsi"][-1], calculate_rsi_series(closes, 14)[-1], places=10)
        self.assertAlmostEqual(values["macd_histogram"][-1], calculate_macd(closes)["histogram"], places=10)
        self.assertAlmostEqual(values["vwap"][-1], calculate_vwap(rows), places=10)
        self.assertAlmostEqual(values["atr"][-1], calculate_atr(rows, 14), places=10)

    def test_backtest_vwap_resets_at_utc_midnight(self):
        rows = [
            {"time": "2026-01-01T23:55:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"time": "2026-01-02T00:00:00Z", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 1},
            {"time": "2026-01-02T00:05:00Z", "open": 220, "high": 221, "low": 219, "close": 220, "volume": 3},
        ]
        values = AdvancedStrategyBacktestService._indicator_series(rows)
        self.assertAlmostEqual(values["vwap"][0], 100.0)
        self.assertAlmostEqual(values["vwap"][1], 200.0)
        self.assertAlmostEqual(values["vwap"][2], 215.0)

    def test_long_signal_uses_next_bar_open_and_adverse_fills(self):
        service = AdvancedStrategyBacktestService(strategy=StubAdvancedStrategy("LONG"))
        result = service.run(candles_fixture("LONG"))
        self.assertEqual(result["total_trades"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["signal_time"], 50)
        self.assertEqual(trade["entry_time"], 51)
        self.assertEqual(trade["exit_time"], 52)
        self.assertEqual(trade["exit_reason"], "take_profit_2")
        self.assertTrue(trade["tp1_hit"])
        self.assertAlmostEqual(trade["tp1_partial_quantity"], trade["quantity"] * 0.5, places=7)
        self.assertAlmostEqual(trade["remaining_quantity"], trade["quantity"] * 0.5, places=7)
        self.assertAlmostEqual(trade["stop_after_tp1"], trade["entry"], places=8)
        self.assertGreater(trade["entry"], 100.0)
        self.assertLess(trade["exit"], trade["take_profit_2"])
        self.assertLessEqual(trade["net_pnl"], trade["gross_pnl"])
        self.assertGreater(trade["tp1_exit_fee"], 0)
        self.assertGreater(trade["tp1_partial_quantity"], 0)
        self.assertAlmostEqual(
            result["total_fees"],
            trade["entry_fee"] + trade["exit_fee"],
            places=7,
        )
        self.assertLessEqual(trade["quantity"] * (
            abs(trade["entry"] - trade["stop_loss"] * (1 - service.slippage_rate))
            + trade["entry"] * service.fee_rate
            + trade["stop_loss"] * (1 - service.slippage_rate) * service.fee_rate
        ), 100.0)

    def test_short_signal_uses_next_bar_open_and_adverse_fills(self):
        service = AdvancedStrategyBacktestService(strategy=StubAdvancedStrategy("SHORT"))
        result = service.run(candles_fixture("SHORT"))
        self.assertEqual(result["total_trades"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["direction"], "SHORT")
        self.assertEqual(trade["signal_time"], 50)
        self.assertEqual(trade["entry_time"], 51)
        self.assertEqual(trade["exit_time"], 52)
        self.assertTrue(trade["tp1_hit"])
        self.assertGreater(trade["entry"], 0)
        self.assertLess(trade["entry"], 100.0)
        self.assertGreater(trade["exit"], trade["take_profit_2"])
        self.assertEqual(trade["exit_reason"], "take_profit_2")

    def test_long_moves_remaining_stop_to_break_even_after_tp1(self):
        rows = candles_fixture("LONG")
        rows[52].update({"open": 100.0, "high": 103.0, "low": 99.0})
        result = AdvancedStrategyBacktestService(strategy=StubAdvancedStrategy("LONG")).run(rows)
        trade = result["trades"][0]
        self.assertTrue(trade["tp1_hit"])
        self.assertEqual(trade["exit_reason"], "breakeven_stop")
        self.assertAlmostEqual(trade["stop_after_tp1"], trade["entry"], places=8)
        self.assertLess(trade["exit"], trade["entry"])

    def test_short_moves_remaining_stop_to_break_even_after_tp1(self):
        rows = candles_fixture("SHORT")
        rows[52].update({"open": 100.0, "high": 100.1, "low": 97.0})
        result = AdvancedStrategyBacktestService(strategy=StubAdvancedStrategy("SHORT")).run(rows)
        trade = result["trades"][0]
        self.assertTrue(trade["tp1_hit"])
        self.assertEqual(trade["exit_reason"], "breakeven_stop")
        self.assertAlmostEqual(trade["stop_after_tp1"], trade["entry"], places=8)
        self.assertGreater(trade["exit"], trade["entry"])

    def test_original_stop_wins_if_stop_and_tp1_are_touched_in_same_bar(self):
        rows = candles_fixture("LONG")
        rows[51].update({"high": 106.0, "low": 94.0})
        result = AdvancedStrategyBacktestService(strategy=StubAdvancedStrategy("LONG")).run(rows)
        trade = result["trades"][0]
        self.assertFalse(trade["tp1_hit"])
        self.assertEqual(trade["exit_reason"], "stop_loss")
        self.assertEqual(trade["tp1_partial_quantity"], 0.0)

    def test_insufficient_history_is_rejected(self):
        service = AdvancedStrategyBacktestService()
        with self.assertRaisesRegex(ValueError, "52 velas"):
            service.run(candles_fixture()[:51])

    def test_invalid_risk_fraction_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 y 1 %"):
            AdvancedStrategyBacktestService(risk_per_trade=0.02)


if __name__ == "__main__":
    unittest.main()
