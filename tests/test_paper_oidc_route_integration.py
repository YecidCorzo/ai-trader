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

    def token(self, subject, audience=AUDIENCE):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": audience,
            "sub": subject,
            "iat": now,
            "exp": now + 300,
        }
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": KEY_ID},
        )

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
