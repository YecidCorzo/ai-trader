class EmaRsiStrategy:

    def __init__(self, fast_period=9, slow_period=21, rsi_period=14):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period

    def generate_signal(self, ema9, ema21, rsi):
        if ema9 > ema21 and rsi >= 50:
            return "LONG"

        if ema9 < ema21 and rsi <= 50:
            return "SHORT"

        return "NEUTRAL"