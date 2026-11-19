# Persistent PAPER API and OIDC setup

The authenticated `/api/paper/*` routes expose the internal persistent PAPER
ledger. They do not connect to an exchange account, accept exchange
credentials, or submit exchange orders. Market marks are read from Binance's
public ticker endpoint only.

## 1. Configure an OIDC provider

AI Trader accepts a standard OIDC-compatible RS256 JWT issuer. No specific
identity vendor is selected or bundled. Create an API audience/client in the
OIDC provider and configure the exact issuer, audience and public JWKS URL:

```sh
export AI_TRADER_OIDC_ISSUER="https://YOUR-ISSUER/"
export AI_TRADER_OIDC_AUDIENCE="ai-trader-paper"
export AI_TRADER_OIDC_JWKS_URL="https://YOUR-ISSUER/.well-known/jwks.json"
# Optional: default 3600; allowed range 60–86400 seconds.
export AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS="3600"
```

All three settings are required. Issuer and JWKS URL must use HTTPS. Tokens
must be signed with RS256 and contain `iss`, `sub`, `aud`, `iat` and `exp`.
The verifier checks signature, exact issuer, audience, expiry, issue time and
not-before (`nbf`) when present. The maximum access-token lifetime is
configurable with `AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS`: it defaults to
3600 seconds, accepts integer values from 60 through 86400, and has an explicit
hard ceiling of 86400 seconds. A token whose `exp - iat` exceeds the configured
maximum is rejected; `exp` must also be strictly greater than `iat`. This
allows shorter-lived tokens by default while supporting providers whose
configured access-token lifetime is up to 24 hours. The default remains one
hour unless the operator explicitly raises the limit. Clock skew is limited to 30 seconds. JWKS is cached
for five minutes to allow key rotation without a network fetch on every
request.

Automated security coverage exercises the real PAPER route dependency with
short-lived test JWTs: invalid signatures (including a different key with the
same `kid`), wrong issuer/audience, expired tokens, unknown `kid`, unsupported
`alg=none`/HS256, and malformed tokens must all return HTTP 401 (never 500).
Verifier unit tests separately cover required `iss`, `sub`, algorithm and
time/audience claims. These hermetic tests do not replace provider-backed
discovery, TLS/JWKS delivery, browser PKCE or session acceptance.

The API does not provide a local token-issuing endpoint. Obtain access tokens
from the configured OIDC provider using its supported Authorization Code +
PKCE flow in the frontend. Do not embed a client secret in a browser or put
access tokens in source control, URLs or logs.

If OIDC is not configured, authenticated PAPER routes fail closed with HTTP
503. Missing credentials return HTTP 401. An invalid or expired token returns
HTTP 401. Account IDs are never treated as authorization: every account and
trade lookup is scoped to the verified issuer/subject pair.

## 2. Configure persistent storage

```sh
export AI_TRADER_DB_PATH="/absolute/path/to/data/ai_trader.sqlite3"
```

The API applies versioned SQLite migrations when a request opens the database.
Use a persistent local filesystem, back up the database and keep its directory
writable by the application user. Do not use an ephemeral container filesystem
for acceptance testing.

## 3. Configure browser origin

CORS is no longer wildcard. The default allows local frontend origins
`http://localhost:3000` and `http://127.0.0.1:3000`. Override with a comma-
separated allow-list:

```sh
export AI_TRADER_CORS_ORIGINS="http://localhost:3000,https://your-ui.example"
```

CORS is not an authentication mechanism; every PAPER route still requires a
verified Bearer token.

## 4. PAPER API

All money values are returned as decimal strings to avoid JSON floating-point
rounding.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/paper/accounts` | List only the authenticated user's accounts |
| POST | `/api/paper/accounts` | Create account with explicit opening capital |
| GET | `/api/paper/accounts/{id}` | Balance, equity, free cash, open positions and breaker |
| GET | `/api/paper/accounts/{id}/trades` | Account-scoped trade history |
| POST | `/api/paper/accounts/{id}/trades` | Engine-sized PAPER LONG/SHORT entry |
| POST | `/api/paper/accounts/{id}/trades/{trade_id}/close` | Close a PAPER trade |
| POST | `/api/paper/accounts/{id}/funding` | Record simulated deposit/withdrawal/adjustment |
| GET | `/api/paper/accounts/{id}/risk` | Read account circuit breaker |
| POST | `/api/paper/accounts/{id}/halt` | Halt this PAPER account |
| POST | `/api/paper/accounts/{id}/reset` | Explicitly reset this account breaker |
| GET | `/api/paper/accounts/{id}/events` | Account ledger and trade audit events |

Entry requests do not accept quantity. The engine calculates size from
persisted equity, stop distance, fees, slippage and free cash. Idempotency keys
are required for account creation, funding and trade entry.

## 5. Start and verify

Install pinned dependencies, then start the API from the repository root:

```sh
python -m pip install -r requirements.txt
PYTHONPATH=backend python -c "import main; print(main.app.title)"
PYTHONPATH=backend uvicorn main:app --host 127.0.0.1 --port 8000
```

Both the documented repository-root command and `cd backend && python -c "import main"`
are supported. Do not set `PYTHONPATH=backend` after changing into the
`backend` directory; that would point Python at a nested `backend/backend`
path.

Check `/health`, then configure the frontend to obtain an OIDC access token
and send it as `Authorization: Bearer <access-token>`. Create a PAPER account
with explicit fictional capital before opening a simulated trade.

## 6. First API smoke test

Open `http://127.0.0.1:8000/docs`, select **Authorize**, and paste the
OIDC access token. Swagger sends it as a Bearer token. The same flow can be
used from curl:

```sh
export AI_TRADER_ACCESS_TOKEN="ACCESS_TOKEN_FROM_YOUR_OIDC_PROVIDER"

curl -sS http://127.0.0.1:8000/api/paper/accounts \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"

curl -sS -X POST http://127.0.0.1:8000/api/paper/accounts \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acceptance PAPER","quote_currency":"USDT","opening_capital":"10000","idempotency_key":"acceptance-opening-001"}'
```

Use the returned account ID to read equity/free cash, list trades, open a
simulated position and inspect ledger events. Do not paste a real exchange
secret or private key into these requests; the access token is issued by the
OIDC identity provider, not by Binance.

## Safety boundaries

- No live exchange endpoints, order routing or exchange API credentials are
  present in this release.
- No DEMO/TESTNET exchange order adapter is claimed.
- Public ticker data is read-only; a stale/unavailable price blocks equity
  refresh or execution.
- Every PAPER API route requires OIDC identity and account ownership.
- Reset requires explicit confirmation and is audited.
- Internal PAPER balances are fictional ledger values, not exchange balances.

## 7. Automated route-level regression

The backend suite includes `tests/test_paper_oidc_route_integration.py`. It
exercises the actual FastAPI PAPER routes with short-lived RS256 tokens signed
by an ephemeral test-only key, a deterministic in-process JWKS key resolver,
and a temporary SQLite database. It verifies the configured authentication
dependency, missing-token rejection, signature/claim validation, account
creation/read and cross-owner isolation.

This is a hermetic regression test, **not** a real identity-provider
acceptance: it does not exercise external OIDC discovery, HTTPS/TLS delivery
of the provider's JWKS, browser Authorization Code + PKCE, provider sessions
or revocation. The controlled-provider procedure in
`docs/PAPER_RELEASE_ACCEPTANCE.md` remains mandatory before release.
