import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from services.market_price_comparison import MarketPriceComparisonService


class MarketPriceComparisonTests(unittest.TestCase):
    BASE_TIME = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

    def service(self, spot=100.0, futures=100.0, threshold=50.0, monotonic=None,
                spot_time=None, futures_time=None, max_skew=2.0):
        binance = Mock()
        bitunix = Mock()
        binance.get_price_snapshot.return_value = {
            "price": spot,
            "retrieved_at": spot_time or self.BASE_TIME,
        }
        bitunix.get_price_snapshot.return_value = {
            "price": futures,
            "retrieved_at": futures_time or self.BASE_TIME,
        }
        return MarketPriceComparisonService(
            binance,
            bitunix,
            max_abs_basis_bps=threshold,
            max_price_skew_seconds=max_skew,
            monotonic=monotonic or (lambda: 10.0),
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
        self.assertEqual(result["price_skew_seconds"], 0)

    def test_exact_threshold_does_not_trigger_alert(self):
        service, _, _ = self.service(spot=100, futures=100.5, threshold=50)
        result = service.compare()
        self.assertAlmostEqual(result["basis_bps"], 50.0)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["alert"])

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
        binance.get_price_snapshot.side_effect = RuntimeError("offline")
        result = service.compare()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["basis_bps"])
        self.assertFalse(result["alert"])

    def test_non_finite_prices_are_unavailable(self):
        service, _, bitunix = self.service()
        bitunix.get_price_snapshot.return_value = {
            "price": float("nan"),
            "retrieved_at": self.BASE_TIME,
        }
        result = service.compare()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["bitunix_futures_last_price"])

    def test_price_skew_above_two_seconds_is_unavailable(self):
        service, _, _ = self.service(
            spot_time=self.BASE_TIME,
            futures_time=self.BASE_TIME + timedelta(seconds=2.001),
        )
        result = service.compare()
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["available"])
        self.assertIsNone(result["basis_bps"])
        self.assertGreater(result["price_skew_seconds"], 2.0)

    def test_price_skew_at_two_seconds_is_allowed(self):
        service, _, _ = self.service(
            spot_time=self.BASE_TIME,
            futures_time=self.BASE_TIME + timedelta(seconds=2),
        )
        result = service.compare()
        self.assertTrue(result["available"])
        self.assertEqual(result["price_skew_seconds"], 2.0)

    def test_naive_provider_timestamp_fails_closed(self):
        service, binance, _ = self.service()
        binance.get_price_snapshot.return_value = {
            "price": 100,
            "retrieved_at": datetime(2026, 11, 22, 12, 0),
        }
        result = service.compare()
        self.assertEqual(result["status"], "unavailable")

    def test_short_cache_prevents_repeated_provider_calls(self):
        service, binance, bitunix = self.service(spot=100, futures=100.1)
        service.compare()
        service.compare()
        binance.get_price_snapshot.assert_called_once()
        bitunix.get_price_snapshot.assert_called_once()

    def test_cache_expires_at_five_second_boundary(self):
        clock = [10.0]
        service, binance, bitunix = self.service(
            spot=100, futures=100.1, monotonic=lambda: clock[0]
        )
        service.compare()
        clock[0] = 14.999
        service.compare()
        binance.get_price_snapshot.assert_called_once()
        bitunix.get_price_snapshot.assert_called_once()

        clock[0] = 15.0
        service.compare()
        self.assertEqual(binance.get_price_snapshot.call_count, 2)
        self.assertEqual(bitunix.get_price_snapshot.call_count, 2)

    def test_threshold_and_skew_must_be_positive_and_finite(self):
        binance, bitunix = Mock(), Mock()
        for threshold in (0, -1, float("inf"), float("nan")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    MarketPriceComparisonService(binance, bitunix, max_abs_basis_bps=threshold)
        for skew in (0, -1, float("inf"), float("nan")):
            with self.subTest(skew=skew):
                with self.assertRaises(ValueError):
                    MarketPriceComparisonService(binance, bitunix, max_price_skew_seconds=skew)


if __name__ == "__main__":
    unittest.main()
