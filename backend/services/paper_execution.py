"""Pre-trade gate for simulated entries; no live order-routing capability."""
from __future__ import annotations

import json
import re
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


# Quote assets supported by Binance spot symbols. Matching is exact: we do not
# infer an account currency from an arbitrary suffix or apply implicit FX.
_BINANCE_QUOTE_ASSETS = frozenset({
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "BTC", "ETH", "BNB",
    "EUR", "TRY", "BRL", "GBP", "AUD", "BIDR", "DAI", "UAH",
    "ZAR", "RUB", "PLN", "RON", "ARS", "NGN", "IDRT",
})


def _validate_account_symbol(symbol: str, quote_currency: str) -> str:
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol debe ser un par spot de Binance")
    normalized = symbol.upper()
    if normalized != symbol or not re.fullmatch(r"[A-Z0-9]{5,30}", normalized):
        raise ValueError(
            "symbol debe usar el formato canónico BASEQUOTE de Binance, sin espacios ni separadores"
        )
    if quote_currency not in _BINANCE_QUOTE_ASSETS:
        raise ValueError(
            f"La moneda {quote_currency} no está admitida como quote asset para ejecución PAPER en Binance"
        )
    matched_quote = next(
        (asset for asset in sorted(_BINANCE_QUOTE_ASSETS, key=len, reverse=True)
         if normalized.endswith(asset)),
        None,
    )
    if matched_quote is None:
        raise ValueError("No se pudo identificar la moneda cotizada del símbolo Binance")
    base_asset = normalized[:-len(matched_quote)]
    if not re.fullmatch(r"[A-Z0-9]{2,20}", base_asset):
        raise ValueError("El símbolo Binance no contiene un activo base válido")
    if matched_quote != quote_currency:
        raise ValueError(
            f"El símbolo cotiza en {matched_quote}, pero la cuenta PAPER usa {quote_currency}; no se aplica conversión FX"
        )
    return normalized


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
        account = self._accounts.get_account(account_id)
        normalized_symbol = _validate_account_symbol(
            symbol, account["quote_currency"]
        )
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
            account_id, additional_symbols=(normalized_symbol,),
        )
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
            equity = self._accounts.calculate_equity(account_id, now=now)
            free_cash = self._accounts.calculate_free_cash(account_id)
            committed_before = self._accounts.calculate_open_commitment(account_id)
            new_notional = qty * entry
            new_commitment = new_notional + opening_fee
            if new_commitment > free_cash:
                self._connection.rollback()
                raise RiskRejectedError("insufficient_free_cash")
            if committed_before + new_commitment > equity:
                self._connection.rollback()
                raise RiskRejectedError("committed_capital_exceeds_equity")
            breaker = CircuitBreaker(self._connection, account_id)
            breaker_halted = breaker.status()["halted"]
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            metrics = self._repository.risk_metrics(
                day_start=day_start.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                day_end=day_end.isoformat(timespec="microseconds").replace("+00:00", "Z"),
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
                    breaker.halt(
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
                "estimated_exit_fee": str(exit_fee),
                "risk_ratio": str(decision.risk_ratio),
                "equity_source": "persisted_paper_account",
            })
            return self._ledger.open_trade(
                symbol=normalized_symbol, strategy=strategy, side=side,
                quantity=qty, entry_price=entry, entry_fee=opening_fee,
                metadata=trade_metadata, paper_account_id=account_id,
            )
        except RiskRejectedError:
            raise
        except Exception:
            self._connection.rollback()
            raise

    def close_position(
        self, trade_id: str, *, account_id: str,
        exit_fee: Decimal | str = "0", exit_reason: str | None = None,
    ) -> dict:
        trade = self._ledger.get_trade(trade_id)
        if trade is None:
            raise ValueError("Operación no encontrada")
        if trade["paper_account_id"] != account_id:
            raise ValueError("La operación no pertenece a la cuenta PAPER indicada")
        closing_fee = _non_negative_decimal(exit_fee, "exit_fee")
        quotes = self._accounts.fetch_open_position_quotes(
            account_id, additional_symbols=(trade["symbol"],),
        )
        quote = next(
            (item for item in quotes if item.symbol == trade["symbol"]),
            None,
        )
        if quote is None:
            raise ValueError("No hay un precio de mercado actual para cerrar la operación")
        return self._close_position_with_quote(
            trade_id, account_id=account_id, quote=quote,
            exit_fee=closing_fee, exit_reason=exit_reason,
        )

    def _close_position_with_quote(
        self, trade_id: str, *, account_id: str, quote,
        exit_fee: Decimal, exit_reason: str | None,
    ) -> dict:
        """Close at an observed public-market quote; never substitute the stop price."""
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            current = self._ledger.get_trade(trade_id)
            if current is None or current["status"] != "OPEN":
                raise ValueError("La operación ya está cerrada o no existe")
            if current["paper_account_id"] != account_id:
                raise ValueError("La operación no pertenece a la cuenta PAPER indicada")
            if current["symbol"] != quote.symbol:
                raise ValueError("La cotización no corresponde al símbolo de la operación")
            now = datetime.now(timezone.utc)
            self._accounts.persist_price_quotes([quote], now=now)
            closed = self._ledger.close_trade(
                trade_id, exit_price=quote.price,
                exit_fee=exit_fee, exit_reason=exit_reason,
            )
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            metrics = self._repository.risk_metrics(
                day_start=day_start.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                day_end=day_end.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                loss_streak_limit=self._risk_engine.limits.max_consecutive_losses,
                account_id=account_id,
            )
            if metrics["consecutive_losses"] >= self._risk_engine.limits.max_consecutive_losses:
                CircuitBreaker(self._connection, account_id).halt(
                    "Risk Engine: consecutive loss limit reached",
                    updated_by="risk_engine",
                )
            return closed
        except Exception:
            self._connection.rollback()
            raise

    def process_stop_losses(self, account_id: str) -> list[dict]:
        """Close PAPER positions whose stop was crossed at a fresh observed quote.

        A stop is triggered at the next successful polling observation. The
        simulated fill uses that observed market price, not the configured stop
        price, so gaps can produce losses larger than planned risk.
        """
        if not account_id or not account_id.strip():
            raise ValueError("account_id es obligatorio")
        self._accounts.get_account(account_id)
        rows = self._connection.execute(
            """SELECT * FROM paper_trades
               WHERE paper_account_id = ? AND status = 'OPEN'
               ORDER BY opened_at, id""",
            (account_id,),
        ).fetchall()
        if not rows:
            return []

        quotes = self._accounts.fetch_open_position_quotes(account_id)
        quote_by_symbol = {quote.symbol: quote for quote in quotes}
        closed = []
        for trade in rows:
            try:
                metadata = json.loads(trade["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"La operación {trade['id']} tiene metadatos inválidos"
                ) from error
            if not isinstance(metadata, dict) or "stop_price" not in metadata:
                raise ValueError(
                    f"La operación {trade['id']} no tiene un stop verificable"
                )
            stop = _positive_decimal(metadata["stop_price"], "stop_price")
            quote = quote_by_symbol.get(trade["symbol"])
            if quote is None:
                raise ValueError(
                    f"No hay una cotización actual para {trade['symbol']}"
                )
            market_price = _positive_decimal(quote.price, "market_price")
            triggered = (
                market_price <= stop if trade["side"] == "LONG"
                else market_price >= stop
            )
            if not triggered:
                continue
            estimated_fee = _non_negative_decimal(
                metadata.get("estimated_exit_fee", "0"),
                "estimated_exit_fee",
            )
            try:
                result = self._close_position_with_quote(
                    trade["id"], account_id=account_id, quote=quote,
                    exit_fee=estimated_fee, exit_reason="stop_loss_triggered",
                )
            except ValueError as error:
                # Another worker may have closed this position after the scan.
                if "ya está cerrada" in str(error):
                    continue
                raise
            closed.append(result)
        return closed
    def reconcile_account(self, account_id: str) -> dict:
        """Expose reconciliation and halt PAPER entries if the ledger is inconsistent."""
        try:
            from backend.services.paper_reconciliation import reconcile_realized_pnl
        except ImportError:
            from services.paper_reconciliation import reconcile_realized_pnl
        self._accounts.get_account(account_id)
        result = reconcile_realized_pnl(self._connection, account_id)
        if not result["consistent"]:
            result["alert"] = "PAPER_LEDGER_INCONSISTENT"
            result["circuit_breaker"] = CircuitBreaker(self._connection, account_id).halt(
                "PAPER ledger reconciliation mismatch", updated_by="reconciliation"
            )
        else:
            result["alert"] = None
            result["circuit_breaker"] = CircuitBreaker(self._connection, account_id).status()
        return result

    def circuit_breaker_status(self, account_id: str) -> dict:
        return CircuitBreaker(self._connection, account_id).status()

    def halt(
        self, account_id: str, reason: str, *, updated_by: str = "operator",
    ) -> dict:
        return CircuitBreaker(self._connection, account_id).halt(
            reason, updated_by=updated_by,
        )

    def reset_circuit_breaker(
        self, account_id: str, *, confirmed_by: str,
    ) -> dict:
        return CircuitBreaker(self._connection, account_id).reset(
            confirmed_by=confirmed_by,
        )
