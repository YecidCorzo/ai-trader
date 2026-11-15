# Multi-symbol AdvancedStrategy acceptance v2

This branch exists only to execute the pre-registered public-market-data acceptance workflow against the code under review in PR #106.

- Acceptance script: `scripts/run_multi_symbol_advanced_strategy_acceptance.py`
- Frozen configuration: `ADV-MULTI-9USDT-1H-10000-5000-1000-1000-1000-v2`
- Universe: BTC, ETH, BNB, XRP, ADA, DOGE, LINK, LTC, AVAX (USDT pairs)
- Timeframe/history: 1h, 10,000 closed candles per symbol
- Walk-forward: 5,000 train / 1,000 validation / four non-overlapping 1,000-candle OOS folds
- Strategy parameters and acceptance thresholds remain frozen; no optimization is performed.
- Public Binance market data only. No credentials, exchange orders, DEMO/LIVE execution, or real funds.
- The resulting artifact must be retained even when the decision is NO_GO.

This run branch is not a release branch and must not be merged into main.