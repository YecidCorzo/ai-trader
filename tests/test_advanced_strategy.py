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


if __name__ == "__main__":
    unittest.main()
