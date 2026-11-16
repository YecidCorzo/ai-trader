import unittest
from unittest.mock import patch

import main
from strategies.ema_rsi_strategy import EmaRsiStrategy


class LegacyEmaRsiCrossoverTests(unittest.TestCase):
    def setUp(self):
        self.strategy = EmaRsiStrategy()

    def test_long_requires_a_fresh_upward_crossover(self):
        self.assertEqual(
            self.strategy.generate_signal(
                ema9=101.0, ema21=100.0, rsi=50.0,
                prev_ema9=99.0, prev_ema21=100.0,
            ),
            "LONG",
        )

    def test_short_requires_a_fresh_downward_crossover(self):
        self.assertEqual(
            self.strategy.generate_signal(
                ema9=99.0, ema21=100.0, rsi=50.0,
                prev_ema9=101.0, prev_ema21=100.0,
            ),
            "SHORT",
        )

    def test_existing_bullish_state_does_not_repeat_long_signals(self):
        self.assertEqual(
            self.strategy.generate_signal(
                ema9=102.0, ema21=100.0, rsi=65.0,
                prev_ema9=101.0, prev_ema21=100.0,
            ),
            "NEUTRAL",
        )

    def test_existing_bearish_state_does_not_repeat_short_signals(self):
        self.assertEqual(
            self.strategy.generate_signal(
                ema9=98.0, ema21=100.0, rsi=35.0,
                prev_ema9=99.0, prev_ema21=100.0,
            ),
            "NEUTRAL",
        )

    def test_rsi_confirmation_is_inclusive_at_fifty(self):
        long_signal = self.strategy.generate_signal(
            ema9=101.0, ema21=100.0, rsi=50.0,
            prev_ema9=99.0, prev_ema21=100.0,
        )
        short_signal = self.strategy.generate_signal(
            ema9=99.0, ema21=100.0, rsi=50.0,
            prev_ema9=101.0, prev_ema21=100.0,
        )
        self.assertEqual(long_signal, "LONG")
        self.assertEqual(short_signal, "SHORT")

    def test_rsi_must_confirm_the_crossover_direction(self):
        long_without_confirmation = self.strategy.generate_signal(
            ema9=101.0, ema21=100.0, rsi=49.99,
            prev_ema9=99.0, prev_ema21=100.0,
        )
        short_without_confirmation = self.strategy.generate_signal(
            ema9=99.0, ema21=100.0, rsi=50.01,
            prev_ema9=101.0, prev_ema21=100.0,
        )
        self.assertEqual(long_without_confirmation, "NEUTRAL")
        self.assertEqual(short_without_confirmation, "NEUTRAL")

    def test_equal_or_non_crossing_ema_values_are_neutral(self):
        equal_now = self.strategy.generate_signal(
            ema9=100.0, ema21=100.0, rsi=60.0,
            prev_ema9=99.0, prev_ema21=100.0,
        )
        equal_previous = self.strategy.generate_signal(
            ema9=101.0, ema21=100.0, rsi=60.0,
            prev_ema9=100.0, prev_ema21=100.0,
        )
        self.assertEqual(equal_now, "NEUTRAL")
        self.assertEqual(equal_previous, "LONG")

    def test_signal_endpoint_passes_current_and_previous_closed_candle_emas(self):
        candles = [
            [index * 300000, "100", "101", "99", str(100 + index), "10"]
            for index in range(20)
        ]
        fast = [100.0] * 18 + [99.0, 101.0]
        slow = [100.0] * 20

        with patch.object(
            main.market_service, "get_candles", return_value=candles
        ) as get_candles, patch.object(
            main, "calculate_ema_series",
            side_effect=lambda closes, period: fast if period == 9 else slow,
        ), patch.object(
            main, "calculate_rsi", return_value=55.0
        ), patch.object(
            main.strategy, "generate_signal", return_value="LONG"
        ) as generate_signal:
            result = main.get_signal()

        get_candles.assert_called_once_with(
            interval="5m", limit=5000, closed_only=True
        )
        generate_signal.assert_called_once_with(
            ema9=101.0,
            ema21=100.0,
            rsi=55.0,
            prev_ema9=99.0,
            prev_ema21=100.0,
        )
        self.assertEqual(result["signal"], "LONG")
        self.assertEqual(result["mode"], "paper")


if __name__ == "__main__":
    unittest.main()
