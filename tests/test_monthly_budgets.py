import unittest
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from backend.api.finance import (
    AccountCreate, CategoryCreate, TransactionCreate,
    create_account, create_category, create_transaction,
)
from backend.api.finance_budgets import (
    MonthlyBudgetCreate, create_monthly_budget, monthly_budget_progress,
)
from backend.infrastructure.database import apply_migrations, connect_database


class MonthlyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.account_id = create_account(
            AccountCreate(name="Everyday", account_type="bank", currency_code="SEK"),
            self.connection,
        )["id"]
        self.food_id = create_category(
            CategoryCreate(name="Food", category_type="expense"), self.connection
        )["id"]
        self.salary_id = create_category(
            CategoryCreate(name="Salary", category_type="income"), self.connection
        )["id"]

    def tearDown(self):
        self.connection.close()

    def create_budget(self, category_id=None, amount="500.00", currency="SEK", year=2026, month=11):
        return create_monthly_budget(
            MonthlyBudgetCreate(
                category_id=category_id or self.food_id,
                currency_code=currency,
                year=year,
                month=month,
                amount=Decimal(amount),
            ),
            self.connection,
        )

    def add_expense(self, amount, date, category_id=None, currency="SEK"):
        return create_transaction(
            TransactionCreate(
                account_id=self.account_id,
                category_id=category_id or self.food_id,
                transaction_type="expense",
                amount=Decimal(amount),
                currency_code=currency,
                occurred_at=date,
            ),
            self.connection,
        )

    def test_progress_aggregates_monthly_expenses_and_reports_remaining(self):
        self.create_budget()
        self.add_expense("125.50", datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.add_expense("25.00", datetime(2026, 11, 20, tzinfo=timezone.utc))
        result = monthly_budget_progress(2026, 11, self.connection)
        budget = result["budgets"][0]
        self.assertEqual(budget["budget_minor"], 50000)
        self.assertEqual(budget["spent_minor"], 15050)
        self.assertEqual(budget["remaining_minor"], 34950)
        self.assertEqual(budget["expense_count"], 2)
        self.assertEqual(budget["status"], "within_budget")
        self.assertFalse(result["fx_applied"])

    def test_over_budget_is_reported_without_clamping_remaining(self):
        self.create_budget(amount="100.00")
        self.add_expense("120.00", datetime(2026, 11, 5, tzinfo=timezone.utc))
        budget = monthly_budget_progress(2026, 11, self.connection)["budgets"][0]
        self.assertEqual(budget["remaining_minor"], -2000)
        self.assertEqual(budget["status"], "over_budget")
        self.assertEqual(budget["utilization_percent"], 120.0)

    def test_excludes_other_months_and_other_categories(self):
        self.create_budget()
        rent_id = create_category(
            CategoryCreate(name="Rent", category_type="expense"), self.connection
        )["id"]
        self.add_expense("10.00", datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc))
        self.add_expense("20.00", datetime(2026, 11, 2, tzinfo=timezone.utc), category_id=self.food_id)
        self.add_expense("99.00", datetime(2026, 11, 3, tzinfo=timezone.utc), category_id=rent_id)
        result = monthly_budget_progress(2026, 11, self.connection)
        self.assertEqual(len(result["budgets"]), 1)
        self.assertEqual(result["budgets"][0]["spent_minor"], 2000)

    def test_rejects_income_category(self):
        with self.assertRaises(HTTPException) as raised:
            self.create_budget(category_id=self.salary_id)
        self.assertEqual(raised.exception.status_code, 422)

    def test_duplicate_budget_returns_conflict(self):
        self.create_budget()
        with self.assertRaises(HTTPException) as raised:
            self.create_budget()
        self.assertEqual(raised.exception.status_code, 409)

    def test_rejects_amount_with_too_many_decimals(self):
        with self.assertRaises(HTTPException) as raised:
            self.create_budget(amount="10.123")
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
