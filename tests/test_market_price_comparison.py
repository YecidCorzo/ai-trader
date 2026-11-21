import unittest
from unittest.mock import Mock

from services.market_price_comparison import MarketPriceComparisonService


class MarketPriceComparisonTests(unittest.TestCase):
    def service(self, spot=100.0, futures=100.0, threshold=50.0):
        binance = Mock()
        bitunix = Mock()
        binance.get_price.return_value = spot
        bitunix.get_price.return_value = futures
        return MarketPriceComparisonService(
            binance, bitunix, max_abs_basis_bps=threshold, monotonic=lambda: 10.0
        ), binance, bitunix

    def test_equal_prices_have_zero_basis_and_no_alert(self):
        service, _, _ = self.service()
        result = service.compare()
        self.assertEqual(result["basis_bps"], 0)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["alert"])
        self.assertTrue(result["shadow_mode"])
        self.assertFalse(result["strategy_source_changed"])
        self.assertFalse(result["orders_enabled"])

    def test_positive_basis_above_threshold_triggers_alert(self):
        service, _, _ = self.service(spot=100, futures=100.6, threshold=50)
        result = service.compare()
        self.assertAlmostEqual(result["basis_bps"], 60.0)
        self.assertEqual(result["status"], "alert")
        self.assertTrue(result["alert"])

    def test_negative_basis_is_signed_and_threshold_uses_absolute_value(self):
        service, _, _ = self.service(spot=100, futures=99.4, threshold=50)
        result = service.compare()
        self.assertAlmostEqual(result["basis_bps"], -60.0)
        self.assertTrue(result["alert"])

    def test_provider_failure_fails_closed_without_false_basis_alert(self):
        service, binance, _ = self.service()
        binance.get_price.side_effect = RuntimeError("offline")
        result = service.compare()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["basis_bps"])
        self.assertFalse(result["alert"])

    def test_non_finite_prices_are_unavailable(self):
        service, _, bitunix = self.service()
        bitunix.get_price.return_value = float("nan")
        result = service.compare()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["bitunix_futures_last_price"])

    def test_short_cache_prevents_repeated_provider_calls(self):
        service, binance, bitunix = self.service(spot=100, futures=100.1)
        service.compare()
        service.compare()
        binance.get_price.assert_called_once()
        bitunix.get_price.assert_called_once()

    def test_threshold_must_be_positive_and_finite(self):
        binance, bitunix = Mock(), Mock()
        for threshold in (0, -1, float("inf"), float("nan")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    MarketPriceComparisonService(
                        binance, bitunix, max_abs_basis_bps=threshold
                    )


if __name__ == "__main__":
    unittest.main()
