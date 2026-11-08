def calculate_rsi_series(closes, period=14):
    """Return RSI values using Wilder's smoothed moving average.

    Values before the first complete period are None. Flat series return 50,
    while a series with gains and no losses returns 100.
    """
    if period < 1:
        raise ValueError("period debe ser positivo")

    values = [float(value) for value in closes]
    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    def to_rsi(avg_gain, avg_loss):
        if avg_gain == 0 and avg_loss == 0:
            return 50.0
        if avg_loss == 0:
            return 100.0
        relative_strength = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    result[period] = to_rsi(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        result[index] = to_rsi(average_gain, average_loss)

    return result


def calculate_rsi(closes, period=14):
    values = calculate_rsi_series(closes, period)
    return values[-1] if values and values[-1] is not None else 50.0
