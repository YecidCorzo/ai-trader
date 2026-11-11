import sqlite3
import unittest

from backend.infrastructure.database import apply_migrations, connect_database


class FinanceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)

    def tearDown(self):
        self.connection.close()

    def create_account(self, account_id="account-1", currency="SEK"):
        self.connection.execute(
            """INSERT INTO accounts (id, name, account_type, currency_code)
               VALUES (?, 'Everyday account', 'bank', ?)""",
            (account_id, currency),
        )

    def test_supported_currencies_are_seeded(self):
        rows = self.connection.execute(
            "SELECT code, minor_unit FROM currencies ORDER BY code"
        ).fetchall()
        self.assertEqual(
            [(row["code"], row["minor_unit"]) for row in rows],
            [("COP", 2), ("EUR", 2), ("SEK", 2), ("USD", 2)],
        )

    def test_account_and_transaction_preserve_original_currency_and_minor_units(self):
        self.create_account(currency="COP")
        self.connection.execute(
            """INSERT INTO categories (id, name, category_type)
               VALUES ('food', 'Food', 'expense')"""
        )
        self.connection.execute(
            """INSERT INTO transactions
               (id, account_id, category_id, transaction_type, amount_minor,
                currency_code, description, occurred_at)
               VALUES ('txn-1', 'account-1', 'food', 'expense', 125000,
                       'COP', 'Groceries', '2026-11-11T10:00:00Z')"""
        )
        row = self.connection.execute(
            """SELECT amount_minor, currency_code FROM transactions WHERE id = 'txn-1'"""
        ).fetchone()
        self.assertEqual((row["amount_minor"], row["currency_code"]), (125000, "COP"))

    def test_rejects_zero_or_negative_transaction_amount(self):
        self.create_account()
        for amount in (0, -1):
            with self.subTest(amount=amount):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(
                        """INSERT INTO transactions
                           (id, account_id, transaction_type, amount_minor,
                            currency_code, occurred_at)
                           VALUES (?, 'account-1', 'expense', ?, 'SEK',
                                   '2026-11-11T10:00:00Z')""",
                        (f"txn-{amount}", amount),
                    )
                self.connection.rollback()

    def test_rejects_unknown_currency_and_account_type(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO accounts (id, name, account_type, currency_code)
                   VALUES ('bad-currency', 'Invalid', 'bank', 'XXX')"""
            )
        self.connection.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO accounts (id, name, account_type, currency_code)
                   VALUES ('bad-type', 'Invalid', 'wallet', 'SEK')"""
            )
        self.connection.rollback()

    def test_transaction_valuation_keeps_fx_provenance(self):
        self.create_account(currency="EUR")
        self.connection.execute(
            """INSERT INTO transactions
               (id, account_id, transaction_type, amount_minor, currency_code, occurred_at)
               VALUES ('txn-eur', 'account-1', 'expense', 1000, 'EUR',
                       '2026-11-11T10:00:00Z')"""
        )
        self.connection.execute(
            """INSERT INTO transaction_valuations
               (id, transaction_id, value_minor, fx_rate, provider,
                effective_at, retrieved_at)
               VALUES ('valuation-1', 'txn-eur', 1125, '11.25', 'test-provider',
                       '2026-11-11T10:00:00Z', '2026-11-11T10:01:00Z')"""
        )
        valuation = self.connection.execute(
            """SELECT base_currency_code, value_minor, fx_rate, rate_convention,
                      provider, effective_at, retrieved_at
               FROM transaction_valuations WHERE id = 'valuation-1'"""
        ).fetchone()
        self.assertEqual(
            tuple(valuation),
            ("SEK", 1125, "11.25", "base_per_unit", "test-provider",
             "2026-11-11T10:00:00Z", "2026-11-11T10:01:00Z"),
        )

    def test_valuation_rejects_invalid_or_non_positive_fx_rate_text(self):
        self.create_account(currency="EUR")
        self.connection.execute(
            """INSERT INTO transactions
               (id, account_id, transaction_type, amount_minor, currency_code, occurred_at)
               VALUES ('txn-eur', 'account-1', 'expense', 1000, 'EUR',
                       '2026-11-11T10:00:00Z')"""
        )
        for invalid_rate in ('', '0', '-1.25', 'abc', '1.2.3'):
            with self.subTest(fx_rate=invalid_rate):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.connection.execute(
                        """INSERT INTO transaction_valuations
                           (id, transaction_id, value_minor, fx_rate, provider,
                            effective_at, retrieved_at)
                           VALUES (?, 'txn-eur', 1125, ?, 'provider',
                                   '2026-11-11T10:00:00Z', '2026-11-11T10:01:00Z')""",
                        (f'bad-valuation-{invalid_rate!r}', invalid_rate),
                    )
                self.connection.rollback()

    def test_foreign_keys_prevent_account_deletion_with_transactions(self):
        self.create_account()
        self.connection.execute(
            """INSERT INTO transactions
               (id, account_id, transaction_type, amount_minor, currency_code, occurred_at)
               VALUES ('txn-1', 'account-1', 'expense', 100, 'SEK',
                       '2026-11-11T10:00:00Z')"""
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM accounts WHERE id = 'account-1'")
        self.connection.rollback()


if __name__ == "__main__":
    unittest.main()
