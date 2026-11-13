# Crypto signal plan contract

The advanced PAPER analysis response uses reference levels, not order instructions or
guaranteed execution prices.

For an actionable signal:

- `signal` is `LONG` or `SHORT`.
- `entry`, `stop_loss`, `take_profit_1` and `take_profit_2` are calculated
  reference prices from the latest completed candle and the supplied indicators.
- `invalidation` explicitly describes the ATR stop boundary:
  - LONG: `trigger = at_or_below`; the thesis is invalidated when the observed
    market price is at or below `invalidation.price`.
  - SHORT: `trigger = at_or_above`; the thesis is invalidated when the observed
    market price is at or above `invalidation.price`.
  - `invalidation.price` equals `stop_loss`; it is not a second, independent
    stop or a guarantee that a simulated exit can fill at that price.
  - `basis = atr_stop` identifies the calculation used.
- `score` is a rule score, not a calibrated probability of profit.
- `reasons` records the technical rules contributing to the selected result.

For `NEUTRAL` signals or invalid ATR, `invalidation` and actionable stop/target
levels are `null`. Consumers must not invent fallback prices.

All levels are analytical references in PAPER mode. Actual paper fills, where
implemented, must use their own documented execution and market-data assumptions.
No live order path is part of this contract.
