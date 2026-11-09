# AI Trader — Financial Intelligence Platform Roadmap

## Product direction

Evolve the existing AI Trader into a personal financial intelligence platform while preserving the current trading application. The platform will bring together:

1. **Personal Finance** — income, expenses, savings, liabilities, cash flow and net worth.
2. **Investment Intelligence** — portfolio positions across stocks, ETFs and crypto, performance, allocation and risk.
3. **AI Trader** — market data, technical indicators, strategies, historical backtests and paper trading.
4. **Market Intelligence** — sourced market news, macroeconomic indicators, events and user-configured alerts.

The application is an analytical and decision-support tool. It must not imply guaranteed returns or execute real trades without a separately approved and explicitly designed capability.

## Currency policy

- **SEK is the platform's base/reporting currency.**
- Transactions and assets may retain their original currency, initially including SEK, EUR, USD and COP.
- Never overwrite the original transaction amount or currency when converting.
- Store the FX rate, rate direction, source/provider, effective timestamp and retrieval timestamp used for each conversion.
- Consolidated balances, net worth, reports and portfolio summaries are presented in SEK.
- If a required FX rate is unavailable or stale, show the value as unavailable/estimated with a clear status; never silently assume parity or invent a rate.
- Use decimal-safe arithmetic for money (for example Python `Decimal`), not binary floating-point arithmetic.

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

## Engineering standards and definition of done

Treat this as a maintainable software product with explicit domain boundaries, contracts and quality gates—not a collection of scripts.

- **Architecture:** separate API/transport, domain models, application services and infrastructure/data access. Keep business rules out of route handlers and UI code.
- **Contracts:** validate inputs and outputs; document endpoints; use consistent error response shapes and HTTP status codes.
- **Data integrity:** use database constraints, migrations/schema versioning, stable IDs, timestamps and explicit provenance. Avoid silent data loss and duplicate imports.
- **Money and FX:** use decimal-safe calculations; retain original currency and amount; make every conversion traceable to a specific FX rate and timestamp.
- **Testing:** unit tests for calculations and domain rules; integration tests for database/repository and API behavior; regression tests for existing trading behavior; end-to-end smoke checks for the main user flows.
- **Security:** keep secrets out of source control; validate uploads; restrict CORS; apply least privilege; do not expose internal exceptions or sensitive account data.
- **Observability:** structured logs, useful health checks and actionable error messages without leaking secrets.
- **Maintainability:** type hints, clear naming, small modules, documented setup, reproducible dependencies and focused commits.
- **User experience:** consistent Spanish UI initially, clear empty/loading/error states, and visible source/time/currency/status for financial data.
- **No fake completeness:** demo/sample data must be explicitly labelled. Missing or stale data must remain visibly missing or stale.

A feature is not considered complete merely because it works once on the developer's machine. It must have appropriate tests, documented behavior, error handling and a reproducible way for the user to verify it.

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
- Do not declare the platform ready for user acceptance until the agreed end-to-end acceptance checklist passes and known limitations are documented.


## Implementation log — 2026-11-08

### Verified local smoke checks (user-run)
- `/health` returned `{"status":"ok"}`.
- `/api/price` returned Binance SOL/USDT market data.
- `/api/candles` returned 5-minute OHLCV candles.
- `/api/signal` returned a NEUTRAL signal in paper mode.
- `/api/signal/v2` returned a LONG signal in paper mode.
- `/dashboard` rendered the chart and dashboard.
- `/api/backtest` returned 128 trades, -33.22% return, 0.2437 profit factor, 33.24% drawdown, and 2,144.60 USDT fees on 10,000 USDT initial virtual capital.
- These are user-observed endpoint results, not an independently reproduced test run.

### Changes on feature/financial-platform
- Added an initial conservative backtest review-gate module and unit tests.
- Added a GitHub Actions backend unit-test workflow using Python's standard-library unittest runner.
- Vendored the upstream Claude Trading Skills Backtest Expert evaluator under `backend/skills/backtest_expert/`, retaining the MIT license and source attribution.
- Added conservative stop execution for gaps through stop levels: fill at the worse candle open rather than optimistically at the stop; stop is assumed first if both stop and target are touched in one OHLC candle; target fills do not assume favorable gap improvement.
- Added unit tests for gap-through-stop, same-candle stop/target ordering, target fills and untouched levels.

