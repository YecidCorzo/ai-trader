# PAPER authentication and account-ownership boundary

## Status

Design decision for the PAPER-only release. This document does **not** enable account
or execution HTTP routes. The current application has no configured identity provider,
token verifier, session store, or user-management system. Until one is selected and
implemented, account/execution routes must remain absent and the API must not accept
an account ID as proof of identity.

## Security invariants

1. **Identity comes from the server.** A future FastAPI dependency must validate a
   credential using a configured verifier and construct the authenticated principal.
   Request bodies, query parameters, headers such as `X-User-Id`, cookies that have
   not been verified, and client-supplied `owner_id` values are never identity sources.
2. **Fail closed.** Missing verifier configuration, missing credentials, invalid
   signatures, wrong issuer/audience, expired credentials, revoked sessions, or
   unavailable revocation state must reject access. There is no anonymous fallback
   and no development bypass enabled by default.
3. **Stable subject.** The principal is identified by the verified pair
   `(issuer, subject)`, not email, display name, username, or a mutable profile field.
   The verifier must validate issuer and audience and must not accept an unverified JWT
   decode as authentication.
4. **Persisted ownership.** Every newly created PAPER account is owned by exactly one
   verified principal. Ownership is stored in the database and is immutable. Existing
   accounts from before ownership is introduced remain unowned; migration must never
   guess an owner or attach them to the first user who logs in.
5. **Authorize every object access.** Account, trade, event, balance, equity, risk,
   circuit-breaker and execution operations must first prove that the authenticated
   principal owns the account. Trade IDs are not authorization tokens. A trade lookup
   must be scoped by both trade ID and account ID.
6. **Prevent enumeration.** A missing account and an account owned by another
   principal should have the same externally visible response (prefer 404). Do not
   reveal the other owner's existence, identity, balance, trades or metadata.
7. **Idempotency is scoped.** Account creation and funding idempotency keys must be
   scoped to the authenticated owner/account. Reusing another owner's key must not
   disclose or mutate their records.
8. **Workers are not users.** The stop worker is a trusted internal process with
   database access, not an HTTP principal. It must never be exposed as a route or
   accept an account identifier from an untrusted caller.
9. **No cross-domain identity.** PAPER account ownership is separate from personal
   finance accounts and any future bank/exchange identity. No bank credentials,
   exchange credentials or real-money actions are part of this boundary.

## Required implementation contract

### Principal

The authentication adapter must return an immutable principal containing:
- verified issuer;
- stable subject;
- credential/session expiry;
- authentication time and credential identifier where supported.

The adapter must validate signature/algorithm allow-list, issuer, audience, expiry,
not-before, and revocation/session state. It must reject malformed or ambiguous
claims. Secrets and raw credentials must not be logged or persisted in application
tables. The domain authorization layer receives only the verified principal, never
the raw bearer token.

### Ownership persistence

Before exposing account creation, add a migration that associates each new account
with the verified `(issuer, subject)`. Enforce:
- both owner fields are non-empty;
- owner fields cannot be changed after account creation;
- ownership cannot be deleted or reassigned;
- legacy rows remain explicitly unowned and inaccessible through user routes;
- indexes support owner-scoped account listing and lookup.

Do not backfill historical ownership. Any legacy account that must be used again
requires an explicit, audited administrative recovery procedure after the identity
provider is configured; it must not be silently claimed.

### Authorization service and route dependencies

Use one central authorization service/dependency rather than repeating ad-hoc
checks in route handlers. It must:
- reject an absent/invalid principal;
- fetch an account only when both account ID and verified owner match;
- fetch a trade only when trade ID, account ID and owner all match;
- pass the authorized account object to downstream services;
- never let a downstream service infer owner identity from a request payload.

All account/execution routes must depend on this authorization boundary. The default
application configuration must not mount those routes until a real verifier is
configured. A test-only fake verifier may be injected in tests, but must not be
selectable through a production environment flag or public request value.

## Required tests before API routes

- missing principal, invalid signature, wrong issuer/audience, expired token,
  not-yet-valid token and revoked session all fail closed;
- verifier unavailable or revocation state unavailable fails closed;
- caller-supplied `owner_id` and `X-User-Id` cannot override verified identity;
- principal A can list/read/use only A's accounts and trades;
- principal A attempting to read, close, fund, halt or reset principal B's account
  receives the same not-found response as a nonexistent account;
- trade IDs from another account cannot be used even when the trade ID is known;
- account ownership and issuer/subject are immutable at the database layer;
- legacy unowned accounts remain inaccessible and are not auto-claimed;
- account-creation and funding idempotency keys cannot cross owner boundaries;
- concurrent account creation cannot create duplicate ownership or bypass checks;
- no account/execution route is mounted when authentication is unconfigured;
- worker-only stop processing remains internal and is not reachable over HTTP.

## API exposure gate

Do not add account creation, account listing, funding, equity, trade execution,
trade close, circuit-breaker, or stop-management HTTP routes until all required tests
above pass with the selected real verifier and the ownership migration. Before that
point, the existing public market-analysis and backtest endpoints remain read-only
analysis surfaces and must not imply that an account is authenticated or ready.

## Provider selection remains an explicit decision

No identity provider is assumed by this design. A provider must be selected based
on deployment needs, supported verification libraries, session revocation behavior,
and operational ownership. Do not invent a home-grown JWT scheme or ship a placeholder
secret as a substitute. Provider selection and configuration are a separate reviewed
implementation step.
