#!/usr/bin/env python3
"""Append-only periodic sampler for the PAPER shadow market basis."""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

from backend.services.bitunix_market_service import BitunixMarketService
from backend.services.market_price_comparison import MarketPriceComparisonService
from backend.services.market_services import MarketService


CSV_FIELDS = [
    "compared_at",
    "symbol",
    "status",
    "binance_spot_price",
    "binance_price_retrieved_at",
    "bitunix_futures_last_price",
    "bitunix_price_retrieved_at",
    "price_skew_seconds",
    "basis_bps",
    "absolute_basis_bps",
    "threshold_bps",
    "alert",
]


def append_sample(path: str | Path, sample: dict) -> None:
    """Append one observation; never truncate or rewrite existing samples."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not output.exists() or output.stat().st_size == 0
    with output.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow({field: sample.get(field) for field in CSV_FIELDS})
        handle.flush()
        os.fsync(handle.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Guarda muestras periódicas del diferencial Binance Spot / Bitunix Futures en modo shadow."
    )
    parser.add_argument("--duration-seconds", type=float, default=3600)
    parser.add_argument("--interval-seconds", type=float, default=6)
    parser.add_argument("--output", default="data/shadow_market_basis.csv")
    args = parser.parse_args(argv)

    if args.duration_seconds <= 0:
        parser.error("--duration-seconds debe ser positivo")
    if args.interval_seconds < MarketPriceComparisonService.CACHE_TTL_SECONDS:
        parser.error("--interval-seconds debe ser al menos 5 segundos para evitar muestras repetidas de caché")

    service = MarketPriceComparisonService(
        MarketService("SOLUSDT"),
        BitunixMarketService("SOLUSDT"),
    )
    deadline = time.monotonic() + args.duration_seconds
    samples = 0
    while True:
        sample = service.compare()
        append_sample(args.output, sample)
        samples += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(args.interval_seconds, remaining))

    print(f"Guardadas {samples} muestras shadow en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
