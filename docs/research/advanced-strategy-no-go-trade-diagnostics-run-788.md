# SOLUSDT 1h NO_GO — exploratory trade diagnostics

**Status: descriptive research only. This is not a new acceptance test and does not change the NO_GO decision.**

Source dataset: [pre-registered SOLUSDT 1h acceptance run #788](./advanced-strategy-acceptance-SOLUSDT-1h-run-788.md) and its complete [40-trade JSON](./advanced-strategy-acceptance-SOLUSDT-1h-run-788.json).

## Scope and guardrails

- Reused the 40 out-of-sample trades from frozen config `SOLUSDT-1H-10000-5000-1000-1000-1000-v1`.
- No strategy parameters, thresholds, filters, sizing, or acceptance gates were changed.
- No new OOS sample was selected or evaluated.
- These breakdowns are post-hoc descriptions of the failed sample. They must not be used to claim statistical significance, optimize the current strategy, or promote it beyond PAPER.
- Any follow-up strategy variant requires a new versioned, pre-registered experiment and a separate untouched holdout.

## Direction breakdown

| Direction | Trades | Net P&L | Avg P&L / trade | Winners | Win rate | Avg MFE | Avg MAE | TP1 | TP2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LONG | 17 | +385.58 USDT | +22.68 USDT | 9 | 52.9% | 1.725R | 0.818R | 11 | 7 |
| SHORT | 23 | -677.63 USDT | -29.46 USDT | 7 | 30.4% | 0.855R | 0.971R | 8 | 6 |
| **Total** | **40** | **-292.05 USDT** | **-7.30 USDT** | **16** | **40.0%** | **1.224R** | **0.906R** | **19** | **13** |

The SHORT side accounts for the negative aggregate result in this sample. This is a diagnostic observation, not evidence that SHORT should be disabled: the sample is small, and the direction split was not a separately pre-registered hypothesis.

## Exit-reason breakdown

| Exit reason | Trades | Net P&L | Average P&L / trade | Notes |
|---|---:|---:|---:|---|
| Stop loss | 20 | -1,981.91 USDT | -99.10 USDT | 5 LONG and 15 SHORT; no TP1 |
| Take profit 2 | 13 | +1,596.19 USDT | +122.78 USDT | All 13 had reached TP1 |
| Stop loss after TP1 | 3 | -31.18 USDT | -10.39 USDT | All 3 had reached TP1 |
| Cost-aware stop | 2 | +77.92 USDT | +38.96 USDT | Both profitable |
| End of data | 2 | +46.93 USDT | +23.46 USDT | One profitable, one losing |

The main loss mechanism in this sample is a group of full initial-stop exits. The 13 TP2 exits are profitable and do not offset the 20 full stop-loss exits plus the smaller remaining losses. This does not establish that the exit logic is defective; entry timing, market regime, and the small number of observations remain confounded.

### Stop-loss exits by direction

| Direction | Stop-loss exits | Average MFE | Average MAE | Net P&L |
|---|---:|---:|---:|---:|
| LONG | 5 | 0.536R | 1.149R | -497.56 USDT |
| SHORT | 15 | 0.180R | 1.273R | -1,484.35 USDT |

SHORT stop-loss exits showed particularly low favourable excursion and higher adverse excursion in this sample. Treat this as a lead for independent research, not a threshold for changing the current model.

## Score breakdown (descriptive only)

| Rule score | Trades | Net P&L | Average P&L / trade | Win rate |
|---:|---:|---:|---:|---:|
| 65 | 1 | +123.63 USDT | +123.63 USDT | 100.0% |
| 70 | 7 | -299.11 USDT | -42.73 USDT | 14.3% |
| 85 | 24 | -52.66 USDT | -2.19 USDT | 45.8% |
| 100 | 8 | -63.91 USDT | -7.99 USDT | 37.5% |

The score is a rule score, not a calibrated probability. These sparse score buckets do not justify changing the minimum score or any other gate.

## Research conclusions

1. **Keep the current release at NO_GO / PAPER only.** Aggregate OOS expectancy remains -7.30133 USDT per trade and profit factor remains 0.856718.
2. **Prioritize independent investigation of SHORT entry failures.** Inspect signal timing, trend-regime transitions, and whether the same entry rules behave differently across directional regimes. Do not use this exact holdout to select new parameters.
3. **Audit initial-stop exits on a fresh, pre-registered sample.** Preserve trade-level MFE/MAE and signal/entry/exit timestamps so entry quality can be separated from exit behaviour.
4. **Do not infer that raising the score threshold fixes the system.** The score buckets are too small and the score is not probabilistic.
5. **Do not promote the strategy or enable LIVE.** Any candidate needs a new experiment ID, fixed symbol/interval/windows, frozen thresholds, sufficient trades per fold, and a previously untouched OOS holdout.

## Safety

PAPER mode only. Public market data only. No exchange credentials, TESTNET/DEMO order routing, or real orders.
