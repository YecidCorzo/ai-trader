"""Immutable identity value created only after credential verification."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    """Stable issuer/subject identity; never contains the raw credential."""

    issuer: str
    subject: str

    def __post_init__(self) -> None:
        issuer = self.issuer.strip() if isinstance(self.issuer, str) else ""
        subject = self.subject.strip() if isinstance(self.subject, str) else ""
        if not issuer or not subject:
            raise ValueError("El principal requiere issuer y subject verificados")
        object.__setattr__(self, "issuer", issuer)
        object.__setattr__(self, "subject", subject)
