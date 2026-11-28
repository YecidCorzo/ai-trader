"""Independent Decimal reconciliation of AdvancedStrategy walk-forward reports.

The backtest engine computes with binary floats and publishes rounded values.
This module does not re-run the strategy. It re-derives the published money
figures from the per-trade rows using ``Decimal`` and fails closed when any
figure cannot be explained by the documented rounding of the report:

* each trade: ``net_pnl == gross_pnl - entry_fee - exit_fee``;
* each fold: ``initial_balance_per_fold + cumulative net_pnl == trade balance``;
* each fold: published ``net_pnl`` and ``fees`` equal the sum of its trades;
* aggregate: published ``net_pnl`` and ``total_fees`` equal the fold sums.

Tolerances are derived from the rounding precision of every field (8 decimals
per trade, 2 decimals for fold net P&L, 6 decimals for aggregates) and grow
only with the number of rounded terms summed. They are bounds on rounding
error, not on financial error: a mismatch above them is reported as a failure.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

RECONCILIATION_VERSION = "walk-forward-ledger-v1"

_HALF_UNIT_8 = Decimal("0.000000005")
_HALF_UNIT_6 = Decimal("0.0000005")
_HALF_UNIT_2 = Decimal("0.005")
_TRADE_MONEY_FIELDS = ("gross_pnl", "entry_fee", "exit_fee", "net_pnl", "balance")


class BacktestReconciliationError(ValueError):
    """Raised when a published backtest report does not reconcile."""


def _decimal(value, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise BacktestReconciliationError(f"{label} debe ser numérico")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BacktestReconciliationError(f"{label} debe ser numérico") from None
    if not result.is_finite():
        raise BacktestReconciliationError(f"{label} debe ser finito")
    return result


def _count(value, label: str) -> int:
    number = _decimal(value, label)
    if number != number.to_integral_value() or number < 0:
        raise BacktestReconciliationError(f"{label} debe ser un entero no negativo")
    return int(number)


def _check(actual: Decimal, expected: Decimal, tolerance: Decimal, label: str) -> Decimal:
    residual = abs(actual - expected)
    if residual > tolerance:
        raise BacktestReconciliationError(
            f"{label} no reconcilia: publicado {actual}, recalculado {expected}, "
            f"diferencia {residual} > tolerancia {tolerance}"
        )
    return residual


def reconcile_walk_forward_ledger(walk_forward: dict) -> dict:
    """Return a reconciliation summary or raise ``BacktestReconciliationError``."""
    if not isinstance(walk_forward, dict):
        raise BacktestReconciliationError("walk_forward debe ser un objeto")
    folds = walk_forward.get("folds")
    trades = walk_forward.get("trades")
    if not isinstance(folds, list) or not isinstance(trades, list):
        raise BacktestReconciliationError("walk_forward debe contener folds y trades")

    initial_balance = _decimal(
        walk_forward.get("initial_balance_per_fold"), "initial_balance_per_fold"
    )
    if initial_balance <= 0:
        raise BacktestReconciliationError("initial_balance_per_fold debe ser positivo")

    expected_trade_total = sum(
        _count(fold.get("trade_count"), f"fold {position} trade_count")
        for position, fold in enumerate(folds, start=1)
    )
    if expected_trade_total != len(trades):
        raise BacktestReconciliationError(
            f"trade_count de los folds ({expected_trade_total}) no coincide con "
            f"las operaciones publicadas ({len(trades)})"
        )
    if walk_forward.get("total_trades") is not None and _count(
        walk_forward["total_trades"], "total_trades"
    ) != len(trades):
        raise BacktestReconciliationError("total_trades no coincide con las operaciones publicadas")

    max_trade_residual = Decimal("0")
    max_balance_residual = Decimal("0")
    total_net = Decimal("0")
    total_fees = Decimal("0")
    fold_summaries = []
    cursor = 0

    for position, fold in enumerate(folds, start=1):
        fold_label = f"fold {fold.get('fold', position)}"
        count = _count(fold.get("trade_count"), f"{fold_label} trade_count")
        balance = initial_balance
        fold_net = Decimal("0")
        fold_fees = Decimal("0")
        for offset, trade in enumerate(trades[cursor:cursor + count], start=1):
            label = f"{fold_label} trade {offset}"
            if not isinstance(trade, dict):
                raise BacktestReconciliationError(f"{label} debe ser un objeto")
            values = {
                field: _decimal(trade.get(field), f"{label} {field}")
                for field in _TRADE_MONEY_FIELDS
            }
            if values["entry_fee"] < 0 or values["exit_fee"] < 0:
                raise BacktestReconciliationError(f"{label} tiene comisiones negativas")
            residual = _check(
                values["net_pnl"],
                values["gross_pnl"] - values["entry_fee"] - values["exit_fee"],
                4 * _HALF_UNIT_8,
                f"{label} net_pnl",
            )
            max_trade_residual = max(max_trade_residual, residual)
            balance += values["net_pnl"]
            fold_net += values["net_pnl"]
            fold_fees += values["entry_fee"] + values["exit_fee"]
            residual = _check(
                values["balance"], balance, (offset + 1) * _HALF_UNIT_8, f"{label} balance"
            )
            max_balance_residual = max(max_balance_residual, residual)
        cursor += count

        _check(
            _decimal(fold.get("net_pnl"), f"{fold_label} net_pnl"),
            fold_net,
            _HALF_UNIT_2 + count * _HALF_UNIT_8,
            f"{fold_label} net_pnl",
        )
        _check(
            _decimal(fold.get("fees"), f"{fold_label} fees"),
            fold_fees,
            (2 * count + 1) * _HALF_UNIT_8,
            f"{fold_label} fees",
        )
        total_net += fold_net
        total_fees += fold_fees
        fold_summaries.append({
            "fold": fold.get("fold", position),
            "trade_count": count,
            "recomputed_net_pnl": str(fold_net),
            "recomputed_fees": str(fold_fees),
            "recomputed_final_balance": str(balance),
        })

    term_count = len(trades)
    _check(
        _decimal(walk_forward.get("net_pnl", 0), "net_pnl"),
        total_net,
        _HALF_UNIT_6 + term_count * _HALF_UNIT_8,
        "net_pnl agregado",
    )
    _check(
        _decimal(walk_forward.get("total_fees", 0), "total_fees"),
        total_fees,
        _HALF_UNIT_6 + (2 * term_count + len(folds)) * _HALF_UNIT_8,
        "total_fees agregado",
    )

    return {
        "status": "RECONCILED",
        "version": RECONCILIATION_VERSION,
        "arithmetic": "decimal_from_published_rounded_values",
        "fold_count": len(folds),
        "trade_count": term_count,
        "recomputed_net_pnl": str(total_net),
        "recomputed_total_fees": str(total_fees),
        "max_trade_identity_residual": str(max_trade_residual),
        "max_balance_chain_residual": str(max_balance_residual),
        "folds": fold_summaries,
        "note": (
            "Confirms internal consistency of the published ledger only; it does "
            "not validate market data, fills or future profitability."
        ),
    }
