"""FastAPI dependency that fails closed when OIDC is not configured."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.security.oidc_verifier import (
    InvalidBearerToken,
    OIDCConfigurationError,
    OIDCJWTVerifier,
)

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _configured_verifier():
    return OIDCJWTVerifier.from_env()


def clear_oidc_verifier_cache():
    """Test/configuration hook; production config is read once per process."""
    _configured_verifier.cache_clear()


def get_verified_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Se requiere autenticación Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        verifier = _configured_verifier()
    except OIDCConfigurationError:
        raise HTTPException(
            status_code=503,
            detail="La autenticación OIDC de PAPER no está configurada",
        ) from None
    try:
        return verifier.verify(credentials.credentials)
    except InvalidBearerToken:
        raise HTTPException(
            status_code=401,
            detail="Credencial Bearer inválida o expirada",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
