import csv
import tempfile
import unittest
from pathlib import Path

from scripts.sample_shadow_market_basis import append_sample


class ShadowBasisSamplerTests(unittest.TestCase):
    def test_appends_rows_without_rewriting_existing_samples(self):
        sample = {
            "compared_at": "2026-11-22T12:00:00+00:00",
            "symbol": "SOL/USDT",
            "status": "ok",
            "binance_spot_price": 100.0,
            "binance_price_retrieved_at": "2026-11-22T12:00:00+00:00",
            "bitunix_futures_last_price": 100.1,
            "bitunix_price_retrieved_at": "2026-11-22T12:00:01+00:00",
            "price_skew_seconds": 1.0,
            "basis_bps": 10.0,
            "absolute_basis_bps": 10.0,
            "threshold_bps": 50.0,
            "alert": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "samples.csv"
            append_sample(path, sample)
            append_sample(path, {**sample, "compared_at": "2026-11-22T12:00:06+00:00"})
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["compared_at"], sample["compared_at"])
            self.assertEqual(rows[1]["compared_at"], "2026-11-22T12:00:06+00:00")


if __name__ == "__main__":
    unittest.main()
