"""Manual, persistent circuit breaker for simulated trading.

Tripping is immediate and persisted. Reset always requires an explicit caller
action and an audit event; this module has no exchange or order-routing code.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from backend.repositories.paper_trading_repository import PaperTradingRepository


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CircuitBreaker:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._repository = PaperTradingRepository(connection)

    def status(self) -> dict:
        row = self._repository.get_risk_control()
        return {
            "halted": bool(row["halted"]),
            "reason": row["reason"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
            "mode": "paper",
        }

    def halt(self, reason: str, *, updated_by: str = "operator") -> dict:
        reason = reason.strip()
        if not reason:
            raise ValueError("Se requiere un motivo para detener PAPER MODE")
        now = _utc_now()
        try:
            self._repository.set_halted(
                halted=True,
                reason=reason,
                updated_at=now,
                updated_by=updated_by,
                event_id=str(uuid4()),
                event_type="CIRCUIT_BREAKER_HALTED",
                details_json=json.dumps({"reason": reason, "updated_by": updated_by}),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.status()

    def reset(self, *, confirmed_by: str) -> dict:
        confirmed_by = confirmed_by.strip()
        if not confirmed_by:
            raise ValueError("El rearme requiere confirmación explícita del operador")
        now = _utc_now()
        try:
            self._repository.set_halted(
                halted=False,
                reason=None,
                updated_at=now,
                updated_by=confirmed_by,
                event_id=str(uuid4()),
                event_type="CIRCUIT_BREAKER_RESET",
                details_json=json.dumps({"confirmed_by": confirmed_by}),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.status()
