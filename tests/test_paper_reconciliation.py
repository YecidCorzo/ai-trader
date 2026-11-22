"""Focused tests for PAPER realized-P&L ledger reconciliation."""

import sqlite3
import unittest

from backend.services.paper_reconciliation import reconcile_realized_pnl


class PaperReconciliationFiniteAmountTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE paper_trades (
                id TEXT PRIMARY KEY,
                paper_account_id TEXT NOT NULL,
                status TEXT NOT NULL,
                realized_pnl TEXT NOT NULL
            );
            CREATE TABLE paper_account_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                reference_id TEXT,
                amount TEXT NOT NULL
            );
            """
        )

    def tearDown(self):
        self.connection.close()

    def add_trade_and_event(self, trade_amount="1.25", event_amount="1.25"):
        self.connection.execute(
            "INSERT INTO paper_trades (id, paper_account_id, status, realized_pnl) VALUES (?, ?, ?, ?)",
            ("trade-1", "account-1", "CLOSED", trade_amount),
        )
        self.connection.execute(
            "INSERT INTO paper_account_events (account_id, event_type, reference_id, amount) VALUES (?, ?, ?, ?)",
            ("account-1", "TRADE_REALIZED_PNL", "trade-1", event_amount),
        )

    def test_exact_finite_trade_and_event_reconcile(self):
        self.add_trade_and_event()
        result = reconcile_realized_pnl(self.connection, "account-1")
        self.assertTrue(result["consistent"])
        self.assertEqual(result["difference"], "0")
        self.assertEqual(result["trade_realized_pnl"], "1.25")
        self.assertEqual(result["event_realized_pnl"], "1.25")

    def test_duplicate_event_reference_is_reported(self):
        self.add_trade_and_event()
        self.connection.execute(
            "INSERT INTO paper_account_events (account_id, event_type, reference_id, amount) VALUES (?, ?, ?, ?)",
            ("account-1", "TRADE_REALIZED_PNL", "trade-1", "0"),
        )
        result = reconcile_realized_pnl(self.connection, "account-1")
        self.assertFalse(result["consistent"])
        self.assertEqual(result["duplicate_event_trade_ids"], ["trade-1"])

    def test_orphan_event_reference_is_reported(self):
        self.add_trade_and_event()
        self.connection.execute(
            "INSERT INTO paper_account_events (account_id, event_type, reference_id, amount) VALUES (?, ?, ?, ?)",
            ("account-1", "TRADE_REALIZED_PNL", "trade-missing", "0"),
        )
        result = reconcile_realized_pnl(self.connection, "account-1")
        self.assertFalse(result["consistent"])
        self.assertEqual(result["orphan_event_trade_ids"], ["trade-missing"])

    def test_missing_event_for_closed_trade_is_reported(self):
        self.connection.execute(
            "INSERT INTO paper_trades (id, paper_account_id, status, realized_pnl) VALUES (?, ?, ?, ?)",
            ("trade-1", "account-1", "CLOSED", "1.25"),
        )
        result = reconcile_realized_pnl(self.connection, "account-1")
        self.assertFalse(result["consistent"])
        self.assertEqual(result["missing_event_trade_ids"], ["trade-1"])

    def test_null_event_reference_uses_explicit_marker(self):
        self.add_trade_and_event()
        self.connection.execute(
            "INSERT INTO paper_account_events (account_id, event_type, reference_id, amount) VALUES (?, ?, ?, ?)",
            ("account-1", "TRADE_REALIZED_PNL", None, "0"),
        )
        result = reconcile_realized_pnl(self.connection, "account-1")
        self.assertFalse(result["consistent"])
        self.assertEqual(result["orphan_event_trade_ids"], ["<missing-reference-id>"])

    def test_non_finite_trade_amount_fails_closed(self):
        self.add_trade_and_event(trade_amount="NaN")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            reconcile_realized_pnl(self.connection, "account-1")

    def test_infinite_event_amount_fails_closed(self):
        self.add_trade_and_event(event_amount="Infinity")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            reconcile_realized_pnl(self.connection, "account-1")

    def test_malformed_event_amount_fails_closed(self):
        self.add_trade_and_event(event_amount="not-a-number")
        with self.assertRaisesRegex(ValueError, "malformed"):
            reconcile_realized_pnl(self.connection, "account-1")


class PaperExecutionInvalidLedgerTests(unittest.TestCase):
    def test_invalid_ledger_value_halts_account_entries(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from backend.services.paper_execution import PaperExecutionService

        service = PaperExecutionService.__new__(PaperExecutionService)
        service._connection = object()
        service._accounts = SimpleNamespace(get_account=lambda account_id: {"id": account_id})
        halted = {"halted": True, "reason": "invalid ledger"}
        breaker = SimpleNamespace(halt=lambda *args, **kwargs: halted)

        with patch(
            "backend.services.paper_reconciliation.reconcile_realized_pnl",
            side_effect=ValueError("malformed or non-finite decimal"),
        ), patch(
            "backend.services.paper_execution.CircuitBreaker",
            return_value=breaker,
        ) as breaker_factory:
            result = service.reconcile_account("account-1")

        self.assertFalse(result["consistent"])
        self.assertEqual(result["alert"], "PAPER_LEDGER_INCONSISTENT")
        self.assertEqual(result["error"], "PAPER_LEDGER_INVALID")
        self.assertTrue(result["circuit_breaker"]["halted"])
        breaker_factory.assert_called_once_with(service._connection, "account-1")



if __name__ == "__main__":
    unittest.main()
