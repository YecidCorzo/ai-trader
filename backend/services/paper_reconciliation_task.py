"""Scheduled reconciliation task for every PAPER account."""
from __future__ import annotations

import logging
import os

try:
    from backend.infrastructure.database import apply_migrations, connect_database
    from backend.services.paper_execution import PaperExecutionService
except ImportError:  # Support running with backend/ as the working directory.
    from infrastructure.database import apply_migrations, connect_database
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
                try:
                    breaker = service.halt(
                        account_id, "PAPER reconciliation task failed",
                        updated_by="reconciliation_task",
                    )
                except Exception:
                    logger.exception("Could not halt PAPER account %s after reconciliation failure", account_id)
                    breaker = {"halted": True, "reason": "halt_state_unavailable"}
                results.append({
                    "account_id": account_id,
                    "consistent": False,
                    "alert": "PAPER_RECONCILIATION_FAILED",
                    "circuit_breaker": breaker,
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
            raise SystemExit(1)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
