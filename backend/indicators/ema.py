def calculate_ema_series(values, period):
    if not isinstance(period, int) or isinstance(period, bool) or period < 1:
        raise ValueError("period debe ser un entero positivo")
    if not values:
        return []
    multiplier = 2 / (period + 1)
    result = [float(values[0])]
    for price in values[1:]:
        price = float(price)
        result.append((price - result[-1]) * multiplier + result[-1])
    return result


def calculate_ema(values, period):
    return calculate_ema_series(values, period)[-1]
