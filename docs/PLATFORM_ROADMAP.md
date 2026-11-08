# AI Trader — Financial Intelligence Platform Roadmap

## Product direction

Evolve the existing AI Trader into a personal financial intelligence platform while preserving the current trading application. The platform will bring together:

1. **Personal Finance** — income, expenses, savings, liabilities, cash flow and net worth.
2. **Investment Intelligence** — portfolio positions across stocks, ETFs and crypto, performance, allocation and risk.
3. **AI Trader** — market data, technical indicators, strategies, historical backtests and paper trading.
4. **Market Intelligence** — sourced market news, macroeconomic indicators, events and user-configured alerts.

The application is an analytical and decision-support tool. It must not imply guaranteed returns or execute real trades without a separately approved and explicitly designed capability.

## Current repository baseline (reviewed on main)

- Backend: FastAPI application in `backend/main.py`.
- Market data: Binance public market-data endpoint in `backend/services/market_services.py`.
- Trading logic: indicators in `backend/indicators/`, strategies in `backend/strategies/`, and historical simulation in `backend/services/backtest_service.py`.
- Frontend: standalone Spanish HTML/CSS/JavaScript dashboard in `frontend/index.html`, served by FastAPI at `/dashboard`.
- Current market instrument: SOL/USDT.
- Existing trading endpoints include dashboard, price, candles, signal, signal/v2 and backtest.
- Current operating mode is paper/demo. Preserve it.
- The repository currently has no root dependency manifest or automated test suite in the reviewed file tree.

## Initial technical findings to validate with tests

1. `backend/main.py` duplicates imports and redefines EMA/RSI functions already available under `backend/indicators/`.
2. The v2 signal calculates EMA values from only the most recent 9, 21 and 50 closes. This restarts the EMA seed on each shortened slice and should be replaced with a consistently calculated series after regression tests.
3. RSI and ATR currently use simple rolling averages. If Wilder smoothing is intended, change the formulas only with explicit tests and comparison against known reference values.
4. VWAP is calculated over the full candle batch. The intended anchor/session definition needs to be decided; the current result should not be labelled as session VWAP without that definition.
5. The inline frontend script calls `loadCandles()` before the Lightweight Charts library script is loaded. The initial chart call therefore exits early; the first retry is scheduled 60 seconds later.
6. The dashboard displays a hard-coded demo balance and empty positions. These are placeholders, not persisted account data.
7. CORS currently allows every origin. Restrict this when the deployment model and frontend origin are defined.
8. API exceptions are returned as ordinary response payloads in some routes. Introduce consistent HTTP error handling and logging without leaking internal exception details.
9. Backtest assumptions need further validation, including short-position collateral/margin treatment, candle execution assumptions, and performance metrics. Backtest output must be described as a simulation, not a forecast.

## Architecture principles

- Keep calculations deterministic and testable in Python. Use an LLM only to explain verified application data, compare scenarios and answer questions through explicit tools.
- Every imported or fetched financial datum should retain source, retrieval timestamp, currency, and verification/status metadata where applicable.
- Separate actuals, estimates, forecasts, assumptions and AI-generated commentary.
- Never fabricate missing balances, transactions, prices, returns or portfolio holdings.
- Start with manual entry and CSV import for personal finance; do not require bank credentials for the first release.
- Store secrets in local environment configuration; never commit credentials or ask the user to paste them into chat.
- Keep exchange integration read-only for market data. Maintain paper trading; no live order execution in this roadmap.
- Preserve existing module boundaries where practical and introduce new modules incrementally.
- Use a local SQLite database initially, behind a repository/service boundary so it can be replaced later if needed.

## Proposed target modules

- `backend/api/` — route modules grouped by domain.
- `backend/models/` — validated request/response and domain models.
- `backend/services/` — application services and external data providers.
- `backend/indicators/` and `backend/strategies/` — existing trading logic, hardened with tests.
- New personal-finance domain: accounts, transactions, categories, budgets and net-worth snapshots.
- New portfolio domain: assets, positions, trades, valuations and performance calculations.
- New market-intelligence domain: source adapters, normalized events and alerts.
- Frontend navigation and domain views, retaining Spanish as the initial UI language.

## Delivery sequence

### Phase 0 — Stabilize and test the current application
- Add a dependency manifest based on verified imports and runtime requirements.
- Add deterministic tests for indicators, strategies, market-data normalization and backtesting.
- Fix calculation and frontend initialization issues only after tests capture intended behavior.
- Add consistent validation, error handling and source/timestamp metadata to market responses.

### Phase 1 — Platform foundation
- Introduce configuration, database setup, migrations/schema versioning and repository patterns.
- Add health/status diagnostics and a documented local development workflow.
- Keep current endpoints compatible while adding modular routers.

### Phase 2 — Personal Finance
- Add accounts, categories, transactions, recurring items, budgets and net-worth snapshots.
- Support manual entry and CSV import with duplicate detection and explicit currency handling.
- Do not connect to banks in the initial release.

### Phase 3 — Investment Intelligence
- Add user-entered/imported holdings for stocks, ETFs and crypto.
- Calculate allocation, cost basis where source data permits, unrealized/realized P&L and currency exposure.
- Clearly show missing prices and valuation timestamps.

### Phase 4 — AI assistant and Market Intelligence
- Add source-backed market and macro information.
- Expose narrowly scoped, read-only tools to the AI assistant.
- Require the assistant to distinguish verified facts, calculations, assumptions and opinion.

### Phase 5 — Trading research improvements
- Validate backtest mechanics and add benchmark/robustness analysis.
- Expand paper-trading portfolio and risk controls.
- Keep live trading out of scope unless separately requested and reviewed.

## Working agreement

- All development happens on `feature/financial-platform`.
- Do not commit to or modify `main`.
- Make small, reviewable commits and run available tests before each change.
- Do not delete or rewrite working functionality merely to fit a new architecture.
- Report what changed, what was tested, and what remains unverified after each implementation step.
