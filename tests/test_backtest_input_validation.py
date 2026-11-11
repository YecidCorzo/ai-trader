import unittest

from backend.services.backtest_service import BacktestService


def valid_candles(count=50):
    rows = []
    for index in range(count):
        price = 100.0 + index * 0.1
        rows.append({
            "time": index + 1,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + 0.2,
            "volume": 10,
        })
    return rows


class BacktestInputValidationTests(unittest.TestCase):
    def test_rejects_non_finite_configuration(self):
        with self.assertRaises(ValueError):
            BacktestService(fee_rate=float("nan"))

    def test_rejects_invalid_fee_and_slippage_rates(self):
        for kwargs in ({"fee_rate": -0.1}, {"slippage_rate": 1.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                BacktestService(**kwargs)

    def test_rejects_inconsistent_ohlc(self):
        candles = valid_candles()
        candles[10]["high"] = candles[10]["open"] - 1
        with self.assertRaisesRegex(ValueError, "OHLC inconsistentes"):
            BacktestService().run(candles)

    def test_rejects_non_finite_prices(self):
        candles = valid_candles()
        candles[10]["close"] = float("nan")
        with self.assertRaisesRegex(ValueError, "no finitos"):
            BacktestService().run(candles)

    def test_rejects_negative_volume(self):
        candles = valid_candles()
        candles[10]["volume"] = -1
        with self.assertRaisesRegex(ValueError, "volumen no puede ser negativo"):
            BacktestService().run(candles)

    def test_rejects_missing_timestamp(self):
        candles = valid_candles()
        candles[10]["time"] = None
        with self.assertRaisesRegex(ValueError, "timestamp"):
            BacktestService().run(candles)

    def test_rejects_inconsistent_timestamp_types(self):
        candles = valid_candles()
        candles[10]["time"] = "not-a-timestamp"
        with self.assertRaisesRegex(ValueError, "timestamps"):
            BacktestService().run(candles)

    def test_rejects_non_integer_indicator_periods(self):
        with self.assertRaises(ValueError):
            BacktestService().run(valid_candles(), fast_period=9.5)


if __name__ == "__main__":
    unittest.main()
