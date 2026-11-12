"""Pre-trade gate for simulated entries; no live order-routing capability."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

try:
    from backend.repositories.paper_trading_repository import PaperTradingRepository
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.services.paper_account import PaperAccountService
    from backend.services.risk_engine import RiskEngine, RiskSnapshot
    from backend.services.trade_ledger import TradeLedger
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from repositories.paper_trading_repository import PaperTradingRepository
    from services.circuit_breaker import CircuitBreaker
    from services.paper_account import PaperAccountService
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
    """Validate risk from a persisted PAPER account before recording an entry."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        risk_engine: RiskEngine | None = None,
        account_service: PaperAccountService | None = None,
    ) -> None:
        self._connection = connection
        self._repository = PaperTradingRepository(connection)
        self._ledger = TradeLedger(connection)
        self._breaker = CircuitBreaker(connection)
        self._risk_engine = risk_engine or RiskEngine()
        self._accounts = account_service or PaperAccountService(connection)

    def open_position(
        self, *, account_id: str, symbol: str, strategy: str, side: str,
        quantity: Decimal | str, stop_price: Decimal | str,
        entry_fee: Decimal | str = "0",
        estimated_exit_fee: Decimal | str = "0", metadata: dict | None = None,
    ) -> dict:
        if not account_id or not account_id.strip():
            raise ValueError("account_id es obligatorio")
        side = side.strip().upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side debe ser LONG o SHORT")
        qty = _positive_decimal(quantity, "quantity")
        stop = _positive_decimal(stop_price, "stop_price")
        opening_fee = _non_negative_decimal(entry_fee, "entry_fee")
        exit_fee = _non_negative_decimal(estimated_exit_fee, "estimated_exit_fee")

        # Network I/O happens before acquiring SQLite's write lock. The quotes
        # are checked again for age and persisted inside the atomic risk transaction.
        quotes = self._accounts.fetch_open_position_quotes(
            account_id, additional_symbols=(symbol,),
        )
        normalized_symbol = symbol.strip().upper()
        entry_quote = next(
            (quote for quote in quotes if quote.symbol == normalized_symbol),
            None,
        )
        if entry_quote is None:
            raise ValueError("No hay un precio de mercado actual para el símbolo")
        entry = _positive_decimal(entry_quote.price, "market_entry_price")

        if side == "LONG" and stop >= entry:
            raise ValueError("El stop de LONG debe estar por debajo del precio de mercado")
        if side == "SHORT" and stop <= entry:
            raise ValueError("El stop de SHORT debe estar por encima del precio de mercado")
        planned_loss = abs(entry - stop) * qty + opening_fee + exit_fee

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            open_positions = self._repository.count_open_trades(account_id)
            if open_positions >= self._risk_engine.limits.max_open_positions:
                self._connection.rollback()
                raise RiskRejectedError("max_open_positions_reached")
            self._accounts.persist_price_quotes(quotes, now=now)
            equity = self._accounts.calculate_equity(account_id, quotes=quotes, now=now)
            breaker_halted = self._breaker.status()["halted"]
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            metrics = self._repository.risk_metrics(
                day_start=day_start.isoformat(timespec="seconds").replace("+00:00", "Z"),
                day_end=day_end.isoformat(timespec="seconds").replace("+00:00", "Z"),
                loss_streak_limit=self._risk_engine.limits.max_consecutive_losses,
                account_id=account_id,
            )
            snapshot = RiskSnapshot(
                equity=equity,
                planned_loss=planned_loss,
                daily_realized_pnl=metrics["daily_realized_pnl"],
                open_positions=open_positions,
                trades_today=metrics["trades_today"],
                consecutive_losses=metrics["consecutive_losses"],
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
                "paper_account_id": account_id,
                "stop_price": str(stop),
                "planned_loss": str(planned_loss),
                "risk_ratio": str(decision.risk_ratio),
                "equity_source": "persisted_paper_account",
            })
            return self._ledger.open_trade(
                symbol=symbol, strategy=strategy, side=side,
                quantity=qty, entry_price=entry, entry_fee=opening_fee,
                metadata=trade_metadata, paper_account_id=account_id,
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
