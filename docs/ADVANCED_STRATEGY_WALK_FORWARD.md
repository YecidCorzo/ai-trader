# AdvancedStrategy chronological walk-forward

Endpoint: `GET /api/backtest/advanced/walk-forward`.

This route runs the same `AdvancedStrategyBacktestService` used by
`/api/backtest/advanced`, not the legacy EMA/RSI BacktestService.

## Window semantics

- Training, validation and test windows are chronological and non-overlapping.
- Strategy parameters remain fixed; this implementation does not optimize on
  train or validation data.
- Indicators are warmed with all candles strictly before the test window.
- The final pre-test candle may produce a signal. Its simulated entry is at
  the first test candle's open, so no test-window entry is backdated.
- Every fold starts with independent virtual capital. Aggregate P&L is the sum
  of fold P&L, not a compounded portfolio curve.
- The same fees, adverse slippage, risk cap, 1R partial TP1, break-even stop and
  TP2 logic are used in each fold.

The response includes per-fold trade count, net P&L, expectancy, profit factor,
drawdown, fees and test ranges, plus aggregate out-of-sample metrics and a
buy-and-hold comparison. It does not certify profitability or authorize live
trading.
