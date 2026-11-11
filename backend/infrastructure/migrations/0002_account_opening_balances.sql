-- Explicit opening balances are required before an account can report a current balance.
CREATE TABLE account_opening_balances (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL CHECK (amount_minor BETWEEN -9000000000000000 AND 9000000000000000),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON UPDATE RESTRICT ON DELETE RESTRICT,
    as_of TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
