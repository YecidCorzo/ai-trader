# PAPER authentication and account-ownership boundary

## Current implementation status

The persistent PAPER API routes are mounted in `backend/main.py` under
`/api/paper/*`. They are protected by `get_verified_principal` and fail
closed: a request without a Bearer credential receives HTTP 401; if OIDC
environment configuration is missing, a request with credentials receives
HTTP 503. The routes are not conditionally removed from the FastAPI app.

The active verifier is `OIDCJWTVerifier` in
`backend/security/oidc_verifier.py`. It uses a configured HTTPS issuer,
audience and JWKS URL; validates RS256 signatures and required `iss`, `sub`,
`aud`, `iat` and `exp` claims; and caches the JWKS client/key set. Invalid or
expired credentials return HTTP 401. A JWKS connection failure is classified
as provider unavailability and returns HTTP 503, rather than incorrectly
asking the user to re-authenticate with HTTP 401. This is a provider-neutral
JWT/JWKS verifier, not a complete provider integration.

**Release status: BLOCKED pending additional provider-backed acceptance and
security closure.** A local Keycloak 26.8.2 integration smoke test was completed
on 2026-11-17 (recorded below): Authorization Code + PKCE S256 issued a token
that the API accepted with HTTP 200. This is completed evidence and must not be
repeated as an unstarted setup task. It is not yet full release acceptance:
two-user isolation against the selected provider, provider/JWKS key rotation
and outage behavior, and a documented revocation/session policy remain open.

The active verifier enforces a configurable access-token lifetime through
`AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS` (default 3600 seconds; accepted
range 60–86400 seconds; hard ceiling 86400 seconds), requires `exp > iat`, and
validates `nbf` when present. Token/session revocation, provider introspection,
and required `auth_time` or a maximum authentication age are not implemented.
The verifier uses a configured JWKS URL. The Authorization Code + PKCE flow
was exercised separately against Keycloak, but OIDC discovery, browser
sign-in/session handling and authenticated PAPER account management are not
implemented in the AI Trader dashboard.

## Recorded Keycloak smoke test (2026-11-17)

The following setup and smoke-test steps were completed in the development
environment and are recorded as completed work:

- Keycloak 26.8.2, realm `ai-trader`.
- Issuer: `https://localhost:8443/realms/ai-trader`.
- OIDC client used for the authorization flow: `ai-trader-test`.
- API audience: `ai-trader-api`.
- Authorization Code flow with PKCE method S256 completed successfully.
- Test identity: `trader-test`.
- The returned access token contained a subject and audience values
  `ai-trader-api` and `account`.
- Authenticated API request returned HTTP 200; `/health` returned HTTP 200.

No access token, client secret or private key is stored in this document. The smoke-test result is operator-reported; no sanitized command transcript, CI artifact or other independently reviewable output was retained. Treat it as declared evidence without an attached artifact, not as independently reproducible proof.
This evidence proves that the configured Keycloak token could be exchanged
and accepted by the API in that development setup. It does **not** prove
second-user account isolation with Keycloak, key rotation, provider/JWKS
outage recovery, token revocation, production certificate trust, or the
complete PAPER account/trade/ledger lifecycle. Those remain separate
acceptance checks. The dashboard itself still has no OIDC login UI.

## Security invariants

1. **Identity comes from the server.** A principal is constructed only after
   server-side bearer-token verification. Request bodies, query parameters,
   headers such as `X-User-Id`, unverified cookies and client-supplied
   `owner_id` values are never identity sources.
2. **Fail closed.** Missing credentials, missing OIDC configuration, invalid
   signatures, wrong issuer/audience, expired or not-yet-valid credentials, and
   unavailable required security state must reject access. There is no
   anonymous fallback or development bypass.
3. **Stable subject.** The principal is the verified pair (issuer, subject),
   not email, display name, username or a mutable profile field.
