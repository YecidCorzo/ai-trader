# AdvancedStrategy regime filters

A LONG/SHORT signal must pass all score-category checks and all regime filters.
The current defaults are explicit simulation heuristics, not fitted or
profitability-validated parameters.

- **EMA50 slope:** percentage change from the EMA50 value five closed candles
  earlier to the current EMA50. LONG requires a slope above +0.01%; SHORT
  requires below -0.01% over that five-candle span.
- **ATR% band:** ATR divided by close must be between 0.10% and 5.00%, inclusive.
  Below the band is treated as insufficient movement; above it is treated as
  unusually volatile for this initial configuration.
- **Relative volume:** current candle volume must be at least 1.0× the mean
  volume of the latest 20 closed candles. Fewer than 20 candles or a zero mean
  fails closed.

The API response exposes the measured ATR%, EMA50 slope, current/mean volume,
volume ratio, thresholds and each filter's pass/fail state. The live endpoint
and AdvancedStrategy backtest use the same EMA50 slope calculation and 20-bar
volume context. The backtest still only evaluates completed candles and enters
on the next candle.

These defaults must be fixed before a future strategy research run; do not
change thresholds after seeing out-of-sample results and then report those
same results as independent validation.
