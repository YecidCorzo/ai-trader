"""Exact reconciliation for the immutable PAPER realized-P&L ledger."""
from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation


def reconcile_realized_pnl(connection: sqlite3.Connection, account_id: str) -> dict:
    """Compare CLOSED trade P&L with its one-to-one account ledger postings.

    Decimal parsing is exact. Malformed persisted values fail closed instead
    of being reported as a consistent ledger.
    """
    trades = connection.execute(
        """SELECT realized_pnl FROM paper_trades
           WHERE paper_account_id = ? AND status = 'CLOSED'
           ORDER BY id""",
        (account_id,),
    ).fetchall()
    events = connection.execute(
        """SELECT amount FROM paper_account_events
           WHERE account_id = ? AND event_type = 'TRADE_REALIZED_PNL'
           ORDER BY sequence""",
        (account_id,),
    ).fetchall()
    try:
        trade_total = sum((Decimal(row["realized_pnl"]) for row in trades), Decimal("0"))
        event_total = sum((Decimal(row["amount"]) for row in events), Decimal("0"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("PAPER realized-P&L ledger contains a malformed decimal") from None

    difference = trade_total - event_total
    return {
        "account_id": account_id,
        "closed_trade_count": len(trades),
        "realized_event_count": len(events),
        "trade_realized_pnl": trade_total,
        "event_realized_pnl": event_total,
        "difference": difference,
        "consistent": difference == 0 and len(trades) == len(events),
    }
