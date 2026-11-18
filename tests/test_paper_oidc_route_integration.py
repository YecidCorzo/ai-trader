"""Route-level PAPER OIDC integration using ephemeral test keys and SQLite."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from backend.main import app
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
            "backend.security.oidc_verifier.PyJWKClient",
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


if __name__ == "__main__":
    unittest.main()
