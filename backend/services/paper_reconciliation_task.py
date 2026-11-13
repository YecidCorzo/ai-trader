"""Scheduled reconciliation task for every PAPER account."""
from __future__ import annotations

import logging
import os

try:
    from backend.infrastructure.database import apply_migrations, connect_database
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.services.paper_execution import PaperExecutionService
except ImportError:  # Support running with backend/ as the working directory.
    from infrastructure.database import apply_migrations, connect_database
    from services.circuit_breaker import CircuitBreaker
    from services.paper_execution import PaperExecutionService

logger = logging.getLogger(__name__)


class PaperReconciliationTask:
    """Reconcile every PAPER account and fail closed on task errors."""

    def __init__(self, connection, *, execution_service_factory=None) -> None:
        self._connection = connection
        self._execution_service_factory = execution_service_factory or PaperExecutionService

    def run_once(self) -> list[dict]:
        rows = self._connection.execute(
            "SELECT id FROM paper_accounts ORDER BY created_at, id"
        ).fetchall()
        results = []
        for row in rows:
            account_id = row["id"]
            service = self._execution_service_factory(self._connection)
            try:
                result = service.reconcile_account(account_id)
                results.append({"account_id": account_id, **result})
            except Exception:
                logger.exception("PAPER reconciliation task failed for account %s", account_id)
                breaker = CircuitBreaker(self._connection, account_id)
                try:
                    # This is an internal safety action, not a user operation.
                    # CircuitBreaker records the system actor and persists the
                    # halt without requiring a VerifiedPrincipal.
                    breaker.halt(
                        "PAPER reconciliation task failed",
                        updated_by="reconciliation_task",
                        actor={"type": "system", "name": "paper_reconciliation_task"},
                    )
                except Exception:
                    logger.exception(
                        "Could not persist PAPER circuit-breaker halt for account %s",
                        account_id,
                    )

                # Never report a requested/intended halt as successful. Read
                # the authoritative persisted state after the write attempt.
                try:
                    breaker_state = breaker.status()
                except Exception:
                    logger.exception(
                        "Could not read persisted PAPER circuit-breaker state for account %s",
                        account_id,
                    )
                    breaker_state = {
                        "halted": False,
                        "reason": "halt_state_unavailable",
                        "account_id": account_id,
                        "mode": "paper",
                    }
                results.append({
                    "account_id": account_id,
                    "consistent": False,
                    "alert": "PAPER_RECONCILIATION_FAILED",
                    "halted": bool(breaker_state["halted"]),
                    "circuit_breaker": breaker_state,
                })
        return results


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("AI_TRADER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    connection = connect_database()
    try:
        apply_migrations(connection)
        results = PaperReconciliationTask(connection).run_once()
        inconsistent = [item for item in results if not item["consistent"]]
        logger.info(
            "PAPER reconciliation completed: accounts=%d inconsistent=%d",
            len(results), len(inconsistent),
        )
        if inconsistent:
            # Exit 1 is consumed by cron/systemd monitoring and alerting.
            raise SystemExit(1)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
