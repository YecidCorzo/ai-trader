import unittest
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.infrastructure.database import apply_migrations, connect_database
from backend.main import app
from backend.security.principal import VerifiedPrincipal
from backend.services.paper_price import PriceQuote
from backend.api.paper_routes import (
    get_db_connection,
    get_price_provider,
)
from backend.security.dependencies import get_verified_principal


class FakePriceProvider:
    def __init__(self):
        self.price = Decimal("100")

    def get_price(self, symbol):
        return PriceQuote(
            symbol=symbol,
            price=self.price,
            source="test_public_quote",
            retrieved_at=datetime.now(timezone.utc),
        )


class PaperRoutesTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.principal = VerifiedPrincipal("https://issuer.example", "paper-user-a")
        self.provider = FakePriceProvider()

        def override_connection():
            yield self.connection

        app.dependency_overrides[get_db_connection] = override_connection
        app.dependency_overrides[get_verified_principal] = lambda: self.principal
        app.dependency_overrides[get_price_provider] = lambda: self.provider
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.connection.close()

    def create_account(self, key="create-account"):
        response = self.client.post(
            "/api/paper/accounts",
            json={
                "name": "Test PAPER",
                "quote_currency": "USDT",
                "opening_capital": "10000",
                "idempotency_key": key,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["account"]["id"]

    def test_create_list_and_read_owner_scoped_paper_account(self):
        account_id = self.create_account()
        listed = self.client.get("/api/paper/accounts")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["accounts"]), 1)
        self.assertEqual(listed.json()["accounts"][0]["balance"], "10000.00000000")

        detail = self.client.get(f"/api/paper/accounts/{account_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["mode"], "paper")
        self.assertEqual(detail.json()["balance"], "10000.00000000")
        self.assertEqual(detail.json()["equity"], "10000.00000000")
        self.assertEqual(detail.json()["free_cash"], "10000.00000000")
        self.assertFalse(detail.json()["live_trading_authorized"])

        self.principal = VerifiedPrincipal("https://issuer.example", "paper-user-b")
        hidden = self.client.get(f"/api/paper/accounts/{account_id}")
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(self.client.get("/api/paper/accounts").json()["accounts"], [])

    def test_open_close_and_list_paper_trade_uses_engine_costs(self):
        account_id = self.create_account()
        opened = self.client.post(
            f"/api/paper/accounts/{account_id}/trades",
            json={
                "symbol": "SOLUSDT",
                "strategy": "AdvancedStrategy",
                "side": "LONG",
                "stop_price": "95",
                "idempotency_key": "open-sol-1",
            },
        )
        self.assertEqual(opened.status_code, 201, opened.text)
        trade = opened.json()["trade"]
        self.assertGreater(Decimal(trade["entry_price"]), Decimal("100"))
        self.assertGreater(Decimal(trade["entry_fee"]), Decimal("0"))
        self.assertGreater(Decimal(trade["quantity"]), Decimal("0"))

        self.provider.price = Decimal("110")
        closed = self.client.post(
            f"/api/paper/accounts/{account_id}/trades/{trade['id']}/close",
            json={"exit_reason": "manual_test_close"},
        )
        self.assertEqual(closed.status_code, 200, closed.text)
        closed_trade = closed.json()["trade"]
        self.assertEqual(closed_trade["status"], "CLOSED")
        self.assertLess(Decimal(closed_trade["exit_price"]), Decimal("110"))
        self.assertGreater(Decimal(closed_trade["exit_fee"]), Decimal("0"))

        listed = self.client.get(f"/api/paper/accounts/{account_id}/trades?status=CLOSED")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["trades"]), 1)

    def test_halt_reset_and_account_events_are_persisted(self):
        account_id = self.create_account()
        halted = self.client.post(
            f"/api/paper/accounts/{account_id}/halt",
            json={"reason": "operator test"},
        )
        self.assertEqual(halted.status_code, 200, halted.text)
        self.assertTrue(halted.json()["halted"])

        reset = self.client.post(
            f"/api/paper/accounts/{account_id}/reset",
            json={"confirmed": True},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertFalse(reset.json()["halted"])

        events = self.client.get(f"/api/paper/accounts/{account_id}/events")
        self.assertEqual(events.status_code, 200)
        types = [event["event_type"] for event in events.json()["trade_events"]]
        self.assertIn("CIRCUIT_BREAKER_HALTED", types)
        self.assertIn("CIRCUIT_BREAKER_RESET", types)

    def test_paper_routes_reject_missing_bearer_credentials(self):
        app.dependency_overrides.pop(get_verified_principal, None)
        response = self.client.get("/api/paper/accounts")
        self.assertEqual(response.status_code, 401)

    def test_funding_is_owner_scoped_and_cannot_withdraw_committed_cash(self):
        account_id = self.create_account()
        response = self.client.post(
            f"/api/paper/accounts/{account_id}/funding",
            json={
                "event_type": "WITHDRAWAL",
                "amount": "10001",
                "idempotency_key": "withdraw-too-much",
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
