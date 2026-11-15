# PAPER account, trade ledger and risk controls

Everything in this module is simulated. It does not connect to an exchange
account, submit exchange orders, transfer funds, or enable live trading.
The HTTP API described below operates only on the internal PAPER ledger.

## Explicit PAPER account capital

A PAPER account is separate from personal-finance accounts and bank balances.
Creating it requires an explicit opening capital, quote currency and
idempotency key; there is no default balance and no assumed 10,000-unit
starting amount.

New accounts have an immutable verified owner (`issuer` + stable `subject`).
The owner-scoped account-creation idempotency key is stored as a SHA-256 digest.
Legacy accounts and trades created before the account migration remain
unassigned; they are not attached to a new account and their history is never
used to infer or invent starting capital.

Opening capital, deposits, withdrawals, adjustments and realized trade P&L are
stored as append-only account events. Funding events require an idempotency key:
reusing it with identical data returns the original event, while conflicting
reuse is rejected. Withdrawals and negative adjustments cannot consume cash
committed to open positions. All events use the account's quote currency.

## Market valuation and equity

The default read-only price provider uses Binance's public
`https://data-api.binance.vision/api/v3/ticker/price` endpoint. It needs no API
key or exchange credentials. The ticker response does not provide a trusted
exchange event timestamp, so the application records local retrieval time;
this must not be described as an exchange-generated timestamp.

Price snapshots are append-only. The default maximum age is 30 seconds.
Missing, malformed, future-dated or stale prices for any open position fail
closed; the service does not silently reuse a stale mark or assume a price.
The provider can be replaced in tests by an injected provider that returns a
`PriceQuote` with a source and timezone-aware retrieval timestamp.

Equity is calculated as:

`account event balance + unrealized P&L on open positions - their entry fees`

Realized P&L is posted to the account ledger in the same SQLite transaction as
the trade-close and audit events. The amount is net of entry and exit fees.
Position marks use Decimal arithmetic and the stored quote currency; the market
symbol's quote asset must match the PAPER account currency. There is no
implicit FX conversion.

## Trade execution and risk gate

The internal `PaperExecutionService` contract is account-scoped and requires
a `VerifiedPrincipal`. The caller supplies the account, symbol, strategy,
direction, stop and idempotency key. The service obtains the entry quote from
the public market provider, derives equity from persisted account events and
fresh price snapshots, and calculates quantity from the risk budget and
available cash. The caller cannot provide quantity, equity, an entry fill, an
exit fill or a caller-built risk snapshot.

The service applies adverse simulated slippage and fees before sizing. The
optional risk fraction is capped at 1% of persisted account equity. A failed
risk check creates no trade. Account IDs scope open positions, daily trade
counts, realized daily P&L and loss streaks. Concurrent entry checks serialize
through a SQLite write transaction.

A close also requires the verified owner and account ID. The service obtains a
fresh public market quote; callers cannot choose the simulated exit price.

Default conservative limits:

- Maximum planned loss per trade: 1% of current account equity.
- Maximum realized daily loss: 3% of current account equity.
- Maximum open positions: 1 per PAPER account.
- Maximum trades per day: 5 per PAPER account.
- Maximum consecutive losses: 3 per PAPER account.

Opening and closing prices, quantities and fees are stored as decimal strings.
LONG and SHORT realized P&L is calculated with Decimal. Opening and closing
actions produce append-only audit events with durable sequence numbers.
Account events and price snapshots reject updates, deletes and replacement
attempts. A closed trade cannot be closed a second time.

**Planned risk is not a guaranteed maximum loss.** The stop worker is
polling-based. A price can gap beyond the configured stop between polls, so a
simulated fill can be worse than the stop. One recorded scenario realized
194 USDT against 100 USDT planned risk (1.94× the plan); this is an observed
example, not a prediction of typical slippage or a maximum bound.

## Authenticated PAPER HTTP API

The FastAPI application mounts the owner-scoped router at `/api/paper`.
Every route requires an `Authorization: Bearer <OIDC access token>` header.
The server validates the token and derives the account owner from its verified
issuer and subject claims. An account ID by itself never grants access.

Configure these environment variables in the API runtime:

- `AI_TRADER_OIDC_ISSUER`: exact HTTPS issuer expected in the token.
- `AI_TRADER_OIDC_AUDIENCE`: expected token audience.
- `AI_TRADER_OIDC_JWKS_URL`: HTTPS URL for the issuer's JSON Web Key Set.

