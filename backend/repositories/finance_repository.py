"""SQLite repository for personal-finance persistence.

This module owns SQL for accounts, categories, currencies and transactions.
It deliberately does not own HTTP validation or transaction commits: those
remain at the application boundary so callers can compose operations safely.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Sequence


class FinanceRepository:
    """Encapsulate personal-finance SQL behind a small persistence interface."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self._connection.execute(sql, params).fetchone()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self._connection.execute(sql, params).fetchall()

    def list_currencies(self) -> list[sqlite3.Row]:
        return self._all(
            "SELECT code, name, minor_unit FROM currencies ORDER BY code"
        )

    def get_currency(self, code: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT code, minor_unit FROM currencies WHERE code = ?", (code,)
        )

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
            "SELECT currency_code, is_active FROM accounts WHERE id = ?",
            (account_id,),
        )

    def list_accounts(self, include_inactive: bool = False) -> list[sqlite3.Row]:
        query = "SELECT * FROM accounts"
        if not include_inactive:
            query += " WHERE is_active = 1"
        query += " ORDER BY name COLLATE NOCASE, id"
        return self._all(query)

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
        query += " ORDER BY category_type, name COLLATE NOCASE, id"
        return self._all(query, params)

    def create_transaction(
        self,
        transaction_id: str,
        account_id: str,
        category_id: str | None,
        transaction_type: str,
        amount_minor: int,
        currency_code: str,
        description: str | None,
        occurred_at: str,
        source: str,
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
        self,
        *,
        account_id: str | None = None,
        transaction_type: str | None = None,
        occurred_at_from: str | None = None,
        occurred_at_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
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