4. **Persisted ownership.** Every newly created PAPER account is owned by
   exactly one verified principal. Ownership is stored in the database and
   immutable. Legacy rows remain unowned; migrations never guess an owner.
5. **Authorize every object access.** Account, trade, event, balance, equity,
   risk, circuit-breaker and execution operations must prove account ownership.
   Trade IDs are not authorization tokens; trade lookup is scoped by trade ID
   and account ID.
6. **Prevent enumeration.** A missing account and an account owned by another
   principal should have the same externally visible response (404).
7. **Idempotency is scoped.** Account-creation idempotency is scoped to the
   verified issuer/subject; funding and trade-entry keys are scoped to the
   account.
8. **Workers are not users.** The stop worker is an internal process with
   database access, not an HTTP principal. It is not exposed as a route.
9. **No cross-domain identity.** PAPER ownership is separate from personal
   finance accounts and any future bank/exchange identity. No bank credentials,
   exchange credentials or real-money actions are part of this boundary.

## Principal and verifier

`VerifiedPrincipal` is immutable and contains only verified issuer and subject.
It does not contain the raw credential.

The active verifier requires HTTPS issuer/JWKS configuration, permits RS256
only, requires `exp`, `iat`, `iss`, `sub` and `aud`, checks
signature/issuer/audience/time claims, validates `nbf` when present, and
rejects malformed or oversized bearer tokens. The maximum `exp - iat`
lifetime is configured by `AI_TRADER_OIDC_MAX_TOKEN_LIFETIME_SECONDS`: default
3600 seconds, minimum 60, hard maximum 86400. `exp` must be strictly greater
than `iat`. Raw tokens are not persisted in PAPER application tables.

The following are **not currently implemented by the active verifier** and
must not be represented as covered:
- provider session or token revocation checks;
- OAuth token introspection or a revocation/denylist store;
- required `auth_time` or a maximum authentication age;
- OIDC discovery and provider-specific browser sign-in/session handling.

The access-token lifetime ceiling is implemented, but it does not revoke a
token before expiry. Before release, choose and document a revocation strategy
and its residual exposure window. Provider outage, external TLS/JWKS delivery
and key-rotation behavior must be exercised with the selected provider.

## Ownership persistence

Migration `0007_paper_account_ownership.sql` adds verified
(issuer, subject) ownership to new PAPER accounts. SQLite constraints/triggers
require both owner fields and prevent ownership changes. Legacy rows remain
explicitly unowned and inaccessible through owner-scoped routes.

Do not backfill historical ownership. Any legacy account that must be
recovered requires a separate, explicit and audited administrative procedure;
it must not be silently claimed by the first user who logs in.

## Authorization and routes

`PaperAuthorizationService` performs account lookups using account ID plus
verified issuer/subject, and trade lookups using trade ID, account ID and
verified owner. Cross-owner and nonexistent resources map to the same
not-found response (404).

The router has a router-level `Depends(get_verified_principal)`; handlers also
request the same dependency to receive the principal. Account creation,
listing, funding, equity, trades, events, risk, halt and reset are therefore
authenticated API surfaces. The stop worker remains an internal process.

The API is mounted even when OIDC is not configured; it must fail closed
rather than become anonymously accessible. Do not add a development bypass or
accept account IDs as proof of identity.

## Automated coverage currently present

The following coverage is present in the current integration line and was
added by merged PRs #122–#125:

- Verifier unit tests cover valid RS256 identity, expired token, wrong
  audience, wrong issuer, missing subject, HS256/none rejection,
  malformed/empty/oversized token, JWKS client reuse, missing configuration
  (503), missing Bearer (401), HTTPS configuration, `nbf` rejection, exact
  3600-second lifetime acceptance, 3601-second rejection, `exp == iat`
  rejection, and environment range/default validation for the configurable
  lifetime ceiling.
- Route-level tests use ephemeral RSA keys, an in-process deterministic JWKS
  resolver and temporary SQLite. They exercise missing credentials, invalid
  signature (including same `kid`), wrong issuer/audience, expired token,
  unknown `kid`, unsupported algorithms, malformed token, account
  creation/read and cross-owner isolation.