The verifier accepts RS256-signed JWTs and validates signature, issuer,
audience, expiry, issued-at time and subject. The JWKS set is cached by the
verification client. If the Bearer token is missing or invalid/expired, the API
returns 401. If OIDC is not configured, it returns 503 and fails closed.

This is provider-neutral token verification, not a bundled identity provider
or a browser sign-in implementation. The deployment owner must configure an
OIDC provider and perform a real provider-backed acceptance test before
relying on the HTTP account API. No user tokens, private keys, client secrets
or other credentials belong in the repository, PRs or logs. Do not paste
personal credentials into development tools.

Available routes:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/paper/accounts` | List accounts owned by the verified principal; includes ledger balance |
| POST | `/api/paper/accounts` | Create an account with explicit opening capital and an idempotency key |
| GET | `/api/paper/accounts/{account_id}` | Read account balance, fresh-mark equity, free cash, open positions and risk status |
| GET | `/api/paper/accounts/{account_id}/trades` | List that account's OPEN/CLOSED trades |
| POST | `/api/paper/accounts/{account_id}/trades` | Open a PAPER trade; server calculates quantity and simulated entry fill |
| POST | `/api/paper/accounts/{account_id}/trades/{trade_id}/close` | Close a PAPER trade at a fresh public quote |
| POST | `/api/paper/accounts/{account_id}/funding` | Record an idempotent simulated deposit, withdrawal or adjustment |
| GET | `/api/paper/accounts/{account_id}/risk` | Read account circuit-breaker status |
| POST | `/api/paper/accounts/{account_id}/halt` | Halt that PAPER account |
| POST | `/api/paper/accounts/{account_id}/reset` | Reset after explicit confirmation |
| GET | `/api/paper/accounts/{account_id}/events` | Read account funding and trade audit events |

The trade-open request accepts `symbol`, `strategy`, `side` (`LONG` or
`SHORT`), `stop_price`, `idempotency_key`, and an optional
`risk_fraction` no greater than 0.01. It does not accept a quantity or price
fill. The close request accepts an optional exit-fee estimate and reason, not
an exit price. Funding requests are ledger events only; they do not move money
or connect to a bank or exchange account.

The API responses explicitly report `live_trading_authorized: false`. No
exchange credentials, live endpoints, real funds or live order-routing
capabilities are part of this API.

The general `/api/dashboard` endpoint remains a static unconfigured placeholder
and is not linked to the authenticated account. Use
`GET /api/paper/accounts/{account_id}` for owner-scoped account balance and
equity. Do not interpret the placeholder dashboard response as account state.

## Circuit breaker

The halt state persists in SQLite per PAPER account and reset requires
explicit confirmation. One account's circuit breaker does not halt another
account. The legacy global breaker remains available only for older internal
callers; account-based execution always uses the account-scoped breaker.

## Automatic PAPER stop-loss monitoring

The stop level is monitored by a separate polling worker. Start it alongside
the API, using the same database path:

```bash
python -m backend.services.paper_stop_worker
```

The worker scans funded PAPER accounts with open positions, retrieves fresh
public Binance ticker prices, and closes positions when the observed price is
at or beyond the configured stop:

- LONG: observed price is less than or equal to the stop.
- SHORT: observed price is greater than or equal to the stop.

The simulated exit fill uses the observed market quote, not the configured
stop price. The worker defaults to a one-second polling interval; set
`AI_TRADER_STOP_POLL_SECONDS` to change it. It uses the same
`AI_TRADER_DB_PATH` environment variable as the API and applies pending
migrations at startup.

If the worker is stopped, the database is unavailable, or market data is
stale/unavailable, no automatic stop execution occurs during that period.
Keep the worker running under a process supervisor for continuous monitoring.
This does not guarantee a maximum loss and must never be described as
real-money stop protection.

## Release and safety boundary

- PAPER only: no real funds, bank integration, exchange account credentials,
  live endpoints or live orders.
- Binance is used only for public read-only ticker data.
- Missing opening capital or stale/missing market marks fail closed.
- Legacy trades remain unassigned; no historical starting balance is inferred.
- The OIDC verifier is implemented, but a real provider-backed deployment
  acceptance test remains an environment-level release gate.
- This is a risk-control gate, not a guarantee against loss or a live-trading
  authorization.
