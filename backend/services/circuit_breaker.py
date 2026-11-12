"""Manual, persistent PAPER circuit breaker with optional account isolation."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

try:
    from backend.repositories.paper_trading_repository import PaperTradingRepository
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from repositories.paper_trading_repository import PaperTradingRepository


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CircuitBreaker:
    def __init__(self, connection: sqlite3.Connection, account_id: str | None = None) -> None:
        self._connection = connection
        self._repository = PaperTradingRepository(connection)
        self._account_id = account_id

    def status(self) -> dict:
        row = (
            self._repository.get_account_risk_control(self._account_id)
            if self._account_id is not None
            else self._repository.get_risk_control()
        )
        result = {
            "halted": bool(row["halted"]),
            "reason": row["reason"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
            "mode": "paper",
        }
        if self._account_id is not None:
            result["account_id"] = self._account_id
        return result

    def _set_halted(
        self, *, halted: bool, reason: str | None, updated_at: str,
        updated_by: str, event_type: str, details: dict,
    ) -> None:
        arguments = {
            "halted": halted,
            "reason": reason,
            "updated_at": updated_at,
            "updated_by": updated_by,
            "event_id": str(uuid4()),
            "event_type": event_type,
            "details_json": json.dumps(details, sort_keys=True),
        }
        if self._account_id is not None:
            self._repository.set_account_halted(
                account_id=self._account_id, **arguments
            )
        else:
            self._repository.set_halted(**arguments)

    def halt(self, reason: str, *, updated_by: str = "operator") -> dict:
        reason = reason.strip()
        if not reason:
            raise ValueError("Se requiere un motivo para detener PAPER MODE")
        now = _utc_now()
        details = {"reason": reason, "updated_by": updated_by}
        if self._account_id is not None:
            details["account_id"] = self._account_id
        try:
            self._set_halted(
                halted=True, reason=reason, updated_at=now,
                updated_by=updated_by, event_type="CIRCUIT_BREAKER_HALTED",
                details=details,
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
        details = {"confirmed_by": confirmed_by}
        if self._account_id is not None:
            details["account_id"] = self._account_id
        try:
            self._set_halted(
                halted=False, reason=None, updated_at=now,
                updated_by=confirmed_by, event_type="CIRCUIT_BREAKER_RESET",
                details=details,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.status()
