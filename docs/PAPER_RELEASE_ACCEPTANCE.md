# PAPER release acceptance checklist

This is an operator-run acceptance procedure for the persistent PAPER API. It uses fictional capital and public read-only market prices. It must never be run against a live exchange account.

## Preconditions

- [ ] Use a controlled test deployment and a dedicated OIDC test tenant/client.
- [ ] Configure `AI_TRADER_OIDC_ISSUER`, `AI_TRADER_OIDC_AUDIENCE` and `AI_TRADER_OIDC_JWKS_URL` with the provider's HTTPS values.
- [ ] Configure `AI_TRADER_DB_PATH` to a persistent, backed-up test database.
- [ ] Start the API and the PAPER stop worker against the same database path.
- [ ] Obtain a short-lived access token from the OIDC provider using its supported Authorization Code + PKCE flow.
- [ ] Keep tokens in the local shell only. Never commit them, paste them into issues/PRs, put them in URLs, or include them in logs.
- [ ] Confirm this is a fresh test database or that the test account ID is known. Do not infer starting capital from legacy trades.

If OIDC is not configured, the PAPER API must fail closed with HTTP 503. A request without a Bearer token must return HTTP 401. Do not bypass these checks to make the test pass.

## 1. Verify API and authentication boundary

```sh
export AI_TRADER_BASE_URL="http://127.0.0.1:8000"
export AI_TRADER_ACCESS_TOKEN="TOKEN_FROM_YOUR_OIDC_TEST_PROVIDER"

curl -i "$AI_TRADER_BASE_URL/health"
curl -i "$AI_TRADER_BASE_URL/api/paper/accounts"
curl -i "$AI_TRADER_BASE_URL/api/paper/accounts" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"
```

Expected:
- `/health` returns HTTP 200.
- PAPER accounts without a token return HTTP 401.
- With a valid token, the account list returns HTTP 200 and only accounts owned by that OIDC issuer/subject.

Also verify an expired token and a token with the wrong audience are rejected with HTTP 401.

## 2. Create a PAPER account with explicit fictional capital

Choose a unique idempotency key for this test run. The example capital below is fictional test capital, not a deposit or exchange balance.

```sh
curl -fsS -X POST "$AI_TRADER_BASE_URL/api/paper/accounts" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Release acceptance PAPER",
    "quote_currency": "USDT",
    "opening_capital": "1000",
    "idempotency_key": "release-acceptance-opening-REPLACE-ME"
  }'
```

Record the returned `account.id` as `ACCOUNT_ID`. Repeat the exact request with the same idempotency key and confirm it does not create a second opening-capital event. Reuse the key with different data and confirm the request is rejected.

```sh
export ACCOUNT_ID="ACCOUNT_ID_FROM_CREATE_RESPONSE"

curl -fsS "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"
```

Expected: balance, equity and free cash are decimal strings; the opening balance is 1000 USDT before any simulated trade; no real funds are moved.

## 3. Verify analysis and simulated trade execution

First request the public, read-only technical analysis:

```sh
curl -fsS "$AI_TRADER_BASE_URL/api/signal/v2"
```

Review the signal, entry, stop, take-profit levels and reasons. A `NEUTRAL` signal is a valid result; do not force a trade just to make the checklist pass.

Only if a controlled test trade is explicitly intended:
1. Select LONG or SHORT based on the returned analysis.
2. Set `STOP_PRICE` on the correct side of the current market price (below entry for LONG, above entry for SHORT).
3. Use the returned account ID and a new unique idempotency key.
4. Do not submit quantity or entry fill; the service must calculate the simulated position size.

```sh
export STOP_PRICE="REPLACE_WITH_REVIEWED_STOP_PRICE"

curl -i -X POST "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID/trades" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"symbol\": \"SOLUSDT\",
    \"strategy\": \"release-acceptance\",
    \"side\": \"LONG\",
    \"stop_price\": \"$STOP_PRICE\",
    \"idempotency_key\": \"release-acceptance-trade-REPLACE-ME\",
    \"risk_fraction\": \"0.01\"
  }"
```

The example uses LONG. For SHORT, change `side` to `SHORT` and ensure the stop is above the current entry. Record the returned `trade.id`. A risk rejection or stale-price response is a safe fail-closed result; investigate it rather than weakening controls.

Close only the test trade created in this step:

```sh
export TRADE_ID="TRADE_ID_FROM_OPEN_RESPONSE"

curl -i -X POST "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID/trades/$TRADE_ID/close" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"exit_reason":"release acceptance test"}'
```

## 4. Reconcile ledger and ownership

```sh
curl -fsS "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"

curl -fsS "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID/trades" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"

curl -fsS "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID/events" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"

curl -fsS "$AI_TRADER_BASE_URL/api/paper/accounts/$ACCOUNT_ID/risk" \
  -H "Authorization: Bearer $AI_TRADER_ACCESS_TOKEN"
```

- [ ] The trade is CLOSED and appears in history.
- [ ] Opening/closing events and realized P&L reconcile with the account balance.
- [ ] Equity/free cash are consistent with the persisted ledger and fresh marks.
- [ ] Replaying the same idempotency key does not duplicate a trade or funding event.
- [ ] A second OIDC test identity cannot list, read, trade, fund, halt or reset the first identity's account (resources should be indistinguishable from not found).
- [ ] Missing/stale market data blocks valuation/execution instead of reusing stale prices.

## 5. Dashboard boundary

Open `/dashboard/` and verify:
- [ ] Price and candles load from the same FastAPI origin.
- [ ] The analysis panel displays the live response from `/api/signal/v2`.
- [ ] A failed analysis request is shown as unavailable, not as a fabricated signal.
- [ ] The analysis button does not create or close a PAPER trade.
- [ ] The general dashboard balance remains clearly unconfigured; it is not an authenticated account view.

The dashboard does not yet implement OIDC sign-in or authenticated PAPER account management. Use the authenticated API/Swagger flow for this acceptance procedure.

## 6. Release decision

Record the deployment, OIDC provider/client configuration identifier (never its secret), database migration version, test identity, timestamps, API results and CI run. Do not record access tokens.

Release acceptance is **PASS** only when every applicable check above is completed and independently reviewed. Otherwise record **BLOCKED** with the exact failed step. A passing API acceptance does not establish strategy profitability or guarantee stop-loss execution during gaps/outages.

## Safety boundary

- PAPER only; all capital is fictional.
- No exchange account credentials, live endpoints, exchange orders or real funds.
- Binance is used only for public read-only market prices.
- Stop monitoring is polling-based and is not guaranteed protection against gaps or worker/database/provider outages.
