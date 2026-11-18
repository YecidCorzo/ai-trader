# PAPER execution cost and sizing model

This model applies only to the internal PAPER ledger. It does not route orders,
connect to an exchange account, or place live/demo exchange orders.

## Engine-owned assumptions

- Fee floor: 0.10% of executed notional on both entry and exit.
- Slippage: 0.05% adverse to the trader on both entry and exit.
- Maximum planned risk: 1.00% of persisted account equity per trade. A configured
  RiskEngine limit below 1.00% remains authoritative.
- A caller-supplied entry or exit fee may increase the modeled fee, but cannot
  reduce the engine fee floor.
- Caller-supplied quantity is not accepted. The execution service computes it.

## Fill direction

| Position | Entry fill | Exit fill |
|---|---|---|
| LONG | quote × (1 + slippage) | quote × (1 − slippage) |
| SHORT | quote × (1 − slippage) | quote × (1 + slippage) |

The stop-loss planned exit is also adjusted adversely by the same slippage
rate. Entry and estimated stop-exit fees are included in per-unit planned loss.

## PAPER equity

For risk sizing and account reporting, open positions contribute estimated net
liquidation P&L, not gross mark-to-entry P&L. The estimate applies the same
side-aware adverse exit slippage and 0.10% exit-fee floor as simulated closing,
subtracts the entry fee already incurred, and honors any larger persisted
minimum exit fee supplied when the position was opened. With an unchanged
public quote, closing immediately should reconcile to the same account equity.
This remains an estimate: quotes can move before a close and actual stop-worker
fees/fills may differ after a gap.

## Position sizing

The service computes per-unit loss from the adverse entry fill to the adverse
stop fill, including both fee floors. It calculates the risk budget from
persisted account equity and the requested risk fraction (never above the
configured engine cap), then sizes quantity as the lesser of:

1. risk budget remaining after any caller-supplied fee amounts, divided by
   per-unit loss; and
2. free cash remaining after caller-supplied entry fee, divided by entry fill
   plus the entry fee rate.

Quantity is rounded down to eight decimal places. If equity, stop distance,
costs, risk budget or free cash cannot produce a positive finite quantity, the
entry is rejected. The final planned loss is recomputed with the actual fee
floors and checked again against the 1% engine limit before the ledger write.

## Exit and limitations

Exit fills apply adverse slippage and the exit fee is the greater of the
caller-supplied amount and 0.10% of actual simulated exit notional. Stop
monitoring polls public market quotes and closes at the next observed quote,
not at the configured stop price. A gap and polling delay can therefore make
realized loss exceed the 1.00% planned-risk budget: one observed scenario
realized 194 USDT against 100 USDT planned (1.94×). The 1.00% limit is a
position-sizing target, not a guaranteed maximum loss. This model is a
conservative simulation assumption, not an exchange fill guarantee.
