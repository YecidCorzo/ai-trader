# AdvancedStrategy real-history acceptance run

The dedicated GitHub Actions workflow runs the immutable
`SOLUSDT-1H-10000-5000-1000-1000-1000-v1` acceptance sample against Binance
public market data. It uses no exchange credentials and submits no orders.

Workflow: `.github/workflows/advanced-strategy-acceptance.yml`.

The workflow prints the full JSON report and uploads the same report as the
`advanced-strategy-acceptance-SOLUSDT-1h-<run>` artifact. The artifact includes:

- Exact pre-registered symbol, interval and train/validation/test windows.
- Actual number and UTC time range of closed candles received.
- All fold metrics and the aggregate GO/NO-GO decision.
- Every simulated trade, including MFE, MAE, cost in R, TP1/TP2 outcomes,
  fees, exit reason and timestamps.
- Explicit PAPER-only safety metadata.
- `ledger_reconciliation`: an independent `Decimal` re-derivation of the
  published money figures (see below).

## Ledger reconciliation

`backend/services/backtest_reconciliation.py` does not re-run the strategy. It
re-derives the published figures from the per-trade rows with `Decimal`:

- per trade, `net_pnl = gross_pnl - entry_fee - exit_fee`;
- per fold, `initial_balance_per_fold + cumulative net_pnl` equals each
  trade's published `balance`;
- per fold, `net_pnl` and `fees` equal the sum of that fold's trades;
- in aggregate, `net_pnl` and `total_fees` equal the fold sums, and the fold
  trade counts equal the published trade list.

Tolerances only cover the documented rounding of each field (8 decimals per
trade, 2 for fold net P&L, 6 for aggregates) and grow with the number of
rounded terms. Missing, non-finite or negative-fee values fail closed.

If reconciliation fails, the runner still writes the full report with
`ledger_reconciliation.status = "FAILED"` for audit, then exits with code 1 so
the workflow fails: an unreconciled ledger cannot support GO or NO_GO.
Reconciliation proves internal consistency of the report only. It does not
validate market data, fill realism or future profitability.

The published run #788 artifact reconciles: 40 trades, recomputed net P&L
`-292.05318018` USDT and fees `313.29244217` USDT (regression test in
`tests/test_backtest_reconciliation.py`). Its NO_GO decision is unchanged.

A NO_GO is a valid completed research result. It must be published as-is; do
not change strategy thresholds or acceptance gates after inspecting the sample.
If fewer than 7,000 closed hourly candles are available, the runner publishes
NO_GO without fabricating folds. Fewer than 10,000 candles cannot produce the
four pre-registered folds and therefore cannot pass the fold-count gate.

A successful workflow run does not authorize LIVE trading. The result remains
research evidence for PAPER mode only.
