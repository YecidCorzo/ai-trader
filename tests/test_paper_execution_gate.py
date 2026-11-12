import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from backend.infrastructure.database import apply_migrations, connect_database
from backend.services.paper_execution import PaperExecutionService, RiskRejectedError
from backend.services.trade_ledger import TradeLedger
from backend.services.risk_engine import RiskEngine, RiskLimits, RiskSnapshot


class PaperExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")
        apply_migrations(self.connection)
        self.execution = PaperExecutionService(self.connection)

    def tearDown(self):
        self.connection.close()

    def snapshot(self, **overrides):
        values = {
            "equity": Decimal("10000"),
            "planned_loss": Decimal("1"),  # Recomputed from entry/stop by the service.
            "daily_realized_pnl": Decimal("0"),
            "open_positions": 0,  # Recomputed from the ledger by the service.
            "trades_today": 0,
            "consecutive_losses": 0,
        }
        values.update(overrides)
        return RiskSnapshot(**values)

    def test_approved_entry_is_recorded_as_paper_and_stop_risk_is_audited(self):
        trade = self.execution.open_position(
            symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
            quantity="1", entry_price="100", stop_price="95",
            risk_snapshot=self.snapshot(), entry_fee="0.1",
            estimated_exit_fee="0.1",
        )
        self.assertEqual(trade["status"], "OPEN")
        metadata = json.loads(trade["metadata_json"])
        self.assertEqual(metadata["mode"], "paper")
        self.assertEqual(metadata["stop_price"], "95")
        self.assertEqual(metadata["planned_loss"], "5.2")

    def test_actual_open_position_count_blocks_second_entry(self):
        self.execution.open_position(
            symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
            quantity="1", entry_price="100", stop_price="95",
            risk_snapshot=self.snapshot(),
        )
        with self.assertRaises(RiskRejectedError) as raised:
            self.execution.open_position(
                symbol="BTCUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="95",
                risk_snapshot=self.snapshot(),
            )
        self.assertEqual(raised.exception.reason, "max_open_positions_reached")

    def test_risk_over_one_percent_rejects_entry(self):
        with self.assertRaises(RiskRejectedError) as raised:
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="3", entry_price="100", stop_price="95",
                risk_snapshot=self.snapshot(equity=Decimal("1000")),
            )
        self.assertEqual(raised.exception.reason, "per_trade_risk_limit_exceeded")

    def test_daily_loss_is_derived_from_ledger_not_caller_snapshot(self):
        ledger = TradeLedger(self.connection)
        prior = ledger.open_trade(
            symbol="SOLUSDT", strategy="test", side="LONG",
            quantity="10", entry_price="100",
        )
        ledger.close_trade(prior["id"], exit_price="70")

        with self.assertRaises(RiskRejectedError) as raised:
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="95",
                # Deliberately lie about the counters: persisted ledger must win.
                risk_snapshot=self.snapshot(daily_realized_pnl=Decimal("0")),
            )
        self.assertEqual(raised.exception.reason, "daily_loss_limit_reached")
        self.assertTrue(self.execution.circuit_breaker_status()["halted"])
        with self.assertRaises(RiskRejectedError) as halted:
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="95",
                risk_snapshot=self.snapshot(),
            )
        self.assertEqual(halted.exception.reason, "circuit_breaker_halted")

        self.execution.reset_circuit_breaker(confirmed_by="operator")
        self.assertFalse(self.execution.circuit_breaker_status()["halted"])

    def test_manual_halt_blocks_entry(self):
        self.execution.halt("operator requested stop")
        with self.assertRaises(RiskRejectedError) as raised:
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="95",
                risk_snapshot=self.snapshot(),
            )
        self.assertEqual(raised.exception.reason, "circuit_breaker_halted")

    def test_invalid_stop_side_is_rejected_before_any_ledger_write(self):
        with self.assertRaisesRegex(ValueError, "stop de LONG"):
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="101",
                risk_snapshot=self.snapshot(),
            )
        count = self.connection.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        self.assertEqual(count, 0)

    def test_daily_trade_count_and_loss_streak_are_derived_from_ledger(self):
        ledger = TradeLedger(self.connection)
        for index in range(3):
            trade = ledger.open_trade(
                symbol="SOLUSDT", strategy="test", side="LONG",
                quantity="1", entry_price="10",
            )
            ledger.close_trade(trade["id"], exit_price="9")

        with self.assertRaises(RiskRejectedError) as raised:
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="95",
                risk_snapshot=self.snapshot(
                    daily_realized_pnl=Decimal("0"),
                    trades_today=0,
                    consecutive_losses=0,
                ),
            )
        self.assertEqual(raised.exception.reason, "consecutive_loss_limit_reached")

    def test_concurrent_entries_serialize_and_only_one_position_is_open(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "paper.sqlite3")
            setup = connect_database(database_path)
            apply_migrations(setup)
            setup.close()

            def attempt(symbol):
                connection = connect_database(database_path)
                try:
                    service = PaperExecutionService(connection)
                    return service.open_position(
                        symbol=symbol, strategy="ema-rsi", side="LONG",
                        quantity="1", entry_price="100", stop_price="95",
                        risk_snapshot=self.snapshot(),
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
                        "SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'"
                    ).fetchone()[0],
                    1,
                )
            finally:
                verify.close()


if __name__ == "__main__":
    unittest.main()