### Not yet verified / next engineering gates
- CI status has not yet reported a completed run; tests must pass before this work is considered validated.
- The vendored Backtest Expert evaluator is not yet connected to `/api/backtest`.
- The custom review module is an initial gate, not yet a full implementation of the upstream five-dimension scoring and decision framework.
- The backtest engine still needs tests for short collateral assumptions, entry/exit fees, position sizing, equity-curve/intrabar drawdown, end-of-data liquidation, candle validation, and benchmark/stress testing.
- The reported 128-trade backtest is not proof of strategy validity; the negative expectancy is a rejection signal, not a reason to tune parameters until the mechanics are audited.
- Signal endpoint and dashboard disagreement remains open; unify indicators and signal source after regression tests.
- PAPER MODE remains mandatory. No live order execution is implemented or authorized.


## Implementation log — 2026-11-09

### Backtest research foundation (feature/backtest-statistical-research)
- Added chronological expanding-window train/validation/test split utility. Each test window is held out from its corresponding training and validation slices; no random shuffle is used.
- Added seeded iid bootstrap resampling of recorded net trade PnL, reporting final-balance and maximum-drawdown percentiles plus an explicitly defined drawdown-based ruin threshold.
- Added a long-only Buy & Hold baseline using the first candle open and final candle close, charging adverse entry/exit slippage and fees.
- Added standard-library regression tests for chronological boundaries, insufficient history, deterministic Monte Carlo output, invalid samples and benchmark costs.
- These are research utilities only. They are not yet wired into the API or the strategy engine; a caller must supply already validated, completed candles and closed trades.
- Monte Carlo iid resampling does not preserve trade clustering or changing market regimes. Its output is a conditional historical resampling estimate, not a forecast or proof of edge.
- Parameter sensitivity, true rolling out-of-sample strategy reruns, benchmark parity review and API integration remain separate gates.

### Claude Trading Skills integration policy
- Preserve upstream attribution and license for every vendored skill.
- Integrate skills as isolated, testable domain capabilities; do not blindly copy prompts or allow an LLM to perform authoritative accounting or order execution.
- Backtest Expert is the first vendored skill and remains a review layer, not deployment authorization.
- Next candidates for evaluation: position sizing/risk management, market-regime analysis and trading journal/memory. Verify each candidate against the upstream repository and license before adding it.
- All skill outputs must disclose inputs, assumptions, provenance and limitations. No skill can enable live trading.

### Branch and review note
- PRs #14–#16 were merged into their respective stacked feature branches. They are not thereby considered merged into `main`; the branch chain must be reviewed and integrated deliberately.
- The statistical research work is based on the latest VWAP/signal feature branch and is submitted separately for review.
- PAPER MODE remains mandatory.


### Upstream Claude Trading Skills catalog review — 2026-11-09
Reviewed the upstream skill catalog at commit `163ceb48968c71a701dd9cc77d827258d9b5b348` (MIT license). Candidate selection is based on actual skill documentation, not assumed names:

1. **crypto-regime-analyzer** — strong fit for crypto market posture; it uses CoinGecko and Binance public funding data. Integrate only after provider adapters, freshness checks, missing-component handling and rate-limit behavior are independently tested. Its risk-on/off bands are heuristic, not validated allocation instructions.
2. **position-sizer** — useful risk-sizing methodology, but the upstream skill is explicitly long-stock oriented. Reuse only the validated fixed-fractional/ATR concepts after adapting contracts for crypto, fees, slippage, minimum notional and current paper portfolio exposure. Do not import stock-specific share assumptions or Kelly outputs as an order recommendation.
3. **drawdown-circuit-breaker** — valuable as a paper-risk guardrail, but it depends on Trader Memory Core state and uses US Eastern calendar boundaries. Adapt the state contract and timezone policy before integration; it is a recommendation layer, not broker enforcement.
4. **trader-memory-core** — potentially useful for thesis lifecycle and postmortems, but upstream dependencies include YAML/JSON Schema and its accounting explicitly rejects short-equity accounting. Do not import it wholesale into the existing crypto engine; first define a platform-neutral thesis/trade journal model and preserve explicit LONG/SHORT semantics.
5. **portfolio-manager** — not selected for initial integration because its full mode is Alpaca-centric and requires brokerage connectivity. Its offline CSV review can be evaluated later, but no broker credentials or live account access are part of the current scope.

