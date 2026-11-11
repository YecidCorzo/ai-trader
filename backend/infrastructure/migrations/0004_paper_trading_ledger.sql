-- Persistent audit trail for simulated trades and the paper-trading stop switch.
CREATE TABLE paper_trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL CHECK (length(trim(symbol)) > 0),
    strategy TEXT NOT NULL CHECK (length(trim(strategy)) > 0),
    side TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    quantity TEXT NOT NULL CHECK (CAST(quantity AS REAL) > 0),
    entry_price TEXT NOT NULL CHECK (CAST(entry_price AS REAL) > 0),
    exit_price TEXT,
    entry_fee TEXT NOT NULL DEFAULT '0' CHECK (CAST(entry_fee AS REAL) >= 0),
    exit_fee TEXT,
    realized_pnl TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (status = 'OPEN' AND exit_price IS NULL AND exit_fee IS NULL
         AND realized_pnl IS NULL AND closed_at IS NULL)
        OR
        (status = 'CLOSED' AND exit_price IS NOT NULL AND exit_fee IS NOT NULL
         AND realized_pnl IS NOT NULL AND closed_at IS NOT NULL)
    )
);

CREATE INDEX idx_paper_trades_status_opened
    ON paper_trades (status, opened_at DESC);

CREATE INDEX idx_paper_trades_symbol_opened
    ON paper_trades (symbol, opened_at DESC);

CREATE TABLE paper_trade_events (
    id TEXT PRIMARY KEY,
    trade_id TEXT REFERENCES paper_trades(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN ('TRADE_OPENED', 'TRADE_CLOSED', 'CIRCUIT_BREAKER_HALTED', 'CIRCUIT_BREAKER_RESET')),
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);

CREATE INDEX idx_paper_trade_events_trade_time
    ON paper_trade_events (trade_id, occurred_at);

CREATE TABLE paper_risk_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    halted INTEGER NOT NULL DEFAULT 0 CHECK (halted IN (0, 1)),
    reason TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_by TEXT NOT NULL DEFAULT 'system'
);

INSERT INTO paper_risk_control (id, halted, reason, updated_by)
VALUES (1, 0, NULL, 'migration');
