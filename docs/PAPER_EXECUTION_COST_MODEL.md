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
monitoring still polls public market quotes; gaps and polling delay can cause
losses larger than planned. This model is a conservative simulation
assumption, not an exchange fill guarantee or a promise that realized losses
cannot exceed 1%.
