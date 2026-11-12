"""Persistent capital ledger and fail-closed PAPER mark-to-market equity."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from backend.services.paper_price import BinancePublicPriceProvider, PriceQuote


class PaperAccountError(ValueError):
    pass


class MissingOpeningCapitalError(PaperAccountError):
    pass


class StaleMarketPriceError(PaperAccountError):
    pass


def _money(value: Decimal | str | int, field: str, *, allow_negative: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise PaperAccountError(f"{field} debe ser un decimal válido") from None
    if (
        not amount.is_finite()
        or amount == 0
        or abs(amount) > Decimal("9000000000000000")
        or (amount < 0 and not allow_negative)
    ):
        raise PaperAccountError(f"{field} debe ser finito y {'no cero' if allow_negative else 'positivo'}")
    return amount


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperAccountError("La fecha debe incluir zona horaria")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


class PaperAccountService:
    """One or more isolated simulated accounts; each needs explicit opening capital."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        price_provider=None,
        *,
        max_price_age: timedelta = timedelta(seconds=30),
    ) -> None:
        if max_price_age <= timedelta(0):
            raise ValueError("max_price_age debe ser positivo")
        self._connection = connection
        self._price_provider = price_provider or BinancePublicPriceProvider()
        self._max_price_age = max_price_age

    def create_account(
        self, *, name: str, quote_currency: str,
        opening_capital: Decimal | str | int,
        idempotency_key: str,
        account_id: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        name = name.strip()
        currency = quote_currency.strip().upper()
        key = idempotency_key.strip()
        amount = _money(opening_capital, "opening_capital")
        if not name or not key:
            raise PaperAccountError("name e idempotency_key son obligatorios")
        if not 3 <= len(currency) <= 8 or not currency.isalnum():
            raise PaperAccountError("quote_currency inválida")
        identifier = account_id or str(uuid4())
        now = _timestamp(created_at)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                """SELECT id, name, quote_currency FROM paper_accounts
                   WHERE creation_key = ?""",
                (key,),
            ).fetchone()
            if existing is not None:
                opening = self._connection.execute(
                    """SELECT amount, currency_code FROM paper_account_events
                       WHERE account_id = ? AND event_type = 'OPENING_CAPITAL'""",
                    (existing["id"],),
                ).fetchone()
                if (
                    existing["name"] != name
                    or existing["quote_currency"] != currency
                    or opening is None
                    or Decimal(opening["amount"]) != amount
                    or opening["currency_code"] != currency
                    or (account_id is not None and existing["id"] != account_id)
                ):
                    raise PaperAccountError("idempotency_key ya utilizado para otra cuenta o capital")
                identifier = existing["id"]
                self._connection.commit()
                return self.get_account(identifier)
            self._connection.execute(
                """INSERT INTO paper_accounts
                   (id, name, quote_currency, creation_key, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (identifier, name, currency, key, now),
            )
            self._connection.execute(
                """INSERT INTO paper_account_risk_controls
                   (account_id, halted, reason, updated_at, updated_by)
                   VALUES (?, 0, NULL, ?, 'system')""",
                (identifier, now),
            )
            self._insert_event(
                account_id=identifier, event_type="OPENING_CAPITAL",
                amount=amount, currency=currency, idempotency_key=key,
                reference_id=None, occurred_at=now,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.get_account(identifier)

    def get_account(self, account_id: str) -> dict:
        row = self._connection.execute(
            "SELECT * FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise PaperAccountError("Cuenta PAPER no encontrada")
        events = self._connection.execute(
            "SELECT COUNT(*) FROM paper_account_events WHERE account_id = ? AND event_type = 'OPENING_CAPITAL'",
            (account_id,),
        ).fetchone()[0]
        if events != 1:
            raise MissingOpeningCapitalError("La cuenta PAPER no tiene capital inicial explícito")
        return dict(row)

    def record_funding(
        self, account_id: str, *, event_type: str,
        amount: Decimal | str | int, idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> dict:
        event_type = event_type.strip().upper()
        if event_type not in {"DEPOSIT", "WITHDRAWAL", "ADJUSTMENT"}:
            raise PaperAccountError("event_type debe ser DEPOSIT, WITHDRAWAL o ADJUSTMENT")
        value = _money(amount, "amount", allow_negative=(event_type == "ADJUSTMENT"))
        if event_type == "WITHDRAWAL" and value < 0:
            raise PaperAccountError("El retiro se expresa como importe positivo")
        account = self.get_account(account_id)
        signed = -value if event_type == "WITHDRAWAL" else value
        key = idempotency_key.strip()
        if not key:
            raise PaperAccountError("idempotency_key es obligatorio")
        now = _timestamp(occurred_at)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                "SELECT id, amount, event_type FROM paper_account_events WHERE account_id = ? AND idempotency_key = ?",
                (account_id, key),
            ).fetchone()
            if existing:
                if existing["event_type"] != event_type or Decimal(existing["amount"]) != signed:
                    raise PaperAccountError("idempotency_key ya utilizado con otro contenido")
                self._connection.commit()
                return dict(existing)
            balance = self._balance(account_id)
            if signed < 0 and balance + signed < 0:
                raise PaperAccountError("El movimiento supera el saldo disponible de la cuenta PAPER")
            self._insert_event(
                account_id=account_id, event_type=event_type, amount=signed,
                currency=account["quote_currency"], idempotency_key=key,
                reference_id=None, occurred_at=now,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        row = self._connection.execute(
            "SELECT * FROM paper_account_events WHERE account_id = ? AND idempotency_key = ?",
            (account_id, key),
        ).fetchone()
        return dict(row)

    def fetch_open_position_quotes(
        self, account_id: str, *, additional_symbols: tuple[str, ...] = (),
    ) -> list[PriceQuote]:
        self.get_account(account_id)
        rows = self._connection.execute(
            """SELECT DISTINCT symbol FROM paper_trades
               WHERE paper_account_id = ? AND status = 'OPEN' ORDER BY symbol""",
            (account_id,),
        ).fetchall()
        symbols = {row["symbol"] for row in rows}
        symbols.update(symbol.strip().upper() for symbol in additional_symbols if symbol.strip())
        quotes = []
        for symbol in sorted(symbols):
            quote = self._price_provider.get_price(symbol)
            if not isinstance(quote, PriceQuote):
                raise StaleMarketPriceError("El proveedor de precios devolvió un formato no verificable")
            if quote.symbol != symbol or quote.source.strip() == "":
                raise StaleMarketPriceError("La cotización no corresponde al símbolo solicitado")
            quotes.append(quote)
        return quotes

    def get_equity(self, account_id: str) -> Decimal:
        """Fetch fresh marks and persist their snapshots before returning equity."""
        quotes = self.fetch_open_position_quotes(account_id)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            self.persist_price_quotes(quotes, now=now)
            equity = self.calculate_equity(account_id, now=now)
            self._connection.commit()
            return equity
        except Exception:
            self._connection.rollback()
            raise

    def persist_price_quotes(self, quotes: list[PriceQuote], *, now: datetime | None = None) -> None:
        checked_at = _utc(now)
        for quote in quotes:
            retrieved = _utc(quote.retrieved_at)
            age = checked_at - retrieved
            if age < timedelta(0) or age > self._max_price_age:
                raise StaleMarketPriceError(f"Precio stale o con timestamp inválido para {quote.symbol}")
            price = _money(quote.price, "market_price")
            self._connection.execute(
                """INSERT INTO paper_price_snapshots
                   (id, symbol, price, source, retrieved_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid4()), quote.symbol, str(price), quote.source, _timestamp(retrieved)),
            )

    def _balance(self, account_id: str) -> Decimal:
        rows = self._connection.execute(
            "SELECT amount FROM paper_account_events WHERE account_id = ? ORDER BY sequence",
            (account_id,),
        ).fetchall()
        if not rows:
            raise MissingOpeningCapitalError("La cuenta PAPER no tiene capital inicial explícito")
        return sum((Decimal(row["amount"]) for row in rows), Decimal("0"))

    def calculate_equity(
        self, account_id: str, *, now: datetime | None = None,
    ) -> Decimal:
        """Recompute equity only from persisted account events and price snapshots."""
        self.get_account(account_id)
        checked_at = _utc(now)
        rows = self._connection.execute(
            """SELECT symbol, side, quantity, entry_price, entry_fee
               FROM paper_trades
               WHERE paper_account_id = ? AND status = 'OPEN'""",
            (account_id,),
        ).fetchall()
        unrealized = Decimal("0")
        for trade in rows:
            latest = self._connection.execute(
                """SELECT price, retrieved_at FROM paper_price_snapshots
                   WHERE symbol = ? ORDER BY sequence DESC LIMIT 1""",
                (trade["symbol"],),
            ).fetchone()
            if latest is None:
                raise StaleMarketPriceError(f"No hay precio disponible para {trade['symbol']}")
            price = Decimal(latest["price"])
            retrieved = datetime.fromisoformat(latest["retrieved_at"].replace("Z", "+00:00"))
            age = checked_at - retrieved
            if age < timedelta(0) or age > self._max_price_age:
                raise StaleMarketPriceError(f"Precio stale o con timestamp inválido para {trade['symbol']}")
            quantity = Decimal(trade["quantity"])
            entry = Decimal(trade["entry_price"])
            gross = quantity * (price - entry) if trade["side"] == "LONG" else quantity * (entry - price)
            unrealized += gross - Decimal(trade["entry_fee"])
        return self._balance(account_id) + unrealized

    def _insert_event(
        self, *, account_id: str, event_type: str, amount: Decimal,
        currency: str, idempotency_key: str, reference_id: str | None,
        occurred_at: str,
    ) -> None:
        self._connection.execute(
            """INSERT INTO paper_account_events
               (id, account_id, event_type, amount, currency_code,
                idempotency_key, reference_id, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), account_id, event_type, str(amount), currency,
             idempotency_key, reference_id, occurred_at),
        )
