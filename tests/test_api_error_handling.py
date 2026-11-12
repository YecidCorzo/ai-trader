import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.main import get_signal_v2, run_backtest


class ApiErrorHandlingTests(unittest.TestCase):
    def assert_generic_internal_error(self, endpoint):
        with self.assertRaises(HTTPException) as raised:
            endpoint()

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail,
            "Error interno del servidor",
        )
        self.assertNotIn("private backend detail", raised.exception.detail)

    @patch(
        "backend.main.market_service.get_candles",
        side_effect=RuntimeError("private backend detail"),
    )
    def test_signal_v2_does_not_return_internal_exception(self, _get_candles):
        self.assert_generic_internal_error(get_signal_v2)

    @patch(
        "backend.main.market_service.get_candles",
        side_effect=RuntimeError("private backend detail"),
    )
    def test_backtest_does_not_return_internal_exception(self, _get_candles):
        self.assert_generic_internal_error(run_backtest)

    @patch(
        "backend.main.market_service.get_candles",
        side_effect=HTTPException(status_code=503, detail="Market data unavailable"),
    )
    def test_signal_v2_preserves_expected_http_errors(self, _get_candles):
        with self.assertRaises(HTTPException) as raised:
            get_signal_v2()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Market data unavailable")

    @patch(
        "backend.main.market_service.get_candles",
        side_effect=HTTPException(status_code=503, detail="Market data unavailable"),
    )
    def test_backtest_preserves_expected_http_errors(self, _get_candles):
        with self.assertRaises(HTTPException) as raised:
            run_backtest()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Market data unavailable")


if __name__ == "__main__":
    unittest.main()
