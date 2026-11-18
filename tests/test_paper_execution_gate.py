import json
import random
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.infrastructure.database import apply_migrations, connect_database
from backend.security.principal import VerifiedPrincipal
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
        self.principal = VerifiedPrincipal(issuer="https://tests.example", subject="paper-user-1")
        self.accounts = PaperAccountService(self.connection, self.provider)
        self.account = self.accounts.create_account(
            name="Demo account", quote_currency="USDT",
            opening_capital="10000", idempotency_key="initial-capital",
            principal=self.principal,
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
            "stop_price": "95",
            "entry_fee": "0.1",
            "estimated_exit_fee": "0.1",
            "principal": self.principal,
            "idempotency_key": str(uuid4()),
        }
        values.update(overrides)
        return self.execution.open_position(**values)

    def test_account_requires_explicit_opening_capital(self):
        with self.assertRaises(TypeError):
            self.accounts.create_account(
                name="Missing capital", quote_currency="USDT",
                idempotency_key="missing",
                principal=self.principal,
            )
        self.connection.execute(
            "INSERT INTO paper_accounts (id, name, quote_currency, creation_key, created_at, owner_issuer, owner_subject) VALUES ('empty', 'Empty', 'USDT', 'empty-account', '2026-11-12T00:00:00Z', 'https://tests.example', 'paper-user-1')"
        )
        with self.assertRaises(MissingOpeningCapitalError):
            self.accounts.get_account("empty")

    def test_account_creation_is_idempotent_and_rejects_conflicting_reuse(self):
        repeated = self.accounts.create_account(
            name="Demo account", quote_currency="USDT",
            opening_capital="10000", idempotency_key="initial-capital",
            principal=self.principal,
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
                principal=self.principal,
            )

    def test_approved_entry_uses_persisted_account_equity(self):
        trade = self.open_position()
        self.assertEqual(trade["status"], "OPEN")
        self.assertEqual(trade["paper_account_id"], self.account["id"])
        self.assertGreater(Decimal(trade["entry_price"]), Decimal("100"))
        self.assertGreater(Decimal(trade["entry_fee"]), Decimal("0"))
        metadata = json.loads(trade["metadata_json"])
        self.assertLessEqual(Decimal(metadata["planned_loss"]), Decimal("100"))
        self.assertLessEqual(Decimal(metadata["risk_ratio"]), Decimal("0.01"))
        self.assertEqual(self.accounts.get_account(self.account["id"])["quote_currency"], "USDT")

    def test_risk_gate_does_not_accept_caller_controlled_equity(self):
        with self.assertRaises(TypeError):
            self.execution.open_position(
                account_id=self.account["id"], symbol="SOLUSDT",
                strategy="ema-rsi", side="LONG",
                stop_price="95",
                principal=self.principal, idempotency_key="risk-snapshot-test",
                risk_snapshot={"equity": "999999999"},
            )

    def test_risk_limit_uses_account_capital_not_a_caller_snapshot(self):
        small = self.accounts.create_account(
            name="Small demo", quote_currency="USDT",
            opening_capital="100", idempotency_key="small-opening",
            principal=self.principal,
        )
        trade = self.open_position(
            account_id=small["id"], stop_price="95",
            entry_fee="0", estimated_exit_fee="0",
        )
        self.assertLessEqual(
            Decimal(json.loads(trade["metadata_json"])["planned_loss"]),
            Decimal("1"),
        )

    def test_binance_symbol_must_have_a_valid_base_and_exact_quote_asset(self):
        invalid_symbols = [
            "", "USDT", "SOL/USDT", "SOL-USDT", " SOLUSDT",
            "SOLUSDT ", "SOLUSDTXYZ", "SOLUSDTUSDC", "1USDT",
        ]
        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                with self.assertRaises(ValueError):
                    self.open_position(symbol=symbol)

        # The canonical Binance symbol is accepted and stored normalized.
        trade = self.open_position(symbol="SOLUSDT")
        self.assertEqual(trade["symbol"], "SOLUSDT")

    def test_account_quote_asset_must_be_supported_for_binance_spot(self):
        usd = self.accounts.create_account(
            name="USD demo", quote_currency="USD",
            opening_capital="10000", idempotency_key="usd-opening",
            principal=self.principal,
        )
        with self.assertRaisesRegex(ValueError, "no está admitida"):
            self.open_position(account_id=usd["id"], symbol="SOLUSD")

    def test_trade_quote_currency_must_match_account_currency(self):
        usdc = self.accounts.create_account(
            name="USDC demo", quote_currency="USDC",
            opening_capital="10000", idempotency_key="usdc-opening",
            principal=self.principal,
        )
        with self.assertRaisesRegex(ValueError, "cotiza en USDT"):
            self.open_position(account_id=usdc["id"], symbol="SOLUSDT")

    def test_open_positions_and_loss_metrics_are_scoped_to_account(self):
        second = self.accounts.create_account(
            name="Second demo", quote_currency="USDT",
            opening_capital="10000", idempotency_key="second-opening",
            principal=self.principal,
        )
        self.open_position()
        other = self.open_position(account_id=second["id"])
        self.assertEqual(other["paper_account_id"], second["id"])

    def test_circuit_breaker_is_isolated_per_paper_account(self):
        second = self.accounts.create_account(
            name="Independent demo", quote_currency="USDT",
            opening_capital="10000", idempotency_key="independent-opening",
            principal=self.principal,
        )
        self.execution.halt(self.account["id"], "operator requested stop", principal=self.principal)
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
            strategy="test", side="LONG",
            stop_price="99",
            entry_fee="0", estimated_exit_fee="0",
            principal=self.principal, idempotency_key="daily-loss-entry",
        )
        self.provider.price = Decimal("70")
        closed = self.execution.close_position(prior["id"], account_id=self.account["id"], principal=self.principal)
        self.assertLess(self.accounts.calculate_equity(self.account["id"]), Decimal("10000"))
        self.assertLess(Decimal(closed["realized_pnl"]), Decimal("0"))
        self.provider.price = Decimal("100")
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position()
        self.assertEqual(raised.exception.reason, "daily_loss_limit_reached")
        self.assertTrue(self.execution.circuit_breaker_status(self.account["id"])["halted"])

    def test_trade_realized_pnl_is_booked_once_with_trade_close(self):
        trade = self.open_position()
        self.provider.price = Decimal("110")
        closed = self.execution.close_position(
            trade["id"], account_id=self.account["id"], exit_fee="0.1", principal=self.principal
        )
        quantity = Decimal(closed["quantity"])
        gross = quantity * (Decimal(closed["exit_price"]) - Decimal(closed["entry_price"]))
        expected_net = gross - Decimal(closed["entry_fee"]) - Decimal(closed["exit_fee"])
        self.assertEqual(Decimal(closed["realized_pnl"]), expected_net.quantize(Decimal("0.00000001")))
        self.assertLess(Decimal(closed["exit_price"]), Decimal("110"))
        self.assertGreaterEqual(Decimal(closed["exit_fee"]), quantity * Decimal(closed["exit_price"]) * Decimal("0.001"))
        events = self.connection.execute(
            """SELECT amount, idempotency_key FROM paper_account_events
               WHERE account_id = ? AND event_type = 'TRADE_REALIZED_PNL'""",
            (self.account["id"],),
        ).fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(Decimal(events[0]["amount"]), expected_net.quantize(Decimal("0.00000001")))
        self.assertEqual(events[0]["idempotency_key"], f"trade-close:{trade['id']}")

    def test_net_liquidation_equity_matches_immediate_close_for_long_and_short(self):
        for side, stop_price in (("LONG", "95"), ("SHORT", "105")):
            with self.subTest(side=side):
                trade = self.open_position(
                    side=side,
                    stop_price=stop_price,
                    idempotency_key=f"net-equity-{side.lower()}",
                )
                equity_before_close = self.accounts.get_equity(self.account["id"])
                closed = self.execution.close_position(
                    trade["id"],
                    account_id=self.account["id"],
                    principal=self.principal,
                )
                equity_after_close = self.accounts.get_equity(self.account["id"])
                self.assertEqual(closed["status"], "CLOSED")
                self.assertEqual(equity_before_close, equity_after_close)

    def test_invalid_adverse_exit_fill_is_not_reported_as_bad_metadata(self):
        self.open_position()
        now = datetime.now(timezone.utc)
        self.accounts.persist_price_quotes(
            [PriceQuote(
                symbol="SOLUSDT", price=Decimal("0.00000001"),
                source="test-fixture", retrieved_at=now,
            )],
            now=now,
        )
        with self.assertRaisesRegex(PaperAccountError, "Cotización/fill inválido"):
            self.accounts.calculate_equity(self.account["id"], now=now)

    def test_requested_exit_fee_is_used_for_manual_and_stop_closes(self):
        for close_by_stop in (False, True):
            with self.subTest(close_by_stop=close_by_stop):
                self.provider.price = Decimal("100")
                trade = self.open_position(
                    estimated_exit_fee="5",
                    idempotency_key=f"requested-exit-fee-{close_by_stop}",
                )
                metadata = json.loads(trade["metadata_json"])
                self.assertEqual(Decimal(metadata["requested_exit_fee"]), Decimal("5"))
                self.provider.price = Decimal("90")
                if close_by_stop:
                    closed = self.execution.process_stop_losses(self.account["id"])
                    self.assertEqual(len(closed), 1)
                    result = closed[0]
                else:
                    result = self.execution.close_position(
                        trade["id"], account_id=self.account["id"],
                        principal=self.principal,
                    )
                self.assertGreaterEqual(Decimal(result["exit_fee"]), Decimal("5"))

    def test_randomized_multi_position_equity_reconciles_for_manual_and_stop_closes(self):
        rng = random.Random(113114)
        symbols = ("SOLUSDT", "BTCUSDT", "ETHUSDT")
        for side in ("LONG", "SHORT"):
            for case in range(20):
                with self.subTest(side=side, case=case):
                    self.provider.price = Decimal("100")
                    account = self.accounts.create_account(
                        name=f"Property {side} {case}", quote_currency="USDT",
                        opening_capital="10000",
                        idempotency_key=f"property-{side.lower()}-{case}",
                        principal=self.principal,
                    )
                    execution = PaperExecutionService(
                        self.connection,
                        risk_engine=RiskEngine(RiskLimits(max_open_positions=3)),
                        account_service=self.accounts,
                    )
                    self.execution = execution
                    count = rng.randint(2, 3)
                    trades = []
                    for index in range(count):
                        stop = (str(Decimal(rng.randint(9500, 9900)) / 100)
                                if side == "LONG"
                                else str(Decimal(rng.randint(10100, 10500)) / 100))
                        trades.append(self.open_position(
                            account_id=account["id"], symbol=symbols[index],
                            side=side, stop_price=stop, estimated_exit_fee="5",
                            idempotency_key=f"property-{side.lower()}-{case}-{index}",
                        ))
                    gap_price = (Decimal(rng.randint(8000, 9400)) / 100
                                 if side == "LONG"
                                 else Decimal(rng.randint(10600, 12000)) / 100)
                    self.provider.price = gap_price
                    before = self.accounts.get_equity(account["id"])
                    if case % 2:
                        closed = execution.process_stop_losses(account["id"])
                        self.assertEqual(len(closed), count)
                    else:
                        for trade in trades:
                            execution.close_position(
                                trade["id"], account_id=account["id"],
                                principal=self.principal,
                            )
                    after = self.accounts.get_equity(account["id"])
                    self.assertEqual(before, after)

    def test_exit_price_is_market_sourced_and_account_scoped(self):
        trade = self.open_position()
        with self.assertRaises(TypeError):
            self.execution.close_position(
                trade["id"], account_id=self.account["id"], exit_price="999999", principal=self.principal
            )
        other = self.accounts.create_account(
            name="Not owner", quote_currency="USDT",
            opening_capital="10000", idempotency_key="not-owner",
            principal=self.principal,
        )
        with self.assertRaisesRegex(LookupError, "no encontrado"):
            self.execution.close_position(trade["id"], account_id=other["id"], principal=self.principal)

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
            self.execution.close_position(trade["id"], account_id=self.account["id"], principal=self.principal)
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
                strategy="ema-rsi", side="LONG",
                stop_price="95", principal=self.principal,
                idempotency_key="stale-entry",
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
                strategy="ema-rsi", side="LONG",
                stop_price="95", principal=self.principal,
                idempotency_key="unavailable-entry",
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
                principal=self.principal,
            )
            setup.close()

            def attempt(symbol):
                connection = connect_database(database_path)
                try:
                    account_service = PaperAccountService(connection, FakePriceProvider())
                    service = PaperExecutionService(connection, account_service=account_service)
                    return service.open_position(
                        account_id=account["id"], symbol=symbol,
                        strategy="ema-rsi", side="LONG",
                        stop_price="95", principal=self.principal,
                        idempotency_key=f"concurrent-{symbol}",
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


    def test_entry_notional_and_fee_cannot_exceed_free_cash(self):
        self.execution = PaperExecutionService(
            self.connection, risk_engine=RiskEngine(RiskLimits(max_open_positions=2)),
            account_service=self.accounts,
        )
        self.open_position(stop_price="99.99", entry_fee="0", estimated_exit_fee="0")
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position(stop_price="95", entry_fee="1", estimated_exit_fee="0")
        self.assertEqual(raised.exception.reason, "insufficient_free_cash")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'").fetchone()[0], 1)

    def test_total_open_commitment_cannot_exceed_current_equity(self):
        self.execution = PaperExecutionService(
            self.connection, risk_engine=RiskEngine(RiskLimits(max_open_positions=2)),
            account_service=self.accounts,
        )
        self.open_position(stop_price="98.8", entry_fee="0", estimated_exit_fee="0")
        self.provider.price = Decimal("80")
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position(stop_price="79.99", entry_fee="0", estimated_exit_fee="0")
        self.assertEqual(raised.exception.reason, "committed_capital_exceeds_equity")
        self.assertLess(self.accounts.get_equity(self.account["id"]), Decimal("10000"))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'").fetchone()[0], 1)

    def test_withdrawal_cannot_consume_cash_committed_to_open_positions(self):
        self.execution = PaperExecutionService(
            self.connection, risk_engine=RiskEngine(RiskLimits(max_open_positions=2)),
            account_service=self.accounts,
        )
        self.open_position(stop_price="99.99", entry_fee="0", estimated_exit_fee="0")
        with self.assertRaisesRegex(PaperAccountError, "efectivo libre"):
            self.accounts.record_funding(
                self.account["id"], event_type="WITHDRAWAL", amount="1001",
                idempotency_key="withdraw-committed-cash",
            )
        self.assertLess(self.accounts.calculate_free_cash(self.account["id"]), Decimal("1"))

    def test_negative_adjustment_cannot_consume_cash_committed_to_open_positions(self):
        self.execution = PaperExecutionService(
            self.connection, risk_engine=RiskEngine(RiskLimits(max_open_positions=2)),
            account_service=self.accounts,
        )
        self.open_position(stop_price="99.99", entry_fee="0", estimated_exit_fee="0")
        with self.assertRaisesRegex(PaperAccountError, "efectivo libre"):
            self.accounts.record_funding(
                self.account["id"], event_type="ADJUSTMENT", amount="-1001",
                idempotency_key="adjust-committed-cash",
            )
        self.assertLess(self.accounts.calculate_free_cash(self.account["id"]), Decimal("1"))

    def test_third_consecutive_loss_halts_until_reset_then_allows_entry(self):
        self.execution = PaperExecutionService(
            self.connection,
            risk_engine=RiskEngine(RiskLimits(max_daily_loss=Decimal("0.5"))),
            account_service=self.accounts,
        )
        for index in range(3):
            self.provider.price = Decimal("100")
            trade = self.open_position(entry_fee="0", estimated_exit_fee="0")
            self.provider.price = Decimal("99")
            self.execution.close_position(trade["id"], account_id=self.account["id"], principal=self.principal)
            halted = self.execution.circuit_breaker_status(self.account["id"])["halted"]
            self.assertEqual(halted, index == 2)

        self.provider.price = Decimal("100")
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position(entry_fee="0", estimated_exit_fee="0")
        self.assertEqual(raised.exception.reason, "circuit_breaker_halted")

        reset = self.execution.reset_circuit_breaker(
            self.account["id"], principal=self.principal,
        )
        self.assertFalse(reset["halted"])
        metrics = self.execution._repository.risk_metrics(
            day_start="2026-11-13T00:00:00.000000Z",
            day_end="2026-11-14T00:00:00.000000Z",
            loss_streak_limit=3, account_id=self.account["id"],
        )
        self.assertEqual(metrics["consecutive_losses"], 0)
        reopened = self.open_position(entry_fee="0", estimated_exit_fee="0")
        self.assertEqual(reopened["status"], "OPEN")

    def test_open_idempotency_key_returns_same_trade_and_rejects_conflicting_reuse(self):
        first = self.open_position(idempotency_key="stable-open-request")
        repeated = self.open_position(idempotency_key="stable-open-request")
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(repeated["idempotency_key"], "stable-open-request")
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position(idempotency_key="stable-open-request", risk_fraction="0.005")
        self.assertEqual(raised.exception.reason, "idempotency_key_conflict")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM paper_trades WHERE paper_account_id = ?", (self.account["id"],)).fetchone()[0], 1)

    def test_engine_owns_long_and_short_fills_fees_and_sizing(self):
        long_trade = self.open_position(side="LONG", stop_price="95", entry_fee="0", estimated_exit_fee="0")
        long_metadata = json.loads(long_trade["metadata_json"])
        self.assertGreater(Decimal(long_trade["entry_price"]), Decimal(long_metadata["entry_quote"]))
        self.assertGreater(Decimal(long_trade["entry_fee"]), Decimal(long_trade["quantity"]) * Decimal(long_trade["entry_price"]) * Decimal("0.001") - Decimal("0.00000001"))
        self.assertLessEqual(Decimal(long_metadata["planned_loss"]), Decimal("100"))
        self.provider.price = Decimal("110")
        long_closed = self.execution.close_position(long_trade["id"], account_id=self.account["id"], principal=self.principal)
        self.assertLess(Decimal(long_closed["exit_price"]), Decimal("110"))

        self.provider.price = Decimal("100")
        second = self.accounts.create_account(
            name="Short demo", quote_currency="USDT", opening_capital="10000",
            idempotency_key="short-opening", principal=self.principal,
        )
        short_trade = self.open_position(
            account_id=second["id"], side="SHORT", stop_price="105",
            entry_fee="0", estimated_exit_fee="0",
        )
        short_metadata = json.loads(short_trade["metadata_json"])
        self.assertLess(Decimal(short_trade["entry_price"]), Decimal(short_metadata["entry_quote"]))
        self.provider.price = Decimal("90")
        short_closed = self.execution.close_position(short_trade["id"], account_id=second["id"], principal=self.principal)
        self.assertGreater(Decimal(short_closed["exit_price"]), Decimal("90"))

    def test_risk_fraction_cannot_exceed_one_percent_engine_limit(self):
        with self.assertRaises(RiskRejectedError) as raised:
            self.open_position(risk_fraction="0.010001")
        self.assertEqual(raised.exception.reason, "risk_fraction_exceeds_engine_limit")

    def test_quantity_is_not_a_caller_controlled_execution_input(self):
        with self.assertRaises(TypeError):
            self.execution.open_position(
                account_id=self.account["id"], symbol="SOLUSDT", strategy="ema-rsi",
                side="LONG", quantity="999999", stop_price="95",
                principal=self.principal, idempotency_key="caller-quantity",
            )

    def test_verified_actor_is_persisted_on_open_close_halt_and_reset(self):
        trade = self.open_position(idempotency_key="actor-audit-open")
        opened = self.connection.execute(
            "SELECT details_json FROM paper_trade_events WHERE trade_id = ? AND event_type = 'TRADE_OPENED'",
            (trade["id"],),
        ).fetchone()
        expected_actor = {"type": "verified_principal", "issuer": self.principal.issuer, "subject": self.principal.subject}
        self.assertEqual(json.loads(opened["details_json"])["actor"], expected_actor)
        self.provider.price = Decimal("101")
        self.execution.close_position(trade["id"], account_id=self.account["id"], principal=self.principal)
        closed = self.connection.execute(
            "SELECT details_json FROM paper_trade_events WHERE trade_id = ? AND event_type = 'TRADE_CLOSED'",
            (trade["id"],),
        ).fetchone()
        self.assertEqual(json.loads(closed["details_json"])["actor"], expected_actor)
        self.execution.halt(self.account["id"], "audit test", principal=self.principal)
        self.execution.reset_circuit_breaker(self.account["id"], principal=self.principal)
        control_events = self.connection.execute(
            "SELECT event_type, details_json FROM paper_trade_events WHERE trade_id IS NULL ORDER BY sequence DESC LIMIT 2"
        ).fetchall()
        self.assertEqual({row["event_type"] for row in control_events}, {"CIRCUIT_BREAKER_HALTED", "CIRCUIT_BREAKER_RESET"})
        for event in control_events:
            self.assertEqual(json.loads(event["details_json"])["actor"], expected_actor)

if __name__ == "__main__":
    unittest.main()
