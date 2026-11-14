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


class AdvancedStrategyCategoryConfirmationTests(unittest.TestCase):
    @staticmethod
    def candles():
        prior = {"high": 100.0, "low": 98.0, "close": 99.0, "volume": 10.0}
        last = {"high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0}
        return [dict(prior) for _ in range(19)] + [last]

    def test_long_requires_trend_momentum_and_volume_categories(self):
        strategy = AdvancedStrategy()
        missing_volume = strategy.evaluate(
            candles=self.candles(),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=None, atr=2.0,
            ema_trend_slope=0.001,
        )
        self.assertEqual(missing_volume["signal"], "NEUTRAL")
        self.assertTrue(missing_volume["category_confirmations"]["long"]["trend"])
        self.assertTrue(missing_volume["category_confirmations"]["long"]["momentum"])
        self.assertFalse(missing_volume["category_confirmations"]["long"]["volume"])

        confirmed = strategy.evaluate(
            candles=self.candles(),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=2.0,
            ema_trend_slope=0.001,
        )
        self.assertEqual(confirmed["signal"], "LONG")
        self.assertEqual(confirmed["category_scores"]["trend"]["long"], 40)
        self.assertEqual(confirmed["category_scores"]["momentum"]["long"], 30)
        self.assertEqual(confirmed["category_scores"]["volume"]["long"], 15)

    def test_momentum_and_volume_cannot_replace_trend_confirmation(self):
        result = AdvancedStrategy().evaluate(
            candles=self.candles(),
            ema_fast=100.0, ema_slow=100.0, ema_trend=101.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=2.0,
            ema_trend_slope=0.001,
        )
        self.assertEqual(result["signal"], "NEUTRAL")
        self.assertFalse(result["category_confirmations"]["long"]["trend"])
        self.assertTrue(result["category_confirmations"]["long"]["momentum"])
        self.assertTrue(result["category_confirmations"]["long"]["volume"])


class AdvancedStrategyInvalidationTests(unittest.TestCase):
    @staticmethod
    def candles(direction):
        if direction == "LONG":
            prior = {"high": 100.0, "low": 98.0, "close": 99.0, "volume": 10.0}
            last = {"high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0}
        else:
            prior = {"high": 102.0, "low": 100.0, "close": 101.0, "volume": 10.0}
            last = {"high": 101.0, "low": 99.0, "close": 99.5, "volume": 10.0}
        return [dict(prior) for _ in range(19)] + [last]

    def test_long_plan_declares_at_or_below_atr_invalidation(self):
        result = AdvancedStrategy().evaluate(
            candles=self.candles("LONG"),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=2.0,
            ema_trend_slope=0.001,
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
            ema_trend_slope=-0.001,
        )
        self.assertEqual(result["signal"], "SHORT")
        self.assertEqual(result["invalidation"], {
            "price": result["stop_loss"],
            "trigger": "at_or_above",
            "basis": "atr_stop",
        })

    def test_atr_percent_outside_configured_band_blocks_signal(self):
        strategy = AdvancedStrategy()
        low_atr = strategy.evaluate(
            candles=AdvancedStrategyCategoryConfirmationTests.candles(),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=0.01,
            ema_trend_slope=0.001,
        )
        high_atr = strategy.evaluate(
            candles=AdvancedStrategyCategoryConfirmationTests.candles(),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=6.0,
            ema_trend_slope=0.001,
        )
        self.assertEqual(low_atr["signal"], "NEUTRAL")
        self.assertFalse(low_atr["regime_filters"]["atr_ok"])
        self.assertEqual(high_atr["signal"], "NEUTRAL")
        self.assertFalse(high_atr["regime_filters"]["atr_ok"])

    def test_relative_volume_below_twenty_bar_mean_blocks_signal(self):
        candles = AdvancedStrategyCategoryConfirmationTests.candles()
        candles[-1]["volume"] = 0.1
        result = AdvancedStrategy().evaluate(
            candles=candles,
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=2.0,
            ema_trend_slope=0.001,
        )
        self.assertEqual(result["signal"], "NEUTRAL")
        self.assertFalse(result["regime_filters"]["volume_ok"])
        self.assertLess(result["regime_filters"]["volume_ratio"], 1.0)

    def test_ema_slope_must_agree_with_trade_direction(self):
        result = AdvancedStrategy().evaluate(
            candles=AdvancedStrategyCategoryConfirmationTests.candles(),
            ema_fast=101.0, ema_slow=100.0, ema_trend=100.0,
            rsi=60.0, macd={"histogram": 1.0}, vwap=100.0, atr=2.0,
            ema_trend_slope=-0.001,
        )
        self.assertEqual(result["signal"], "NEUTRAL")
        self.assertFalse(result["regime_filters"]["long_ema_slope_ok"])
        self.assertTrue(result["regime_filters"]["short_ema_slope_ok"])

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
