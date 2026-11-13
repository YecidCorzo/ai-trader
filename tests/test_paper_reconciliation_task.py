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
        principal = VerifiedPrincipal("https://tests.example", "reconciliation-owner")
        accounts = PaperAccountService(self.connection)
        self.first = accounts.create_account(
            name="First", quote_currency="USDT", opening_capital="10000",
            idempotency_key="first-capital", principal=principal, account_id="account-a",
        )
        self.second = accounts.create_account(
            name="Second", quote_currency="USDT", opening_capital="10000",
            idempotency_key="second-capital", principal=principal, account_id="account-b",
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


if __name__ == "__main__":
    unittest.main()
