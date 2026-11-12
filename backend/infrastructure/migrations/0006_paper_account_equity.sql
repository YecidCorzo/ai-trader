-- Dedicated, simulated PAPER account capital and market-mark ledger.
-- Existing trades remain unassigned; never infer their account or starting capital.
CREATE TABLE paper_accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    quote_currency TEXT NOT NULL CHECK (
        length(quote_currency) BETWEEN 3 AND 8
        AND quote_currency = upper(quote_currency)
    ),
    created_at TEXT NOT NULL
);

ALTER TABLE paper_trades
    ADD COLUMN paper_account_id TEXT
    REFERENCES paper_accounts(id) ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE INDEX idx_paper_trades_account_status
    ON paper_trades (paper_account_id, status, opened_at DESC);

CREATE TABLE paper_account_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL REFERENCES paper_accounts(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('OPENING_CAPITAL', 'DEPOSIT', 'WITHDRAWAL', 'ADJUSTMENT', 'TRADE_REALIZED_PNL')
    ),
    amount TEXT NOT NULL CHECK (
        amount NOT GLOB '*[^0-9eE+.-]*'
        AND CAST(amount AS REAL) != 0
    ),
    currency_code TEXT NOT NULL CHECK (
        length(currency_code) BETWEEN 3 AND 8
        AND currency_code = upper(currency_code)
    ),
    idempotency_key TEXT NOT NULL,
    reference_id TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE (account_id, idempotency_key)
);

CREATE UNIQUE INDEX idx_paper_account_single_opening_capital
    ON paper_account_events(account_id)
    WHERE event_type = 'OPENING_CAPITAL';

CREATE INDEX idx_paper_account_events_account_sequence
    ON paper_account_events(account_id, sequence);

CREATE TRIGGER paper_account_events_require_opening_capital
BEFORE INSERT ON paper_account_events
WHEN NEW.event_type <> 'OPENING_CAPITAL'
 AND NOT EXISTS (
    SELECT 1 FROM paper_account_events
    WHERE account_id = NEW.account_id AND event_type = 'OPENING_CAPITAL'
 )
BEGIN
    SELECT RAISE(ABORT, 'PAPER account requires explicit opening capital');
END;

CREATE TRIGGER paper_account_events_opening_capital_first
BEFORE INSERT ON paper_account_events
WHEN NEW.event_type = 'OPENING_CAPITAL'
 AND EXISTS (
    SELECT 1 FROM paper_account_events WHERE account_id = NEW.account_id
 )
BEGIN
    SELECT RAISE(ABORT, 'PAPER opening capital must be the first account event');
END;

CREATE TRIGGER paper_account_events_no_replace
BEFORE INSERT ON paper_account_events
WHEN EXISTS (
    SELECT 1 FROM paper_account_events
    WHERE id = NEW.id
       OR (NEW.sequence > 0 AND sequence = NEW.sequence)
       OR (account_id = NEW.account_id AND idempotency_key = NEW.idempotency_key)
)
BEGIN
    SELECT RAISE(ABORT, 'PAPER account events are append-only and idempotent');
END;

CREATE TRIGGER paper_account_events_no_update
BEFORE UPDATE ON paper_account_events
BEGIN
    SELECT RAISE(ABORT, 'PAPER account events are append-only');
END;

CREATE TRIGGER paper_account_events_no_delete
BEFORE DELETE ON paper_account_events
BEGIN
    SELECT RAISE(ABORT, 'PAPER account events are append-only');
END;

CREATE TABLE paper_price_snapshots (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL CHECK (length(trim(symbol)) > 0),
    price TEXT NOT NULL CHECK (
        price NOT GLOB '*[^0-9eE+.-]*'
        AND CAST(price AS REAL) > 0
    ),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    retrieved_at TEXT NOT NULL
);

CREATE INDEX idx_paper_price_snapshots_symbol_sequence
    ON paper_price_snapshots(symbol, sequence DESC);

CREATE TRIGGER paper_price_snapshots_no_replace
BEFORE INSERT ON paper_price_snapshots
WHEN EXISTS (
    SELECT 1 FROM paper_price_snapshots
    WHERE id = NEW.id
       OR (NEW.sequence > 0 AND sequence = NEW.sequence)
)
BEGIN
    SELECT RAISE(ABORT, 'PAPER price snapshots are append-only');
END;

CREATE TRIGGER paper_price_snapshots_no_update
BEFORE UPDATE ON paper_price_snapshots
BEGIN
    SELECT RAISE(ABORT, 'PAPER price snapshots are append-only');
END;

CREATE TRIGGER paper_price_snapshots_no_delete
BEFORE DELETE ON paper_price_snapshots
BEGIN
    SELECT RAISE(ABORT, 'PAPER price snapshots are append-only');
END;

-- Link only newly created trades to an explicitly funded PAPER account.
-- Legacy rows keep NULL and are deliberately excluded from account equity.
CREATE TRIGGER paper_trades_account_requires_funding
BEFORE INSERT ON paper_trades
WHEN NEW.paper_account_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM paper_account_events
    WHERE account_id = NEW.paper_account_id AND event_type = 'OPENING_CAPITAL'
 )
BEGIN
    SELECT RAISE(ABORT, 'PAPER trade requires an explicitly funded account');
END;
