import unittest
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from backend.api.finance import (
    AccountCreate,
    CategoryCreate,
    TransactionCreate,
    create_account,
    create_category,
    create_transaction,
    list_currencies,
    list_transactions,
)
from backend.infrastructure.database import apply_migrations, connect_database


class FinanceApiTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)

    def tearDown(self):
        self.connection.close()

    def create_account(self, currency="SEK"):
        result = create_account(
            AccountCreate(name="Main account", account_type="bank", currency_code=currency),
            self.connection,
        )
        return result["id"]

    def create_category(self, category_type="expense"):
        result = create_category(
            CategoryCreate(name="Groceries", category_type=category_type),
            self.connection,
        )
        return result["id"]

    def test_currencies_endpoint_returns_seeded_currencies(self):
        rows = list_currencies(self.connection)
        self.assertEqual({row["code"] for row in rows}, {"SEK", "EUR", "USD", "COP"})

    def test_create_and_list_account(self):
        account_id = self.create_account("COP")
        rows = self.connection.execute("SELECT * FROM accounts").fetchall()
        account = next(dict(row) for row in rows if row["id"] == account_id)
        self.assertEqual(account["currency_code"], "COP")

    def test_reject_unsupported_currency(self):
        with self.assertRaises(HTTPException) as raised:
            create_account(
                AccountCreate(name="Unknown", account_type="bank", currency_code="XXX"),
                self.connection,
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_create_expense_stores_integer_minor_units_and_original_currency(self):
        account_id = self.create_account("SEK")
        category_id = self.create_category("expense")
        result = create_transaction(
            TransactionCreate(
                account_id=account_id,
                category_id=category_id,
                transaction_type="expense",
                amount=Decimal("125.50"),
                currency_code="SEK",
                description="Food",
                occurred_at=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc),
            ),
            self.connection,
        )
        row = self.connection.execute(
            "SELECT amount_minor, currency_code FROM transactions WHERE id = ?",
            (result["id"],),
        ).fetchone()
        self.assertEqual((row["amount_minor"], row["currency_code"]), (12550, "SEK"))

    def test_reject_amount_with_too_many_decimal_places(self):
        account_id = self.create_account("SEK")
        category_id = self.create_category()
        with self.assertRaises(HTTPException) as raised:
            create_transaction(
                TransactionCreate(
                    account_id=account_id,
                    category_id=category_id,
                    transaction_type="expense",
                    amount=Decimal("12.345"),
                    currency_code="SEK",
                    occurred_at=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc),
                ),
                self.connection,
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_reject_category_type_mismatch(self):
        account_id = self.create_account()
        income_category = self.create_category("income")
        with self.assertRaises(HTTPException) as raised:
            create_transaction(
                TransactionCreate(
                    account_id=account_id,
                    category_id=income_category,
                    transaction_type="expense",
                    amount=Decimal("12.00"),
                    currency_code="SEK",
                    occurred_at=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc),
                ),
                self.connection,
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_reject_naive_datetime(self):
        account_id = self.create_account()
        category_id = self.create_category()
        with self.assertRaises(HTTPException) as raised:
            create_transaction(
                TransactionCreate(
                    account_id=account_id,
                    category_id=category_id,
                    transaction_type="expense",
                    amount=Decimal("12.00"),
                    currency_code="SEK",
                    occurred_at=datetime(2026, 11, 11, 10, 0),
                ),
                self.connection,
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_list_transactions_filters_by_account(self):
        account_id = self.create_account()
        category_id = self.create_category()
        create_transaction(
            TransactionCreate(
                account_id=account_id,
                category_id=category_id,
                transaction_type="expense",
                amount=Decimal("12.00"),
                currency_code="SEK",
                occurred_at=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc),
            ),
            self.connection,
        )
        rows = list_transactions(account_id=account_id, connection=self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_minor"], 1200)


if __name__ == "__main__":
    unittest.main()
