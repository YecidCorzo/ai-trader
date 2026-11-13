"""Authenticated owner-scoped API for persistent internal PAPER accounts."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

try:
    from backend.infrastructure.database import apply_migrations, connect_database
    from backend.security.dependencies import get_verified_principal
    from backend.security.principal import VerifiedPrincipal
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.services.paper_account import (
        MissingOpeningCapitalError, PaperAccountError, PaperAccountService,
        StaleMarketPriceError,
    )
    from backend.services.paper_authorization import (
        PaperAuthorizationService, PaperResourceNotFoundError,
    )
    from backend.services.paper_execution import PaperExecutionService, RiskRejectedError
    from backend.services.paper_price import BinancePublicPriceProvider
except ImportError:
    from infrastructure.database import apply_migrations, connect_database
    from security.dependencies import get_verified_principal
    from security.principal import VerifiedPrincipal
    from services.circuit_breaker import CircuitBreaker
    from services.paper_account import (
        MissingOpeningCapitalError, PaperAccountError, PaperAccountService,
        StaleMarketPriceError,
    )
    from services.paper_authorization import (
        PaperAuthorizationService, PaperResourceNotFoundError,
    )
    from services.paper_execution import PaperExecutionService, RiskRejectedError
    from services.paper_price import BinancePublicPriceProvider


router = APIRouter(prefix="/api/paper", tags=["PAPER accounts"])


class CreatePaperAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    quote_currency: str = Field(min_length=3, max_length=8)
    opening_capital: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)


class PaperFundingRequest(BaseModel):
    event_type: Literal["DEPOSIT", "WITHDRAWAL", "ADJUSTMENT"]
    amount: Decimal
    idempotency_key: str = Field(min_length=1, max_length=128)


class OpenPaperTradeRequest(BaseModel):
    symbol: str = Field(min_length=5, max_length=30)
    strategy: str = Field(min_length=1, max_length=80)
    side: Literal["LONG", "SHORT"]
    stop_price: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    risk_fraction: Decimal | None = Field(default=None, gt=0, le=0.01)


class ClosePaperTradeRequest(BaseModel):
    exit_fee: Decimal = Field(default=Decimal("0"), ge=0)
    exit_reason: str | None = Field(default=None, max_length=120)


class HaltPaperAccountRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)


class ResetPaperAccountRequest(BaseModel):
    confirmed: bool


def get_db_connection():
    connection = connect_database()
    try:
        apply_migrations(connection)
        yield connection
    finally:
        connection.close()


def get_price_provider():
    return BinancePublicPriceProvider()


def get_paper_account_service(
    connection: sqlite3.Connection = Depends(get_db_connection),
    price_provider=Depends(get_price_provider),
):
    return PaperAccountService(connection, price_provider=price_provider)


def get_paper_execution_service(
    connection: sqlite3.Connection = Depends(get_db_connection),
    accounts: PaperAccountService = Depends(get_paper_account_service),
):
    return PaperExecutionService(connection, account_service=accounts)


def _authorization(connection):
    return PaperAuthorizationService(connection)


def _raise_paper_error(error):
    if isinstance(error, PaperResourceNotFoundError):
        raise HTTPException(status_code=404, detail="Recurso PAPER no encontrado") from None
    if isinstance(error, RiskRejectedError):
        raise HTTPException(status_code=409, detail=error.reason) from None
    if isinstance(error, StaleMarketPriceError):
        raise HTTPException(status_code=503, detail="Precio de mercado no disponible o desactualizado") from None
    if isinstance(error, MissingOpeningCapitalError):
        raise HTTPException(status_code=409, detail="La cuenta PAPER requiere capital inicial explícito") from None
    if isinstance(error, (PaperAccountError, ValueError)):
        raise HTTPException(status_code=422, detail=str(error)) from None
    raise HTTPException(status_code=500, detail="Error interno en operación PAPER") from None


def _actor(principal: VerifiedPrincipal):
    return {
        "type": "oidc_verified_user",
        "issuer": principal.issuer,
        "subject": principal.subject,
    }


@router.get("/accounts")
def list_paper_accounts(
    connection: sqlite3.Connection = Depends(get_db_connection),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    rows = connection.execute(
        """SELECT * FROM paper_accounts
           WHERE owner_issuer = ? AND owner_subject = ?
           ORDER BY created_at DESC, id""",
        (principal.issuer, principal.subject),
    ).fetchall()
    accounts = []
    for row in rows:
        events = connection.execute(
            "SELECT amount FROM paper_account_events WHERE account_id = ? ORDER BY sequence",
            (row["id"],),
        ).fetchall()
        item = dict(row)
        item["balance"] = str(sum((Decimal(event["amount"]) for event in events), Decimal("0")))
        accounts.append(item)
    return {
        "mode": "paper",
        "accounts": accounts,
        "live_trading_authorized": False,
    }


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_paper_account(
    payload: CreatePaperAccountRequest,
    accounts: PaperAccountService = Depends(get_paper_account_service),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        account = accounts.create_account(
            name=payload.name,
            quote_currency=payload.quote_currency,
            opening_capital=payload.opening_capital,
            idempotency_key=payload.idempotency_key,
            principal=principal,
        )
        return {"mode": "paper", "account": account, "live_trading_authorized": False}
    except Exception as error:
        _raise_paper_error(error)


@router.get("/accounts/{account_id}")
def get_paper_account(
    account_id: str,
    connection: sqlite3.Connection = Depends(get_db_connection),
    accounts: PaperAccountService = Depends(get_paper_account_service),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        account = accounts.get_account(account_id)
        balance_rows = connection.execute(
            "SELECT amount FROM paper_account_events WHERE account_id = ? ORDER BY sequence",
            (account_id,),
        ).fetchall()
        balance = sum((Decimal(row["amount"]) for row in balance_rows), Decimal("0"))
        equity = accounts.get_equity(account_id)
        free_cash = accounts.calculate_free_cash(account_id)
        positions = connection.execute(
            """SELECT * FROM paper_trades
               WHERE paper_account_id = ? AND status = 'OPEN'
               ORDER BY opened_at, id""",
            (account_id,),
        ).fetchall()
        return {
            "mode": "paper",
            "account": account,
            "balance": str(balance),
            "equity": str(equity),
            "free_cash": str(free_cash),
            "open_positions": [dict(row) for row in positions],
            "risk": CircuitBreaker(connection, account_id).status(),
            "live_trading_authorized": False,
        }
    except Exception as error:
        _raise_paper_error(error)


@router.get("/accounts/{account_id}/trades")
def list_paper_trades(
    account_id: str,
    status_filter: Literal["OPEN", "CLOSED"] | None = Query(default=None, alias="status"),
    symbol: str | None = Query(default=None, min_length=5, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_db_connection),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        clauses = ["paper_account_id = ?"]
        params: list[object] = [account_id]
        if status_filter:
            clauses.append("status = ?")
            params.append(status_filter)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        rows = connection.execute(
            "SELECT * FROM paper_trades WHERE " + " AND ".join(clauses)
            + " ORDER BY opened_at DESC, id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return {"mode": "paper", "trades": [dict(row) for row in rows]}
    except Exception as error:
        _raise_paper_error(error)


@router.post("/accounts/{account_id}/trades", status_code=status.HTTP_201_CREATED)
def open_paper_trade(
    account_id: str,
    payload: OpenPaperTradeRequest,
    connection: sqlite3.Connection = Depends(get_db_connection),
    execution: PaperExecutionService = Depends(get_paper_execution_service),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        trade = execution.open_position(
            account_id=account_id,
            symbol=payload.symbol.upper(),
            strategy=payload.strategy,
            side=payload.side,
            stop_price=payload.stop_price,
            principal=principal,
            idempotency_key=payload.idempotency_key,
            risk_fraction=payload.risk_fraction,
        )
        return {"mode": "paper", "trade": trade, "live_trading_authorized": False}
    except Exception as error:
        _raise_paper_error(error)


@router.post("/accounts/{account_id}/trades/{trade_id}/close")
def close_paper_trade(
    account_id: str,
    trade_id: str,
    payload: ClosePaperTradeRequest,
    connection: sqlite3.Connection = Depends(get_db_connection),
    execution: PaperExecutionService = Depends(get_paper_execution_service),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_trade(principal, account_id, trade_id)
        trade = execution.close_position(
            trade_id,
            account_id=account_id,
            exit_fee=payload.exit_fee,
            exit_reason=payload.exit_reason,
            principal=principal,
        )
        return {"mode": "paper", "trade": trade, "live_trading_authorized": False}
    except Exception as error:
        _raise_paper_error(error)


@router.post("/accounts/{account_id}/funding")
def fund_paper_account(
    account_id: str,
    payload: PaperFundingRequest,
    connection: sqlite3.Connection = Depends(get_db_connection),
    accounts: PaperAccountService = Depends(get_paper_account_service),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        event = accounts.record_funding(
            account_id,
            event_type=payload.event_type,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
        )
        return {"mode": "paper", "event": event, "live_trading_authorized": False}
    except Exception as error:
        _raise_paper_error(error)


@router.get("/accounts/{account_id}/risk")
def get_paper_risk_status(
    account_id: str,
    connection: sqlite3.Connection = Depends(get_db_connection),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        return CircuitBreaker(connection, account_id).status()
    except Exception as error:
        _raise_paper_error(error)


@router.post("/accounts/{account_id}/halt")
def halt_paper_account(
    account_id: str,
    payload: HaltPaperAccountRequest,
    connection: sqlite3.Connection = Depends(get_db_connection),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        return CircuitBreaker(connection, account_id).halt(
            payload.reason,
            updated_by=principal.subject,
            actor=_actor(principal),
        )
    except Exception as error:
        _raise_paper_error(error)


@router.post("/accounts/{account_id}/reset")
def reset_paper_account(
    account_id: str,
    payload: ResetPaperAccountRequest,
    connection: sqlite3.Connection = Depends(get_db_connection),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Se requiere confirmación explícita")
    try:
        _authorization(connection).require_account(principal, account_id)
        return CircuitBreaker(connection, account_id).reset(
            confirmed_by=principal.subject,
            actor=_actor(principal),
        )
    except Exception as error:
        _raise_paper_error(error)


@router.get("/accounts/{account_id}/events")
def list_paper_account_events(
    account_id: str,
    connection: sqlite3.Connection = Depends(get_db_connection),
    principal: VerifiedPrincipal = Depends(get_verified_principal),
):
    try:
        _authorization(connection).require_account(principal, account_id)
        account_events = connection.execute(
            """SELECT * FROM paper_account_events
               WHERE account_id = ? ORDER BY sequence""",
            (account_id,),
        ).fetchall()
        trade_events = connection.execute(
            """SELECT event.* FROM paper_trade_events AS event
               LEFT JOIN paper_trades AS trade ON trade.id = event.trade_id
               WHERE trade.paper_account_id = ?
                  OR (event.trade_id IS NULL
                      AND json_extract(event.details_json, '$.account_id') = ?)
               ORDER BY event.sequence""",
            (account_id, account_id),
        ).fetchall()
        return {
            "mode": "paper",
            "account_events": [dict(row) for row in account_events],
            "trade_events": [dict(row) for row in trade_events],
        }
    except Exception as error:
        _raise_paper_error(error)
