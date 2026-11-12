"""Auditable ledger for simulated fills; this service cannot place real orders."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

try:
    from backend.repositories.paper_trading_repository import PaperTradingRepository
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from repositories.paper_trading_repository import PaperTradingRepository


def _decimal(value: Decimal | str | int, field: str, *, allow_zero: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} debe ser un decimal válido") from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"{field} debe ser {'no negativo' if allow_zero else 'positivo'} y finito")
    return result


def _utc_timestamp(value: datetime | None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class TradeLedger:
    """Record and close simulated positions with decimal-safe realized P&L."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._repository = PaperTradingRepository(connection)

    def open_trade(
        self, *, symbol: str, strategy: str, side: str,
        quantity: Decimal | str, entry_price: Decimal | str,
        entry_fee: Decimal | str = "0", opened_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> dict:
        symbol = symbol.strip().upper()
        strategy = strategy.strip()
        side = side.strip().upper()
        if not symbol or not strategy:
            raise ValueError("symbol y strategy son obligatorios")
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side debe ser LONG o SHORT")
        qty = _decimal(quantity, "quantity")
        price = _decimal(entry_price, "entry_price")
        fee = _decimal(entry_fee, "entry_fee", allow_zero=True)
        timestamp = _utc_timestamp(opened_at)
        trade_id = str(uuid4())
        event_details = {
            "mode": "paper",
            "symbol": symbol,
            "side": side,
            "quantity": str(qty),
            "entry_price": str(price),
            "entry_fee": str(fee),
        }
        try:
            self._repository.create_trade({
                "id": trade_id,
                "event_id": str(uuid4()),
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "quantity": str(qty),
                "entry_price": str(price),
                "entry_fee": str(fee),
                "opened_at": timestamp,
                "metadata_json": json.dumps(metadata or {}, sort_keys=True),
                "event_details_json": json.dumps(event_details, sort_keys=True),
            })
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return dict(self._repository.get_trade(trade_id))

    def close_trade(
        self, trade_id: str, *, exit_price: Decimal | str,
        exit_fee: Decimal | str = "0", closed_at: datetime | None = None,
        exit_reason: str | None = None,
    ) -> dict:
        trade = self._repository.get_trade(trade_id)
        if trade is None:
            raise ValueError("Operación no encontrada")
        if trade["status"] != "OPEN":
            raise ValueError("La operación ya está cerrada")

        price = _decimal(exit_price, "exit_price")
        fee = _decimal(exit_fee, "exit_fee", allow_zero=True)
        quantity = Decimal(trade["quantity"])
        entry = Decimal(trade["entry_price"])
        entry_fee = Decimal(trade["entry_fee"])
        gross_pnl = (
            quantity * (price - entry)
            if trade["side"] == "LONG"
            else quantity * (entry - price)
        )
        realized = gross_pnl - entry_fee - fee
        timestamp = _utc_timestamp(closed_at)
        details = {
            "mode": "paper",
            "exit_price": str(price),
            "exit_fee": str(fee),
            "gross_pnl": str(gross_pnl),
            "realized_pnl": str(realized),
            "exit_reason": exit_reason,
        }
        try:
            updated = self._repository.close_trade(
                trade_id=trade_id,
                exit_price=str(price),
                exit_fee=str(fee),
                realized_pnl=str(realized),
                closed_at=timestamp,
                exit_reason=exit_reason,
                event_id=str(uuid4()),
                event_details_json=json.dumps(details, sort_keys=True),
            )
            if not updated:
                raise ValueError("La operación ya fue cerrada")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return dict(self._repository.get_trade(trade_id))

    def get_trade(self, trade_id: str) -> dict | None:
        row = self._repository.get_trade(trade_id)
        return dict(row) if row is not None else None

    def list_trades(
        self, *, status: str | None = None, symbol: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        if status not in {None, "OPEN", "CLOSED"}:
            raise ValueError("status debe ser OPEN o CLOSED")
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("Paginación fuera de rango")
        return [
            dict(row) for row in self._repository.list_trades(
                status=status, symbol=symbol.upper() if symbol else None,
                limit=limit, offset=offset,
            )
        ]
