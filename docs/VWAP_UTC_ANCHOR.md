# UTC-day anchored VWAP

`calculate_vwap(candles)` returns the volume-weighted typical price for the
UTC calendar day of the final candle only. Candles from previous UTC dates are
ignored. The same rule is used by `/api/signal/v2` and the
AdvancedStrategy backtest indicator series.

Every candle must include `time` or `timestamp`. Supported timestamp forms:

- Unix epoch seconds.
- Unix epoch milliseconds (automatically recognized).
- ISO-8601 strings with an explicit UTC offset or `Z`.
- Timezone-aware Python datetime values.

Naive datetimes and timestamps without timezone information are rejected for
string/datetime inputs rather than silently interpreted in the server's local
timezone. Binance kline open timestamps are converted to epoch seconds by the
live signal endpoint.

If the current UTC day's total volume is zero, VWAP is unavailable (`None`);
the strategy must not manufacture a directional VWAP confirmation.
