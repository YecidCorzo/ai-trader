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

Migration `0001_create_personal_finance_schema.sql` creates:

- `currencies`: ISO-style currency codes and minor-unit precision; the initial
  reference set is SEK, EUR, USD and COP.
- `accounts`: user-managed account metadata and its default currency.
- `categories`: income/expense categories with optional parent categories.
- `transactions`: immutable source amount in integer minor units and its
  original currency. A transaction is not converted in place.
- `transaction_valuations`: optional reporting-currency values with the FX
  rate stored as decimal text, a documented `base_per_unit` convention,
  provider, effective/retrieved timestamps and actual/estimated status.

The reporting-currency default is SEK. Valuations are optional because an FX
rate may be unavailable; callers must not invent a rate or silently assume
parity. Account balances are derived from transactions in a later application
service, not stored as a second mutable source of truth in this initial schema.
