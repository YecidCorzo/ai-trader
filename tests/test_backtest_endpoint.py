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


    def test_walk_forward_endpoint_returns_paper_research_result(self):
        candles = [[i, "100", "101", "99", "100", "10"] for i in range(40)]
        research = {
            "framework": "fixed_parameter_chronological_walk_forward",
            "mode": "paper",
            "fold_count": 2,
            "total_trades": 10,
        }
        with patch.object(main.market_service, "get_candles", return_value=candles) as get_candles, \
             patch.object(main, "run_walk_forward_backtests", return_value=research) as run_research:
            result = main.run_walk_forward(
                limit=40,
                interval="1d",
                train_size=20,
                validation_size=10,
                test_size=5,
                step_size=5,
            )

        get_candles.assert_called_once_with(
            interval="1d", limit=40, closed_only=True
        )
        run_research.assert_called_once()
        self.assertEqual(result["fold_count"], 2)
        self.assertEqual(result["mode"], "paper")
        self.assertEqual(result["symbol"], "SOL/USDT")

    def test_walk_forward_endpoint_rejects_overlapping_test_windows(self):
        with self.assertRaises(HTTPException) as context:
            main.run_walk_forward(
                limit=100,
                interval="1d",
                train_size=50,
                validation_size=20,
                test_size=10,
                step_size=5,
            )
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("solapadas", context.exception.detail)

    def test_walk_forward_endpoint_rejects_insufficient_requested_history(self):
        with self.assertRaises(HTTPException) as context:
            main.run_walk_forward(
                limit=100,
                interval="1d",
                train_size=80,
                validation_size=15,
                test_size=10,
                step_size=5,
            )
        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
