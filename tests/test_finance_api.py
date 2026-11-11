import unittest
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.finance import get_connection, router
from backend.infrastructure.database import apply_migrations, connect_database


class FinanceApiTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        app = FastAPI()
        app.include_router(router)

        def override_connection():
            yield self.connection

        app.dependency_overrides[get_connection] = override_connection
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.connection.close()

    def create_account(self, currency="SEK"):
        response = self.client.post(
            "/api/finance/accounts",
            json={
                "name": "Main account",
                "account_type": "bank",
                "currency_code": currency,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def create_category(self, category_type="expense"):
        response = self.client.post(
            "/api/finance/categories",
            json={"name": "Groceries", "category_type": category_type},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_currencies_endpoint_returns_seeded_currencies(self):
        response = self.client.get("/api/finance/currencies")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["code"] for row in response.json()}, {"SEK", "EUR", "USD", "COP"})

    def test_create_and_list_account(self):
        account_id = self.create_account("COP")
        response = self.client.get("/api/finance/accounts")
        self.assertEqual(response.status_code, 200)
        account = next(row for row in response.json() if row["id"] == account_id)
        self.assertEqual(account["currency_code"], "COP")

    def test_reject_unsupported_currency(self):
        response = self.client.post(
            "/api/finance/accounts",
            json={"name": "Unknown", "account_type": "bank", "currency_code": "XXX"},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_expense_stores_integer_minor_units_and_original_currency(self):
        account_id = self.create_account("SEK")
        category_id = self.create_category("expense")
        response = self.client.post(
            "/api/finance/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "transaction_type": "expense",
                "amount": "125.50",
                "currency_code": "SEK",
                "description": "Food",
                "occurred_at": "2026-11-11T10:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        row = self.connection.execute(
            "SELECT amount_minor, currency_code FROM transactions WHERE id = ?",
            (response.json()["id"],),
        ).fetchone()
        self.assertEqual((row["amount_minor"], row["currency_code"]), (12550, "SEK"))

    def test_reject_amount_with_too_many_decimal_places(self):
        account_id = self.create_account("SEK")
        category_id = self.create_category()
        response = self.client.post(
            "/api/finance/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "transaction_type": "expense",
                "amount": "12.345",
                "currency_code": "SEK",
                "occurred_at": "2026-11-11T10:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_reject_category_type_mismatch(self):
        account_id = self.create_account()
        income_category = self.create_category("income")
        response = self.client.post(
            "/api/finance/transactions",
            json={
                "account_id": account_id,
                "category_id": income_category,
                "transaction_type": "expense",
                "amount": "12.00",
                "currency_code": "SEK",
                "occurred_at": "2026-11-11T10:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_reject_naive_datetime(self):
        account_id = self.create_account()
        category_id = self.create_category()
        response = self.client.post(
            "/api/finance/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "transaction_type": "expense",
                "amount": "12.00",
                "currency_code": "SEK",
                "occurred_at": "2026-11-11T10:00:00",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_list_transactions_filters_by_account(self):
        account_id = self.create_account()
        category_id = self.create_category()
        created = self.client.post(
            "/api/finance/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "transaction_type": "expense",
                "amount": "12.00",
                "currency_code": "SEK",
                "occurred_at": "2026-11-11T10:00:00Z",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        listed = self.client.get("/api/finance/transactions", params={"account_id": account_id})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["amount_minor"], 1200)


if __name__ == "__main__":
    unittest.main()
