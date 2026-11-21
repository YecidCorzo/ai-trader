# Shadow market-data provider comparison

The MarketDataProvider protocol defines the shared read-only price/candle contract for Binance Spot and Bitunix USDT-M Futures. It does not include authentication, balances, positions, orders, leverage, or execution methods.

GET /api/market-data/shadow-comparison compares Binance Spot price with Bitunix Futures lastPrice for SOL/USDT. The signed basis is:

(Bitunix Futures LAST_PRICE - Binance Spot price) / Binance Spot price * 10,000

The default alert threshold is an absolute basis greater than 50 basis points. A positive value means Futures trades at a premium; a negative value means a discount. The endpoint reports ok, alert, or unavailable and caches the comparison for five seconds.

This is a monitoring-only shadow path:
- Binance remains the existing strategy data source.
- Bitunix is not selected by the dashboard's strategy, signal, backtest, position sizing, stops, or risk calculations.
- The Bitunix price used is LAST_PRICE, not MARK_PRICE.
- Provider disagreement does not change signals or create orders.
- An unavailable/invalid provider produces no numeric basis and no false alert.
- No exchange credentials, DEMO/TESTNET, LIVE endpoints, orders, or real funds are used.
