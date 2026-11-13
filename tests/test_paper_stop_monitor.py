import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.infrastructure.database import apply_migrations, connect_database
from backend.security.principal import VerifiedPrincipal
from backend.services.paper_account import PaperAccountService, StaleMarketPriceError
from backend.services.paper_execution import PaperExecutionService
from backend.services.paper_price import PriceQuote
from backend.services.paper_stop_worker import PaperStopWorker


class FakePriceProvider:
    def __init__(self, price="100", age=timedelta(0)):
        self.price = Decimal(price)
        self.age = age

    def get_price(self, symbol):
        return PriceQuote(
            symbol=symbol,
            price=self.price,
            source="test-fixture",
            retrieved_at=datetime.now(timezone.utc) - self.age,
        )


class PaperStopMonitorTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.provider = FakePriceProvider()
        self.principal = VerifiedPrincipal(issuer="https://tests.example", subject="paper-user-1")
        self.accounts = PaperAccountService(self.connection, self.provider)
        self.account = self.accounts.create_account(
            name="Stop monitor demo",
            quote_currency="USDT",
            opening_capital="10000",
            idempotency_key="stop-monitor-opening",
            principal=self.principal,
        )
        self.execution = PaperExecutionService(
            self.connection, account_service=self.accounts
        )

    def tearDown(self):
        self.connection.close()

    def open_trade(self, *, side="LONG", stop="95"):
        return self.execution.open_position(
            account_id=self.account["id"],
            symbol="SOLUSDT",
            strategy="stop-monitor-test",
            side=side,
            stop_price=stop,
            entry_fee="0.1",
            estimated_exit_fee="0.1",
            principal=self.principal,
            idempotency_key=f"stop-{side}-{stop}",
        )

    def test_long_stop_closes_at_observed_gap_price_not_stop_price(self):
        trade = self.open_trade(side="LONG", stop="95")
        self.provider.price = Decimal("90")

        closed = self.execution.process_stop_losses(self.account["id"])

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["id"], trade["id"])
        self.assertEqual(closed[0]["status"], "CLOSED")
        self.assertEqual(Decimal(closed[0]["exit_price"]), Decimal("89.955"))
        expected = (
            Decimal(closed[0]["quantity"])
            * (Decimal(closed[0]["exit_price"]) - Decimal(closed[0]["entry_price"]))
            - Decimal(closed[0]["entry_fee"])
            - Decimal(closed[0]["exit_fee"])
        )
        self.assertEqual(Decimal(closed[0]["realized_pnl"]), expected.quantize(Decimal("0.00000001")) )
        self.assertEqual(closed[0]["exit_reason"], "stop_loss_triggered")

    def test_short_stop_closes_when_market_rises_through_stop(self):
        trade = self.open_trade(side="SHORT", stop="105")
        self.provider.price = Decimal("108")

        closed = self.execution.process_stop_losses(self.account["id"])

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["id"], trade["id"])
        self.assertEqual(Decimal(closed[0]["exit_price"]), Decimal("108.054"))
        expected = (
            Decimal(closed[0]["quantity"])
            * (Decimal(closed[0]["entry_price"]) - Decimal(closed[0]["exit_price"]))
            - Decimal(closed[0]["entry_fee"])
            - Decimal(closed[0]["exit_fee"])
        )
        self.assertEqual(Decimal(closed[0]["realized_pnl"]), expected.quantize(Decimal("0.00000001")) )
        self.assertEqual(closed[0]["exit_reason"], "stop_loss_triggered")

    def test_position_remains_open_when_stop_has_not_been_crossed(self):
        trade = self.open_trade()
        self.provider.price = Decimal("96")

        self.assertEqual(self.execution.process_stop_losses(self.account["id"]), [])
        stored = self.execution._ledger.get_trade(trade["id"])
        self.assertEqual(stored["status"], "OPEN")

    def test_stale_quote_never_triggers_a_simulated_fill(self):
        trade = self.open_trade()
        self.provider.price = Decimal("90")
        self.provider.age = timedelta(minutes=2)

        with self.assertRaises(StaleMarketPriceError):
            self.execution.process_stop_losses(self.account["id"])

        stored = self.execution._ledger.get_trade(trade["id"])
        self.assertEqual(stored["status"], "OPEN")

    def test_repeated_poll_does_not_close_a_trade_twice(self):
        trade = self.open_trade()
        self.provider.price = Decimal("90")

        first = self.execution.process_stop_losses(self.account["id"])
        second = self.execution.process_stop_losses(self.account["id"])

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["id"], trade["id"])
        self.assertEqual(second, [])

    def test_worker_discovers_open_accounts_and_processes_stops(self):
        trade = self.open_trade()
        self.provider.price = Decimal("90")
        worker = PaperStopWorker(
            self.connection,
            execution_service_factory=lambda connection: self.execution,
        )

        closed = worker.run_once()

        self.assertEqual([item["id"] for item in closed], [trade["id"]])


if __name__ == "__main__":
    unittest.main()
