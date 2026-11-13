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
- The initial implementation exits the full position at TP2. TP1 is reported
  but partial TP1 execution and break-even stop movement are deliberately
  deferred to their own strategy PR.
- The report includes trade count, net P&L, expectancy, win rate, profit
  factor, maximum drawdown, fees, reasons and timestamps.

## Limitations

This is a historical simulation, not a prediction or profitability claim.
The model uses OHLC bars and cannot reconstruct intrabar tick ordering. The
current VWAP input is cumulative from the start of the supplied history; UTC
daily anchoring is a separate follow-up item. No live or exchange DEMO orders
are placed.
