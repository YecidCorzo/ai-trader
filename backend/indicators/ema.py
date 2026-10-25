def calculate_ema(values, period):
    multiplier = 2 / (period + 1)
    ema = values[0]

    for price in values[1:]:
        ema = (price - ema) * multiplier + ema

    return ema