"""Tests for the provider-backed PAPER OIDC acceptance helper."""

import base64
import json
import unittest

from scripts.verify_paper_oidc_ownership import _ensure_distinct_test_identities


def make_token(*, issuer="https://keycloak.test/realms/ai-trader", subject="user-a"):
    payload = json.dumps({"iss": issuer, "sub": subject}).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


class PaperOidcAcceptanceHelperTests(unittest.TestCase):
    def test_accepts_distinct_subjects_from_same_issuer(self):
        _ensure_distinct_test_identities(
            make_token(subject="user-a"),
            make_token(subject="user-b"),
        )

    def test_rejects_different_tokens_for_same_subject(self):
        first = make_token(subject="user-a")
        payload = first.split(".")[1]
        second = f"another-header.{payload}.another-signature"
        with self.assertRaisesRegex(ValueError, "mismo subject"):
            _ensure_distinct_test_identities(first, second)

    def test_rejects_different_issuers(self):
        with self.assertRaisesRegex(ValueError, "mismo issuer"):
            _ensure_distinct_test_identities(
                make_token(issuer="https://issuer-a.test", subject="user-a"),
                make_token(issuer="https://issuer-b.test", subject="user-b"),
            )

    def test_rejects_non_jwt_token(self):
        with self.assertRaisesRegex(ValueError, "formato JWT"):
            _ensure_distinct_test_identities("opaque-token-a", "opaque-token-b")

    def test_rejects_missing_subject(self):
        payload = base64.urlsafe_b64encode(
            json.dumps({"iss": "https://keycloak.test/realms/ai-trader"}).encode()
        ).decode().rstrip("=")
        token_without_subject = f"header.{payload}.signature"
        with self.assertRaisesRegex(ValueError, "subject válido"):
            _ensure_distinct_test_identities(
                token_without_subject,
                make_token(subject="user-b"),
            )

    def test_rejects_malformed_jwt_payload(self):
        with self.assertRaisesRegex(ValueError, "leer los claims"):
            _ensure_distinct_test_identities(
                "header.bm90LWpzb24.signature",
                make_token(subject="user-b"),
            )


if __name__ == "__main__":
    unittest.main()
