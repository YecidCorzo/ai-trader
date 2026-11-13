import json
import unittest

from backend.infrastructure.database import apply_migrations, connect_database
from backend.security.principal import VerifiedPrincipal
from backend.services.paper_account import PaperAccountService
from backend.services.paper_reconciliation_task import PaperReconciliationTask
from backend.services.trade_ledger import TradeLedger


class PaperReconciliationTaskTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.principal = VerifiedPrincipal("https://tests.example", "reconciliation-owner")
        accounts = PaperAccountService(self.connection)
        self.first = accounts.create_account(
            name="First", quote_currency="USDT", opening_capital="10000",
            idempotency_key="first-capital", principal=self.principal, account_id="account-a",
        )
        self.second = accounts.create_account(
            name="Second", quote_currency="USDT", opening_capital="10000",
            idempotency_key="second-capital", principal=self.principal, account_id="account-b",
        )

    def tearDown(self):
        self.connection.close()

    def test_task_reconciles_all_accounts_and_halts_only_inconsistent_account(self):
        ledger = TradeLedger(self.connection)
        trade = ledger.open_trade(
            symbol="SOLUSDT", strategy="task-test", side="LONG",
            quantity="1", entry_price="100", paper_account_id=self.first["id"],
        )
        closed = ledger.close_trade(trade["id"], exit_price="90")
        self.connection.execute("DROP TRIGGER paper_trades_closed_financial_immutable")
        self.connection.execute(
            "UPDATE paper_trades SET realized_pnl = '-999' WHERE id = ?",
            (closed["id"],),
        )

        results = PaperReconciliationTask(self.connection).run_once()
        by_account = {item["account_id"]: item for item in results}
        self.assertEqual(set(by_account), {self.first["id"], self.second["id"]})
        self.assertFalse(by_account[self.first["id"]]["consistent"])
        self.assertEqual(by_account[self.first["id"]]["alert"], "PAPER_LEDGER_INCONSISTENT")
        self.assertTrue(by_account[self.first["id"]]["circuit_breaker"]["halted"])
        self.assertTrue(by_account[self.second["id"]]["consistent"])
        self.assertFalse(by_account[self.second["id"]]["circuit_breaker"]["halted"])

    def test_task_failure_persists_system_halt_and_reports_stored_state(self):
        class FailingReconciliationService:
            def __init__(self, connection):
                self.connection = connection

            def reconcile_account(self, account_id):
                raise RuntimeError("forced reconciliation failure")

        result = PaperReconciliationTask(
            self.connection,
            execution_service_factory=FailingReconciliationService,
        ).run_once()

        by_account = {item["account_id"]: item for item in result}
        failed = by_account[self.first["id"]]
        self.assertFalse(failed["consistent"])
        self.assertEqual(failed["alert"], "PAPER_RECONCILIATION_FAILED")
        self.assertTrue(failed["halted"])
        self.assertTrue(failed["circuit_breaker"]["halted"])

        stored = self.connection.execute(
            "SELECT halted, reason, updated_by FROM paper_account_risk_controls WHERE account_id = ?",
            (self.first["id"],),
        ).fetchone()
        self.assertEqual(stored["halted"], 1)
        self.assertEqual(stored["reason"], "PAPER reconciliation task failed")
        self.assertEqual(stored["updated_by"], "reconciliation_task")

        event = self.connection.execute(
            """SELECT details_json FROM paper_trade_events
               WHERE event_type = 'CIRCUIT_BREAKER_HALTED'
                 AND json_extract(details_json, '$.account_id') = ?
               ORDER BY sequence DESC LIMIT 1""",
            (self.first["id"],),
        ).fetchone()
        self.assertEqual(
            json.loads(event["details_json"])["actor"],
            {"type": "system", "name": "paper_reconciliation_task"},
        )
        self.assertFalse(by_account[self.second["id"]]["halted"])

    def test_task_reports_halt_false_when_persistence_fails(self):
        class FailingReconciliationService:
            def __init__(self, connection):
                self.connection = connection

            def reconcile_account(self, account_id):
                raise RuntimeError("forced reconciliation failure")

        self.connection.execute(
            """CREATE TRIGGER reject_reconciliation_halt
               BEFORE UPDATE OF halted ON paper_account_risk_controls
               BEGIN SELECT RAISE(ABORT, 'forced halt persistence failure'); END"""
        )
        results = PaperReconciliationTask(
            self.connection,
            execution_service_factory=FailingReconciliationService,
        ).run_once()
        failed = next(item for item in results if item["account_id"] == self.first["id"])
        self.assertFalse(failed["halted"])
        self.assertFalse(failed["circuit_breaker"]["halted"])
        stored = self.connection.execute(
            "SELECT halted FROM paper_account_risk_controls WHERE account_id = ?",
            (self.first["id"],),
        ).fetchone()
        self.assertEqual(stored["halted"], 0)


if __name__ == "__main__":
    unittest.main()
