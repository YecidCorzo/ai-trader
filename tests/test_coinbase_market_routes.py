import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.api.coinbase_routes import coinbase_market_services
from services.coinbase_market_service import CoinbaseMarketDataError


class FakeCoinbaseMarketService:
    def __init__(self):
        self.price_snapshot = {
            "price": 123.45,
            "retrieved_at": datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc),
        }
        self.candle_result = {
            "candles": [[1_800_000_000_000, 120.0, 125.0, 119.0, 123.0, 456.0]],
            "complete": True,
            "history_exhausted": False,
            "provider_page_short": False,
            "requested": 1,
            "returned": 1,
        }
        self.price_error = None
        self.candle_error = None
        self.candle_value_error = None
        self.last_candle_call = None

    def get_price_snapshot(self):
        if self.price_error:
            raise self.price_error
        return self.price_snapshot

    def get_candles(self, interval, limit, *, closed_only, include_metadata):
        self.last_candle_call = {
            "interval": interval,
            "limit": limit,
            "closed_only": closed_only,
            "include_metadata": include_metadata,
        }
        if self.candle_value_error:
            raise self.candle_value_error
        if self.candle_error:
            raise self.candle_error
        return self.candle_result


class CoinbaseMarketRoutesTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCoinbaseMarketService()
        self.service_patch = patch.dict(
            coinbase_market_services,
            {"SOL-EUR": self.fake, "SOL-USDC": self.fake},
            clear=True,
        )
        self.service_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.service_patch.stop()

    def test_price_endpoint_returns_timestamped_public_snapshot(self):
        response = self.client.get("/api/coinbase/price")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["symbol"], "SOL/EUR")
        self.assertEqual(payload["product_id"], "SOL-EUR")
        self.assertEqual(payload["price"], 123.45)
        self.assertEqual(payload["source"], "Coinbase Exchange")
        self.assertEqual(payload["price_type"], "last_traded_price")
        self.assertEqual(payload["mode"], "paper")
        self.assertEqual(payload["retrieved_at"], "2026-11-23T05:00:00+00:00")

    def test_price_endpoint_supports_the_second_allowlisted_product(self):
        response = self.client.get("/api/coinbase/price?product_id=SOL-USDC")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["symbol"], "SOL/USDC")

    def test_unsupported_product_is_rejected_by_request_validation(self):
        response = self.client.get("/api/coinbase/price?product_id=SOL-USDT")
        self.assertEqual(response.status_code, 422)

    def test_price_upstream_error_is_mapped_without_leaking_details(self):
        self.fake.price_error = CoinbaseMarketDataError(
            "sensitive upstream detail", status_code=503
        )
        response = self.client.get("/api/coinbase/price")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Proveedor Coinbase de datos de mercado no disponible",
        )
        self.assertNotIn("sensitive", response.text)

    def test_candles_endpoint_returns_normalized_ohlcv_and_metadata(self):
        response = self.client.get("/api/coinbase/candles?interval=1h&limit=1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["symbol"], "SOL/EUR")
        self.assertEqual(payload["source"], "Coinbase Exchange")
        self.assertEqual(payload["candles"], [{
            "time": 1_800_000_000,
            "open": 120.0,
            "high": 125.0,
            "low": 119.0,
            "close": 123.0,
            "volume": 456.0,
        }])
        self.assertEqual(payload["candles_requested"], 1)
        self.assertEqual(payload["candles_returned"], 1)
        self.assertTrue(payload["complete"])
        self.assertIsNone(payload["warning"])
        self.assertEqual(payload["mode"], "paper")
        self.assertEqual(self.fake.last_candle_call, {
            "interval": "1h",
            "limit": 1,
            "closed_only": True,
            "include_metadata": True,
        })

    def test_incomplete_history_is_explicit_and_not_silently_marked_complete(self):
        self.fake.candle_result.update({
            "candles": [],
            "complete": False,
            "history_exhausted": True,
            "provider_page_short": True,
            "requested": 100,
            "returned": 0,
        })
        response = self.client.get("/api/coinbase/candles?limit=100")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candles"], [])
        self.assertFalse(payload["complete"])
        self.assertTrue(payload["history_exhausted"])
        self.assertTrue(payload["provider_page_short"])
        self.assertIn("Histórico incompleto", payload["warning"])

    def test_invalid_interval_from_service_returns_400(self):
        self.fake.candle_value_error = ValueError("Unsupported Coinbase candle interval")
        response = self.client.get("/api/coinbase/candles?interval=7m")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Unsupported Coinbase candle interval",
        )

    def test_invalid_limit_is_rejected_before_provider_call(self):
        response = self.client.get("/api/coinbase/candles?limit=1001")
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.fake.last_candle_call)

    def test_candle_upstream_error_is_mapped_without_leaking_details(self):
        self.fake.candle_error = CoinbaseMarketDataError(
            "internal upstream response", status_code=502
        )
        response = self.client.get("/api/coinbase/candles")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "Proveedor Coinbase de datos de mercado no disponible",
        )
        self.assertNotIn("upstream", response.text)


if __name__ == "__main__":
    unittest.main()
