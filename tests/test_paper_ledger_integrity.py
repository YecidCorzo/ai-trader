import sqlite3
import unittest
from decimal import Decimal

from backend.infrastructure.database import apply_migrations, connect_database
from backend.security.principal import VerifiedPrincipal
from backend.services.paper_account import PaperAccountService
from backend.services.paper_execution import PaperExecutionService
from backend.services.paper_reconciliation import reconcile_realized_pnl
from backend.services.trade_ledger import TradeLedger


class PaperLedgerIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.accounts = PaperAccountService(self.connection)
        self.principal = VerifiedPrincipal("https://issuer.example", "ledger-test-owner")
        self.account = self.accounts.create_account(
            name="Integrity demo", quote_currency="USDT",
            opening_capital="10000", idempotency_key="integrity-opening",
            principal=self.principal, account_id="account-a",
        )
        self.ledger = TradeLedger(self.connection)

    def tearDown(self):
        self.connection.close()

    def close_trade(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="integrity-test", side="LONG",
            quantity="1", entry_price="100", entry_fee="0.1",
            paper_account_id=self.account["id"],
        )
        return self.ledger.close_trade(trade["id"], exit_price="110", exit_fee="0.1")

    def insert_realized_event(self, *, account_id="account-a", reference_id,
                              amount="9.8", key="manual-event"):
        self.connection.execute(
            """INSERT INTO paper_account_events
               (id, account_id, event_type, amount, currency_code,
                idempotency_key, reference_id, occurred_at)
               VALUES (?, ?, 'TRADE_REALIZED_PNL', ?, 'USDT', ?, ?, ?)""",
            ("event-" + key, account_id, amount, key, reference_id,
             "2026-11-13T10:00:00.000000Z"),
        )

    def test_close_creates_one_matching_event_and_reconciles(self):
        closed = self.close_trade()
        self.assertEqual(Decimal(closed["realized_pnl"]), Decimal("9.8"))
        result = reconcile_realized_pnl(self.connection, self.account["id"])
        self.assertTrue(result["consistent"])
        self.assertEqual(result["closed_trade_count"], 1)
        self.assertEqual(result["realized_event_count"], 1)
        self.assertEqual(result["difference"], Decimal("0"))

    def test_monetary_values_use_eight_decimal_half_even_rounding(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="rounding", side="LONG",
            quantity="1", entry_price="100", entry_fee="0",
            paper_account_id=self.account["id"],
        )
        closed = self.ledger.close_trade(
            trade["id"], exit_price="100.000000015", exit_fee="0"
        )
        self.assertEqual(closed["realized_pnl"], "0.00000002")

    def test_zero_realized_pnl_is_a_valid_single_ledger_posting(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="break-even", side="LONG",
            quantity="1", entry_price="100", entry_fee="0",
            paper_account_id=self.account["id"],
        )
        closed = self.ledger.close_trade(trade["id"], exit_price="100", exit_fee="0")
        self.assertEqual(Decimal(closed["realized_pnl"]), Decimal("0"))
        result = reconcile_realized_pnl(self.connection, self.account["id"])
        self.assertTrue(result["consistent"])
        self.assertEqual(result["event_realized_pnl"], Decimal("0"))

    def test_duplicate_realized_event_for_trade_is_rejected(self):
        closed = self.close_trade()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_realized_event(reference_id=closed["id"])

    def test_realized_event_requires_existing_closed_trade_in_same_account(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_realized_event(reference_id="missing-trade")
        closed = self.close_trade()
        second = self.accounts.create_account(
            name="Other demo", quote_currency="USDT", opening_capital="1000",
            idempotency_key="other-opening", principal=self.principal, account_id="account-b",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_realized_event(
                account_id=second["id"], reference_id=closed["id"],
                key="wrong-account",
            )

    def test_realized_event_amount_must_match_closed_trade(self):
        closed = self.close_trade()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_realized_event(
                reference_id=closed["id"], amount="9.81", key="wrong-amount",
            )

    def test_closed_trade_financial_columns_are_immutable(self):
        closed = self.close_trade()
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE paper_trades SET realized_pnl = '100' WHERE id = ?",
                (closed["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE paper_trades SET entry_price = '1' WHERE id = ?",
                (closed["id"],),
            )

    def test_sql_triggers_reject_excess_precision_and_leading_zeroes(self):
        for index, value in enumerate(("1.000000001", "01.25", "0002")):
            with self.subTest(value=value):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(
                        """INSERT INTO paper_account_events
                           (id, account_id, event_type, amount, currency_code, idempotency_key, occurred_at)
                           VALUES (?, ?, 'DEPOSIT', ?, 'USDT', ?, ?)""",
                        (f"precision-event-{index}", self.account["id"], value,
                         f"precision-key-{index}", "2026-11-13T10:00:00.000000Z"),
                    )

    def test_account_event_rejects_malformed_decimal_strings(self):
        for index, value in enumerate(("1-2", "1e", "1e5e5")):
            with self.subTest(value=value):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(
                        """INSERT INTO paper_account_events
                           (id, account_id, event_type, amount, currency_code,
                            idempotency_key, occurred_at)
                           VALUES (?, ?, 'DEPOSIT', ?, 'USDT', ?, ?)""",
                        (f"bad-event-{index}", self.account["id"], value,
                         f"bad-event-key-{index}", "2026-11-13T10:00:00Z"),
                    )

    def test_trade_insert_rejects_malformed_decimal_strings(self):
        for field in ("quantity", "entry_price", "entry_fee"):
            for index, value in enumerate(("1-2", "1e", "1e5e5")):
                with self.subTest(field=field, value=value):
                    values = {
                        "quantity": "1", "entry_price": "100", "entry_fee": "0",
                    }
                    values[field] = value
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.connection.execute(
                            """INSERT INTO paper_trades
                               (id, symbol, strategy, side, quantity, entry_price,
                                entry_fee, status, opened_at, metadata_json, paper_account_id)
                               VALUES (?, 'SOLUSDT', 'bad-input', 'LONG', ?, ?, ?,
                                       'OPEN', '2026-11-13T10:00:00Z', '{}', ?)""",
                            (f"bad-trade-{field}-{index}", values["quantity"],
                             values["entry_price"], values["entry_fee"],
                             self.account["id"]),
                        )

    def test_trade_ledger_limits_decimals_and_normalizes_leading_zeroes(self):
        with self.assertRaisesRegex(ValueError, "8 decimales"):
            self.ledger.open_trade(symbol="SOLUSDT", strategy="precision", side="LONG", quantity="1.000000001", entry_price="100")
        normalized = self.ledger.open_trade(symbol="SOLUSDT", strategy="precision", side="LONG", quantity="0001.2500", entry_price="000100.5000")
        self.assertEqual(normalized["quantity"], "1.2500")
        self.assertEqual(normalized["entry_price"], "100.5000")

    def test_reconciliation_detects_a_trade_ledger_mismatch(self):
        closed = self.close_trade()
        self.connection.execute("DROP TRIGGER paper_trades_closed_financial_immutable")
        self.connection.execute(
            "UPDATE paper_trades SET realized_pnl = '999' WHERE id = ?",
            (closed["id"],),
        )
        result = reconcile_realized_pnl(self.connection, self.account["id"])
        self.assertFalse(result["consistent"])
        self.assertEqual(result["trade_realized_pnl"], Decimal("999"))
        self.assertEqual(result["event_realized_pnl"], Decimal("9.8"))
        self.assertEqual(result["difference"], Decimal("989.2"))
        exposed = PaperExecutionService(self.connection).reconcile_account(self.account["id"])
        self.assertEqual(exposed["alert"], "PAPER_LEDGER_INCONSISTENT")
        self.assertTrue(exposed["circuit_breaker"]["halted"])


if __name__ == "__main__":
    unittest.main()
