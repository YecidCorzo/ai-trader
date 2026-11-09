import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class BacktestEndpointTests(unittest.TestCase):
    def test_backtest_accepts_requested_history_and_returns_audit_metadata(self):
        candles = [
            [1000, "100", "102", "99", "101", "10"],
            [2000, "101", "103", "100", "102", "12"],
        ]

        class FakeBacktester:
            def __init__(self, **kwargs):
                self.settings = kwargs

            def run(self, received):
                self.received = received
                return {"mode": "paper", "final_balance": 10000.0}

        with patch.object(main.market_service, "get_candles", return_value=candles) as get_candles, \
             patch.object(main, "BacktestService", FakeBacktester), \
             patch.object(main, "review_backtest", return_value={"status": "reviewed"}):
            result = main.run_backtest(limit=20000, interval="5m")

        get_candles.assert_called_once_with(
            interval="5m", limit=20000, closed_only=True
        )
        self.assertEqual(result["candles_requested"], 20000)
        self.assertEqual(result["candles_received"], 2)
        self.assertEqual(result["history_start"], 1000)
        self.assertEqual(result["history_end"], 2000)
        self.assertEqual(result["interval"], "5m")
        self.assertEqual(result["mode"], "paper")

    def test_backtest_rejects_unsupported_interval(self):
        with self.assertRaises(HTTPException) as context:
            main.run_backtest(limit=5000, interval="7m")

        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
