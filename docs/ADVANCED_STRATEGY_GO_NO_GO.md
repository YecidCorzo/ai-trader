# AdvancedStrategy pre-registered GO / NO-GO gates

These thresholds are fixed before running the acceptance sample. Do not tune
them after inspecting the same out-of-sample results and then present those
results as independent confirmation.

Endpoint: `GET /api/backtest/advanced/acceptance` runs one immutable sample. It has no
query overrides: symbol, interval and window sizes are part of the config ID
returned in every report. It uses the same fee/slippage, risk sizing, 1R
partial TP1, 1.5R cost-aware stop activation and TP2 logic as the AdvancedStrategy
backtest. The evaluator fails closed when required metrics are missing.

## Frozen acceptance sample

| Setting | Pre-registered value |
|---|---:|
| Config ID | `SOLUSDT-1H-10000-5000-1000-1000-1000-v1` |
| Symbol | `SOL/USDT` (`SOLUSDT`) |
| Interval | `1h` |
| Requested closed candles | 10,000 |
| Training window | 5,000 candles |
| Validation window | 1,000 candles |
| OOS test window | 1,000 candles |
| Step between OOS folds | 1,000 candles |
| Minimum history to execute one fold | 7,000 candles |
| Expected folds with full history | 4 |

The full 10,000-candle sample yields four chronological, non-overlapping
1,000-candle OOS folds. If fewer than 10,000 candles are returned, the report
records the actual history and the fold-count/sample gates can only produce
NO_GO. If fewer than 7,000 closed candles are available, no OOS fold is run and
the endpoint returns a fail-closed NO_GO report rather than pretending the
sample was completed. A future symbol, interval or window change requires a
new config ID and a new untouched acceptance sample.

## Required aggregate out-of-sample gates

| Metric | GO threshold |
|---|---:|
| Total OOS trades | At least 100 |
| Expectancy per trade | Strictly greater than 0 after costs |
| Profit factor | At least 1.20 |
| Maximum drawdown across folds | At most 15% |

## Walk-forward stability gates

- At least 4 chronological, non-overlapping test folds.
- Every fold must contain at least 25 closed trades.
- At least 75% of folds must each show positive net expectancy and profit
  factor greater than 1.0.
- The aggregate OOS sample must still meet the 100-trade, expectancy and
  profit-factor gates above.

A missing metric, insufficient fold sample, or failed criterion returns
`NO_GO`. There is no discretionary override in the evaluator.

## Interpretation

`GO` means only that this historical sample passed these pre-registered
filters. It does not prove future profitability, establish statistical
significance, validate an exchange adapter, or authorize LIVE trading. Any
subsequent strategy change, cost assumption change, or parameter tuning
requires a new untouched out-of-sample evaluation. Paper observation is still
required before any separate future release can be considered.
