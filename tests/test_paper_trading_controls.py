import sqlite3
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

from backend.infrastructure.database import apply_migrations, connect_database
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.risk_engine import RiskEngine, RiskLimits, RiskSnapshot
from backend.services.trade_ledger import TradeLedger


class PaperTradingControlsTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        self.applied = apply_migrations(self.connection)
        self.ledger = TradeLedger(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_migration_adds_paper_ledger_and_initial_unhalted_state(self):
        self.assertIn("0004", self.applied)
        status = CircuitBreaker(self.connection).status()
        self.assertFalse(status["halted"])
        self.assertEqual(status["mode"], "paper")

    def test_long_trade_records_decimal_realized_pnl_and_audit_events(self):
        opened = self.ledger.open_trade(
            symbol="solusdt", strategy="ema-rsi", side="LONG",
            quantity="2", entry_price="100", entry_fee="1",
            opened_at=datetime(2026, 11, 11, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(opened["status"], "OPEN")
        closed = self.ledger.close_trade(
            opened["id"], exit_price="110", exit_fee="1",
            closed_at=datetime(2026, 11, 11, 11, tzinfo=timezone.utc),
            exit_reason="take_profit",
        )
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(Decimal(closed["realized_pnl"]), Decimal("18"))
        events = self.connection.execute(
            "SELECT event_type FROM paper_trade_events WHERE trade_id = ? ORDER BY occurred_at, id",
            (opened["id"],),
        ).fetchall()
        self.assertEqual({row["event_type"] for row in events}, {"TRADE_OPENED", "TRADE_CLOSED"})

    def test_short_trade_calculates_profit_and_loss_direction_correctly(self):
        opened = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="SHORT",
            quantity="3", entry_price="100", entry_fee="0.5",
        )
        closed = self.ledger.close_trade(
            opened["id"], exit_price="90", exit_fee="0.5"
        )
        self.assertEqual(Decimal(closed["realized_pnl"]), Decimal("29"))

    def test_closed_trade_cannot_be_closed_twice(self):
        opened = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="LONG",
            quantity="1", entry_price="10",
        )
        self.ledger.close_trade(opened["id"], exit_price="11")
        with self.assertRaisesRegex(ValueError, "ya está cerrada"):
            self.ledger.close_trade(opened["id"], exit_price="12")

    def test_invalid_trade_values_and_naive_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.open_trade(
                symbol="SOLUSDT", strategy="test", side="LONG",
                quantity="NaN", entry_price="10",
            )
        with self.assertRaises(ValueError):
            self.ledger.open_trade(
                symbol="SOLUSDT", strategy="test", side="LONG",
                quantity="1", entry_price="10",
                opened_at=datetime(2026, 11, 11, 10),
            )

    def test_manual_circuit_breaker_persists_and_requires_operator_reset(self):
        breaker = CircuitBreaker(self.connection)
        halted = breaker.halt("daily loss threshold reached", updated_by="operator")
        self.assertTrue(halted["halted"])
        self.assertEqual(halted["reason"], "daily loss threshold reached")
        with self.assertRaisesRegex(ValueError, "confirmación explícita"):
            breaker.reset(confirmed_by=" ")
        reset = breaker.reset(confirmed_by="operator")
        self.assertFalse(reset["halted"])
        events = self.connection.execute(
            "SELECT event_type FROM paper_trade_events WHERE trade_id IS NULL"
        ).fetchall()
        self.assertEqual(
            {row["event_type"] for row in events},
            {"CIRCUIT_BREAKER_HALTED", "CIRCUIT_BREAKER_RESET"},
        )

    def test_risk_engine_approves_within_limits_and_blocks_violations(self):
        engine = RiskEngine()
        approved = engine.evaluate(RiskSnapshot(
            equity=Decimal("10000"), planned_loss=Decimal("100")
        ))
        self.assertTrue(approved.approved)

        cases = [
            (RiskSnapshot(Decimal("10000"), Decimal("101")), "per_trade_risk_limit_exceeded"),
            (RiskSnapshot(Decimal("10000"), Decimal("50"), daily_realized_pnl=Decimal("-300")), "daily_loss_limit_reached"),
            (RiskSnapshot(Decimal("10000"), Decimal("50"), open_positions=1), "max_open_positions_reached"),
            (RiskSnapshot(Decimal("10000"), Decimal("50"), trades_today=5), "daily_trade_limit_reached"),
            (RiskSnapshot(Decimal("10000"), Decimal("50"), consecutive_losses=3), "consecutive_loss_limit_reached"),
            (RiskSnapshot(Decimal("10000"), Decimal("50"), circuit_breaker_halted=True), "circuit_breaker_halted"),
        ]
        for snapshot, reason in cases:
            with self.subTest(reason=reason):
                decision = engine.evaluate(snapshot)
                self.assertFalse(decision.approved)
                self.assertEqual(decision.reason, reason)

    def test_risk_limits_reject_unsafe_configuration(self):
        with self.assertRaises(ValueError):
            RiskLimits(max_risk_per_trade=Decimal("0.02"))
        with self.assertRaises(ValueError):
            RiskLimits(max_open_positions=0)

    def test_open_rolls_back_trade_when_audit_event_insert_fails(self):
        self.connection.execute("""
            CREATE TRIGGER fail_open_event
            BEFORE INSERT ON paper_trade_events
            WHEN NEW.event_type = 'TRADE_OPENED'
            BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END
        """)
        with self.assertRaises(Exception):
            self.ledger.open_trade(
                symbol="SOLUSDT", strategy="test", side="LONG",
                quantity="1", entry_price="10",
            )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM paper_trade_events").fetchone()[0],
            0,
        )

    def test_close_rolls_back_status_when_audit_event_insert_fails(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="LONG",
            quantity="1", entry_price="10",
        )
        self.connection.execute("""
            CREATE TRIGGER fail_close_event
            BEFORE INSERT ON paper_trade_events
            WHEN NEW.event_type = 'TRADE_CLOSED'
            BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END
        """)
        with self.assertRaises(Exception):
            self.ledger.close_trade(trade["id"], exit_price="11")
        stored = self.ledger.get_trade(trade["id"])
        self.assertEqual(stored["status"], "OPEN")
        self.assertIsNone(stored["closed_at"])
        events = self.ledger._repository.list_events(trade["id"])
        self.assertEqual([event["event_type"] for event in events], ["TRADE_OPENED"])

    def test_invalid_quantity_price_and_fees_are_rejected_without_writes(self):
        invalid_cases = [
            {"quantity": "0", "entry_price": "10", "entry_fee": "0"},
            {"quantity": "-1", "entry_price": "10", "entry_fee": "0"},
            {"quantity": "1", "entry_price": "NaN", "entry_fee": "0"},
            {"quantity": "1", "entry_price": "10", "entry_fee": "-0.01"},
            {"quantity": "1", "entry_price": "10", "entry_fee": "Infinity"},
        ]
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.ledger.open_trade(
                        symbol="SOLUSDT", strategy="test", side="LONG", **values
                    )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0],
            0,
        )

    def test_invalid_exit_price_and_fee_leave_open_trade_unchanged(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="LONG",
            quantity="1", entry_price="10",
        )
        for price, fee in [("0", "0"), ("NaN", "0"), ("11", "-1"), ("11", "Infinity")]:
            with self.subTest(price=price, fee=fee):
                with self.assertRaises(ValueError):
                    self.ledger.close_trade(
                        trade["id"], exit_price=price, exit_fee=fee
                    )
        self.assertEqual(self.ledger.get_trade(trade["id"])["status"], "OPEN")

    def test_consecutive_losses_follow_close_event_order_when_timestamps_tie(self):
        same_close_time = datetime(2026, 11, 11, 10, tzinfo=timezone.utc)
        deterministic_ids = [
            UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),  # Earlier losing trade ID.
            UUID("11111111-1111-1111-1111-111111111111"),
            UUID("22222222-2222-2222-2222-222222222222"),
            UUID("00000000-0000-0000-0000-000000000000"),  # Later winning trade ID.
            UUID("33333333-3333-3333-3333-333333333333"),
            UUID("44444444-4444-4444-4444-444444444444"),
        ]
        with patch("backend.services.trade_ledger.uuid4", side_effect=deterministic_ids):
            losing = self.ledger.open_trade(
                symbol="SOLUSDT", strategy="test", side="LONG",
                quantity="1", entry_price="10",
                opened_at=datetime(2026, 11, 11, 9, tzinfo=timezone.utc),
            )
            self.ledger.close_trade(
                losing["id"], exit_price="9", closed_at=same_close_time
            )
            winning = self.ledger.open_trade(
                symbol="BTCUSDT", strategy="test", side="LONG",
                quantity="1", entry_price="10",
                opened_at=datetime(2026, 11, 11, 9, tzinfo=timezone.utc),
            )
            self.ledger.close_trade(
                winning["id"], exit_price="11", closed_at=same_close_time
            )

        self.connection.execute("VACUUM")
        metrics = self.ledger._repository.risk_metrics(
            day_start="2026-11-11T00:00:00Z",
            day_end="2026-11-12T00:00:00Z",
            loss_streak_limit=3,
        )
        self.assertEqual(metrics["consecutive_losses"], 0)

    def test_daily_metrics_use_microsecond_inclusive_start_and_exclusive_end(self):
        self.ledger.open_trade(
            symbol="SOLUSDT", strategy="boundary", side="LONG", quantity="1", entry_price="10",
            opened_at=datetime.fromisoformat("2026-11-12T23:59:59.999999+00:00"),
        )
        self.ledger.open_trade(
            symbol="BTCUSDT", strategy="boundary", side="LONG", quantity="1", entry_price="10",
            opened_at=datetime.fromisoformat("2026-11-13T00:00:00.000000+00:00"),
        )
        self.ledger.open_trade(
            symbol="ETHUSDT", strategy="boundary", side="LONG", quantity="1", entry_price="10",
            opened_at=datetime.fromisoformat("2026-11-14T00:00:00.000000+00:00"),
        )
        metrics = self.ledger._repository.risk_metrics(
            day_start="2026-11-13T00:00:00.000000Z",
            day_end="2026-11-14T00:00:00.000000Z", loss_streak_limit=3,
        )
        self.assertEqual(metrics["trades_today"], 1)
        self.assertEqual(metrics["daily_realized_pnl"], Decimal("0"))

    def test_audit_events_reject_updates_and_deletes(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="LONG",
            quantity="1", entry_price="10",
        )
        event = self.connection.execute(
            "SELECT id, details_json FROM paper_trade_events WHERE trade_id = ?",
            (trade["id"],),
        ).fetchone()

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE paper_trade_events SET details_json = '{}' WHERE id = ?",
                (event["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM paper_trade_events WHERE id = ?",
                (event["id"],),
            )

        stored = self.connection.execute(
            "SELECT details_json FROM paper_trade_events WHERE id = ?",
            (event["id"],),
        ).fetchone()
        self.assertEqual(stored["details_json"], event["details_json"])


    def test_insert_or_replace_cannot_overwrite_audit_event_when_recursive_triggers_off(self):
        trade = self.ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="LONG",
            quantity="1", entry_price="10",
        )
        event = self.connection.execute(
            """SELECT sequence, id, trade_id, event_type, details_json, occurred_at
               FROM paper_trade_events WHERE trade_id = ?""",
            (trade["id"],),
        ).fetchone()

        self.connection.execute("PRAGMA recursive_triggers = OFF")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT OR REPLACE INTO paper_trade_events
                   (id, trade_id, event_type, details_json, occurred_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event["id"], event["trade_id"], event["event_type"],
                    '{"tampered": true}', event["occurred_at"],
                ),
            )

        stored = self.connection.execute(
            """SELECT sequence, details_json FROM paper_trade_events
               WHERE id = ?""",
            (event["id"],),
        ).fetchone()
        self.assertEqual(stored["sequence"], event["sequence"])
        self.assertEqual(stored["details_json"], event["details_json"])


if __name__ == "__main__":
    unittest.main()
