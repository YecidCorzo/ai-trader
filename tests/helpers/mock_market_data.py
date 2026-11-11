"""Deterministic OHLCV fixtures for AI Trader tests.

These fixtures are synthetic and must never be treated as live market data.
"""
import random


SCENARIOS = ("uptrend", "downtrend", "sideways", "volatile", "gap", "zero_volume")


def generate_ohlcv(
    count=160,
    scenario="sideways",
    seed=7,
    start_price=100.0,
    start_timestamp=1_700_000_000_000,
    interval_ms=300_000,
):
    """Generate deterministic Binance-shaped OHLCV rows.

    Each row follows [timestamp, open, high, low, close, volume].
    """
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("count debe ser un entero positivo")
    if scenario not in SCENARIOS:
        raise ValueError(f"Escenario no soportado: {scenario}")
    if start_price <= 0 or interval_ms <= 0:
        raise ValueError("start_price e interval_ms deben ser positivos")

    rng = random.Random(seed)
    price = float(start_price)
    rows = []

    for index in range(count):
        if scenario == "uptrend":
            drift, noise = 0.0018, 0.0015
        elif scenario == "downtrend":
            drift, noise = -0.0018, 0.0015
        elif scenario == "volatile":
            drift, noise = 0.0, 0.025
        elif scenario == "sideways":
            # Mean reversion keeps the path in a range instead of a random walk.
            drift = max(-0.002, min(0.002, (start_price - price) / start_price * 0.12))
            noise = 0.0015
        else:
            drift, noise = 0.0, 0.0015

        gap_multiplier = 1.0
        if scenario == "gap" and index == count // 2:
            gap_multiplier = 1.08

        open_price = price * gap_multiplier
        change = drift + rng.uniform(-noise, noise)
        close = max(0.000001, open_price * (1 + change))
        wick = abs(rng.uniform(0.0002, noise * 1.5 + 0.0002))
        high = max(open_price, close) * (1 + wick)
        low = min(open_price, close) * (1 - wick)
        volume = 0.0 if scenario == "zero_volume" else round(
            rng.uniform(10.0, 1000.0), 6
        )

        rows.append([
            start_timestamp + index * interval_ms,
            round(open_price, 8),
            round(high, 8),
            round(low, 8),
            round(close, 8),
            volume,
        ])
        price = close

    return rows


def make_invalid_ohlcv(kind="negative_volume"):
    """Return one intentionally invalid candle for negative-path tests."""
    candle = [1_700_000_000_000, 100.0, 102.0, 99.0, 101.0, 10.0]
    if kind == "negative_volume":
        candle[5] = -1.0
    elif kind == "inconsistent_ohlc":
        candle[2] = 98.0
    elif kind == "non_finite_close":
        candle[4] = float("nan")
    else:
        raise ValueError(f"Tipo inválido no soportado: {kind}")
    return candle
