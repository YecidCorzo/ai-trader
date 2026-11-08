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
The upstream evaluator is vendored for review. It is not yet wired into the /api/backtest response. The backtest engine still needs independent execution-model fixes and tests before its outputs can be considered reliable.
