"""Exact one-to-one reconciliation for the immutable PAPER realized-P&L ledger."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation


def _finite_decimal(value: object) -> Decimal:
    """Parse a persisted amount and reject NaN or infinities."""
    amount = Decimal(value)
    if not amount.is_finite():
        raise ValueError("PAPER realized-P&L ledger contains a non-finite decimal")
    return amount


def reconcile_realized_pnl(connection: sqlite3.Connection, account_id: str) -> dict:
    """Compare every CLOSED trade with exactly one matching account P&L posting.

    Both aggregate totals and per-trade reference/amount matching are checked.
    This prevents offsetting posting errors from cancelling in the aggregate.
    Malformed or non-finite persisted values fail closed instead of being
    reported as a consistent ledger.
    """
    trades = connection.execute(
        """SELECT id, realized_pnl FROM paper_trades
           WHERE paper_account_id = ? AND status = 'CLOSED'
           ORDER BY id""",
        (account_id,),
    ).fetchall()
    events = connection.execute(
        """SELECT reference_id, amount FROM paper_account_events
           WHERE account_id = ? AND event_type = 'TRADE_REALIZED_PNL'
           ORDER BY sequence""",
        (account_id,),
    ).fetchall()
    try:
        trade_amounts = {
            str(row["id"]): _finite_decimal(row["realized_pnl"])
            for row in trades
        }
        event_amounts: dict[str, list[Decimal]] = defaultdict(list)
        for row in events:
            reference_id = str(row["reference_id"]) if row["reference_id"] is not None else "<missing-reference-id>"
            event_amounts[reference_id].append(_finite_decimal(row["amount"]))
        trade_total = sum(trade_amounts.values(), Decimal("0"))
        event_total = sum((amount for postings in event_amounts.values() for amount in postings), Decimal("0"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("PAPER realized-P&L ledger contains a malformed or non-finite decimal") from None

    trade_ids = set(trade_amounts)
    event_ids = set(event_amounts)
    missing_event_trade_ids = sorted(trade_ids - event_ids)
    orphan_event_trade_ids = sorted(event_ids - trade_ids)
    duplicate_event_trade_ids = sorted(
        trade_id for trade_id, postings in event_amounts.items()
        if trade_id and len(postings) != 1
    )
    mismatched_trade_ids = sorted(
        trade_id for trade_id in trade_ids & event_ids
        if len(event_amounts[trade_id]) == 1
        and event_amounts[trade_id][0] != trade_amounts[trade_id]
    )
    difference = trade_total - event_total
    consistent = (
        difference == 0
        and len(trades) == len(events)
        and not missing_event_trade_ids
        and not orphan_event_trade_ids
        and not duplicate_event_trade_ids
        and not mismatched_trade_ids
        and "<missing-reference-id>" not in event_amounts
    )
    return {
        "account_id": account_id,
        "closed_trade_count": len(trades),
        "realized_event_count": len(events),
        "trade_realized_pnl": str(trade_total),
        "event_realized_pnl": str(event_total),
        "difference": str(difference),
        "missing_event_trade_ids": missing_event_trade_ids,
        "orphan_event_trade_ids": orphan_event_trade_ids,
        "duplicate_event_trade_ids": duplicate_event_trade_ids,
        "mismatched_trade_ids": mismatched_trade_ids,
        "consistent": consistent,
    }
