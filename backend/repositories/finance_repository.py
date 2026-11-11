"""SQLite repository for personal-finance persistence.

All personal-finance SQL lives here. HTTP validation and transaction commits
remain at the API boundary so callers can compose repository operations safely.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Sequence


class FinanceRepository:
    """Encapsulate personal-finance SQL behind a persistence interface."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self._connection.execute(sql, params).fetchone()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self._connection.execute(sql, params).fetchall()

    def list_currencies(self) -> list[sqlite3.Row]:
        return self._all("SELECT code, name, minor_unit FROM currencies ORDER BY code")

    def get_currency(self, code: str) -> sqlite3.Row | None:
        return self._one("SELECT code, minor_unit FROM currencies WHERE code = ?", (code,))

    def create_account(
        self, account_id: str, name: str, account_type: str,
        currency_code: str, institution: str | None,
    ) -> None:
        self._connection.execute(
            """INSERT INTO accounts (id, name, account_type, currency_code, institution)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, name, account_type, currency_code, institution),
        )

    def get_account(self, account_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def get_active_account_currency(self, account_id: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT currency_code, is_active FROM accounts WHERE id = ?", (account_id,)
        )

    def list_accounts(self, include_inactive: bool = False) -> list[sqlite3.Row]:
        query = "SELECT * FROM accounts"
        if not include_inactive:
            query += " WHERE is_active = 1"
        return self._all(query + " ORDER BY name COLLATE NOCASE, id")

    def get_category(self, category_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM categories WHERE id = ?", (category_id,))

    def get_active_category(self, category_id: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT category_type FROM categories WHERE id = ? AND is_active = 1",
            (category_id,),
        )

    def create_category(
        self, category_id: str, name: str, category_type: str, parent_id: str | None,
    ) -> None:
        self._connection.execute(
            """INSERT INTO categories (id, name, category_type, parent_id)
               VALUES (?, ?, ?, ?)""",
            (category_id, name, category_type, parent_id),
        )

    def list_categories(
        self, category_type: str | None = None, include_inactive: bool = False,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if category_type:
            clauses.append("category_type = ?")
            params.append(category_type)
        if not include_inactive:
            clauses.append("is_active = 1")
        query = "SELECT * FROM categories"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return self._all(query + " ORDER BY category_type, name COLLATE NOCASE, id", params)

    def create_transaction(
        self, transaction_id: str, account_id: str, category_id: str | None,
        transaction_type: str, amount_minor: int, currency_code: str,
        description: str | None, occurred_at: str, source: str,
        external_reference: str | None,
    ) -> None:
        self._connection.execute(
            """INSERT INTO transactions
               (id, account_id, category_id, transaction_type, amount_minor,
                currency_code, description, occurred_at, source, external_reference)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                transaction_id, account_id, category_id, transaction_type,
                amount_minor, currency_code, description, occurred_at, source,
                external_reference,
            ),
        )

    def list_transactions(
        self, *, account_id: str | None = None,
        transaction_type: str | None = None,
        occurred_at_from: str | None = None, occurred_at_to: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if account_id:
            clauses.append("account_id = ?")
            params.append(account_id)
        if transaction_type:
            clauses.append("transaction_type = ?")
            params.append(transaction_type)
        if occurred_at_from:
            clauses.append("occurred_at >= ?")
            params.append(occurred_at_from)
        if occurred_at_to:
            clauses.append("occurred_at <= ?")
            params.append(occurred_at_to)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self._all(
            """SELECT id, account_id, category_id, transaction_type, amount_minor,
                      currency_code, description, occurred_at, source
               FROM transactions""" + where +
            " ORDER BY occurred_at DESC, id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )

    def cash_flow_totals(
        self, date_from: str | None, date_to: str | None, account_id: str | None,
    ) -> list[sqlite3.Row]:
        clauses = ["transaction_type IN ('income', 'expense')"]
        params: list[Any] = []
        if date_from:
            clauses.append("occurred_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("occurred_at <= ?")
            params.append(date_to)
        if account_id:
            clauses.append("account_id = ?")
            params.append(account_id)
        return self._all(
            """SELECT currency_code,
                      SUM(CASE WHEN transaction_type = 'income' THEN amount_minor ELSE 0 END) AS income_minor,
                      SUM(CASE WHEN transaction_type = 'expense' THEN amount_minor ELSE 0 END) AS expense_minor,
                      COUNT(*) AS transaction_count
               FROM transactions WHERE """ + " AND ".join(clauses) +
            " GROUP BY currency_code ORDER BY currency_code",
            params,
        )

    def expenses_by_category(
        self, date_from: str | None, date_to: str | None, account_id: str | None,
    ) -> list[sqlite3.Row]:
        clauses = ["t.transaction_type = 'expense'"]
        params: list[Any] = []
        if date_from:
            clauses.append("t.occurred_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("t.occurred_at <= ?")
            params.append(date_to)
        if account_id:
            clauses.append("t.account_id = ?")
            params.append(account_id)
        return self._all(
            """SELECT t.currency_code, t.category_id, c.name AS category_name,
                      SUM(t.amount_minor) AS expense_minor, COUNT(*) AS transaction_count
               FROM transactions t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE """ + " AND ".join(clauses) +
            """ GROUP BY t.currency_code, t.category_id, c.name
                ORDER BY t.currency_code, expense_minor DESC""",
            params,
        )

    def get_account_with_currency(self, account_id: str) -> sqlite3.Row | None:
        return self._one(
            """SELECT a.currency_code, a.is_active, c.minor_unit
               FROM accounts a JOIN currencies c ON c.code = a.currency_code
               WHERE a.id = ?""",
            (account_id,),
        )

    def upsert_opening_balance(
        self, account_id: str, amount_minor: int, currency_code: str, as_of: str,
    ) -> None:
        self._connection.execute(
            """INSERT INTO account_opening_balances (account_id, amount_minor, currency_code, as_of)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET
                   amount_minor = excluded.amount_minor,
                   currency_code = excluded.currency_code,
                   as_of = excluded.as_of,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (account_id, amount_minor, currency_code, as_of),
        )

    def list_active_accounts_with_opening_balances(self) -> list[sqlite3.Row]:
        return self._all(
            """SELECT a.id, a.name, a.account_type, a.currency_code,
                      o.amount_minor AS opening_balance_minor, o.as_of AS opening_balance_as_of
               FROM accounts a
               LEFT JOIN account_opening_balances o ON o.account_id = a.id
               WHERE a.is_active = 1
               ORDER BY a.currency_code, a.name COLLATE NOCASE, a.id"""
        )

    def account_movements_after(self, account_id: str, as_of: str) -> sqlite3.Row:
        return self._one(
            """SELECT
                 COALESCE(SUM(CASE WHEN transaction_type = 'income' THEN amount_minor ELSE 0 END), 0) AS income_minor,
                 COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount_minor ELSE 0 END), 0) AS expense_minor,
                 SUM(CASE WHEN transaction_type IN ('transfer', 'adjustment') THEN 1 ELSE 0 END) AS unsupported_count
               FROM transactions WHERE account_id = ? AND occurred_at > ?""",
            (account_id, as_of),
        )

    def get_expense_category(self, category_id: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT category_type, is_active FROM categories WHERE id = ?",
            (category_id,),
        )

    def create_monthly_budget(
        self, budget_id: str, category_id: str, currency_code: str,
        year: int, month: int, amount_minor: int,
    ) -> None:
        self._connection.execute(
            """INSERT INTO monthly_category_budgets
               (id, category_id, currency_code, budget_year, budget_month, amount_minor)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (budget_id, category_id, currency_code, year, month, amount_minor),
        )

    def monthly_budget_progress(
        self, year: int, month: int, start: str, end: str,
    ) -> list[sqlite3.Row]:
        return self._all(
            """SELECT b.id, b.category_id, c.name AS category_name,
                      b.currency_code, b.budget_year, b.budget_month, b.amount_minor,
                      COALESCE(SUM(t.amount_minor), 0) AS spent_minor,
                      COUNT(t.id) AS expense_count
               FROM monthly_category_budgets b
               JOIN categories c ON c.id = b.category_id
               LEFT JOIN transactions t
                 ON t.category_id = b.category_id
                AND t.currency_code = b.currency_code
                AND t.transaction_type = 'expense'
                AND t.occurred_at >= ? AND t.occurred_at < ?
               WHERE b.budget_year = ? AND b.budget_month = ?
               GROUP BY b.id, b.category_id, c.name, b.currency_code,
                        b.budget_year, b.budget_month, b.amount_minor
               ORDER BY b.currency_code, c.name COLLATE NOCASE, b.id""",
            (start, end, year, month),
        )
