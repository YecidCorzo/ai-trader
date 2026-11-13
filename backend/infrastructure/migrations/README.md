# Database migrations

Store forward-only SQLite migrations in this directory using the filename
format `NNNN_short_description.sql`, for example
`0001_create_accounts.sql`.

Rules:

- Use the next unused four-digit version; never edit a migration after it has
  been applied to a user's database.
- Keep each migration transactional and avoid SQLite statements that manage
  their own transactions.
- Add tests for both the schema change and migration rollback/idempotency.
- Keep money as integer minor units or decimal strings; do not store monetary
  values as binary floating-point numbers.
- Preserve source currency, source amount, provider and timestamps when
  introducing financial records.

## Initial personal-finance schema

Migration `0001_create_personal_finance_schema.sql` creates currencies,
personal-finance accounts, categories, transactions and optional transaction
valuations. Personal-finance account balances are separate from the PAPER
trading account ledger.

## PAPER trading and account equity

Migrations `0004_paper_trading_ledger.sql` and
`0005_immutable_paper_trade_events.sql` add simulated trades, a persistent
circuit breaker and append-only audit events with durable sequence numbers.

Migration `0006_paper_account_equity.sql` adds explicitly funded PAPER
accounts, append-only capital/P&L events, immutable public-market price
snapshots, and an optional account link on new trades. Legacy trades remain
unassigned and are not used to infer opening capital. A PAPER account requires
an explicit opening-capital event before funding events or linked trades can
be recorded.

PAPER accounts are not connected to personal-finance accounts, real bank
balances or exchange wallets. Migration `0007_paper_account_ownership.sql`
adds immutable issuer/subject ownership for new accounts. Pre-existing rows
remain unowned and are not auto-claimed. Account-creation idempotency keys are
stored as owner-scoped SHA-256 digests.

Provider-neutral principal, fail-closed bearer dependency and owner-scoped
account/trade lookup primitives are implemented, but no production identity
provider is configured and no HTTP account/execution routes are enabled. A
real verifier and its expiry, audience, issuer and revocation tests remain a
gate before any such routes can be added.

Migration `0009_paper_trade_idempotency.sql` adds an account-scoped unique idempotency key to new PAPER trades. Open, close and breaker audit events persist the verified issuer/subject actor; internal stop and risk actions are labeled as system actors.
