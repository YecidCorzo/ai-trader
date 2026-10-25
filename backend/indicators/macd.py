def calculate_macd(values, fast_period=12, slow_period=26, signal_period=9):
    if len(values) < slow_period + signal_period:
        return {
            "macd": 0.0,
            "signal": 0.0,
            "histogram": 0.0
        }

    def ema_series(prices, period):
        multiplier = 2 / (period + 1)
        result = [prices[0]]

        for price in prices[1:]:
            result.append(
                (price - result[-1]) * multiplier + result[-1]
            )

        return result

    fast_ema = ema_series(values, fast_period)
    slow_ema = ema_series(values, slow_period)

    macd_values = [
        fast - slow
        for fast, slow in zip(fast_ema, slow_ema)
    ]

    signal_values = ema_series(macd_values, signal_period)

    macd = macd_values[-1]
    signal = signal_values[-1]

    return {
        "macd": macd,
        "signal": signal,
        "histogram": macd - signal
    }
