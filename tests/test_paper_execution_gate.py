import json
import unittest
from decimal import Decimal

from backend.infrastructure.database import apply_migrations, connect_database
from backend.services.paper_execution import PaperExecutionService, RiskRejectedError
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

    def test_daily_loss_breach_automatically_halts_until_manual_reset(self):
        with self.assertRaises(RiskRejectedError) as raised:
            self.execution.open_position(
                symbol="SOLUSDT", strategy="ema-rsi", side="LONG",
                quantity="1", entry_price="100", stop_price="95",
                risk_snapshot=self.snapshot(daily_realized_pnl=Decimal("-300")),
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


if __name__ == "__main__":
    unittest.main()
