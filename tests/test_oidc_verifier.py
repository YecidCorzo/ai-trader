import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.security.dependencies import (
    clear_oidc_verifier_cache,
    get_verified_principal,
)
from backend.security.oidc_verifier import (
    InvalidBearerToken,
    OIDCConfigurationError,
    OIDCJWTVerifier,
)


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJwksClient:
    def __init__(self, key):
        self.signing_key = FakeSigningKey(key)

    def get_signing_key_from_jwt(self, token):
        return self.signing_key


class OIDCVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.private_key.public_key()

    def verifier(self):
        return OIDCJWTVerifier(
            issuer="https://identity.example.test/",
            audience="ai-trader-paper",
            jwks_url="https://identity.example.test/.well-known/jwks.json",
            jwks_client=FakeJwksClient(self.public_key),
        )

    def token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": "https://identity.example.test/",
            "aud": "ai-trader-paper",
            "sub": "user-123",
            "iat": now,
            "exp": now + 300,
        }
        claims.update(overrides)
        return jwt.encode(
            claims, self.private_key, algorithm="RS256",
            headers={"kid": "test-key"},
        )

    def test_valid_oidc_token_creates_issuer_subject_principal(self):
        principal = self.verifier().verify(self.token())
        self.assertEqual(principal.issuer, "https://identity.example.test/")
        self.assertEqual(principal.subject, "user-123")

    def test_expired_wrong_issuer_and_wrong_audience_tokens_are_rejected(self):
        verifier = self.verifier()
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(exp=int(time.time()) - 1))
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(iss="https://attacker.example/"))
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(aud="another-api"))

    def test_missing_required_subject_and_unsupported_algorithm_are_rejected(self):
        claims = {
            "iss": "https://identity.example.test/",
            "aud": "ai-trader-paper",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        }
        token = jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test-key"})
        with self.assertRaises(InvalidBearerToken):
            self.verifier().verify(token)
        token_hs = jwt.encode(
            {"iss": "https://identity.example.test/", "aud": "ai-trader-paper",
             "sub": "user-123", "iat": int(time.time()), "exp": int(time.time()) + 300},
            "not-a-real-secret", algorithm="HS256",
        )
        with self.assertRaises(InvalidBearerToken):
            self.verifier().verify(token_hs)

    def test_invalid_oversized_and_empty_tokens_are_rejected(self):
        verifier = self.verifier()
        for token in ("", "not-a-jwt", "x" * 16385):
            with self.assertRaises(InvalidBearerToken):
                verifier.verify(token)

    def test_missing_oidc_configuration_fails_closed_with_503(self):
        clear_oidc_verifier_cache()
        with patch.dict("os.environ", {}, clear=True):
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
            with self.assertRaises(HTTPException) as raised:
                get_verified_principal(credentials)
        self.assertEqual(raised.exception.status_code, 503)
        clear_oidc_verifier_cache()

    def test_missing_bearer_token_returns_401(self):
        with self.assertRaises(HTTPException) as raised:
            get_verified_principal(None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_oidc_configuration_requires_https(self):
        with self.assertRaises(OIDCConfigurationError):
            OIDCJWTVerifier(
                issuer="http://identity.example/",
                audience="ai-trader-paper",
                jwks_url="http://identity.example/jwks",
            )


if __name__ == "__main__":
    unittest.main()
