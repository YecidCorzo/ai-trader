-- First personal-finance schema. Monetary values are integer minor units.
CREATE TABLE currencies (
    code TEXT PRIMARY KEY CHECK (length(code) = 3 AND code = upper(code)),
    minor_unit INTEGER NOT NULL CHECK (minor_unit BETWEEN 0 AND 4),
    name TEXT NOT NULL
);

INSERT INTO currencies (code, minor_unit, name) VALUES
    ('SEK', 2, 'Swedish krona'),
    ('EUR', 2, 'Euro'),
    ('USD', 2, 'US dollar'),
    ('COP', 2, 'Colombian peso');

CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    account_type TEXT NOT NULL CHECK (
        account_type IN ('cash', 'bank', 'credit_card', 'savings', 'investment', 'other')
    ),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON UPDATE RESTRICT ON DELETE RESTRICT,
    institution TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    category_type TEXT NOT NULL CHECK (category_type IN ('income', 'expense')),
    parent_id TEXT REFERENCES categories(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (name, category_type, parent_id)
);

CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    category_id TEXT REFERENCES categories(id) ON UPDATE RESTRICT ON DELETE SET NULL,
    transaction_type TEXT NOT NULL CHECK (
        transaction_type IN ('income', 'expense', 'transfer', 'adjustment')
    ),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON UPDATE RESTRICT ON DELETE RESTRICT,
    description TEXT,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (length(trim(source)) > 0),
    external_reference TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (account_id, source, external_reference)
);

CREATE INDEX idx_transactions_account_occurred
    ON transactions (account_id, occurred_at DESC);
CREATE INDEX idx_transactions_category_occurred
    ON transactions (category_id, occurred_at DESC);
CREATE INDEX idx_transactions_type_occurred
    ON transactions (transaction_type, occurred_at DESC);

CREATE TABLE transaction_valuations (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON UPDATE RESTRICT ON DELETE CASCADE,
    base_currency_code TEXT NOT NULL DEFAULT 'SEK'
        REFERENCES currencies(code) ON UPDATE RESTRICT ON DELETE RESTRICT,
    value_minor INTEGER NOT NULL CHECK (value_minor >= 0),
    fx_rate TEXT NOT NULL CHECK (
        fx_rate NOT GLOB '*[^0-9.]*'
        AND fx_rate GLOB '[0-9]*'
        AND (length(fx_rate) - length(replace(fx_rate, '.', ''))) <= 1
        AND CAST(fx_rate AS NUMERIC) > 0
    ),
    rate_convention TEXT NOT NULL DEFAULT 'base_per_unit'
        CHECK (rate_convention = 'base_per_unit'),
    provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
    effective_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    valuation_status TEXT NOT NULL DEFAULT 'actual'
        CHECK (valuation_status IN ('actual', 'estimated')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (transaction_id, base_currency_code, provider, effective_at)
);

CREATE INDEX idx_transaction_valuations_transaction
    ON transaction_valuations (transaction_id, effective_at DESC);
