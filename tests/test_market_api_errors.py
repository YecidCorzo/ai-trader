import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from services.market_services import MarketDataError


class BinanceApiErrorMappingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("backend.main.market_service.get_price", side_effect=MarketDataError("timeout", status_code=503))
    def test_price_timeout_returns_503_not_500(self, _get_price):
        response = self.client.get("/api/price")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Proveedor de datos de mercado no disponible")

    @patch("backend.main.market_service.get_candles", side_effect=MarketDataError("upstream bad response", status_code=502))
    def test_candles_upstream_failure_returns_502_not_500(self, _get_candles):
        response = self.client.get("/api/candles")
        self.assertEqual(response.status_code, 502)

    @patch("backend.main.market_service.get_candles", side_effect=MarketDataError("unavailable", status_code=503))
    def test_advanced_signal_maps_binance_failure_to_503(self, _get_candles):
        response = self.client.get("/api/signal/v2")
        self.assertEqual(response.status_code, 503)

    @patch("backend.main.market_service.get_candles", side_effect=MarketDataError("gateway failure", status_code=502))
    def test_advanced_backtest_maps_binance_failure_to_502(self, _get_candles):
        response = self.client.get("/api/backtest/advanced")
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
