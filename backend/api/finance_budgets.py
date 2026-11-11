"""Monthly category budgets and actual spending progress.

Amounts remain in the original transaction currency; no FX conversion is inferred.
The reporting month uses UTC calendar boundaries.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

try:
    from backend.api.finance import _minor_amount, get_connection
    from backend.repositories.finance_repository import FinanceRepository
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from api.finance import _minor_amount, get_connection
    from repositories.finance_repository import FinanceRepository


router = APIRouter(prefix="/api/finance", tags=["personal-finance"])


class MonthlyBudgetCreate(BaseModel):
    category_id: str
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=4)


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = f"{year:04d}-{month:02d}-01T00:00:00Z"
    if month == 12:
        end = f"{year + 1:04d}-01-01T00:00:00Z"
    else:
        end = f"{year:04d}-{month + 1:02d}-01T00:00:00Z"
    return start, end


@router.post("/budgets", status_code=status.HTTP_201_CREATED)
def create_monthly_budget(
    payload: MonthlyBudgetCreate,
    connection: sqlite3.Connection = Depends(get_connection),
):
    repository = FinanceRepository(connection)
    category = repository.get_expense_category(payload.category_id)
    if category is None or not category["is_active"]:
        raise HTTPException(status_code=422, detail="Categoría no encontrada o inactiva")
    if category["category_type"] != "expense":
        raise HTTPException(status_code=422, detail="El presupuesto requiere una categoría de gasto")

    currency = repository.get_currency(payload.currency_code)
    if currency is None:
        raise HTTPException(status_code=422, detail="Moneda no soportada")

    amount_minor = _minor_amount(payload.amount, currency["minor_unit"])
    budget_id = str(uuid4())
    try:
        repository.create_monthly_budget(
            budget_id, payload.category_id, payload.currency_code,
            payload.year, payload.month, amount_minor,
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya existe un presupuesto para esta categoría, moneda y mes",
        ) from None

    return {
        "id": budget_id,
        "category_id": payload.category_id,
        "currency_code": payload.currency_code,
        "year": payload.year,
        "month": payload.month,
        "amount_minor": amount_minor,
    }


@router.get("/budgets/progress")
def monthly_budget_progress(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    connection: sqlite3.Connection = Depends(get_connection),
):
    start, end = _month_bounds(year, month)
    rows = FinanceRepository(connection).monthly_budget_progress(year, month, start, end)

    budgets = []
    for row in rows:
        remaining = row["amount_minor"] - row["spent_minor"]
        utilization = round(row["spent_minor"] * 100 / row["amount_minor"], 2)
        budgets.append({
            "id": row["id"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
            "currency_code": row["currency_code"],
            "year": row["budget_year"],
            "month": row["budget_month"],
            "budget_minor": row["amount_minor"],
            "spent_minor": row["spent_minor"],
            "remaining_minor": remaining,
            "utilization_percent": utilization,
            "expense_count": row["expense_count"],
            "status": "over_budget" if remaining < 0 else "within_budget",
        })

    return {
        "period": {"year": year, "month": month, "timezone": "UTC"},
        "currency_basis": "original_transaction_currency",
        "fx_applied": False,
        "budgets": budgets,
    }
