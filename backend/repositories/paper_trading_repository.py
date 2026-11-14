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
                status, opened_at, metadata_json, paper_account_id, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)""",
            (
                trade["id"], trade["symbol"], trade["strategy"], trade["side"],
                trade["quantity"], trade["entry_price"], trade["entry_fee"],
                trade["opened_at"], trade["metadata_json"], trade.get("paper_account_id"),
                trade.get("idempotency_key"),
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
            return self._all("SELECT * FROM paper_trade_events ORDER BY sequence")
        return self._all(
            "SELECT * FROM paper_trade_events WHERE trade_id = ? ORDER BY sequence",
            (trade_id,),
        )

    def count_open_trades(self, account_id: str | None = None) -> int:
        if account_id is None:
            row = self._one("SELECT COUNT(*) AS trade_count FROM paper_trades WHERE status = 'OPEN'")
        else:
            row = self._one(
                """SELECT COUNT(*) AS trade_count FROM paper_trades
                   WHERE status = 'OPEN' AND paper_account_id = ?""",
                (account_id,),
            )
        return int(row["trade_count"])

    def risk_metrics(
        self, *, day_start: str, day_end: str, loss_streak_limit: int,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Derive risk counters from persisted trades, scoped to a PAPER account."""
        from decimal import Decimal

        account_clause = " AND paper_account_id = ?" if account_id is not None else ""
        account_params = (account_id,) if account_id is not None else ()
        opened = self._one(
            "SELECT COUNT(*) AS trade_count FROM paper_trades "
            "WHERE opened_at >= ? AND opened_at < ?" + account_clause,
            (day_start, day_end, *account_params),
        )
        closed_today = self._all(
            "SELECT realized_pnl FROM paper_trades "
            "WHERE status = 'CLOSED' AND closed_at >= ? AND closed_at < ?" + account_clause,
            (day_start, day_end, *account_params),
        )
        daily_pnl = sum(
            (Decimal(row["realized_pnl"]) for row in closed_today),
            Decimal("0"),
        )
        reset = None
        if account_id is not None:
            reset = self._connection.execute(
                """SELECT sequence FROM paper_trade_events
                   WHERE event_type = 'CIRCUIT_BREAKER_RESET'
                     AND json_extract(details_json, '$.account_id') = ?
                   ORDER BY sequence DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
        reset_clause = " AND event.sequence > ?" if reset is not None else ""
        reset_params = (reset["sequence"],) if reset is not None else ()
        recent_closed = self._all(
            """SELECT trade.realized_pnl
               FROM paper_trades AS trade
               JOIN paper_trade_events AS event
                 ON event.trade_id = trade.id
                AND event.event_type = 'TRADE_CLOSED'
               WHERE trade.status = 'CLOSED'""" + account_clause + reset_clause + """
               ORDER BY event.sequence DESC
               LIMIT ?""",
            (*account_params, *reset_params, loss_streak_limit),
        )
        consecutive_losses = 0
        for row in recent_closed:
            if Decimal(row["realized_pnl"]) >= 0:
                break
            consecutive_losses += 1
        return {
            "trades_today": int(opened["trade_count"]),
            "daily_realized_pnl": daily_pnl,
            "consecutive_losses": consecutive_losses,
        }

    def get_account_risk_control(self, account_id: str) -> sqlite3.Row:
        row = self._one(
            "SELECT * FROM paper_account_risk_controls WHERE account_id = ?",
            (account_id,),
        )
        if row is None:
            raise RuntimeError("Falta el control de riesgo de la cuenta PAPER")
        return row

    def set_account_halted(
        self, *, account_id: str, halted: bool, reason: str | None,
        updated_at: str, updated_by: str, event_id: str,
        event_type: str, details_json: str,
    ) -> bool:
        current = self.get_account_risk_control(account_id)
        target = 1 if halted else 0
        if current["halted"] == target:
            return False
        cursor = self._connection.execute(
            """UPDATE paper_account_risk_controls
               SET halted = ?, reason = ?, updated_at = ?, updated_by = ?
               WHERE account_id = ?""",
            (target, reason, updated_at, updated_by, account_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("No se pudo actualizar el control de riesgo PAPER")
        self.add_event(
            event_id, None, event_type, details_json, updated_at
        )
        return True

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
