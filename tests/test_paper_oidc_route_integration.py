"""Route-level PAPER OIDC integration using ephemeral test keys and SQLite."""

import os
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import jwt
from jwt.exceptions import PyJWKClientConnectionError
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.paper_routes import get_price_provider
from backend.services.paper_price import PriceQuote
from backend.security.dependencies import clear_oidc_verifier_cache
from backend.security.oidc_verifier import _get_jwks_client


ISSUER = "https://paper-oidc.integration.test/"
AUDIENCE = "ai-trader-paper-integration"
JWKS_URL = "https://paper-oidc.integration.test/.well-known/jwks.json"
KEY_ID = "paper-integration-key"


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJwksClient:
    """Deterministic key resolver; JWT signature validation remains real."""

    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        header = jwt.get_unverified_header(token)
        if header.get("kid") != KEY_ID:
            raise ValueError("Unknown test signing key")
        return FakeSigningKey(self.public_key)



class FixedPriceProvider:
    """Fixed public-price substitute for deterministic route tests."""

    def get_price(self, symbol):
        return PriceQuote(
            symbol=symbol,
            price=Decimal("100"),
            source="fixed-route-test",
            retrieved_at=datetime.now(timezone.utc),
        )


class PaperOidcRouteIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "paper-oidc.sqlite3"
        self.env_patcher = patch.dict(os.environ, {
            "AI_TRADER_DB_PATH": str(self.db_path),
            "AI_TRADER_OIDC_ISSUER": ISSUER,
            "AI_TRADER_OIDC_AUDIENCE": AUDIENCE,
            "AI_TRADER_OIDC_JWKS_URL": JWKS_URL,
        })
        self.env_patcher.start()

        clear_oidc_verifier_cache()
        _get_jwks_client.cache_clear()
        self.jwks_client = FakeJwksClient(self.public_key)
        self.jwks_patcher = patch(
            "backend.security.oidc_verifier.ResilientPyJWKClient",
            return_value=self.jwks_client,
        )
        self.jwks_patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.jwks_patcher.stop()
        clear_oidc_verifier_cache()
        _get_jwks_client.cache_clear()
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def token(
        self, subject, audience=AUDIENCE, *, issuer=ISSUER,
        expires_at=None, signing_key=None, kid=KEY_ID, algorithm="RS256",
    ):
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "iat": now,
            "exp": now + 300 if expires_at is None else expires_at,
        }
        key = self.private_key if signing_key is None else signing_key
        encode_key = "" if algorithm == "none" else ("route-test-hmac-secret" if algorithm == "HS256" else key)
        return jwt.encode(
            claims, encode_key, algorithm=algorithm, headers={"kid": kid},
        )

    def test_paper_routes_reject_adversarial_tokens_with_401_not_500(self):
        wrong_signing_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048,
        )
        invalid_tokens = {
            "wrong-signature-same-kid": self.token(
                "owner-a", signing_key=wrong_signing_key,
            ),
            "wrong-issuer": self.token(
                "owner-a", issuer="https://attacker.example/",
            ),
            "expired": self.token(
                "owner-a", expires_at=int(time.time()) - 300,
            ),
            "unknown-kid": self.token("owner-a", kid="unknown-key-id"),
            "algorithm-none": self.token("owner-a", algorithm="none"),
            "hs256": self.token("owner-a", algorithm="HS256"),
            "malformed": "this-is-not-a-jwt",
        }
        for case, token in invalid_tokens.items():
            with self.subTest(case=case):
                response = self.client.get(
                    "/api/paper/accounts",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 401, response.text)
                self.assertNotEqual(response.status_code, 500)

    def test_jwks_provider_connection_failure_returns_503(self):
        token = self.token("owner-a")
        with patch.object(
            self.jwks_client,
            "get_signing_key_from_jwt",
            side_effect=PyJWKClientConnectionError("test JWKS outage"),
        ):
            response = self.client.get(
                "/api/paper/accounts",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("Bearer", response.text)

    def test_owner_cannot_mutate_or_operate_on_another_users_account(self):
        owner_a_token = self.token("owner-a")
        owner_b_token = self.token("owner-b")
        created = self.client.post(
            "/api/paper/accounts",
            headers={"Authorization": f"Bearer {owner_a_token}"},
            json={
                "name": "Cross-owner mutation guard",
                "quote_currency": "USDT",
                "opening_capital": "2500",
                "idempotency_key": "cross-owner-opening-a",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        account_id = created.json()["account"]["id"]
        owner_b_headers = {"Authorization": f"Bearer {owner_b_token}"}

        requests = [
            ("list-trades", "GET", f"/api/paper/accounts/{account_id}/trades", None),
            ("open-trade", "POST", f"/api/paper/accounts/{account_id}/trades", {
                "symbol": "SOLUSDT",
                "strategy": "cross-owner-test",
                "side": "LONG",
                "stop_price": "100",
                "idempotency_key": "cross-owner-trade-b",
            }),
            ("close-trade", "POST", f"/api/paper/accounts/{account_id}/trades/known-trade-id/close", {
                "exit_fee": "0",
            }),
            ("fund-account", "POST", f"/api/paper/accounts/{account_id}/funding", {
                "event_type": "DEPOSIT",
                "amount": "100",
                "idempotency_key": "cross-owner-funding-b",
            }),
            ("read-risk", "GET", f"/api/paper/accounts/{account_id}/risk", None),
            ("halt-account", "POST", f"/api/paper/accounts/{account_id}/halt", {
                "reason": "cross-owner authorization regression",
            }),
            ("reset-account", "POST", f"/api/paper/accounts/{account_id}/reset", {
                "confirmed": True,
            }),
            ("read-events", "GET", f"/api/paper/accounts/{account_id}/events", None),
        ]

        for case, method, url, payload in requests:
            with self.subTest(operation=case):
                response = self.client.request(
                    method,
                    url,
                    headers=owner_b_headers,
                    json=payload,
                )
                self.assertEqual(response.status_code, 404, response.text)

        owner_a_read = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers={"Authorization": f"Bearer {owner_a_token}"},
        )
        self.assertEqual(owner_a_read.status_code, 200, owner_a_read.text)
        self.assertEqual(owner_a_read.json()["balance"], "2500.00000000")


    def test_cross_owner_close_requires_real_trade_and_hides_account_mismatch(self):
        app.dependency_overrides[get_price_provider] = FixedPriceProvider
        try:
            owner_a_token = self.token("owner-a")
            owner_b_token = self.token("owner-b")
            owner_a_headers = {"Authorization": f"Bearer {owner_a_token}"}
            owner_b_headers = {"Authorization": f"Bearer {owner_b_token}"}

            account_a_response = self.client.post(
                "/api/paper/accounts",
                headers=owner_a_headers,
                json={
                    "name": "Owner A close isolation",
                    "quote_currency": "USDT",
                    "opening_capital": "2500",
                    "idempotency_key": "owner-a-close-isolation",
                },
            )
            self.assertEqual(account_a_response.status_code, 201, account_a_response.text)
            account_a = account_a_response.json()["account"]["id"]

            account_b_response = self.client.post(
                "/api/paper/accounts",
                headers=owner_b_headers,
                json={
                    "name": "Owner B close isolation",
                    "quote_currency": "USDT",
                    "opening_capital": "2500",
                    "idempotency_key": "owner-b-close-isolation",
                },
            )
            self.assertEqual(account_b_response.status_code, 201, account_b_response.text)
            account_b = account_b_response.json()["account"]["id"]

            opened = self.client.post(
                f"/api/paper/accounts/{account_a}/trades",
                headers=owner_a_headers,
                json={
                    "symbol": "SOLUSDT",
                    "strategy": "cross-owner-close-test",
                    "side": "LONG",
                    "stop_price": "95",
                    "idempotency_key": "owner-a-real-trade",
                },
            )
            self.assertEqual(opened.status_code, 201, opened.text)
            trade_id = opened.json()["trade"]["id"]

            risk_before = self.client.get(
                f"/api/paper/accounts/{account_a}/risk",
                headers=owner_a_headers,
            )
            self.assertEqual(risk_before.status_code, 200, risk_before.text)

            close_payload = {"exit_fee": "0"}
            # (a) B cannot close A's actual trade through A's account.
            close_on_a = self.client.post(
                f"/api/paper/accounts/{account_a}/trades/{trade_id}/close",
                headers=owner_b_headers,
                json=close_payload,
            )
            self.assertEqual(close_on_a.status_code, 404, close_on_a.text)

            # (b) B cannot pair A's real trade ID with B's own account.
            # The API must not disclose whether the foreign trade exists.
            close_on_b = self.client.post(
                f"/api/paper/accounts/{account_b}/trades/{trade_id}/close",
                headers=owner_b_headers,
                json=close_payload,
            )
            self.assertEqual(close_on_b.status_code, 404, close_on_b.text)

            # Failed cross-owner halt/reset attempts must not alter A's breaker.
            halt = self.client.post(
                f"/api/paper/accounts/{account_a}/halt",
                headers=owner_b_headers,
                json={"reason": "cross-owner breaker isolation"},
            )
            self.assertEqual(halt.status_code, 404, halt.text)
            reset = self.client.post(
                f"/api/paper/accounts/{account_a}/reset",
                headers=owner_b_headers,
                json={"confirmed": True},
            )
            self.assertEqual(reset.status_code, 404, reset.text)

            risk_after = self.client.get(
                f"/api/paper/accounts/{account_a}/risk",
                headers=owner_a_headers,
            )
            self.assertEqual(risk_after.status_code, 200, risk_after.text)
            self.assertEqual(risk_after.json(), risk_before.json())

            # The real position remains open after all denied attempts.
            owner_a_trades = self.client.get(
                f"/api/paper/accounts/{account_a}/trades",
                headers=owner_a_headers,
                params={"status": "OPEN"},
            )
            self.assertEqual(owner_a_trades.status_code, 200, owner_a_trades.text)
            self.assertEqual([trade["id"] for trade in owner_a_trades.json()["trades"]], [trade_id])
        finally:
            app.dependency_overrides.pop(get_price_provider, None)

    def test_paper_routes_verify_rs256_identity_and_enforce_owner_scope(self):
        missing_token = self.client.get("/api/paper/accounts")
        self.assertEqual(missing_token.status_code, 401)

        owner_a_token = self.token("owner-a")
        created = self.client.post(
            "/api/paper/accounts",
            headers={"Authorization": f"Bearer {owner_a_token}"},
            json={
                "name": "OIDC route integration",
                "quote_currency": "USDT",
                "opening_capital": "2500",
                "idempotency_key": "oidc-route-owner-a-opening",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        account_id = created.json()["account"]["id"]

        owner_a_read = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers={"Authorization": f"Bearer {owner_a_token}"},
        )
        self.assertEqual(owner_a_read.status_code, 200, owner_a_read.text)
        self.assertEqual(owner_a_read.json()["balance"], "2500.00000000")
        self.assertEqual(owner_a_read.json()["equity"], "2500.00000000")
        self.assertFalse(owner_a_read.json()["live_trading_authorized"])

        owner_b_read = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers={"Authorization": f"Bearer {self.token('owner-b')}"},
        )
        self.assertEqual(owner_b_read.status_code, 404)

        wrong_audience = self.client.get(
            "/api/paper/accounts",
            headers={"Authorization": f"Bearer {self.token('owner-a', 'other-api')}"},
        )
        self.assertEqual(wrong_audience.status_code, 401)


    def test_concurrent_http_funding_retries_create_one_ledger_event(self):
        token = self.token("owner-concurrent-funding")
        headers = {"Authorization": f"Bearer {token}"}
        created = self.client.post(
            "/api/paper/accounts",
            headers=headers,
            json={
                "name": "Concurrent HTTP funding",
                "quote_currency": "USDT",
                "opening_capital": "1000",
                "idempotency_key": "concurrent-http-opening",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        account_id = created.json()["account"]["id"]
        url = f"/api/paper/accounts/{account_id}/funding"
        payload = {
            "event_type": "DEPOSIT",
            "amount": "100",
            "idempotency_key": "concurrent-http-deposit",
        }

        def submit_funding(_):
            # Separate clients force independent request/DB connections while
            # sharing only the persistent test database and verified identity.
            with TestClient(app) as client:
                return client.post(url, headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit_funding, range(2)))

        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
        event_ids = [response.json()["event"]["id"] for response in responses]
        self.assertEqual(event_ids[0], event_ids[1])

        events = self.client.get(
            f"/api/paper/accounts/{account_id}/events",
            headers=headers,
        )
        self.assertEqual(events.status_code, 200, events.text)
        deposits = [
            event for event in events.json()["account_events"]
            if event["event_type"] == "DEPOSIT"
        ]
        self.assertEqual(len(deposits), 1)
        self.assertEqual(deposits[0]["amount"], "100.00000000")

        account = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers=headers,
        )
        self.assertEqual(account.status_code, 200, account.text)
        self.assertEqual(account.json()["balance"], "1100.00000000")


    def test_concurrent_http_close_requests_record_one_realized_result(self):
        app.dependency_overrides[get_price_provider] = FixedPriceProvider
        token = self.token("owner-concurrent-close")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            created = self.client.post(
                "/api/paper/accounts", headers=headers,
                json={"name": "Concurrent HTTP close", "quote_currency": "USDT",
                      "opening_capital": "1000", "idempotency_key": "concurrent-close-opening"},
            )
            self.assertEqual(created.status_code, 201, created.text)
            account_id = created.json()["account"]["id"]
            opened = self.client.post(
                f"/api/paper/accounts/{account_id}/trades", headers=headers,
                json={"symbol": "SOLUSDT", "strategy": "concurrent-close-test",
                      "side": "LONG", "stop_price": "95",
                      "idempotency_key": "concurrent-close-trade"},
            )
            self.assertEqual(opened.status_code, 201, opened.text)
            trade_id = opened.json()["trade"]["id"]
            close_url = f"/api/paper/accounts/{account_id}/trades/{trade_id}/close"

            def submit_close(_):
                with TestClient(app) as client:
                    return client.post(close_url, headers=headers,
                                       json={"exit_reason": "concurrent close regression"})

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(submit_close, range(2)))
            self.assertEqual(sorted(r.status_code for r in responses), [200, 422])

            events = self.client.get(f"/api/paper/accounts/{account_id}/events", headers=headers)
            self.assertEqual(events.status_code, 200, events.text)
            realized = [event for event in events.json()["account_events"]
                        if event["event_type"] == "TRADE_REALIZED_PNL"]
            self.assertEqual(len(realized), 1)
            trades = self.client.get(
                f"/api/paper/accounts/{account_id}/trades", headers=headers,
                params={"status": "CLOSED"},
            )
            self.assertEqual(trades.status_code, 200, trades.text)
            self.assertEqual([trade["id"] for trade in trades.json()["trades"]], [trade_id])
        finally:
            app.dependency_overrides.pop(get_price_provider, None)


    def test_client_supplied_identity_cannot_override_verified_oidc_principal(self):
        owner_a_token = self.token("owner-a")
        owner_b_token = self.token("owner-b")
        spoofed_headers = {
            "Authorization": f"Bearer {owner_a_token}",
            "X-User-Id": "owner-b",
            "X-Owner-Id": "owner-b",
        }
        created = self.client.post(
            "/api/paper/accounts",
            headers=spoofed_headers,
            json={
                "name": "Identity source regression",
                "quote_currency": "USDT",
                "opening_capital": "1000",
                "idempotency_key": "identity-source-owner-a",
                "owner_id": "owner-b",
                "owner_issuer": ISSUER,
                "owner_subject": "owner-b",
                "user_id": "owner-b",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        account_id = created.json()["account"]["id"]

        # The verified bearer token is the sole source of identity. Spoofed
        # headers and extra JSON fields must not transfer ownership to B.
        owner_a_accounts = self.client.get(
            "/api/paper/accounts",
            headers={"Authorization": f"Bearer {owner_a_token}"},
        )
        self.assertEqual(owner_a_accounts.status_code, 200, owner_a_accounts.text)
        self.assertEqual(
            [account["id"] for account in owner_a_accounts.json()["accounts"]],
            [account_id],
        )

        owner_b_accounts = self.client.get(
            "/api/paper/accounts",
            headers={"Authorization": f"Bearer {owner_b_token}"},
        )
        self.assertEqual(owner_b_accounts.status_code, 200, owner_b_accounts.text)
        self.assertEqual(owner_b_accounts.json()["accounts"], [])

        owner_b_read = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers={"Authorization": f"Bearer {owner_b_token}"},
        )
        self.assertEqual(owner_b_read.status_code, 404, owner_b_read.text)



    def test_account_creation_idempotency_is_enforced_at_http_boundary(self):
        headers = {"Authorization": f"Bearer {self.token('owner-idempotency')}"}
        payload = {
            "name": "HTTP idempotency acceptance",
            "quote_currency": "USDT",
            "opening_capital": "1000",
            "idempotency_key": "http-account-create-idempotency",
        }

        first = self.client.post("/api/paper/accounts", headers=headers, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        account_id = first.json()["account"]["id"]

        replay = self.client.post("/api/paper/accounts", headers=headers, json=payload)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()["account"]["id"], account_id)

        events = self.client.get(
            f"/api/paper/accounts/{account_id}/events",
            headers=headers,
        )
        self.assertEqual(events.status_code, 200, events.text)
        opening_events = [
            event for event in events.json()["account_events"]
            if event["event_type"] == "OPENING_CAPITAL"
        ]
        self.assertEqual(len(opening_events), 1)
        self.assertEqual(opening_events[0]["amount"], "1000.00000000")

        conflicting_payload = {**payload, "opening_capital": "2000"}
        conflict = self.client.post(
            "/api/paper/accounts",
            headers=headers,
            json=conflicting_payload,
        )
        self.assertEqual(conflict.status_code, 422, conflict.text)

        account = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers=headers,
        )
        self.assertEqual(account.status_code, 200, account.text)
        self.assertEqual(account.json()["balance"], "1000.00000000")



    def test_funding_idempotency_is_enforced_at_http_boundary(self):
        headers = {"Authorization": f"Bearer {self.token('owner-funding-idempotency')}"}
        account_response = self.client.post(
            "/api/paper/accounts",
            headers=headers,
            json={
                "name": "HTTP funding idempotency",
                "quote_currency": "USDT",
                "opening_capital": "1000",
                "idempotency_key": "funding-idempotency-opening",
            },
        )
        self.assertEqual(account_response.status_code, 201, account_response.text)
        account_id = account_response.json()["account"]["id"]
        url = f"/api/paper/accounts/{account_id}/funding"
        payload = {
            "event_type": "DEPOSIT",
            "amount": "100",
            "idempotency_key": "http-funding-replay",
        }

        first = self.client.post(url, headers=headers, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        replay = self.client.post(url, headers=headers, json=payload)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["event"]["id"], first.json()["event"]["id"])

        conflict = self.client.post(
            url,
            headers=headers,
            json={**payload, "amount": "150"},
        )
        self.assertEqual(conflict.status_code, 422, conflict.text)

        events = self.client.get(
            f"/api/paper/accounts/{account_id}/events",
            headers=headers,
        )
        self.assertEqual(events.status_code, 200, events.text)
        deposits = [
            event for event in events.json()["account_events"]
            if event["event_type"] == "DEPOSIT"
        ]
        self.assertEqual(len(deposits), 1)
        self.assertEqual(deposits[0]["amount"], "100.00000000")

        account = self.client.get(
            f"/api/paper/accounts/{account_id}",
            headers=headers,
        )
        self.assertEqual(account.status_code, 200, account.text)
        self.assertEqual(account.json()["balance"], "1100.00000000")


    def test_account_equity_route_returns_503_when_current_mark_is_stale(self):
        app.dependency_overrides[get_price_provider] = FixedPriceProvider
        token = self.token("owner-stale-equity")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            created = self.client.post(
                "/api/paper/accounts",
                headers=headers,
                json={
                    "name": "Stale equity route regression",
                    "quote_currency": "USDT",
                    "opening_capital": "1000",
                    "idempotency_key": "stale-equity-route-opening",
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            account_id = created.json()["account"]["id"]

            opened = self.client.post(
                f"/api/paper/accounts/{account_id}/trades",
                headers=headers,
                json={
                    "symbol": "SOLUSDT",
                    "strategy": "stale-equity-route-test",
                    "side": "LONG",
                    "stop_price": "95",
                    "idempotency_key": "stale-equity-route-trade",
                },
            )
            self.assertEqual(opened.status_code, 201, opened.text)

            class StalePriceProvider:
                def get_price(self, symbol):
                    return PriceQuote(
                        symbol=symbol,
                        price=Decimal("110"),
                        source="stale-route-test",
                        retrieved_at=datetime.now(timezone.utc) - timedelta(minutes=2),
                    )

            # A previously persisted fresh mark exists. The account endpoint
            # must reject the stale current quote instead of reusing that mark.
            app.dependency_overrides[get_price_provider] = StalePriceProvider
            stale_read = self.client.get(
                f"/api/paper/accounts/{account_id}",
                headers=headers,
            )
            self.assertEqual(stale_read.status_code, 503, stale_read.text)
            self.assertEqual(
                stale_read.json()["detail"],
                "Precio de mercado no disponible o desactualizado",
            )
        finally:
            app.dependency_overrides.pop(get_price_provider, None)


    def test_realized_ledger_reconciliation_matches_lifecycle_and_halts_on_mismatch(self):
        app.dependency_overrides[get_price_provider] = FixedPriceProvider
        token = self.token("owner-ledger-reconciliation")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            created = self.client.post(
                "/api/paper/accounts",
                headers=headers,
                json={
                    "name": "Ledger reconciliation lifecycle",
                    "quote_currency": "USDT",
                    "opening_capital": "1000",
                    "idempotency_key": "ledger-reconciliation-opening",
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            account_id = created.json()["account"]["id"]

            realized_values = []
            for symbol, key in (
                ("SOLUSDT", "ledger-reconciliation-trade-one"),
                ("BTCUSDT", "ledger-reconciliation-trade-two"),
            ):
                opened = self.client.post(
                    f"/api/paper/accounts/{account_id}/trades",
                    headers=headers,
                    json={
                        "symbol": symbol,
                        "strategy": "ledger-reconciliation-test",
                        "side": "LONG",
                        "stop_price": "95",
                        "idempotency_key": key,
                    },
                )
                self.assertEqual(opened.status_code, 201, opened.text)
                trade_id = opened.json()["trade"]["id"]

                closed = self.client.post(
                    f"/api/paper/accounts/{account_id}/trades/{trade_id}/close",
                    headers=headers,
                    json={"exit_reason": "ledger reconciliation acceptance"},
                )
                self.assertEqual(closed.status_code, 200, closed.text)
                closed_trade = closed.json()["trade"]
                self.assertEqual(closed_trade["status"], "CLOSED")
                realized_values.append(Decimal(str(closed_trade["realized_pnl"])))

            events_response = self.client.get(
                f"/api/paper/accounts/{account_id}/events",
                headers=headers,
            )
            self.assertEqual(events_response.status_code, 200, events_response.text)
            realized_events = [
                event for event in events_response.json()["account_events"]
                if event["event_type"] == "TRADE_REALIZED_PNL"
            ]
            self.assertEqual(len(realized_events), 2)
            self.assertEqual(
                sorted(Decimal(event["amount"]) for event in realized_events),
                sorted(realized_values),
            )

            account_response = self.client.get(
                f"/api/paper/accounts/{account_id}",
                headers=headers,
            )
            self.assertEqual(account_response.status_code, 200, account_response.text)
            account = account_response.json()
            expected_balance = Decimal("1000") + sum(realized_values, Decimal("0"))
            self.assertEqual(Decimal(account["balance"]), expected_balance)
            self.assertEqual(Decimal(account["equity"]), expected_balance)
            self.assertEqual(Decimal(account["free_cash"]), expected_balance)
            self.assertEqual(account["open_positions"], [])

            reconciled = self.client.post(
                f"/api/paper/accounts/{account_id}/reconcile",
                headers=headers,
            )
            self.assertEqual(reconciled.status_code, 200, reconciled.text)
            result = reconciled.json()["reconciliation"]
            self.assertTrue(result["consistent"])
            self.assertIsInstance(result["trade_realized_pnl"], str)
            self.assertIsInstance(result["event_realized_pnl"], str)
            self.assertIsInstance(result["difference"], str)
            self.assertEqual(result["closed_trade_count"], 2)
            self.assertEqual(result["realized_event_count"], 2)
            self.assertEqual(
                Decimal(str(result["trade_realized_pnl"])),
                sum(realized_values, Decimal("0")),
            )
            self.assertEqual(
                Decimal(str(result["event_realized_pnl"])),
                sum(realized_values, Decimal("0")),
            )
            self.assertEqual(Decimal(str(result["difference"])), Decimal("0"))
            self.assertFalse(result["circuit_breaker"]["halted"])

            # A second identity must not be able to invoke the account-scoped
            # reconciliation action.
            foreign = self.client.post(
                f"/api/paper/accounts/{account_id}/reconcile",
                headers={"Authorization": f"Bearer {self.token('owner-ledger-foreign')}"},
            )
            self.assertEqual(foreign.status_code, 404, foreign.text)

            # Offset two postings in opposite directions: aggregate P&L remains
            # unchanged, but per-trade reconciliation must still detect both.
            with sqlite3.connect(self.db_path) as connection:
                rows = connection.execute(
                    """SELECT id, amount FROM paper_account_events
                       WHERE account_id = ? AND event_type = 'TRADE_REALIZED_PNL'
                       ORDER BY sequence""",
                    (account_id,),
                ).fetchall()
                self.assertEqual(len(rows), 2)
                # The production ledger is append-only. Temporarily remove its
                # DB triggers only inside this disposable test database to
                # model historical/on-disk corruption, then restore them.
                triggers = connection.execute(
                    """SELECT name, sql FROM sqlite_master
                       WHERE type = 'trigger' AND tbl_name = 'paper_account_events'"""
                ).fetchall()
                self.assertTrue(triggers, "append-only protection trigger must exist")
                for trigger_name, _ in triggers:
                    escaped_name = trigger_name.replace('"', '""')
                    connection.execute(f'DROP TRIGGER "{escaped_name}"')
                try:
                    connection.execute(
                        "UPDATE paper_account_events SET amount = ? WHERE id = ?",
                        (str(Decimal(rows[0][1]) + Decimal("1")), rows[0][0]),
                    )
                    connection.execute(
                        "UPDATE paper_account_events SET amount = ? WHERE id = ?",
                        (str(Decimal(rows[1][1]) - Decimal("1")), rows[1][0]),
                    )
                    connection.commit()
                finally:
                    for _, trigger_sql in triggers:
                        connection.execute(trigger_sql)
                    connection.commit()

            mismatch = self.client.post(
                f"/api/paper/accounts/{account_id}/reconcile",
                headers=headers,
            )
            self.assertEqual(mismatch.status_code, 200, mismatch.text)
            mismatch_result = mismatch.json()["reconciliation"]
            self.assertFalse(mismatch_result["consistent"])
            self.assertEqual(Decimal(str(mismatch_result["difference"])), Decimal("0"))
            self.assertEqual(len(mismatch_result["mismatched_trade_ids"]), 2)
            self.assertEqual(mismatch_result["alert"], "PAPER_LEDGER_INCONSISTENT")
            self.assertTrue(mismatch_result["circuit_breaker"]["halted"])

            blocked_open = self.client.post(
                f"/api/paper/accounts/{account_id}/trades",
                headers=headers,
                json={
                    "symbol": "SOLUSDT",
                    "strategy": "must-remain-halted",
                    "side": "LONG",
                    "stop_price": "95",
                    "idempotency_key": "ledger-mismatch-must-block-entry",
                },
            )
            self.assertEqual(blocked_open.status_code, 409, blocked_open.text)
        finally:
            app.dependency_overrides.pop(get_price_provider, None)


if __name__ == "__main__":
    unittest.main()
