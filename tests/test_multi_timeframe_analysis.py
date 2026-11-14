import unittest

from backend.services.multi_timeframe_analysis import MultiTimeframeAnalysisService


class FakeMarketService:
    def __init__(self, closes=None, short_history=None):
        self.closes = closes or {"1h": 100.0, "4h": 100.0}
        self.short_history = set(short_history or ())
        self.calls = []

    def get_candles(self, *, interval, limit, closed_only):
        self.calls.append((interval, limit, closed_only))
        count = 51 if interval in self.short_history else 60
        close = self.closes[interval]
        base_time_ms = 1767312000000
        interval_ms = {"1h": 3_600_000, "4h": 14_400_000}[interval]
        rows = []
        for index in range(count):
            price = close + index * 0.001
            rows.append([
                base_time_ms + index * interval_ms,
                price - 0.05,
                price + 0.2,
                price - 0.2,
                price,
                10.0,
            ])
        return rows


class PriceDirectionStrategy:
    def evaluate(self, *, candles, **kwargs):
        price = candles[-1]["close"]
        signal = "LONG" if price >= 95 else "SHORT"
        return {
            "signal": signal,
            "score": 80,
            "long_score": 80 if signal == "LONG" else 0,
            "short_score": 80 if signal == "SHORT" else 0,
            "category_scores": {},
            "category_confirmations": {},
            "regime_filters": {},
            "entry": price,
            "stop_loss": price - 1 if signal == "LONG" else price + 1,
            "take_profit_1": price + 1 if signal == "LONG" else price - 1,
            "take_profit_2": price + 2 if signal == "LONG" else price - 2,
            "invalidation": None,
            "reasons": ["fixture"],
        }


class MultiTimeframeAnalysisTests(unittest.TestCase):
    def service(self, market):
        return MultiTimeframeAnalysisService(
            market, strategy_factory=PriceDirectionStrategy, limit=60,
        )

    def test_all_closed_timeframes_must_agree_for_long_consensus(self):
        market = FakeMarketService()
        result = self.service(market).run()
        self.assertEqual(result["consensus"], "LONG")
        self.assertEqual(set(result["timeframes"]), {"1h", "4h"})
        for interval, analysis in result["timeframes"].items():
            self.assertTrue(analysis["available"])
            self.assertEqual(analysis["signal"], "LONG")
            self.assertIn("ema_50", analysis["indicators"])
            self.assertIn("vwap_utc_day", analysis["indicators"])
        self.assertTrue(all(call[2] is True for call in market.calls))
        self.assertFalse(result["live_trading_authorized"])

    def test_mixed_timeframe_directions_return_neutral_consensus(self):
        market = FakeMarketService(closes={"1h": 100.0, "4h": 90.0})
        result = self.service(market).run()
        self.assertEqual(result["timeframes"]["4h"]["signal"], "SHORT")
        self.assertEqual(result["consensus"], "NEUTRAL")
        self.assertIn("no confirman", result["reason"])

    def test_insufficient_history_fails_closed_for_whole_consensus(self):
        market = FakeMarketService(short_history={"1h"})
        result = self.service(market).run()
        self.assertEqual(result["timeframes"]["1h"]["reason"], "insufficient_closed_history")
        self.assertEqual(result["consensus"], "NEUTRAL")

    def test_at_least_two_distinct_timeframes_are_required(self):
        with self.assertRaisesRegex(ValueError, "al menos dos"):
            self.service(FakeMarketService()).run(intervals=["1h"])


if __name__ == "__main__":
    unittest.main()