The upstream skill names above are verified candidates, not claims that those skills have already been installed. Backtest Expert remains the only upstream skill vendored so far. Every additional skill will be adapted behind a local interface, with source/license attribution and tests; no third-party script will be allowed to execute trades or override PAPER MODE.


## Strategy profitability research gate — 2026-11-09

### Objective
Find out whether an existing or minimally modified strategy has a repeatable positive net edge on SOL/USDT. This is a research objective, not a promised outcome. Preserve the financial-intelligence platform direction and keep all trading in PAPER MODE.

### Immediate research sequence
1. **Establish a reproducible baseline.** Freeze the current EMA 9/21 + Wilder RSI 14 crossover rules, ATR stop, 2R target, 0.1% fee per side and 0.05% adverse slippage. Record exact candle source, interval, UTC range, retrieval time, and candle count with every run.
2. **Audit the simulator before tuning.** Verify entry at next-candle open, stop/target ordering, gap handling, fee application, sizing, short collateral assumptions, and end-of-data liquidation. Add reference tests for any discrepancy before strategy changes.
3. **Diagnose, do not optimize blindly.** Report LONG and SHORT separately, net expectancy per trade, profit factor, trade count, exposure, average win/loss, drawdown, fees, and benchmark-relative return. A positive aggregate caused by one side or one short period is not sufficient.
4. **Test a small, predeclared hypothesis set.** Compare baseline against simple, explainable variants (trend filter, volatility/regime filter, and long-only/short-only ablations). Change one hypothesis at a time. Do not search a huge parameter grid and select the historical winner.
5. **Use chronological evaluation.** Select parameters only on training/validation windows. Freeze the selected configuration before evaluating the next untouched test window. Keep a final holdout untouched until the research protocol is fixed.
6. **Compare fairly.** Use the same timestamps, instrument, starting capital, fee and slippage assumptions for strategy and Buy & Hold. Report both absolute net return and excess return over the benchmark.
7. **Paper-forward validation.** A historical result is not sufficient for promotion. Run the frozen candidate in paper mode on unseen live market data and compare expected versus realized execution costs.

### Minimum evidence before calling a strategy promising
- At least 100 closed out-of-sample trades across multiple chronological test windows; if the sample cannot reach this, mark evidence as insufficient rather than lowering the bar.
- Positive net expectancy after fees and slippage in aggregate out-of-sample results.
- Profit factor above 1.2 out of sample, with no single window or side masking material losses in the other windows.
- Maximum drawdown below 20% in the evaluated paper portfolio, with exposure and tail losses disclosed.
- Positive net excess return versus Buy & Hold over the same test windows, or a clearly stated risk-adjusted benefit if absolute return is lower.
- No material data leakage, lookahead, survivorship or execution-model issue found in the audit.
- Results repeated on a second market regime and followed by a paper-forward observation period.

These are internal research gates, not guarantees and not financial advice. Passing them means "promising enough for continued paper validation", never automatic live deployment.

### Current known status
- The prior reported EMA/RSI backtest was negative (−33.22% over its reported sample); it is not a viable profitability baseline.
- Existing statistical helpers provide chronological slicing and a simple iid trade-PnL bootstrap, but they do not yet rerun strategy parameter selection across train/validation/test windows.
- The current backtest route fetches up to 5,000 closed 5-minute candles. This is only about 17 days of data at full coverage and is inadequate for robust multi-regime conclusions.
- The advanced strategy's rule score is not a calibrated win probability and is not evidence of positive expectancy.
- No strategy is currently certified profitable. Keep PAPER MODE mandatory.
