# Claude Trading Skills integration

## Source and license
- Upstream: https://github.com/tradermonty/claude-trading-skills
- Skill: Backtest Expert
- Upstream source: skills/backtest-expert
- License: MIT; upstream LICENSE is retained in this directory.
- The evaluator scores supplied backtest metrics. It does not validate the trading engine itself or guarantee future performance.

## Integration policy
- Integrate skills incrementally, retaining source attribution and license.
- Skills are analysis/research capabilities, never permission to trade.
- No exchange order execution, credentials, or live-trading pathway is introduced.
- Require deterministic tests, documented inputs/outputs, and explicit decision gates.
- Start with Backtest Expert because the current strategy has negative expectancy.
- Candidate follow-ups: Position Sizer, Technical Analyst, Trader Memory Core, Signal Postmortem, and market-regime analysis. Validate crypto/ETF compatibility and data requirements before adoption; US-equity-specific screeners are not assumed to apply to SOL/USDT.

## Current status
The upstream evaluator is vendored and connected to the /api/backtest response through backend/services/backtest_review.py. It adds a five-dimension quality assessment; this assessment evaluates supplied metrics, not the correctness of the engine or future profitability.

The engine currently:
- Simulates entries at the next candle open and applies configurable fees and slippage.
- Resolves stop/target ambiguity conservatively (stop first) and fills stop gaps at the candle open.
- Marks open positions to market for maximum drawdown, including estimated exit fees.
- Caps short notional using available balance, but does not model exchange margin, maintenance margin, or liquidation. Short-side results therefore remain a simplified paper simulation.

The evaluator's DEPLOY decision is a research verdict only. The API explicitly returns live_trading_authorized=false; no live execution path is enabled. Continue validating accounting, data quality, and execution assumptions before relying on any backtest result.
