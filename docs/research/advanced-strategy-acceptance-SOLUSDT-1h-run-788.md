# AdvancedStrategy real-history acceptance — run #788

**Decision: NO_GO (2/7 criteria passed).**

- **Config:** `SOLUSDT-1H-10000-5000-1000-1000-1000-v1`
- **Symbol / interval:** SOL/USDT / 1h
- **History:** 10,000 of 10,000 closed candles
- **UTC range:** 2025-09-24T07:00:00.000Z to 2026-11-14T22:00:00.000Z
- **OOS folds:** 4
- **OOS trades:** 40

## Aggregate OOS result

| Metric | Result |
|---|---:|
| Net P&L (sum of independent folds) | -292.05318 USDT |
| Expectancy per trade | -7.30133 USDT |
| Profit factor | 0.856718 |
| Average test return | -0.730133% |
| Excess vs buy-and-hold | -1.046369% |
| Max fold drawdown | 8.87% |
| Average MFE | 1.224458R |
| Average MAE | 0.906168R |
| Average cost | 0.131687R |
| TP2 hits | 13/40 (32.5%) |
| TP2 rate after TP1 | 68.4211% |

## Fold results

| Fold | Trades | Net P&L | Expectancy | Profit factor | Max DD | TP2 hits / rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 21 | -425.05 | -20.2402 | 0.6466 | 8.87% | 6/21 (28.5714%) |
| 2 | 4 | 121.23 | 30.3063 | 1.9681 | 1.96% | 2/4 (50%) |
| 3 | 6 | 73.68 | 12.2807 | 1.3436 | 2.35% | 2/6 (33.3333%) |
| 4 | 9 | -61.92 | -6.8797 | 0.8752 | 2.72% | 3/9 (33.3333%) |

## GO/NO-GO criteria

| Criterion | Actual | Required | Passed |
|---|---:|---|---|
| oos_trade_count | 40 | >= 100 | NO |
| positive_oos_expectancy | -7.30133 | > 0 after fees and slippage | NO |
| oos_profit_factor | 0.856718 | >= 1.20 | NO |
| maximum_fold_drawdown | 8.87 | <= 15.0% | YES |
| walk_forward_fold_count | 4 | >= 4 | YES |
| minimum_trades_per_fold | [21,4,6,9] | every fold >= 25 | NO |
| walk_forward_stability | {"fold_count":4,"positive_fold_ratio":0,"stable_folds":0} | >= 75% folds with >= 25 trades, positive expectancy and PF > 1.0 | NO |

## Interpretation

Only 2 of 7 pre-registered criteria passed. The sample fails on OOS trade count, positive expectancy, aggregate profit factor, minimum trades per fold and walk-forward stability. Maximum fold drawdown and the minimum fold count passed.

This is a valid completed **NO_GO** result. No thresholds or gates were changed after inspecting OOS data. The strategy is not promoted beyond PAPER.

## Full trade-level report

The adjacent JSON file contains all 40 trades, all fold details, per-trade MFE/MAE/cost-in-R, TP1/TP2 flags, fees, exits and timestamps.

- [GitHub Actions run #788](https://github.com/YecidCorzo/ai-trader/actions/runs/43653687408)
- Workflow artifact: `advanced-strategy-acceptance-SOLUSDT-1h-788`

**Safety:** Binance public market data only. No exchange credentials or orders; LIVE trading is not authorized.
