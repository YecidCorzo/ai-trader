import unittest

from backend.infrastructure.database import apply_migrations, connect_database
from backend.repositories.finance_repository import FinanceRepository


class FinanceRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.repository = FinanceRepository(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_account_category_and_transaction_persistence(self):
        self.assertEqual(
            {row["code"] for row in self.repository.list_currencies()},
            {"SEK", "EUR", "USD", "COP"},
        )
        self.repository.create_account(
            "account-1", "Everyday", "bank", "SEK", None
        )
        self.repository.create_category(
            "category-1", "Food", "expense", None
        )
        self.repository.create_transaction(
            "transaction-1", "account-1", "category-1", "expense",
            12550, "SEK", "Groceries", "2026-11-05T12:00:00Z",
            "manual", None,
        )
        self.connection.commit()

        account = self.repository.get_account("account-1")
        category = self.repository.get_category("category-1")
        transactions = self.repository.list_transactions(
            account_id="account-1",
            transaction_type="expense",
            occurred_at_from="2026-11-01T00:00:00Z",
            occurred_at_to="2026-11-30T23:59:59Z",
        )
        self.assertEqual(account["currency_code"], "SEK")
        self.assertEqual(category["name"], "Food")
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["amount_minor"], 12550)

    def test_reporting_queries_keep_currency_and_category_boundaries(self):
        self.repository.create_account(
            "account-1", "Everyday", "bank", "SEK", None
        )
        self.repository.create_category(
            "food", "Food", "expense", None
        )
        self.repository.create_category(
            "salary", "Salary", "income", None
        )
        self.repository.create_transaction(
            "expense-1", "account-1", "food", "expense", 2500,
            "SEK", None, "2026-11-05T12:00:00Z", "manual", None,
        )
        self.repository.create_transaction(
            "income-1", "account-1", "salary", "income", 500000,
            "SEK", None, "2026-11-01T12:00:00Z", "manual", None,
        )
        self.connection.commit()

        totals = self.repository.cash_flow_totals(
            "2026-11-01T00:00:00Z", "2026-11-30T23:59:59Z", "account-1"
        )
        expenses = self.repository.expenses_by_category(
            "2026-11-01T00:00:00Z", "2026-11-30T23:59:59Z", "account-1"
        )
        self.assertEqual(totals[0]["income_minor"], 500000)
        self.assertEqual(totals[0]["expense_minor"], 2500)
        self.assertEqual(expenses[0]["category_name"], "Food")
        self.assertEqual(expenses[0]["expense_minor"], 2500)

    def test_filter_values_are_bound_parameters_not_sql_fragments(self):
        self.repository.create_account(
            "account-safe", "Safe", "bank", "SEK", None
        )
        self.repository.create_category(
            "category-safe", "Food", "expense", None
        )
        self.repository.create_transaction(
            "transaction-safe", "account-safe", "category-safe", "expense",
            100, "SEK", None, "2026-11-05T12:00:00Z", "manual", None,
        )
        self.connection.commit()

        injected = self.repository.list_transactions(
            account_id="' OR 1=1 --",
            transaction_type="expense",
        )
        self.assertEqual(injected, [])
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
