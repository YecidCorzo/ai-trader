import unittest
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from backend.api.finance import AccountCreate, CategoryCreate, TransactionCreate, create_account, create_category, create_transaction
from backend.api.finance_reports import cash_flow_report
from backend.infrastructure.database import apply_migrations, connect_database


class CashFlowReportTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.account_id = create_account(
            AccountCreate(name="Everyday", account_type="bank", currency_code="SEK"),
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

    def add_transaction(self, kind, amount, category_id, date):
        return create_transaction(
            TransactionCreate(
                account_id=self.account_id,
                category_id=category_id,
                transaction_type=kind,
                amount=Decimal(amount),
                currency_code="SEK",
                occurred_at=date,
            ),
            self.connection,
        )

    def test_report_aggregates_income_expenses_and_category_in_minor_units(self):
        self.add_transaction("income", "30000.00", self.income_category, datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.add_transaction("expense", "125.50", self.expense_category, datetime(2026, 11, 2, tzinfo=timezone.utc))
        result = cash_flow_report(connection=self.connection)
        self.assertEqual(result["totals"], [{
            "currency_code": "SEK",
            "income_minor": 3000000,
            "expense_minor": 12550,
            "net_minor": 2987450,
            "transaction_count": 2,
        }])
        self.assertEqual(result["expenses_by_category"][0]["category_name"], "Food")
        self.assertFalse(result["fx_applied"])

    def test_report_filters_by_date_range(self):
        self.add_transaction("income", "100.00", self.income_category, datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.add_transaction("expense", "20.00", self.expense_category, datetime(2026, 11, 2, tzinfo=timezone.utc))
        result = cash_flow_report(
            date_from=datetime(2026, 11, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 11, 30, tzinfo=timezone.utc),
            connection=self.connection,
        )
        self.assertEqual(result["totals"][0]["income_minor"], 0)
        self.assertEqual(result["totals"][0]["expense_minor"], 2000)

    def test_rejects_naive_dates_and_reversed_ranges(self):
        with self.assertRaises(HTTPException):
            cash_flow_report(date_from=datetime(2026, 11, 1), connection=self.connection)
        with self.assertRaises(HTTPException):
            cash_flow_report(
                date_from=datetime(2026, 11, 2, tzinfo=timezone.utc),
                date_to=datetime(2026, 11, 1, tzinfo=timezone.utc),
                connection=self.connection,
            )


if __name__ == "__main__":
    unittest.main()
