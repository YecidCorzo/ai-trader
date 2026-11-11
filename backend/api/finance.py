"""Personal-finance API backed by the versioned SQLite schema."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

try:
    from backend.infrastructure.database import connect_database, migrate_database
    from backend.repositories.finance_repository import FinanceRepository
except ImportError:  # Support running uvicorn with backend/ as the app directory.
    from infrastructure.database import connect_database, migrate_database
    from repositories.finance_repository import FinanceRepository


router = APIRouter(prefix="/api/finance", tags=["personal-finance"])
AccountType = Literal["cash", "bank", "credit_card", "savings", "investment", "other"]
CategoryType = Literal["income", "expense"]
TransactionType = Literal["income", "expense", "transfer", "adjustment"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    account_type: AccountType
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    institution: str | None = Field(default=None, max_length=120)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category_type: CategoryType
    parent_id: str | None = None


class TransactionCreate(BaseModel):
    account_id: str
    category_id: str | None = None
    transaction_type: TransactionType
    amount: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=4)
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    description: str | None = Field(default=None, max_length=500)
    occurred_at: datetime
    source: str = Field(default="manual", min_length=1, max_length=40)
    external_reference: str | None = Field(default=None, max_length=160)


class TransactionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_id: str
    category_id: str | None
    transaction_type: str
    amount: str
    currency_code: str
    description: str | None
    occurred_at: str
    source: str


def get_connection():
    connection = connect_database()
    try:
        yield connection
    finally:
        connection.close()


def _clean_text(value: str) -> str:
    return value.strip()


def _minor_amount(amount: Decimal, minor_unit: int) -> int:
    try:
        scaled = amount * (Decimal(10) ** minor_unit)
        integral = scaled.to_integral_exact()
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="Importe no válido") from None
    if scaled != integral:
        raise HTTPException(
            status_code=422,
            detail=f"El importe admite como máximo {minor_unit} decimales",
        )
    result = int(integral)
    if result <= 0 or result > 9_000_000_000_000_000:
        raise HTTPException(status_code=422, detail="Importe fuera del rango permitido")
    return result


def _iso_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="occurred_at debe incluir zona horaria, por ejemplo Z o +01:00",
        )
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.get("/currencies")
def list_currencies(connection: sqlite3.Connection = Depends(get_connection)):
    return [dict(row) for row in FinanceRepository(connection).list_currencies()]


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, connection: sqlite3.Connection = Depends(get_connection)):
    repository = FinanceRepository(connection)
    name = _clean_text(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="El nombre de la cuenta no puede estar vacío")
    if repository.get_currency(payload.currency_code) is None:
        raise HTTPException(status_code=422, detail="Moneda no soportada")
    account_id = str(uuid4())
    try:
        repository.create_account(
            account_id,
            name,
            payload.account_type,
            payload.currency_code,
            _clean_text(payload.institution) or None if payload.institution else None,
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        raise HTTPException(status_code=409, detail="No se pudo crear la cuenta") from None
    row = repository.get_account(account_id)
    return dict(row)


@router.get("/accounts")
def list_accounts(
    include_inactive: bool = False,
    connection: sqlite3.Connection = Depends(get_connection),
):
    rows = FinanceRepository(connection).list_accounts(include_inactive)
    return [dict(row) for row in rows]


@router.get("/accounts/{account_id}")
def get_account(account_id: str, connection: sqlite3.Connection = Depends(get_connection)):
    row = FinanceRepository(connection).get_account(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return dict(row)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, connection: sqlite3.Connection = Depends(get_connection)):
    repository = FinanceRepository(connection)
    name = _clean_text(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="El nombre de la categoría no puede estar vacío")
    if payload.parent_id:
        parent = repository.get_active_category(payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=422, detail="Categoría padre no encontrada o inactiva")
        if parent["category_type"] != payload.category_type:
            raise HTTPException(status_code=422, detail="La categoría padre debe ser del mismo tipo")
    category_id = str(uuid4())
    try:
        repository.create_category(category_id, name, payload.category_type, payload.parent_id)
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        raise HTTPException(status_code=409, detail="La categoría ya existe o no es válida") from None
    row = repository.get_active_category(category_id)
    return {
        "id": category_id,
        "name": name,
        "category_type": row["category_type"],
        "parent_id": payload.parent_id,
    }


@router.get("/categories")
def list_categories(
    category_type: CategoryType | None = None,
    include_inactive: bool = False,
    connection: sqlite3.Connection = Depends(get_connection),
):
    rows = FinanceRepository(connection).list_categories(category_type, include_inactive)
    return [dict(row) for row in rows]


@router.post("/transactions", status_code=status.HTTP_201_CREATED, response_model=TransactionView)
def create_transaction(
    payload: TransactionCreate,
    connection: sqlite3.Connection = Depends(get_connection),
):
    repository = FinanceRepository(connection)
    account = repository.get_active_account_currency(payload.account_id)
    if account is None or not account["is_active"]:
        raise HTTPException(status_code=422, detail="Cuenta no encontrada o inactiva")
    currency = repository.get_currency(payload.currency_code)
    if currency is None:
        raise HTTPException(status_code=422, detail="Moneda no soportada")
    if payload.currency_code != account["currency_code"]:
        raise HTTPException(
            status_code=422,
            detail="La moneda de la transacción debe coincidir con la moneda de la cuenta",
        )
    if payload.transaction_type in ("income", "expense"):
        if payload.category_id is None:
            raise HTTPException(status_code=422, detail="Ingresos y gastos requieren categoría")
        category = repository.get_active_category(payload.category_id)
        if category is None or category["category_type"] != payload.transaction_type:
            raise HTTPException(status_code=422, detail="Categoría no válida para el tipo de transacción")
    elif payload.category_id is not None:
        raise HTTPException(status_code=422, detail="Transferencias y ajustes no admiten categoría en esta versión")

    amount_minor = _minor_amount(payload.amount, currency["minor_unit"])
    transaction_id = str(uuid4())
    occurred_at = _iso_datetime(payload.occurred_at)
    description = _clean_text(payload.description) or None if payload.description else None
    source = _clean_text(payload.source)
    try:
        repository.create_transaction(
            transaction_id,
            payload.account_id,
            payload.category_id,
            payload.transaction_type,
            amount_minor,
            payload.currency_code,
            description,
            occurred_at,
            source,
            payload.external_reference,
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Transacción duplicada o referencia relacionada no válida",
        ) from None
    return {
        "id": transaction_id,
        "account_id": payload.account_id,
        "category_id": payload.category_id,
        "transaction_type": payload.transaction_type,
        "amount": str(payload.amount),
        "currency_code": payload.currency_code,
        "description": description,
        "occurred_at": occurred_at,
        "source": source,
    }


@router.get("/transactions")
def list_transactions(
    account_id: str | None = None,
    transaction_type: TransactionType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_connection),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from no puede ser posterior a date_to")
    rows = FinanceRepository(connection).list_transactions(
        account_id=account_id,
        transaction_type=transaction_type,
        occurred_at_from=_iso_datetime(date_from) if date_from else None,
        occurred_at_to=_iso_datetime(date_to) if date_to else None,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": row["id"],
            "account_id": row["account_id"],
            "category_id": row["category_id"],
            "transaction_type": row["transaction_type"],
            "amount_minor": row["amount_minor"],
            "currency_code": row["currency_code"],
            "description": row["description"],
            "occurred_at": row["occurred_at"],
            "source": row["source"],
        }
        for row in rows
    ]


def initialize_finance_database() -> None:
    """Apply pending schema migrations when the FastAPI application starts."""
    migrate_database()
