class EmaRsiStrategy:
    """Legacy EMA/RSI crossover strategy used by the 5-minute signal endpoint."""

    def __init__(self, fast_period=9, slow_period=21, rsi_period=14):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period

    def generate_signal(self, ema9, ema21, rsi, prev_ema9, prev_ema21):
        """Emit a signal only on a confirmed EMA crossover.

        The current and previous EMA values must come from consecutive closed
        candles. This keeps the live signal contract aligned with BacktestService.
        """
        if prev_ema9 <= prev_ema21 and ema9 > ema21 and rsi >= 50:
            return "LONG"

        if prev_ema9 >= prev_ema21 and ema9 < ema21 and rsi <= 50:
            return "SHORT"

        return "NEUTRAL"
