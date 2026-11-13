"""Provider-neutral FastAPI authentication dependency factory.

A concrete provider adapter must verify signatures, algorithm allow-lists,
issuer, audience, expiry, not-before and revocation/session state before
returning a VerifiedPrincipal. This module deliberately ships no token
verifier and does not enable account routes by itself.
"""
from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, Request, status

from backend.security.principal import VerifiedPrincipal


class CredentialVerifier(Protocol):
    async def verify_token(self, token: str) -> VerifiedPrincipal:
        """Return a principal only after complete credential verification."""
        ...


def build_current_principal_dependency(verifier: CredentialVerifier | None):
    """Build a fail-closed dependency; unconfigured auth is unavailable, not open."""
    async def current_principal(request: Request) -> VerifiedPrincipal:
        if verifier is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Autenticación no configurada",
            )

        authorization = request.headers.get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not credential.strip()
            or " " in credential.strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales no válidas",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            principal = await verifier.verify_token(credential.strip())
        except Exception:
            # Do not expose verifier details, token fragments or provider diagnostics.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales no válidas",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

        if not isinstance(principal, VerifiedPrincipal):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales no válidas",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal

    return current_principal
