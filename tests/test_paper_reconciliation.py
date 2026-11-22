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
        self.assertEqual(result["difference"], 0)

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


if __name__ == "__main__":
    unittest.main()
