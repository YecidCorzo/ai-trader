"""Pre-trade gate for simulated entries; no live order-routing capability."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal, InvalidOperation

try:
    from backend.repositories.paper_trading_repository import PaperTradingRepository
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.services.risk_engine import RiskEngine, RiskSnapshot
    from backend.services.trade_ledger import TradeLedger
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from repositories.paper_trading_repository import PaperTradingRepository
    from services.circuit_breaker import CircuitBreaker
    from services.risk_engine import RiskEngine, RiskSnapshot
    from services.trade_ledger import TradeLedger


class RiskRejectedError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Entrada PAPER rechazada: {reason}")


def _positive_decimal(value: Decimal | str | int, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} debe ser un decimal válido") from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field} debe ser positivo y finito")
    return result


def _non_negative_decimal(value: Decimal | str | int, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} debe ser un decimal válido") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} debe ser no negativo y finito")
    return result


class PaperExecutionService:
    """Validate risk and breaker state before recording a simulated entry.

    The caller supplies a current equity/daily-P&L/trade-count snapshot. Open
    position count is read from the ledger inside a SQLite write transaction.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._connection = connection
        self._repository = PaperTradingRepository(connection)
        self._ledger = TradeLedger(connection)
        self._breaker = CircuitBreaker(connection)
        self._risk_engine = risk_engine or RiskEngine()

    def open_position(
        self, *, symbol: str, strategy: str, side: str,
        quantity: Decimal | str, entry_price: Decimal | str,
        stop_price: Decimal | str, risk_snapshot: RiskSnapshot,
        entry_fee: Decimal | str = "0",
        estimated_exit_fee: Decimal | str = "0",
        metadata: dict | None = None,
    ) -> dict:
        side = side.strip().upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side debe ser LONG o SHORT")
        qty = _positive_decimal(quantity, "quantity")
        entry = _positive_decimal(entry_price, "entry_price")
        stop = _positive_decimal(stop_price, "stop_price")
        opening_fee = _non_negative_decimal(entry_fee, "entry_fee")
        exit_fee = _non_negative_decimal(estimated_exit_fee, "estimated_exit_fee")

        if side == "LONG" and stop >= entry:
            raise ValueError("El stop de LONG debe estar por debajo de la entrada")
        if side == "SHORT" and stop <= entry:
            raise ValueError("El stop de SHORT debe estar por encima de la entrada")

        planned_loss = abs(entry - stop) * qty + opening_fee + exit_fee

        try:
            # Serialize concurrent entry checks against the same SQLite file.
            self._connection.execute("BEGIN IMMEDIATE")
            breaker_halted = self._breaker.status()["halted"]
            open_positions = len(
                self._repository.list_trades(status="OPEN", limit=500, offset=0)
            )
            snapshot = replace(
                risk_snapshot,
                planned_loss=planned_loss,
                open_positions=open_positions,
                circuit_breaker_halted=breaker_halted,
            )
            decision = self._risk_engine.evaluate(snapshot)
            if not decision.approved:
                if decision.reason == "daily_loss_limit_reached" and not breaker_halted:
                    self._breaker.halt(
                        "Risk Engine: daily loss limit reached",
                        updated_by="risk_engine",
                    )
                else:
                    self._connection.rollback()
                raise RiskRejectedError(decision.reason)

            trade_metadata = dict(metadata or {})
            trade_metadata.update({
                "mode": "paper",
                "stop_price": str(stop),
                "planned_loss": str(planned_loss),
                "risk_ratio": str(decision.risk_ratio),
            })
            return self._ledger.open_trade(
                symbol=symbol,
                strategy=strategy,
                side=side,
                quantity=qty,
                entry_price=entry,
                entry_fee=opening_fee,
                metadata=trade_metadata,
            )
        except RiskRejectedError:
            raise
        except Exception:
            self._connection.rollback()
            raise

    def close_position(
        self, trade_id: str, *, exit_price: Decimal | str,
        exit_fee: Decimal | str = "0", exit_reason: str | None = None,
    ) -> dict:
        return self._ledger.close_trade(
            trade_id, exit_price=exit_price,
            exit_fee=exit_fee, exit_reason=exit_reason,
        )

    def circuit_breaker_status(self) -> dict:
        return self._breaker.status()

    def halt(self, reason: str, *, updated_by: str = "operator") -> dict:
        return self._breaker.halt(reason, updated_by=updated_by)

    def reset_circuit_breaker(self, *, confirmed_by: str) -> dict:
        return self._breaker.reset(confirmed_by=confirmed_by)
