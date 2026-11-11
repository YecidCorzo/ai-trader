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
