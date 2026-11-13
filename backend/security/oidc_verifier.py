"""Provider-neutral OIDC JWT verification for PAPER API access."""
from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient, PyJWKClientError, PyJWTError

try:
    from backend.security.principal import VerifiedPrincipal
except ImportError:
    from security.principal import VerifiedPrincipal


class OIDCConfigurationError(ValueError):
    pass


class InvalidBearerToken(ValueError):
    pass


@dataclass(frozen=True)
class OIDCJWTVerifier:
    issuer: str
    audience: str
    jwks_url: str
    jwks_client: object | None = None
    leeway_seconds: int = 30

    def __post_init__(self):
        if not self.issuer.strip() or not self.audience.strip() or not self.jwks_url.strip():
            raise OIDCConfigurationError("OIDC issuer, audience y JWKS URL son obligatorios")
        if self.leeway_seconds < 0 or self.leeway_seconds > 120:
            raise OIDCConfigurationError("OIDC clock leeway debe estar entre 0 y 120 segundos")

    @classmethod
    def from_env(cls):
        issuer = os.environ.get("AI_TRADER_OIDC_ISSUER", "").strip()
        audience = os.environ.get("AI_TRADER_OIDC_AUDIENCE", "").strip()
        jwks_url = os.environ.get("AI_TRADER_OIDC_JWKS_URL", "").strip()
        if not issuer or not audience or not jwks_url:
            raise OIDCConfigurationError(
                "Configura AI_TRADER_OIDC_ISSUER, AI_TRADER_OIDC_AUDIENCE y AI_TRADER_OIDC_JWKS_URL"
            )
        if not issuer.startswith("https://") or not jwks_url.startswith("https://"):
            raise OIDCConfigurationError("OIDC issuer y JWKS URL deben usar HTTPS")
        return cls(issuer=issuer, audience=audience, jwks_url=jwks_url)

    def verify(self, token: str) -> VerifiedPrincipal:
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise InvalidBearerToken("Bearer token inválido")
        try:
            client = self.jwks_client or PyJWKClient(
                self.jwks_url,
                cache_jwk_set=True,
                lifespan=300,
                timeout=5,
            )
            signing_key = client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=self.leeway_seconds,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            subject = claims.get("sub")
            issuer = claims.get("iss")
            if not isinstance(subject, str) or not subject.strip():
                raise InvalidBearerToken("Bearer token sin subject válido")
            if not isinstance(issuer, str) or issuer != self.issuer:
                raise InvalidBearerToken("Bearer token issuer inválido")
            return VerifiedPrincipal(issuer=issuer, subject=subject)
        except InvalidBearerToken:
            raise
        except (PyJWTError, PyJWKClientError, TypeError, ValueError, KeyError):
            raise InvalidBearerToken("Bearer token inválido o expirado") from None
