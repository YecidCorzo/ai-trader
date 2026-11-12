import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


class PaperApiErrorBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_signal_v2_returns_generic_500_for_unexpected_errors(self):
        with patch.object(
            main.market_service,
            "get_candles",
            side_effect=RuntimeError("private upstream diagnostic"),
        ):
            response = self.client.get("/api/signal/v2")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Error interno del servidor")
        self.assertNotIn("private upstream diagnostic", response.text)

    def test_signal_v2_preserves_explicit_upstream_http_error(self):
        with patch.object(
            main.market_service,
            "get_candles",
            side_effect=HTTPException(
                status_code=503,
                detail="Datos de mercado temporalmente no disponibles",
            ),
        ):
            response = self.client.get("/api/signal/v2")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Datos de mercado temporalmente no disponibles",
        )

    def test_backtest_returns_generic_500_for_unexpected_errors(self):
        with patch.object(
            main.market_service,
            "get_candles",
            side_effect=RuntimeError("private backtest diagnostic"),
        ):
            response = self.client.get("/api/backtest")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Error interno del servidor")
        self.assertNotIn("private backtest diagnostic", response.text)


if __name__ == "__main__":
    unittest.main()
