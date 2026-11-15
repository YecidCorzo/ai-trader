# AdvancedStrategy multi-symbol acceptance — pre-registration v2

**Status: pre-registered before data retrieval.** Immutable protocol. Any change requires a new config ID, PR and untouched hold-out.

## Hypothesis and fixed universe
Evaluate the existing AdvancedStrategy without changing rules or parameters. The only design change from #788 is a fixed multi-market sample. SOLUSDT is excluded because it was already inspected in #788.

Exact Binance spot USDT universe; no substitutions or post-result exclusions:
BTCUSDT, ETHUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LINKUSDT, LTCUSDT, AVAXUSDT.

If any pair lacks complete history or aligned timestamps, abort scored testing and publish BLOCKED/NO_GO. Never silently reduce the universe.

## Frozen data and splits
- Config: `ADV-MULTI-9USDT-1H-10000-5000-1000-1000-1000-v2`
- Binance public read-only market data only; no credentials or orders.
- 1h closed candles; exactly 10,000 per pair.
- All nine series must have identical first and last candle-open timestamps.
- Per pair: 5,000 train/warm-up + 1,000 validation/warm-up + four non-overlapping 1,000-candle OOS folds, step 1,000.
- No fitting, optimization, symbol ranking or OOS-driven selection.

## Frozen strategy and costs
Pin current defaults: min_score=60; ATR stop=1.5; reward/risk=2.0; derived minimum ATR%; max ATR%=0.05; EMA slope minimum=0.0001; volume ratio minimum=1.0 over 20 candles; fee=0.001 per side; adverse slippage=0.0005 per side; max_cost_r=0.15. This is the existing strategy default, not a threshold selected after inspecting this sample. Do not test 0.20R in v2. Report cost_in_r and do not relax the filter.

Each symbol/fold starts with independent 10,000 USDT PAPER capital. Pooled P&L/PF are sums of independent trade outcomes, not a portfolio equity curve. Fold drawdown is the maximum per-symbol fold drawdown, not synthetic portfolio drawdown.

## Frozen GO/NO_GO gates (unchanged from #788)
1. Total OOS trades >=100.
2. Pooled expectancy >0 after fees/slippage.
3. Pooled profit factor >=1.20.
4. Maximum per-symbol fold drawdown <=15%.
5. At least four chronological folds.
6. Every pooled fold >=25 trades.
7. At least 75% of folds have >=25 trades, positive expectancy and PF >1.0.

Missing/non-finite metrics fail closed. Publish all symbols, folds, trades, costs, failures and decision, including NO_GO.

## Research separation
- No parameter changes based on #788 or v2 OOS.
- Any strategy-rule/parameter variant requires a new versioned pre-registration and untouched hold-out.
- SHORT-only is a separate hypothesis. Do not infer it from the 23 SHORT trades in #788 or this pooled result. It needs a distinct pre-registered sample/universe and report; it is not part of v2.
- No promotion beyond PAPER without all gates passing and independent review.

## Reproduction
```sh
PYTHONPATH=backend python scripts/run_multi_symbol_advanced_strategy_acceptance.py --output artifacts/advanced_strategy_acceptance_multi_symbol_v2.json
```
The runner prints and writes the complete JSON report. NO_GO exits zero so the full artifact is published; the decision field is authoritative.

## Safety
PAPER research only. Binance public read-only data only. No exchange credentials, DEMO/LIVE order endpoints, exchange orders, real funds or LIVE authorization.
