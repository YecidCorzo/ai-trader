"""SQLite persistence for simulated trades and paper risk controls."""
from __future__ import annotations

import sqlite3
from typing import Any, Sequence


class PaperTradingRepository:
    """Persistence boundary for the paper-trading ledger and stop switch."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self._connection.execute(sql, params).fetchone()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self._connection.execute(sql, params).fetchall()

    def create_trade(self, trade: dict[str, Any]) -> None:
        self._connection.execute(
            """INSERT INTO paper_trades
               (id, symbol, strategy, side, quantity, entry_price, entry_fee,
                status, opened_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)""",
            (
                trade["id"], trade["symbol"], trade["strategy"], trade["side"],
                trade["quantity"], trade["entry_price"], trade["entry_fee"],
                trade["opened_at"], trade["metadata_json"],
            ),
        )
        self.add_event(
            trade["event_id"], trade["id"], "TRADE_OPENED",
            trade["event_details_json"], trade["opened_at"],
        )

    def get_trade(self, trade_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM paper_trades WHERE id = ?", (trade_id,))

    def list_trades(
        self, *, status: str | None = None, symbol: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self._all(
            "SELECT * FROM paper_trades" + where +
            " ORDER BY opened_at DESC, id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )

    def close_trade(
        self, *, trade_id: str, exit_price: str, exit_fee: str,
        realized_pnl: str, closed_at: str, exit_reason: str | None,
        event_id: str, event_details_json: str,
    ) -> bool:
        cursor = self._connection.execute(
            """UPDATE paper_trades
               SET exit_price = ?, exit_fee = ?, realized_pnl = ?,
                   status = 'CLOSED', closed_at = ?, exit_reason = ?
               WHERE id = ? AND status = 'OPEN'""",
            (
                exit_price, exit_fee, realized_pnl, closed_at,
                exit_reason, trade_id,
            ),
        )
        if cursor.rowcount != 1:
            return False
        self.add_event(
            event_id, trade_id, "TRADE_CLOSED", event_details_json, closed_at
        )
        return True

    def add_event(
        self, event_id: str, trade_id: str | None, event_type: str,
        details_json: str, occurred_at: str,
    ) -> None:
        self._connection.execute(
            """INSERT INTO paper_trade_events
               (id, trade_id, event_type, details_json, occurred_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_id, trade_id, event_type, details_json, occurred_at),
        )

    def list_events(self, trade_id: str | None = None) -> list[sqlite3.Row]:
        if trade_id is None:
            return self._all(
                "SELECT * FROM paper_trade_events ORDER BY occurred_at, id"
            )
        return self._all(
            """SELECT * FROM paper_trade_events
               WHERE trade_id = ? ORDER BY occurred_at, id""",
            (trade_id,),
        )

    def get_risk_control(self) -> sqlite3.Row:
        row = self._one("SELECT * FROM paper_risk_control WHERE id = 1")
        if row is None:
            raise RuntimeError("Falta el estado inicial del control de riesgo")
        return row

    def set_halted(
        self, *, halted: bool, reason: str | None, updated_at: str,
        updated_by: str, event_id: str, event_type: str, details_json: str,
    ) -> bool:
        current = self.get_risk_control()
        target = 1 if halted else 0
        if current["halted"] == target:
            return False
        self._connection.execute(
            """UPDATE paper_risk_control
               SET halted = ?, reason = ?, updated_at = ?, updated_by = ?
               WHERE id = 1""",
            (target, reason, updated_at, updated_by),
        )
        self.add_event(event_id, None, event_type, details_json, updated_at)
        return True
