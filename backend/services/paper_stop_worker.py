"""Polling worker for simulated PAPER stop-loss execution.

Run as a separate process with the same AI_TRADER_DB_PATH as the API:
    python -m backend.services.paper_stop_worker
"""
from __future__ import annotations

import logging
import math
import os
import signal
from threading import Event

try:
    from backend.infrastructure.database import apply_migrations, connect_database
    from backend.services.paper_execution import PaperExecutionService
except ImportError:  # Support running with backend/ as the working directory.
    from infrastructure.database import apply_migrations, connect_database
    from services.paper_execution import PaperExecutionService


logger = logging.getLogger(__name__)


class PaperStopWorker:
    """Poll all funded PAPER accounts and process crossed stop levels."""

    def __init__(
        self,
        connection,
        *,
        poll_interval_seconds: float = 1.0,
        execution_service_factory=None,
    ) -> None:
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds debe ser positivo y finito")
        self._connection = connection
        self._poll_interval_seconds = poll_interval_seconds
        self._execution_service_factory = (
            execution_service_factory or PaperExecutionService
        )

    def run_once(self) -> list[dict]:
        rows = self._connection.execute(
            """SELECT DISTINCT paper_account_id
               FROM paper_trades
               WHERE status = 'OPEN' AND paper_account_id IS NOT NULL
               ORDER BY paper_account_id"""
        ).fetchall()
        closed = []
        for row in rows:
            account_id = row["paper_account_id"]
            try:
                service = self._execution_service_factory(self._connection)
                account_closed = service.process_stop_losses(account_id)
                for trade in account_closed:
                    logger.info(
                        "PAPER stop triggered: account=%s trade=%s symbol=%s exit_price=%s",
                        account_id, trade["id"], trade["symbol"], trade["exit_price"],
                    )
                closed.extend(account_closed)
            except Exception:
                # A bad/stale quote for one account must not stop other accounts.
                logger.exception(
                    "PAPER stop monitoring failed for account %s", account_id
                )
        return closed

    def run_forever(self, stop_event: Event | None = None) -> None:
        stop_event = stop_event or Event()
        logger.info(
            "PAPER stop worker started; poll interval %.3fs",
            self._poll_interval_seconds,
        )
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("PAPER stop worker scan failed")
            stop_event.wait(self._poll_interval_seconds)
        logger.info("PAPER stop worker stopped")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("AI_TRADER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    poll_interval = float(os.environ.get("AI_TRADER_STOP_POLL_SECONDS", "1"))
    connection = connect_database()
    try:
        apply_migrations(connection)
        stop_event = Event()

        def request_stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        PaperStopWorker(
            connection, poll_interval_seconds=poll_interval,
        ).run_forever(stop_event)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
