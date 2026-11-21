# Bitunix USDT-M Futures — public market data

The adapter in `backend/services/bitunix_market_service.py` uses only the
public Futures REST API at `https://fapi.bitunix.com/api/v1/futures/market`.
It is a read-only market-data source and is not selected by the strategy or
PAPER execution engine.

## Endpoints

- `GET /tickers?symbols=SOLUSDT`: exposes `lastPrice` as the last traded
  price and `markPrice` separately when available.
- `GET /kline?symbol=SOLUSDT&interval=5m&limit=...`: LAST_PRICE candles.

**Important:** `lastPrice` is the last traded price, not the mark price.
Neither value is currently wired into stops, position sizing, or risk checks.
Bitunix must not be used for PAPER risk calculations until mark-price behavior
is independently verified and explicitly integrated.

## Candle quality and completeness

- Closed-candle filtering is performed locally using
  `open_time_ms + interval_duration_ms <= current_utc_ms`.
- Monthly `1M` candles are excluded because their duration is calendar-based.
- The adapter rejects non-finite values, invalid OHLC bounds, non-positive
  prices/timestamps, negative volume, duplicate timestamps, gaps, and a
  response whose actual spacing does not match the requested interval.
- The API reports `complete`, `candles_requested`, `candles_returned`,
  and `history_exhausted`. A short provider page is explicitly marked
  incomplete; callers must not treat it as a full requested history.
- The maximum request is 1,000 candles, fetched in pages of at most 200.

## Cost and rate protection

- Public responses are cached for 5 seconds by endpoint and query.
- Requests are serialized with a minimum 150 ms spacing.
- HTTP 418 and 429 are logged and retried with bounded exponential/Retry-After
  backoff. Exhausted retries map to HTTP 503 so callers can retry later.
- Provider errors do not trigger order execution or fallback to a different
  contract type.

## Safety boundaries

- Public endpoints only; no API key, secret, signature, account, balance,
  position, order, leverage, TESTNET/DEMO, or LIVE execution endpoint exists.
- Bitunix USDT-M Futures is not interchangeable with Binance Spot.
- This adapter remains in shadow/read-only mode. A future provider interface
  and Bitunix-vs-Binance basis monitor must be reviewed separately before
  changing any strategy data source.
