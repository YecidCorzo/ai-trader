import sqlite3
import unittest
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.infrastructure.database import apply_migrations, connect_database
from backend.security.authentication import build_current_principal_dependency
from backend.security.principal import VerifiedPrincipal
from backend.services.paper_account import PaperAccountService
from backend.services.paper_authorization import (
    PaperAuthorizationService,
    PaperResourceNotFoundError,
)
from backend.services.paper_execution import PaperExecutionService
from backend.services.paper_price import PriceQuote


class FakeVerifier:
    async def verify_token(self, token):
        if token != "valid-test-token":
            raise ValueError("private verifier detail")
        return VerifiedPrincipal("https://issuer.example", "subject-a")


class FakePriceProvider:
    def get_price(self, symbol):
        return PriceQuote(
            symbol=symbol,
            price=Decimal("100"),
            source="test-fixture",
            retrieved_at=datetime.now(timezone.utc),
        )


class PaperAuthenticationDependencyTests(unittest.TestCase):
    def test_unconfigured_authentication_fails_closed_with_503(self):
        app = FastAPI()
        dependency = build_current_principal_dependency(None)

        @app.get("/protected")
        def protected(principal=Depends(dependency)):
            return {"subject": principal.subject}

        response = TestClient(app).get("/protected", headers={"Authorization": "Bearer any"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Autenticación no configurada")

    def test_missing_or_malformed_bearer_credential_is_rejected(self):
        app = FastAPI()
        dependency = build_current_principal_dependency(FakeVerifier())

        @app.get("/protected")
        def protected(principal=Depends(dependency)):
            return {"subject": principal.subject}

        client = TestClient(app)
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}):
            with self.subTest(headers=headers):
                response = client.get("/protected", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Credenciales no válidas")

    def test_verifier_failure_is_generic_and_does_not_leak_diagnostics(self):
        app = FastAPI()
        dependency = build_current_principal_dependency(FakeVerifier())

        @app.get("/protected")
        def protected(principal=Depends(dependency)):
            return {"subject": principal.subject}

        response = TestClient(app).get(
            "/protected", headers={"Authorization": "Bearer invalid-token"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("private verifier detail", response.text)

    def test_verified_identity_is_used_not_client_supplied_user_header(self):
        app = FastAPI()
        dependency = build_current_principal_dependency(FakeVerifier())

        @app.get("/protected")
        def protected(principal=Depends(dependency)):
            return {"issuer": principal.issuer, "subject": principal.subject}

        response = TestClient(app).get(
            "/protected",
            headers={
                "Authorization": "Bearer valid-test-token",
                "X-User-Id": "attacker-controlled-subject",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "issuer": "https://issuer.example", "subject": "subject-a"
        })

    def test_principal_is_immutable_and_requires_nonempty_identity(self):
        principal = VerifiedPrincipal(" https://issuer.example ", " subject-a ")
        self.assertEqual(principal.issuer, "https://issuer.example")
        self.assertEqual(principal.subject, "subject-a")
        with self.assertRaises((AttributeError, TypeError)):
            principal.subject = "subject-b"
        with self.assertRaises(ValueError):
            VerifiedPrincipal(" ", "subject-a")


class PaperAccountOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.accounts = PaperAccountService(self.connection, FakePriceProvider())
        self.authorization = PaperAuthorizationService(self.connection)
        self.owner_a = VerifiedPrincipal("https://issuer.example", "subject-a")
        self.owner_b = VerifiedPrincipal("https://issuer.example", "subject-b")
        self.account_a = self.accounts.create_account(
            name="Account A", quote_currency="USDT", opening_capital="10000",
            idempotency_key="same-key", principal=self.owner_a,
        )

    def tearDown(self):
        self.connection.close()

    def test_same_idempotency_key_is_scoped_to_verified_owner(self):
        account_b = self.accounts.create_account(
            name="Account B", quote_currency="USDT", opening_capital="20000",
            idempotency_key="same-key", principal=self.owner_b,
        )
        self.assertNotEqual(self.account_a["id"], account_b["id"])
        self.assertEqual(self.account_a["owner_subject"], "subject-a")
        self.assertEqual(account_b["owner_subject"], "subject-b")
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM paper_accounts").fetchone()[0],
            2,
        )

    def test_owner_can_read_only_own_account_and_other_owner_looks_missing(self):
        self.assertEqual(
            self.authorization.require_account(self.owner_a, self.account_a["id"])["id"],
            self.account_a["id"],
        )
        with self.assertRaises(PaperResourceNotFoundError) as cross_owner:
            self.authorization.require_account(self.owner_b, self.account_a["id"])
        with self.assertRaises(PaperResourceNotFoundError) as missing:
            self.authorization.require_account(self.owner_b, "does-not-exist")
        self.assertEqual(str(cross_owner.exception), str(missing.exception))

    def test_new_accounts_require_verified_owner_and_owner_is_immutable(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO paper_accounts
                   (id, name, quote_currency, creation_key, created_at)
                   VALUES ('ownerless', 'Ownerless', 'USDT', 'ownerless-key', '2026-11-12T00:00:00Z')"""
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE paper_accounts SET owner_subject = 'subject-b' WHERE id = ?",
                (self.account_a["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE paper_accounts SET owner_issuer = NULL WHERE id = ?",
                (self.account_a["id"],),
            )

    def test_legacy_unowned_account_is_preserved_but_not_claimed(self):
        migrations = Path(__file__).resolve().parents[1] / "backend" / "infrastructure" / "migrations"
        with tempfile.TemporaryDirectory() as directory:
            legacy_dir = Path(directory) / "legacy_migrations"
            legacy_dir.mkdir()
            for migration in sorted(migrations.glob("000[1-6]_*.sql")):
                shutil.copyfile(migration, legacy_dir / migration.name)

            connection = connect_database(":memory:")
            try:
                apply_migrations(connection, legacy_dir)
                connection.execute(
                    """INSERT INTO paper_accounts
                       (id, name, quote_currency, creation_key, created_at)
                       VALUES ('legacy-account', 'Legacy', 'USDT', 'legacy-key',
                               '2026-11-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO paper_account_risk_controls
                       (account_id, halted, reason, updated_at, updated_by)
                       VALUES ('legacy-account', 0, NULL, '2026-11-01T00:00:00Z', 'migration')"""
                )
                connection.execute(
                    """INSERT INTO paper_account_events
                       (id, account_id, event_type, amount, currency_code,
                        idempotency_key, occurred_at)
                       VALUES ('legacy-opening', 'legacy-account', 'OPENING_CAPITAL',
                               '1000', 'USDT', 'legacy-opening-key',
                               '2026-11-01T00:00:00Z')"""
                )
                connection.commit()
                apply_migrations(connection, migrations)
                row = connection.execute(
                    "SELECT owner_issuer, owner_subject FROM paper_accounts WHERE id = 'legacy-account'"
                ).fetchone()
                self.assertIsNone(row["owner_issuer"])
                self.assertIsNone(row["owner_subject"])
                authorization = PaperAuthorizationService(connection)
                with self.assertRaises(PaperResourceNotFoundError):
                    authorization.require_account(self.owner_a, "legacy-account")
            finally:
                connection.close()

    def test_trade_authorization_is_scoped_by_trade_account_and_owner(self):
        execution = PaperExecutionService(
            self.connection, account_service=self.accounts
        )
        trade = execution.open_position(
            account_id=self.account_a["id"], symbol="SOLUSDT",
            strategy="ownership-test", side="LONG", quantity="1",
            stop_price="95", entry_fee="0", estimated_exit_fee="0",
            principal=self.owner_a, idempotency_key="auth-boundary-open",
        )
        self.assertEqual(
            self.authorization.require_trade(
                self.owner_a, self.account_a["id"], trade["id"]
            )["id"],
            trade["id"],
        )
        with self.assertRaises(PaperResourceNotFoundError):
            self.authorization.require_trade(
                self.owner_b, self.account_a["id"], trade["id"]
            )
        with self.assertRaises(PaperResourceNotFoundError):
            self.authorization.require_trade(
                self.owner_a, "another-account", trade["id"]
            )


if __name__ == "__main__":
    unittest.main()
