import unittest

from backend.services.backtest_service import BacktestService


class BacktestIntrabarDrawdownTests(unittest.TestCase):
    def test_long_intrabar_low_increases_drawdown_vs_close_mark(self):
        _, close_drawdown = BacktestService._update_equity_drawdown(
            balance=10000.0, direction="LONG", entry=100.0, quantity=10.0,
            mark_price=99.0, entry_fee=1.0, fee_rate=0.001,
            peak_equity=10000.0, max_drawdown=0.0,
        )
        _, intrabar_drawdown = BacktestService._update_equity_drawdown(
            balance=10000.0, direction="LONG", entry=100.0, quantity=10.0,
            mark_price=95.0, entry_fee=1.0, fee_rate=0.001,
            peak_equity=10000.0, max_drawdown=0.0,
        )
        self.assertGreater(intrabar_drawdown, close_drawdown)

    def test_short_intrabar_high_increases_drawdown_vs_close_mark(self):
        _, close_drawdown = BacktestService._update_equity_drawdown(
            balance=10000.0, direction="SHORT", entry=100.0, quantity=10.0,
            mark_price=101.0, entry_fee=1.0, fee_rate=0.001,
            peak_equity=10000.0, max_drawdown=0.0,
        )
        _, intrabar_drawdown = BacktestService._update_equity_drawdown(
            balance=10000.0, direction="SHORT", entry=100.0, quantity=10.0,
            mark_price=105.0, entry_fee=1.0, fee_rate=0.001,
            peak_equity=10000.0, max_drawdown=0.0,
        )
        self.assertGreater(intrabar_drawdown, close_drawdown)


if __name__ == "__main__":
    unittest.main()
