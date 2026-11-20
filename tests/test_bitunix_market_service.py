import unittest
from unittest.mock import Mock, patch
import requests

from services.bitunix_market_service import (
    BitunixMarketDataError, BitunixMarketService,
)


class BitunixMarketServiceTests(unittest.TestCase):
    @patch("services.bitunix_market_service.requests.get")
    def test_get_price_uses_last_price_from_public_ticker(self, get):
        response = Mock()
        response.json.return_value = {
            "code": 0,
            "data": [{"symbol": "SOLUSDT", "lastPrice": "150.25", "markPrice": "150.10"}],
        }
        get.return_value = response
        self.assertEqual(BitunixMarketService("SOLUSDT").get_price(), 150.25)
        self.assertEqual(get.call_args.kwargs["timeout"], 10)

    @patch("services.bitunix_market_service.requests.get")
    def test_get_candles_normalizes_to_binance_compatible_rows(self, get):
        response = Mock()
        response.json.return_value = {
            "code": 0,
            "data": [{
                "time": 1700000000000, "open": "10", "high": "12",
                "low": "9", "close": "11", "baseVol": "123",
            }],
        }
        get.return_value = response
        candles = BitunixMarketService().get_candles("5m", 1)
        self.assertEqual(candles, [[1700000000000, 10.0, 12.0, 9.0, 11.0, 123.0]])
        self.assertEqual(get.call_args.kwargs["params"]["type"], "LAST_PRICE")

    @patch("services.bitunix_market_service.requests.get")
    def test_nonzero_api_code_is_error(self, get):
        response = Mock()
        response.json.return_value = {"code": 10001, "data": None}
        get.return_value = response
        with self.assertRaises(BitunixMarketDataError):
            BitunixMarketService().get_price()

    @patch("services.bitunix_market_service.requests.get")
    def test_timeout_is_provider_unavailable(self, get):
        get.side_effect = requests.Timeout()
        with self.assertRaises(BitunixMarketDataError) as caught:
            BitunixMarketService().get_price()
        self.assertEqual(caught.exception.status_code, 503)

    def test_invalid_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            BitunixMarketService().get_candles("7m", 10)

    def test_zero_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            BitunixMarketService().get_candles("5m", 0)


if __name__ == "__main__":
    unittest.main()
