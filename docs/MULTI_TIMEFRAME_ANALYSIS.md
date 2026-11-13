# Multi-timeframe AdvancedStrategy analysis

Endpoint: `GET /api/signal/multi-timeframe`.

The endpoint analyzes the latest 500 **closed** Binance candles independently
on 5m, 15m and 1h using the same AdvancedStrategy rules and verified indicator
inputs used by `/api/signal/v2`:

- EMA 9/21/50 and five-bar EMA50 slope
- Wilder RSI(14)
- MACD(12/26/9)
- UTC-day anchored VWAP
- ATR(14)
- score categories and regime filters

Each timeframe returns its own signal, scores, filter state, indicator values,
closed-candle timestamp, entry, stop, targets, invalidation and reasons.

## Consensus rule

A directional multi-timeframe result is emitted only when all selected
timeframes are available and all return the same LONG or SHORT direction.
Any unavailable timeframe, NEUTRAL result or disagreement returns NEUTRAL.
This is intentionally strict; it avoids treating a lower-timeframe signal as
confirmed when a higher timeframe disagrees.

The endpoint is analysis-only and PAPER-labelled. It does not create a trade,
change an account, connect to exchange credentials, or submit orders.
