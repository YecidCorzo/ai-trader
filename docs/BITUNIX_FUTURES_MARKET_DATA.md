# Bitunix USDT-M Futures — public market data

The Bitunix adapter in backend/services/bitunix_market_service.py is a
read-only data client. It uses the public Futures REST API at
https://fapi.bitunix.com/api/v1/futures/market.

Implemented endpoints:
- GET /tickers?symbols=SOLUSDT — last traded price.
- GET /kline?symbol=SOLUSDT&interval=5m&limit=... — completed LAST_PRICE candles.

Candles are normalized to the existing Binance row format:
[open_time_ms, open, high, low, close, base_volume].

Safety boundaries:
- Public endpoints only; no API key, secret, signature, account, balance,
  position, order, or leverage endpoint is implemented.
- No Bitunix order execution or TESTNET/DEMO integration.
- No existing Binance behavior or strategy parameters are changed.
- Bitunix Futures market data is not interchangeable with Spot data.
- Kline pagination uses the documented exclusive endTime parameter and
  requests at most 200 candles per page.
- The REST Kline endpoint documents that only closed candles are returned.

The adapter is not yet selected by the dashboard or strategy engine. It must
pass its unit tests and be integrated behind explicit provider selection
before those components use it.
