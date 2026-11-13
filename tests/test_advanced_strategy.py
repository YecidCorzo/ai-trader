import unittest

from strategies.advanced_strategy import AdvancedStrategy


class AdvancedStrategyVwapTests(unittest.TestCase):
    def test_unavailable_vwap_does_not_create_false_short_score(self):
        candles = [
            {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 0.0}
            for _ in range(6)
        ]
        result = AdvancedStrategy().evaluate(
            candles=candles,
            ema_fast=100.0,
            ema_slow=100.0,
            ema_trend=100.0,
            rsi=50.0,
            macd={"histogram": 0.0},
            vwap=None,
            atr=1.0,
        )
        self.assertEqual(result["signal"], "NEUTRAL")
        self.assertEqual(result["long_score"], 0)
        self.assertEqual(result["short_score"], 0)
        self.assertTrue(any("VWAP no disponible" in reason for reason in result["reasons"]))


class AdvancedStrategyInvalidationTests(unittest.TestCase):
    @staticmethod
    def candles(direction):
        if direction == "LONG":
            prior = {"high": 100.0, "low": 98.0, "close": 99.0, "volume": 10.0}
            last = {"high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0}
        else:
            prior = {"high": 102.0, "low": 100.0, "close": 101.0, "volume": 10.0}
            last = {"high": 101.0, "low": 99.0, "close": 99.5, "volume": 10.0}
        return [dict(prior) for _ in range(5)] + [last]

    def test_long_plan_declares_at_or_below_atr_invalidation(self):
        result = AdvancedStrategy().evaluate(
            candles=self.candles("LONG"),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=2.0,
        )
        self.assertEqual(result["signal"], "LONG")
        self.assertEqual(result["invalidation"], {
            "price": result["stop_loss"],
            "trigger": "at_or_below",
            "basis": "atr_stop",
        })

    def test_short_plan_declares_at_or_above_atr_invalidation(self):
        result = AdvancedStrategy().evaluate(
            candles=self.candles("SHORT"),
            ema_fast=99.0, ema_slow=100.0, ema_trend=100.0,
            rsi=40.0, macd={"histogram": -1.0}, vwap=100.0, atr=2.0,
        )
        self.assertEqual(result["signal"], "SHORT")
        self.assertEqual(result["invalidation"], {
            "price": result["stop_loss"],
            "trigger": "at_or_above",
            "basis": "atr_stop",
        })

    def test_neutral_and_invalid_atr_plans_have_no_invalidation(self):
        neutral = AdvancedStrategy().evaluate(
            candles=[{"high": 101.0, "low": 99.0, "close": 100.0, "volume": 0.0}
                     for _ in range(6)],
            ema_fast=100.0, ema_slow=100.0, ema_trend=100.0,
            rsi=50.0, macd={"histogram": 0.0}, vwap=None, atr=1.0,
        )
        invalid_atr = AdvancedStrategy().evaluate(
            candles=[{"high": 101.0, "low": 99.0, "close": 100.0}],
            ema_fast=100.0, ema_slow=100.0, ema_trend=100.0,
            rsi=50.0, macd={"histogram": 0.0}, vwap=None, atr=0.0,
        )
        self.assertIsNone(neutral["invalidation"])
        self.assertIsNone(invalid_atr["invalidation"])


if __name__ == "__main__":
    unittest.main()
