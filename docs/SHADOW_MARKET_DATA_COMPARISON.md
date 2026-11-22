# Shadow market-data provider comparison

The `MarketDataProvider` protocol is read-only. It contains no authentication, balances, positions, leverage, or order methods.

`GET /api/market-data/shadow-comparison` compares Binance Spot with Bitunix USDT-M Futures `LAST_PRICE` for SOL/USDT. It records a separate local UTC retrieval timestamp for each provider. Bitunix's timestamp is adjusted for the age of its local ticker cache; Binance's timestamp is recorded after its public ticker response is received. Neither timestamp is an exchange event timestamp.

The comparison is `unavailable` and does not calculate a basis if either provider fails, returns an invalid value, or the retrieval timestamps differ by more than **2 seconds**. The response includes both timestamps and `price_skew_seconds` so the timing quality is visible. A synchronized sample uses:

```text
(Bitunix Futures LAST_PRICE - Binance Spot price) / Binance Spot price * 10,000
```

The default alert threshold is an absolute basis greater than 50 basis points. A positive value means Futures trades at a premium; a negative value means a discount. The endpoint caches for five seconds; the periodic sampler below uses a six-second default interval to avoid repeatedly writing the same cached observation.

## Periodic append-only sampling

For an initial one-hour observation, run:

```sh
python scripts/sample_shadow_market_basis.py --duration-seconds 3600 --interval-seconds 6 --output data/shadow_market_basis.csv
```

The sampler appends one CSV row per observation and never rewrites prior rows. Keep the CSV as research evidence; calculate distributions (median, p90/p95, tails, unavailable rate and sample count) before proposing any threshold or strategy decision. The sampler is observational only and does not send alerts or orders.

## Candle data contract

The provider protocol requires callers to pass `closed_only` explicitly; analysis consumers must use `closed_only=True`. When requested, providers must return completed candles in ascending order, contiguous at the requested interval, and fresh. A forming candle, gap, malformed candle or stale series must fail closed rather than be filled or silently treated as current. No candle series is currently used as an input to the shadow price comparison.

## Safety boundary

- Binance remains the existing strategy data source.
- Bitunix is not selected by the dashboard's strategy, signal, backtest, position sizing, stops, or risk calculations.
- The Bitunix price used is LAST_PRICE, not MARK_PRICE.
- Provider disagreement does not change signals or create orders.
- No exchange credentials, DEMO/TESTNET, LIVE endpoints, orders, or real funds are used.
- This is a cross-market observation, not a like-for-like instrument comparison, arbitrage signal, or profitability estimate.
