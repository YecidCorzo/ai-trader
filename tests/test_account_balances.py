import unittest
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from backend.api.finance import AccountCreate, CategoryCreate, TransactionCreate, create_account, create_category, create_transaction
from backend.api.finance_balances import OpeningBalanceCreate, list_account_balances, set_opening_balance
from backend.infrastructure.database import apply_migrations, connect_database


class AccountBalanceTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.account_id = create_account(
            AccountCreate(name="Daily", account_type="bank", currency_code="SEK"),
            self.connection,
        )["id"]
        self.income_category = create_category(
            CategoryCreate(name="Salary", category_type="income"), self.connection
        )["id"]
        self.expense_category = create_category(
            CategoryCreate(name="Food", category_type="expense"), self.connection
        )["id"]

    def tearDown(self):
        self.connection.close()

    def test_missing_opening_balance_is_not_reported_as_zero(self):
        result = list_account_balances(self.connection)
        self.assertIsNone(result["accounts"][0]["balance_minor"])
        self.assertEqual(result["accounts"][0]["status"], "missing_opening_balance")

    def test_balance_uses_opening_balance_and_later_income_expenses(self):
        set_opening_balance(
            self.account_id,
            OpeningBalanceCreate(
                amount=Decimal("1000.00"),
                as_of=datetime(2026, 11, 1, tzinfo=timezone.utc),
            ),
            self.connection,
        )
        create_transaction(
            TransactionCreate(
                account_id=self.account_id, category_id=self.income_category,
                transaction_type="income", amount=Decimal("250.00"), currency_code="SEK",
                occurred_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
            ), self.connection,
        )
        create_transaction(
            TransactionCreate(
                account_id=self.account_id, category_id=self.expense_category,
                transaction_type="expense", amount=Decimal("75.50"), currency_code="SEK",
                occurred_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
            ), self.connection,
        )
        result = list_account_balances(self.connection)["accounts"][0]
        self.assertEqual(result["balance_minor"], 117450)
        self.assertEqual(result["status"], "complete")

    def test_transfer_or_adjustment_marks_balance_incomplete(self):
        set_opening_balance(
            self.account_id,
            OpeningBalanceCreate(
                amount=Decimal("100.00"),
                as_of=datetime(2026, 11, 1, tzinfo=timezone.utc),
            ),
            self.connection,
        )
        create_transaction(
            TransactionCreate(
                account_id=self.account_id, transaction_type="transfer",
                amount=Decimal("10.00"), currency_code="SEK",
                occurred_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
            ), self.connection,
        )
        result = list_account_balances(self.connection)["accounts"][0]
        self.assertIsNone(result["balance_minor"])
        self.assertEqual(result["status"], "incomplete_unsupported_transactions")
        self.assertEqual(result["unsupported_transaction_count"], 1)

    def test_rejects_naive_opening_balance_date(self):
        with self.assertRaises(HTTPException):
            set_opening_balance(
                self.account_id,
                OpeningBalanceCreate(amount=Decimal("10.00"), as_of=datetime(2026, 11, 1)),
                self.connection,
            )


if __name__ == "__main__":
    unittest.main()
