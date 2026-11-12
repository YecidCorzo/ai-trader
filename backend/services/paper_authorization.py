"""Owner-scoped PAPER account and trade lookups.

These checks are intended to be called by future HTTP handlers after the
server-side credential verifier has produced a VerifiedPrincipal. IDs alone
are never authorization. Cross-owner and nonexistent resources deliberately
produce the same domain error.
"""
from __future__ import annotations

import sqlite3

from backend.security.principal import VerifiedPrincipal


class PaperResourceNotFoundError(LookupError):
    """Resource is absent or not owned by the authenticated principal."""


class PaperAuthorizationService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def require_account(
        self, principal: VerifiedPrincipal, account_id: str,
    ) -> dict:
        row = self._connection.execute(
            """SELECT * FROM paper_accounts
               WHERE id = ? AND owner_issuer = ? AND owner_subject = ?""",
            (account_id, principal.issuer, principal.subject),
        ).fetchone()
        if row is None:
            raise PaperResourceNotFoundError("Recurso PAPER no encontrado")
        return dict(row)

    def require_trade(
        self, principal: VerifiedPrincipal, account_id: str, trade_id: str,
    ) -> dict:
        row = self._connection.execute(
            """SELECT trade.* FROM paper_trades AS trade
               JOIN paper_accounts AS account ON account.id = trade.paper_account_id
               WHERE trade.id = ? AND trade.paper_account_id = ?
                 AND account.owner_issuer = ? AND account.owner_subject = ?""",
            (trade_id, account_id, principal.issuer, principal.subject),
        ).fetchone()
        if row is None:
            raise PaperResourceNotFoundError("Recurso PAPER no encontrado")
        return dict(row)
