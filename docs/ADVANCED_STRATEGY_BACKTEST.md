# AdvancedStrategy backtest

The `/api/backtest/advanced` endpoint replays the same
`AdvancedStrategy.evaluate` implementation used by `/api/signal/v2`.
Signals are evaluated only on completed historical candles. A simulated
position is entered at the next candle's open with adverse slippage.

## Model

- Indicator inputs use the same EMA(9/21/50), Wilder RSI(14), MACD(12/26/9),
  cumulative VWAP and rolling ATR(14) formulas as the live signal endpoint.
- The strategy's ATR stop, TP1 and TP2 are captured at signal time.
- Risk sizing uses balance × configured risk fraction, per-unit stop loss,
  entry/estimated exit fees and adverse slippage, then caps notional by cash.
- Entry and exit fees and adverse slippage are included in simulated P&L.
- Stops and TP2 are resolved against candle OHLC. If both are touched in the
  same candle, the existing conservative resolver assumes the stop occurred
  first. Stop gaps fill at the candle open plus adverse slippage.
- The backtest closes 50% of the position at TP1 (1R), allocates entry/exit
  fees proportionally, and moves the remaining stop to the actual simulated
  entry fill (break-even). The remaining half exits at TP2 or the break-even
  stop. If the original stop and TP1 are both touched in the same OHLC candle,
  the original stop is resolved first. If TP1 is touched and the candle's
  adverse extreme also crosses break-even, the remaining half is conservatively
  assumed stopped at break-even because intrabar ordering is unknowable.
- The report includes trade count, net P&L, expectancy, win rate, profit
  factor, maximum drawdown, total fees, partial TP1 quantities/fees/P&L,
  break-even stop, reasons and timestamps.

## Limitations

This is a historical simulation, not a prediction or profitability claim.
The model uses OHLC bars and cannot reconstruct intrabar tick ordering. The
current VWAP input is cumulative from the start of the supplied history; UTC
daily anchoring is a separate follow-up item. No live or exchange DEMO orders
are placed.
