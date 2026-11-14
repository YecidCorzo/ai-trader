from datetime import datetime, timezone
import math


def utc_day_key(value):
    """Return the UTC calendar date for epoch seconds/ms or an aware datetime."""
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("El timestamp VWAP debe incluir zona horaria")
        timestamp = timestamp.astimezone(timezone.utc)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("El timestamp VWAP debe ser finito")
        seconds = float(value) / 1000.0 if abs(float(value)) >= 100_000_000_000 else float(value)
        try:
            timestamp = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError("Timestamp VWAP fuera de rango") from error
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Timestamp VWAP inválido") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("El timestamp VWAP debe incluir zona horaria")
        timestamp = timestamp.astimezone(timezone.utc)
    else:
        raise ValueError("Cada vela VWAP debe incluir timestamp UTC")
    return timestamp.date()


def calculate_vwap(candles):
    """Calculate the current UTC day's VWAP; older days are excluded."""
    if not candles:
        return None

    last = candles[-1]
    last_time = last.get("time", last.get("timestamp"))
    current_day = utc_day_key(last_time)
    total_price_volume = 0.0
    total_volume = 0.0

    for candle in candles:
        candle_time = candle.get("time", candle.get("timestamp"))
        if utc_day_key(candle_time) != current_day:
            continue
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        volume = float(candle["volume"])
        values = (high, low, close, volume)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("La vela VWAP contiene valores no finitos")
        if min(high, low, close) <= 0 or volume < 0 or high < max(low, close) or low > min(high, close):
            raise ValueError("La vela VWAP contiene OHLC/volumen inválidos")

        typical_price = (high + low + close) / 3.0
        total_price_volume += typical_price * volume
        total_volume += volume

    if total_volume <= 0:
        return None
    return total_price_volume / total_volume
