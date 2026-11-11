"""Account balance reporting with explicit opening balances and honest completeness."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

try:
    from backend.api.finance import get_connection
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from api.finance import get_connection


router = APIRouter(prefix="/api/finance", tags=["personal-finance"])


class OpeningBalanceCreate(BaseModel):
    amount: Decimal = Field(max_digits=20, decimal_places=4)
    as_of: datetime


def _utc_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail="as_of debe incluir zona horaria")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _signed_minor_amount(amount: Decimal, minor_unit: int) -> int:
    try:
        scaled = amount * (Decimal(10) ** minor_unit)
        integral = scaled.to_integral_exact()
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="Importe inicial no válido") from None
    if scaled != integral:
        raise HTTPException(
            status_code=422,
            detail=f"El importe admite como máximo {minor_unit} decimales",
        )
    result = int(integral)
    if abs(result) > 9_000_000_000_000_000:
        raise HTTPException(status_code=422, detail="Importe inicial fuera del rango permitido")
    return result


@router.put("/accounts/{account_id}/opening-balance")
def set_opening_balance(
    account_id: str,
    payload: OpeningBalanceCreate,
    connection: sqlite3.Connection = Depends(get_connection),
):
    account = connection.execute(
        """SELECT a.currency_code, a.is_active, c.minor_unit
           FROM accounts a JOIN currencies c ON c.code = a.currency_code
           WHERE a.id = ?""",
        (account_id,),
    ).fetchone()
    if account is None or not account["is_active"]:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada o inactiva")

    amount_minor = _signed_minor_amount(payload.amount, account["minor_unit"])
    as_of = _utc_datetime(payload.as_of)
    try:
        connection.execute(
            """INSERT INTO account_opening_balances (account_id, amount_minor, currency_code, as_of)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET
                   amount_minor = excluded.amount_minor,
                   currency_code = excluded.currency_code,
                   as_of = excluded.as_of,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (account_id, amount_minor, account["currency_code"], as_of),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar el saldo inicial") from None

    return {
        "account_id": account_id,
        "amount_minor": amount_minor,
        "currency_code": account["currency_code"],
        "as_of": as_of,
    }


@router.get("/balances")
def list_account_balances(connection: sqlite3.Connection = Depends(get_connection)):
    accounts = connection.execute(
        """SELECT a.id, a.name, a.account_type, a.currency_code,
                  o.amount_minor AS opening_balance_minor, o.as_of AS opening_balance_as_of
           FROM accounts a
           LEFT JOIN account_opening_balances o ON o.account_id = a.id
           WHERE a.is_active = 1
           ORDER BY a.currency_code, a.name COLLATE NOCASE, a.id"""
    ).fetchall()

    results = []
    for account in accounts:
        if account["opening_balance_as_of"] is None:
            results.append({
                "account_id": account["id"],
                "name": account["name"],
                "account_type": account["account_type"],
                "currency_code": account["currency_code"],
                "opening_balance_minor": None,
                "opening_balance_as_of": None,
                "income_minor": 0,
                "expense_minor": 0,
                "unsupported_transaction_count": 0,
                "balance_minor": None,
                "status": "missing_opening_balance",
            })
            continue

        params = (account["id"], account["opening_balance_as_of"])
        movements = connection.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN transaction_type = 'income' THEN amount_minor ELSE 0 END), 0) AS income_minor,
                 COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount_minor ELSE 0 END), 0) AS expense_minor,
                 SUM(CASE WHEN transaction_type IN ('transfer', 'adjustment') THEN 1 ELSE 0 END) AS unsupported_count
               FROM transactions
               WHERE account_id = ? AND occurred_at > ?""",
            params,
        ).fetchone()
        unsupported = movements["unsupported_count"] or 0
        complete = unsupported == 0
        results.append({
            "account_id": account["id"],
            "name": account["name"],
            "account_type": account["account_type"],
            "currency_code": account["currency_code"],
            "opening_balance_minor": account["opening_balance_minor"],
            "opening_balance_as_of": account["opening_balance_as_of"],
            "income_minor": movements["income_minor"],
            "expense_minor": movements["expense_minor"],
            "unsupported_transaction_count": unsupported,
            "balance_minor": (
                account["opening_balance_minor"] + movements["income_minor"] - movements["expense_minor"]
                if complete else None
            ),
            "status": "complete" if complete else "incomplete_unsupported_transactions",
        })

    return {
        "balance_basis": "opening_balance_plus_income_minus_expenses",
        "currency_basis": "account_currency",
        "fx_applied": False,
        "accounts": results,
    }
