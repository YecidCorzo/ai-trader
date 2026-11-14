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

A NO_GO is a valid completed research result. It must be published as-is; do
not change strategy thresholds or acceptance gates after inspecting the sample.
If fewer than 7,000 closed hourly candles are available, the runner publishes
NO_GO without fabricating folds. Fewer than 10,000 candles cannot produce the
four pre-registered folds and therefore cannot pass the fold-count gate.

A successful workflow run does not authorize LIVE trading. The result remains
research evidence for PAPER mode only.
