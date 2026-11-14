# AdvancedStrategy regime filters

A LONG/SHORT signal must pass all score-category checks and all regime filters.
The current defaults are explicit simulation heuristics, not fitted or
profitability-validated parameters.

- **EMA50 slope:** percentage change from the EMA50 value five closed candles
  earlier to the current EMA50. LONG requires a slope above +0.01%; SHORT
  requires below -0.01% over that five-candle span.
- **Cost-aware ATR floor:** fee floor is 0.10% and adverse slippage is
  0.05% on both entry and exit. Round-trip cost is therefore 0.30% of nominal:
  `2 × (0.10% + 0.05%)`.
- **Cost in R:** the round-trip cost divided by the ATR stop distance must be
  no greater than 0.15R. With a 1.5×ATR stop, this derives a minimum ATR/close
  of `0.30% ÷ (0.15 × 1.5) = 1.3333…%`, corresponding to a stop distance of
  at least 2.00%. The 5.00% maximum ATR band remains unchanged. The API reports
  the cost rate, stop-distance percentage, cost in R and pass/fail state.
- **Relative volume:** current candle volume must be at least 1.0× the mean
  volume of the latest 20 closed candles. Fewer than 20 candles or a zero mean
  fails closed.

The cost model matches the PAPER engine and AdvancedStrategy backtest defaults.
Changing fee/slippage assumptions derives a new ATR floor mechanically; no
out-of-sample result is used to tune this threshold. The live AdvancedStrategy
signal now evaluates 1h candles, while strict multi-timeframe consensus uses
1h and 4h. The backtest still evaluates only completed candles and enters on
the next candle.

These defaults must be fixed before a future strategy research run; do not
change thresholds after seeing out-of-sample results and then report those
same results as independent validation.
