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
    _get_jwks_client,
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

    def test_expired_and_wrong_audience_tokens_are_rejected(self):
        verifier = self.verifier()
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(exp=int(time.time()) - 300))
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(aud="another-api"))

    def test_exact_maximum_lifetime_is_accepted_and_one_second_over_is_rejected(self):
        now = int(time.time())
        verifier = self.verifier()
        self.assertEqual(
            verifier.verify(self.token(iat=now, exp=now + 3600)).subject,
            "user-123",
        )
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(iat=now, exp=now + 3601))

    def test_exp_equal_to_iat_is_rejected(self):
        now = int(time.time())
        with self.assertRaises(InvalidBearerToken):
            self.verifier().verify(self.token(iat=now, exp=now))

    def test_from_env_defaults_to_one_hour_and_accepts_configured_lower_limit(self):
        env = {
            "AI_TRADER_OIDC_ISSUER": "https://identity.example.test/",
            "AI_TRADER_OIDC_AUDIENCE": "ai-trader-paper",
            "AI_TRADER_OIDC_JWKS_URL": "https://identity.example.test/.well-known/jwks.json",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(OIDCJWTVerifier.from_env().max_token_lifetime_seconds, 3600)
        with patch.dict(
            "os.environ",
            {**env, "AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS": "1800"},
            clear=True,
        ):
            self.assertEqual(OIDCJWTVerifier.from_env().max_token_lifetime_seconds, 1800)

    def test_configured_maximum_allows_provider_tokens_up_to_24_hours(self):
        now = int(time.time())
        verifier = OIDCJWTVerifier(
            issuer="https://identity.example.test/",
            audience="ai-trader-paper",
            jwks_url="https://identity.example.test/.well-known/jwks.json",
            jwks_client=FakeJwksClient(self.public_key),
            max_token_lifetime_seconds=86400,
        )
        self.assertEqual(
            verifier.verify(self.token(iat=now, exp=now + 86400)).subject,
            "user-123",
        )
        with self.assertRaises(InvalidBearerToken):
            verifier.verify(self.token(iat=now, exp=now + 86401))

    def test_from_env_accepts_explicit_24_hour_provider_lifetime(self):
        env = {
            "AI_TRADER_OIDC_ISSUER": "https://identity.example.test/",
            "AI_TRADER_OIDC_AUDIENCE": "ai-trader-paper",
            "AI_TRADER_OIDC_JWKS_URL": "https://identity.example.test/.well-known/jwks.json",
            "AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS": "86400",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(OIDCJWTVerifier.from_env().max_token_lifetime_seconds, 86400)

    def test_from_env_rejects_invalid_token_lifetime_configuration(self):
        env = {
            "AI_TRADER_OIDC_ISSUER": "https://identity.example.test/",
            "AI_TRADER_OIDC_AUDIENCE": "ai-trader-paper",
            "AI_TRADER_OIDC_JWKS_URL": "https://identity.example.test/.well-known/jwks.json",
        }
        for value in ("59", "86401", "not-an-integer", "1.5"):
            with self.subTest(value=value):
                with patch.dict(
                    "os.environ",
                    {**env, "AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS": value},
                    clear=True,
                ):
                    with self.assertRaises(OIDCConfigurationError):
                        OIDCJWTVerifier.from_env()

    def test_not_yet_valid_tokens_are_rejected(self):
        with self.assertRaises(InvalidBearerToken):
            self.verifier().verify(self.token(nbf=int(time.time()) + 300))

    def test_wrong_issuer_is_rejected(self):
        with self.assertRaises(InvalidBearerToken):
            self.verifier().verify(self.token(iss="https://attacker.example/"))

    def test_missing_required_subject_is_rejected(self):
        claims = {
            "iss": "https://identity.example.test/",
            "aud": "ai-trader-paper",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        }
        token = jwt.encode(
            claims, self.private_key, algorithm="RS256",
            headers={"kid": "test-key"},
        )
        with self.assertRaises(InvalidBearerToken):
            self.verifier().verify(token)

    def test_hs256_and_none_algorithms_are_rejected(self):
        claims = {
            "iss": "https://identity.example.test/",
            "aud": "ai-trader-paper",
            "sub": "user-123",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        }
        token_hs = jwt.encode(claims, "not-a-real-secret", algorithm="HS256")
        token_none = jwt.encode(claims, key="", algorithm="none")
        for token in (token_hs, token_none):
            with self.subTest(token_header=jwt.get_unverified_header(token)):
                with self.assertRaises(InvalidBearerToken):
                    self.verifier().verify(token)

    def test_invalid_oversized_and_empty_tokens_are_rejected(self):
        verifier = self.verifier()
        for token in ("", "not-a-jwt", "x" * 16385):
            with self.assertRaises(InvalidBearerToken):
                verifier.verify(token)

    def test_default_jwks_client_is_reused_for_same_url(self):
        _get_jwks_client.cache_clear()
        jwks_url = "https://identity.example.test/.well-known/jwks.json"
        try:
            with patch("backend.security.oidc_verifier.PyJWKClient") as client_factory:
                client_factory.return_value = FakeJwksClient(self.public_key)
                verifier_a = OIDCJWTVerifier(
                    issuer="https://identity.example.test/",
                    audience="ai-trader-paper",
                    jwks_url=jwks_url,
                )
                verifier_b = OIDCJWTVerifier(
                    issuer="https://identity.example.test/",
                    audience="ai-trader-paper",
                    jwks_url=jwks_url,
                )

                token = self.token()
                verifier_a.verify(token)
                verifier_b.verify(token)

                client_factory.assert_called_once_with(
                    jwks_url,
                    cache_jwk_set=True,
                    lifespan=300,
                    timeout=5,
                )
        finally:
            _get_jwks_client.cache_clear()

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
