"""Read-only cash-flow reporting for manually recorded finance transactions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

try:
    from backend.api.finance import get_connection
    from backend.repositories.finance_repository import FinanceRepository
except ImportError:  # Support uvicorn with backend/ as the app directory.
    from api.finance import get_connection
    from repositories.finance_repository import FinanceRepository


router = APIRouter(prefix="/api/finance/reports", tags=["personal-finance"])


def _utc_filter(value: datetime | None, field: str) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail=f"{field} debe incluir zona horaria")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.get("/cash-flow")
def cash_flow_report(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account_id: str | None = None,
    connection: sqlite3.Connection = Depends(get_connection),
):
    """Summarize income and expenses by original currency; no FX is inferred."""
    start = _utc_filter(date_from, "date_from")
    end = _utc_filter(date_to, "date_to")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="date_from no puede ser posterior a date_to")

    repository = FinanceRepository(connection)
    totals = repository.cash_flow_totals(start, end, account_id)
    expenses = repository.expenses_by_category(start, end, account_id)

    return {
        "period": {"date_from": start, "date_to": end},
        "account_id": account_id,
        "currency_basis": "original_transaction_currency",
        "fx_applied": False,
        "totals": [
            {
                "currency_code": row["currency_code"],
                "income_minor": row["income_minor"],
                "expense_minor": row["expense_minor"],
                "net_minor": row["income_minor"] - row["expense_minor"],
                "transaction_count": row["transaction_count"],
            }
            for row in totals
        ],
        "expenses_by_category": [
            {
                "currency_code": row["currency_code"],
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "expense_minor": row["expense_minor"],
                "transaction_count": row["transaction_count"],
            }
            for row in expenses
        ],
    }
