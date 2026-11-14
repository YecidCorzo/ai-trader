# AdvancedStrategy backtest

The `/api/backtest/advanced` endpoint replays the same
`AdvancedStrategy.evaluate` implementation used by `/api/signal/v2`.
Signals are evaluated only on completed historical candles. A simulated
position is entered at the next candle's open with adverse slippage.

## Model

- Indicator inputs use the same EMA(9/21/50), Wilder RSI(14), MACD(12/26/9),
  UTC-day anchored VWAP and rolling ATR(14) formulas as the live signal endpoint.
- The strategy's ATR stop, TP1 and TP2 are captured at signal time.
- Risk sizing uses balance × configured risk fraction, per-unit stop loss,
  entry/estimated exit fees and adverse slippage, then caps notional by cash.
- Entry and exit fees and adverse slippage are included in simulated P&L.
- Stops and TP2 are resolved against candle OHLC. If both are touched in the
  same candle, the existing conservative resolver assumes the stop occurred
  first. Stop gaps fill at the candle open plus adverse slippage.
- The backtest closes 50% of the position at TP1 (1R), allocating entry
  and exit fees proportionally. The remaining half keeps its original stop
  until price reaches 1.5R. Only after that closed-candle threshold is observed
  does the engine activate a cost-aware break-even stop that covers entry fee,
  exit fee and adverse exit slippage. The remaining half exits at TP2 or that
  stop. The activation candle does not retroactively apply the new stop;
  intrabar ordering remains unknowable and the model avoids look-ahead.
- If the original stop and TP1 are both touched in the same OHLC candle, the
  original stop is resolved first. If the original stop is hit after TP1 but
  before 1.5R, the remaining half exits at that original stop.
- Each trade reports MFE, MAE and round-trip cost in R, plus TP1/TP2 hit flags.
  Aggregate and walk-forward reports include TP2 hit rate (all trades and
  conditional on TP1), average MFE/MAE and average cost in R.

## VWAP definition

VWAP is anchored to the UTC calendar day of the final candle supplied to the
indicator. Only candles from that same UTC day contribute; earlier days are
excluded. Each candle uses typical price `(high + low + close) / 3` weighted
by volume. Candles must carry an epoch or timezone-aware timestamp. If the
selected UTC day has no positive total volume, VWAP is unavailable and the
strategy fails closed.

## Limitations

This is a historical simulation, not a prediction or profitability claim.
The model uses OHLC bars and cannot reconstruct intrabar tick ordering. The
VWAP anchor is UTC midnight, not a user-local timezone or exchange session.
No live or exchange DEMO orders are placed.
