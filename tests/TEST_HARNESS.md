# AI Trader deterministic test harness

The harness creates reproducible synthetic OHLCV candles. It does not call Binance,
does not place orders, and does not change the project's PAPER mode.

## Included market scenarios

- `uptrend` and `downtrend`: directional price paths.
- `sideways`: low-volatility range.
- `volatile`: larger random candle moves.
- `gap`: one opening gap.
- `zero_volume`: valid candles with zero volume.

Invalid candles can also be generated for negative-path tests:
`negative_volume`, `inconsistent_ohlc`, and `non_finite_close`.

The generator uses a local seeded random number generator, so the same arguments
produce the same dataset. It emits Binance-shaped rows:
`[timestamp, open, high, low, close, volume]`.

## Run

From the repository root:

```bash
python -m unittest tests.test_mock_market_data -v
```

These tests validate fixture generation and that the existing backtester accepts
a synthetic dataset. They do not establish that a trading strategy is profitable.
