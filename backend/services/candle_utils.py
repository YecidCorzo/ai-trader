def filter_closed_candles(candles, now_ms):
    """Exclude still-forming Binance klines using the exchange close-time field."""
    return [
        candle for candle in candles
        if len(candle) > 6 and int(candle[6]) <= now_ms
    ]
