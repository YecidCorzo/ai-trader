-- Give audit events a durable insertion sequence and enforce append-only semantics.
-- Rebuild the table so sequence is an INTEGER PRIMARY KEY AUTOINCREMENT.
CREATE TABLE paper_trade_events_new (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    trade_id TEXT REFERENCES paper_trades(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'TRADE_OPENED', 'TRADE_CLOSED',
            'CIRCUIT_BREAKER_HALTED', 'CIRCUIT_BREAKER_RESET'
        )
    ),
    details_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);

INSERT INTO paper_trade_events_new
    (id, trade_id, event_type, details_json, occurred_at)
SELECT id, trade_id, event_type, details_json, occurred_at
FROM paper_trade_events
ORDER BY rowid;

DROP TABLE paper_trade_events;
ALTER TABLE paper_trade_events_new RENAME TO paper_trade_events;

CREATE INDEX idx_paper_trade_events_trade_time
    ON paper_trade_events (trade_id, occurred_at);

CREATE TRIGGER paper_trade_events_no_update
BEFORE UPDATE ON paper_trade_events
BEGIN
    SELECT RAISE(ABORT, 'paper_trade_events is append-only');
END;

CREATE TRIGGER paper_trade_events_no_delete
BEFORE DELETE ON paper_trade_events
BEGIN
    SELECT RAISE(ABORT, 'paper_trade_events is append-only');
END;
