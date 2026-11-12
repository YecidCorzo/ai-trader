import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from backend.infrastructure.database import apply_migrations, connect_database
from backend.services.paper_account import (
    MissingOpeningCapitalError, PaperAccountService, PaperAccountError,
    StaleMarketPriceError,
)
from backend.services.paper_execution import PaperExecutionService, RiskRejectedError
from backend.services.paper_price import PriceQuote
from backend.services.risk_engine import RiskEngine, RiskLimits
from backend.services.trade_ledger import TradeLedger


class FakePriceProvider:
    def __init__(self, *, price="100", age=timedelta(0), fail=False):
        self.price = Decimal(price)
        self.age = age
        self.fail = fail

    def get_price(self, symbol):
        if self.fail:
            raise RuntimeError("market data unavailable")
        return PriceQuote(
            symbol=symbol,
            price=self.price,
            source="test-fixture",
            retrieved_at=datetime.now(timezone.utc) - self.age,
        )


class PaperExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.provider = FakePriceProvider()
        self.accounts = PaperAccountService(self.connection, self.provider)
        self.account = self.accounts.create_account(
            name="Demo account", quote_currency="USDT",
            opening_capital="10000", idempotency_key="initial-capital",
        )
        self.execution = PaperExecutionService(
            self.connection, account_service=self.accounts
        )

    def tearDown(self):
        self.connection.close()

    def open_position(self, **overrides):
        values = {
            "account_id": self.account["id"],
            "symbol": "SOLUSDT",
            "strategy": "ema-rsi",
            "side": "LONG",
            "quantity": "1",
            "stop_price": "95",
            "entry_fee": "0.1",
            "estimated_exit_fee": "0.1",
        }
        values.update(overrides)
        return self.execution.open_position(**values)

    def test_account_requires_explicit_opening_capital(self):
        with self.assertRaises(TypeError):
            self.accounts.create_account(
                name="Missing capital", quote_currency="USDT",
                idempotency_key="missing",
            )
        self.connection.execute(
            "INSERT INTO paper_accounts (id, name, quote_currency, creation_key, created_at) VALUES ('empty', 'Empty', 'USDT', 'empty-account', '2026-11-12T00:00:00Z')"
        )
        with self.assertRaises(MissingOpeningCapitalError):
            self.accounts.get_account("empty")

    def test_account_creation_is_idempotent_and_rejects_conflicting_reuse(self):
        repeated = self.accounts.create_account(
            name="Demo account", quote_currency="USDT",
            opening_capital="10000", idempotency_key="initial-capital",
        )
        self.assertEqual(repeated["id"], self.account["id"])
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM paper_accounts"
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(PaperAccountError):
            self.accounts.create_account(
                name="Different account", quote_currency="USDT",
                opening_capital="10000", idempotency_key="initial-capital",
            )

    def test_approved_entry_uses_persisted_account_equity(self):
        trade = self.open_position()
        self.assertEqual(trade["status"], "OPEN")
        self.assertEqual(trade["paper_account_id"], self.account["id"])
        self.assertEqual(self.accounts.get_equity(self.account["id"]), Decimal("9999.9"))
        self.assertEqual(self.accounts.get_account(self.account["id"])["quote_currency"], "USDT")

    def test_risk_gate_does_not_accept_caller_controlled_equity(self):
        with self.assertRaises(TypeError):
            self.execution.open_position(
                account_id=self.account["id"], symbol="SOLUSDT",
                strategy="ema-rsi", side="LONG", quantity="1",
                stop_price="95",
                risk_snapshot={"equity": "999999999"},
            )

    def test_risk_limit_uses_account_capital_not_a_caller_snapshot(self):
        small = self.accounts.create_account(
            name="Small demo", quote_currency="USDT",
            opening_capital="100", idempotency_key="small-opening",
        )
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position(
                account_id=small["id"], quantity="1",
                stop_price="95",
                entry_fee="0", estimated_exit_fee="0",
            )
        self.assertEqual(raised.exception.reason, "per_trade_risk_limit_exceeded")

    def test_open_positions_and_loss_metrics_are_scoped_to_account(self):
        second = self.accounts.create_account(
            name="Second demo", quote_currency="USDT",
            opening_capital="10000", idempotency_key="second-opening",
        )
        self.open_position()
        other = self.open_position(account_id=second["id"])
        self.assertEqual(other["paper_account_id"], second["id"])

    def test_circuit_breaker_is_isolated_per_paper_account(self):
        second = self.accounts.create_account(
            name="Independent demo", quote_currency="USDT",
            opening_capital="10000", idempotency_key="independent-opening",
        )
        self.execution.halt(self.account["id"], "operator requested stop")
        self.assertTrue(self.execution.circuit_breaker_status(self.account["id"])["halted"])
        self.assertFalse(self.execution.circuit_breaker_status(second["id"])["halted"])
        trade = self.open_position(account_id=second["id"])
        self.assertEqual(trade["paper_account_id"], second["id"])
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position()
        self.assertEqual(raised.exception.reason, "circuit_breaker_halted")

    def test_daily_loss_is_derived_from_account_trade_ledger(self):
        prior = self.execution.open_position(
            account_id=self.account["id"], symbol="SOLUSDT",
            strategy="test", side="LONG", quantity="10",
            stop_price="99",
            entry_fee="0", estimated_exit_fee="0",
        )
        self.provider.price = Decimal("70")
        self.execution.close_position(prior["id"], account_id=self.account["id"])
        self.assertEqual(self.accounts.calculate_equity(self.account["id"]), Decimal("9700"))
        self.provider.price = Decimal("100")
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position()
        self.assertEqual(raised.exception.reason, "daily_loss_limit_reached")
        self.assertTrue(self.execution.circuit_breaker_status(self.account["id"])["halted"])

    def test_trade_realized_pnl_is_booked_once_with_trade_close(self):
        trade = self.open_position()
        self.provider.price = Decimal("110")
        closed = self.execution.close_position(
            trade["id"], account_id=self.account["id"], exit_fee="0.1"
        )
        self.assertEqual(Decimal(closed["realized_pnl"]), Decimal("9.8"))
        events = self.connection.execute(
            """SELECT amount, idempotency_key FROM paper_account_events
               WHERE account_id = ? AND event_type = 'TRADE_REALIZED_PNL'""",
            (self.account["id"],),
        ).fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(Decimal(events[0]["amount"]), Decimal("9.8"))
        self.assertEqual(events[0]["idempotency_key"], f"trade-close:{trade['id']}")

    def test_exit_price_is_market_sourced_and_account_scoped(self):
        trade = self.open_position()
        with self.assertRaises(TypeError):
            self.execution.close_position(
                trade["id"], account_id=self.account["id"], exit_price="999999"
            )
        other = self.accounts.create_account(
            name="Not owner", quote_currency="USDT",
            opening_capital="10000", idempotency_key="not-owner",
        )
        with self.assertRaisesRegex(ValueError, "no pertenece"):
            self.execution.close_position(trade["id"], account_id=other["id"])

    def test_close_rolls_back_trade_if_account_event_cannot_be_written(self):
        trade = self.open_position()
        self.connection.execute("""
            CREATE TRIGGER fail_realized_event
            BEFORE INSERT ON paper_account_events
            WHEN NEW.event_type = 'TRADE_REALIZED_PNL'
            BEGIN SELECT RAISE(ABORT, 'injected account event failure'); END
        """)
        self.provider.price = Decimal("110")
        with self.assertRaises(sqlite3.IntegrityError):
            self.execution.close_position(trade["id"], account_id=self.account["id"])
        stored = self.execution._ledger.get_trade(trade["id"])
        self.assertEqual(stored["status"], "OPEN")
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM paper_account_events WHERE event_type = 'TRADE_REALIZED_PNL'"
            ).fetchone()[0],
            0,
        )

    def test_duplicate_funding_is_idempotent_and_conflicting_reuse_is_rejected(self):
        first = self.accounts.record_funding(
            self.account["id"], event_type="DEPOSIT", amount="250",
            idempotency_key="deposit-1",
        )
        second = self.accounts.record_funding(
            self.account["id"], event_type="DEPOSIT", amount="250",
            idempotency_key="deposit-1",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.accounts.calculate_equity(self.account["id"]), Decimal("10250"))
        with self.assertRaises(PaperAccountError):
            self.accounts.record_funding(
                self.account["id"], event_type="DEPOSIT", amount="300",
                idempotency_key="deposit-1",
            )

    def test_account_events_reject_insert_or_replace_and_currency_mismatch(self):
        event = self.connection.execute(
            "SELECT * FROM paper_account_events WHERE account_id = ?",
            (self.account["id"],),
        ).fetchone()
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT OR REPLACE INTO paper_account_events
                   (id, account_id, event_type, amount, currency_code,
                    idempotency_key, reference_id, occurred_at)
                   VALUES (?, ?, 'OPENING_CAPITAL', '999999', 'USDT',
                           'initial-capital', NULL, ?)""",
                (event["id"], self.account["id"], event["occurred_at"]),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO paper_account_events
                   (id, account_id, event_type, amount, currency_code,
                    idempotency_key, occurred_at)
                   VALUES ('bad-currency', ?, 'DEPOSIT', '10', 'USD',
                           'bad-currency', '2026-11-12T00:00:00Z')""",
                (self.account["id"],),
            )

    def test_withdrawal_cannot_exceed_available_balance(self):
        with self.assertRaises(PaperAccountError):
            self.accounts.record_funding(
                self.account["id"], event_type="WITHDRAWAL", amount="10001",
                idempotency_key="too-large",
            )

    def test_stale_or_unavailable_price_fails_closed_for_open_positions(self):
        self.open_position()
        stale_accounts = PaperAccountService(
            self.connection, FakePriceProvider(age=timedelta(minutes=2))
        )
        stale_execution = PaperExecutionService(
            self.connection,
            risk_engine=RiskEngine(RiskLimits(max_open_positions=2)),
            account_service=stale_accounts,
        )
        with self.assertRaises(StaleMarketPriceError):
            stale_execution.open_position(
                account_id=self.account["id"], symbol="BTCUSDT",
                strategy="ema-rsi", side="LONG", quantity="1",
                stop_price="95",
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'"
            ).fetchone()[0],
            1,
        )

    def test_missing_market_price_fails_closed(self):
        self.open_position()
        unavailable = PaperAccountService(
            self.connection, FakePriceProvider(fail=True)
        )
        execution = PaperExecutionService(self.connection, account_service=unavailable)
        with self.assertRaisesRegex(RuntimeError, "market data unavailable"):
            execution.open_position(
                account_id=self.account["id"], symbol="BTCUSDT",
                strategy="ema-rsi", side="LONG", quantity="1",
                stop_price="95",
            )

    def test_price_snapshots_are_append_only(self):
        self.open_position()
        snapshot = self.connection.execute(
            "SELECT id FROM paper_price_snapshots ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE paper_price_snapshots SET price = '1' WHERE id = ?",
                (snapshot["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM paper_price_snapshots WHERE id = ?",
                (snapshot["id"],),
            )

    def test_concurrent_entries_serialize_for_the_same_account(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "paper.sqlite3")
            setup = connect_database(database_path)
            apply_migrations(setup)
            accounts = PaperAccountService(setup, FakePriceProvider())
            account = accounts.create_account(
                name="Concurrent demo", quote_currency="USDT",
                opening_capital="10000", idempotency_key="concurrent-opening",
            )
            setup.close()

            def attempt(symbol):
                connection = connect_database(database_path)
                try:
                    account_service = PaperAccountService(connection, FakePriceProvider())
                    service = PaperExecutionService(connection, account_service=account_service)
                    return service.open_position(
                        account_id=account["id"], symbol=symbol,
                        strategy="ema-rsi", side="LONG", quantity="1",
                        stop_price="95",
                    )
                except RiskRejectedError as error:
                    return error.reason
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, ["SOLUSDT", "BTCUSDT"]))

            self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
            self.assertEqual(results.count("max_open_positions_reached"), 1)
            verify = connect_database(database_path)
            try:
                self.assertEqual(
                    verify.execute(
                        "SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN' AND paper_account_id = ?",
                        (account["id"],),
                    ).fetchone()[0],
                    1,
                )
            finally:
                verify.close()


if __name__ == "__main__":
    unittest.main()
