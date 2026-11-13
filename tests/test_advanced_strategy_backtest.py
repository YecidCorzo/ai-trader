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
                candle.update({"high": 111.0})
            else:
                candle.update({"low": 89.0})
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
        self.assertAlmostEqual(values["rsi"][-1], calculate_rsi_series(closes, 14)[-1], places=10)
        self.assertAlmostEqual(values["macd_histogram"][-1], calculate_macd(closes)["histogram"], places=10)
        self.assertAlmostEqual(values["vwap"][-1], calculate_vwap(rows), places=10)
        self.assertAlmostEqual(values["atr"][-1], calculate_atr(rows, 14), places=10)

    def test_long_signal_uses_next_bar_open_and_adverse_fills(self):
        service = AdvancedStrategyBacktestService(strategy=StubAdvancedStrategy("LONG"))
        result = service.run(candles_fixture("LONG"))
        self.assertEqual(result["total_trades"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["signal_time"], 50)
        self.assertEqual(trade["entry_time"], 51)
        self.assertEqual(trade["exit_time"], 51)
        self.assertEqual(trade["exit_reason"], "take_profit")
        self.assertGreater(trade["entry"], 100.0)
        self.assertLess(trade["exit"], 110.0)
        self.assertLessEqual(trade["net_pnl"], trade["gross_pnl"])
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
        self.assertGreater(trade["entry"], 0)
        self.assertLess(trade["entry"], 100.0)
        self.assertGreater(trade["exit"], 90.0)
        self.assertEqual(trade["exit_reason"], "take_profit")

    def test_insufficient_history_is_rejected(self):
        service = AdvancedStrategyBacktestService()
        with self.assertRaisesRegex(ValueError, "52 velas"):
            service.run(candles_fixture()[:51])

    def test_invalid_risk_fraction_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 y 1 %"):
            AdvancedStrategyBacktestService(risk_per_trade=0.02)


if __name__ == "__main__":
    unittest.main()
