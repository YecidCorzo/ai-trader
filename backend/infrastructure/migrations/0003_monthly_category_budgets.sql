-- Monthly spending limits are tracked per expense category and original currency.
CREATE TABLE monthly_category_budgets (
    id TEXT PRIMARY KEY,
    category_id TEXT NOT NULL REFERENCES categories(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON UPDATE RESTRICT ON DELETE RESTRICT,
    budget_year INTEGER NOT NULL CHECK (budget_year BETWEEN 2000 AND 2100),
    budget_month INTEGER NOT NULL CHECK (budget_month BETWEEN 1 AND 12),
    amount_minor INTEGER NOT NULL CHECK (amount_minor BETWEEN 1 AND 9000000000000000),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (category_id, currency_code, budget_year, budget_month)
);

CREATE INDEX idx_monthly_budgets_period
    ON monthly_category_budgets (budget_year, budget_month, currency_code);
