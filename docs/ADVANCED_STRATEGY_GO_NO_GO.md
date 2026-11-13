# AdvancedStrategy pre-registered GO / NO-GO gates

These thresholds are fixed before running the acceptance sample. Do not tune
them after inspecting the same out-of-sample results and then present those
results as independent confirmation.

Endpoint: `GET /api/backtest/advanced/acceptance`. It runs chronological
AdvancedStrategy walk-forward folds with the same fee/slippage, risk sizing,
1R partial TP1, break-even stop and TP2 logic as the AdvancedStrategy
backtest. The evaluator fails closed when required metrics are missing.

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
