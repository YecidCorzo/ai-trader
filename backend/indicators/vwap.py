def calculate_vwap(candles):
    if not candles:
        return 0.0

    total_price_volume = 0.0
    total_volume = 0.0

    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        volume = float(candle["volume"])

        typical_price = (high + low + close) / 3

        total_price_volume += typical_price * volume
        total_volume += volume

    if total_volume == 0:
        return 0.0

    return total_price_volume / total_volume

