# PAPER authentication and account-ownership boundary

## Current implementation status

The persistent PAPER API routes are **mounted** in `backend/main.py` under
`/api/paper/*`. They are protected by `get_verified_principal` and fail closed:
a request without a Bearer credential receives HTTP 401; if OIDC environment
configuration is missing, a request with credentials receives HTTP 503. The routes
are not conditionally removed from the FastAPI application.

The active verifier is `OIDCJWTVerifier` in
`backend/security/oidc_verifier.py`. It uses a configured HTTPS issuer, audience
and JWKS URL; validates RS256 signatures and required `iss`, `sub`, `aud`,
`iat` and `exp` claims; and caches the JWKS client/key set. This is a
provider-neutral JWT/JWKS verifier, not a complete provider integration.

**Release status: BLOCKED pending provider-backed acceptance and security closure.**
No real OIDC provider has yet been configured and exercised end to end. The
current verifier does not implement token/session revocation, provider introspection,
or an explicit maximum access-token lifetime. Authentication time (`auth_time`)
is not required. These are open security decisions, not capabilities to assume.
The verifier uses a configured JWKS URL; OIDC discovery and browser Authorization
Code + PKCE are not implemented by the API.

## Security invariants

1. **Identity comes from the server.** A principal is constructed only after
   server-side bearer-token verification. Request bodies, query parameters, headers
   such as `X-User-Id`, unverified cookies and client-supplied `owner_id` values
   are never identity sources.
2. **Fail closed.** Missing credentials, missing OIDC configuration, invalid
   signatures, wrong issuer/audience, expired or not-yet-valid credentials, and
   unavailable required security state must reject access. There is no anonymous
   fallback or development bypass.
3. **Stable subject.** The principal is the verified pair `(issuer, subject)`,
   not email, display name, username or a mutable profile field.
4. **Persisted ownership.** Every newly created PAPER account is owned by exactly
   one verified principal. Ownership is stored in the database and immutable.
   Legacy rows remain unowned; migrations never guess an owner.
5. **Authorize every object access.** Account, trade, event, balance, equity, risk,
   circuit-breaker and execution operations must prove account ownership. Trade IDs
   are not authorization tokens; trade lookup is scoped by trade ID and account ID.
6. **Prevent enumeration.** A missing account and an account owned by another
   principal should have the same externally visible response (404).
7. **Idempotency is scoped.** Account creation idempotency is scoped to the verified
   issuer/subject; funding and trade-entry keys are scoped to the account.
8. **Workers are not users.** The stop worker is an internal process with database
   access, not an HTTP principal. It is not exposed as a route.
9. **No cross-domain identity.** PAPER ownership is separate from personal finance
   accounts and any future bank/exchange identity. No bank credentials, exchange
   credentials or real-money actions are part of this boundary.

## Principal and verifier

`VerifiedPrincipal` is immutable and contains only verified issuer and subject.
It does not contain the raw credential.

The active verifier requires HTTPS issuer/JWKS configuration, permits RS256 only,
requires `exp`, `iat`, `iss`, `sub` and `aud`, checks signature/issuer/
audience/time claims, and rejects malformed or oversized bearer tokens. Raw tokens
are not persisted in PAPER application tables.

The following are **not currently implemented by the active verifier** and must
not be represented as covered:
- provider session or token revocation checks;
- OAuth token introspection or a revocation/denylist store;
- an explicit maximum permitted `exp - iat` lifetime;
- required `auth_time` or a maximum authentication age;
- OIDC discovery and provider-specific browser sign-in/session handling.

Before release, choose and document a revocation strategy. If short-lived access
tokens are used instead of per-request introspection, define and enforce a maximum
token lifetime and document the residual revocation window. Provider outage and
JWKS key-rotation behavior must be exercised with the selected provider.

## Ownership persistence

Migration `0007_paper_account_ownership.sql` adds verified
`(issuer, subject)` ownership to new PAPER accounts. SQLite constraints/triggers
require both owner fields and prevent ownership changes. Legacy rows remain
explicitly unowned and inaccessible through owner-scoped routes.

Do not backfill historical ownership. Any legacy account that must be recovered
requires a separate, explicit and audited administrative procedure; it must not be
silently claimed by the first user who logs in.

## Authorization and routes

`PaperAuthorizationService` performs account lookups using account ID plus
verified issuer/subject, and trade lookups using trade ID, account ID and verified
owner. Cross-owner and nonexistent resources map to the same not-found response.

The router has a router-level `Depends(get_verified_principal)`; handlers also
request the same dependency to receive the principal. Account creation, listing,
funding, equity, trades, events, risk, halt and reset are therefore authenticated
API surfaces. The stop worker remains an internal process.

The API is currently mounted even when OIDC is not configured; it must fail closed
rather than become anonymously accessible. Do not add a development bypass or
accept account IDs as proof of identity.

## Automated coverage currently present

- Verifier unit tests cover valid RS256 identity, expired token, wrong audience,
  wrong issuer, missing subject, HS256/none rejection, malformed/empty/oversized
  token, JWKS client reuse, missing configuration (503), missing Bearer (401),
  and HTTPS configuration.
- Route-level tests use ephemeral RSA keys, an in-process deterministic JWKS
  resolver and temporary SQLite. They exercise missing credentials, invalid
  signature (including same `kid`), wrong issuer/audience, expired token,
  unknown `kid`, unsupported algorithms, malformed token, account creation/read,
  and cross-owner read isolation.
- These tests are hermetic. They do not prove real provider discovery, external
  TLS/JWKS delivery, browser PKCE, provider session behavior, revocation, or the
  full set of cross-owner write operations.

Additional tests required before release:
- provider-backed token issuance and JWKS/TLS/key-rotation acceptance;
- explicit maximum token lifetime and the chosen revocation/session policy;
- not-yet-valid token and provider/JWKS outage behavior;
- cross-owner attempts to close, fund, halt and reset, plus trade-ID/account-ID
  mismatch cases;
- caller-supplied `owner_id` and `X-User-Id` spoofing at the actual API boundary;
- concurrent idempotency and funding replay behavior at the API boundary;
- verification that legacy unowned accounts remain inaccessible.

## Provider-backed acceptance gate

A real provider test must use a dedicated test tenant/client, two distinct test
identities, HTTPS issuer/JWKS endpoints, and a disposable or dedicated persistent
test database. Use short-lived access tokens and keep them out of source control,
issues, PRs and logs. The test must cover authenticated account creation with
fictional capital, equity read, simulated trade open/close only when market data
and risk gates permit, ledger reconciliation, and cross-owner isolation.

Do not close issue #47 or declare the PAPER release accepted until the provider-backed
test and the outstanding security checks above have evidence. A successful API
smoke test alone is not release acceptance.

## Safety boundary

- PAPER only; all account capital is fictional.
- No exchange account credentials, live endpoints, exchange orders or real funds.
- Binance is used only for public read-only market prices.
- Missing opening capital or stale/missing market marks fail closed.
- Stop monitoring is polling-based and cannot guarantee execution during gaps,
  outages or worker/database failures.
- Passing authentication acceptance does not establish strategy profitability or
  guarantee trading outcomes.