- PR #122 adds API-boundary identity-spoofing tests: `X-User-Id`,
  `X-Owner-Id` and caller-supplied owner/user fields do not override the
  verified principal. It also covers account-creation and funding idempotency,
  including conflicting replays.
- PR #123 adds concurrent HTTP-boundary funding replay and concurrent trade
  close coverage. Duplicate requests produce one ledger event/realized-P&L
  event. Earlier service/SQLite tests also cover competing withdrawals and
  transaction rollback; they do not claim distributed locking or
  multi-database coordination.
- PR #124 verifies at the authenticated API boundary that a stale market mark
  (older than the 30-second freshness limit) returns HTTP 503 instead of
  silently reusing a previously persisted fresh mark.
- PR #125 verifies that public price-provider timeout, upstream HTTP 5xx,
  connection failure and invalid/non-positive quotes return HTTP 503 on
  account valuation and trade close, leaving the trade open and writing no
  realized-P&L event.
- The JWKS connection-failure regression verifies that the FastAPI PAPER
  boundary returns HTTP 503 when the configured JWKS provider cannot be
  reached; malformed tokens and unknown signing keys remain HTTP 401.

These tests are hermetic. Separately, the recorded Keycloak smoke test above
proves one successful PKCE token exchange and authenticated API request. The
combined evidence still does not prove provider discovery, production-grade
TLS/JWKS delivery, multi-user provider-backed isolation, provider session
behavior, revocation, or provider outage/key-rotation behavior.

## Remaining provider-backed acceptance gate

The next provider-backed acceptance pass must reuse the already configured
Keycloak test realm/client where available (or a dedicated equivalent), use
two distinct test identities, HTTPS issuer/JWKS endpoints, and a disposable or
dedicated persistent test database. Do not redo the completed single-user
PKCE/API smoke test as if it were missing. Use short-lived access tokens and
keep them out of source control, issues, PRs and logs. The remaining end-to-end
pass must cover authenticated account creation with fictional capital, equity
read, simulated trade open/close only when market data and risk gates permit,
ledger reconciliation, and cross-owner isolation.

The following remain release gates and must have recorded evidence:

- repeatable provider-backed acceptance in the controlled release/test
  deployment (the local Keycloak smoke test is already recorded above);
- verification of two distinct Keycloak identities and cross-owner isolation
  against the persistent PAPER API;
- provider/JWKS key rotation and outage behavior, including the selected
  provider's HTTPS/TLS trust configuration;
- a documented revocation/session policy and its residual exposure window;
- dashboard OIDC sign-in and session handling if the dashboard is to be the
  user-facing PAPER interface (the manual PKCE flow already succeeded, but the
  dashboard does not implement it);
- verification that legacy unowned accounts remain inaccessible using the
  provider-backed acceptance setup;
- complete account creation, simulated trade, close and ledger reconciliation
  using the provider-backed test identity.

Do not close issue #47 or declare the PAPER release accepted until the
provider-backed test and the outstanding security checks above have evidence.
A successful hermetic API test or API smoke test alone is not release
acceptance.

## Dashboard limitation

The analysis dashboard is read-only and does not implement OIDC sign-in or
authenticated PAPER account management. The persistent PAPER API can be
exercised through authenticated API/Swagger requests after an operator obtains
a valid token from the selected provider. Do not describe the dashboard as a
complete authenticated PAPER user experience.

## Safety boundary

- PAPER only; all account capital is fictional.
- No exchange account credentials, live endpoints, exchange orders or real
  funds.
- Binance is used only for public read-only market prices.
- Missing opening capital or stale/missing market marks fail closed.
- Stop monitoring is polling-based and cannot guarantee execution during gaps,
  outages or worker/database failures.
- Passing authentication acceptance does not establish strategy profitability
  or guarantee trading outcomes.
