-- Allow zero realized P&L postings while preserving every existing event.
-- The previous 0006 table CHECK rejected zero, although a closed trade may
-- legitimately break even after fees. Recreate append-only guards below.
DROP TRIGGER paper_account_events_require_opening_capital;
DROP TRIGGER paper_account_events_opening_capital_first;
DROP TRIGGER paper_account_events_currency_matches_account;
DROP TRIGGER paper_account_events_amount_sign;
DROP TRIGGER paper_account_events_no_replace;
DROP TRIGGER paper_account_events_no_update;
DROP TRIGGER paper_account_events_no_delete;
-- This trade trigger references paper_account_events; drop it while the table is rebuilt.
DROP TRIGGER paper_trades_account_requires_funding;
DROP INDEX idx_paper_account_single_opening_capital;
DROP INDEX idx_paper_account_events_account_sequence;

CREATE TABLE paper_account_events_new (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL REFERENCES paper_accounts(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('OPENING_CAPITAL', 'DEPOSIT', 'WITHDRAWAL', 'ADJUSTMENT', 'TRADE_REALIZED_PNL')
    ),
    amount TEXT NOT NULL,
    currency_code TEXT NOT NULL CHECK (
        length(currency_code) BETWEEN 3 AND 8
        AND currency_code = upper(currency_code)
    ),
    idempotency_key TEXT NOT NULL,
    reference_id TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE (account_id, idempotency_key)
);

INSERT INTO paper_account_events_new
    (sequence, id, account_id, event_type, amount, currency_code,
     idempotency_key, reference_id, occurred_at)
SELECT sequence, id, account_id, event_type, amount, currency_code,
       idempotency_key, reference_id, occurred_at
FROM paper_account_events
ORDER BY sequence;

DROP TABLE paper_account_events;
ALTER TABLE paper_account_events_new RENAME TO paper_account_events;

CREATE UNIQUE INDEX idx_paper_account_single_opening_capital
    ON paper_account_events(account_id)
    WHERE event_type = 'OPENING_CAPITAL';
CREATE INDEX idx_paper_account_events_account_sequence
    ON paper_account_events(account_id, sequence);

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
 AND EXISTS (SELECT 1 FROM paper_account_events WHERE account_id = NEW.account_id)
BEGIN
    SELECT RAISE(ABORT, 'PAPER opening capital must be the first account event');
END;

CREATE TRIGGER paper_account_events_currency_matches_account
BEFORE INSERT ON paper_account_events
WHEN NEW.currency_code <> (
    SELECT quote_currency FROM paper_accounts WHERE id = NEW.account_id
)
BEGIN
    SELECT RAISE(ABORT, 'PAPER account event currency must match account currency');
END;

CREATE TRIGGER paper_account_events_amount_sign
BEFORE INSERT ON paper_account_events
WHEN (NEW.event_type IN ('OPENING_CAPITAL', 'DEPOSIT') AND CAST(NEW.amount AS REAL) <= 0)
  OR (NEW.event_type = 'WITHDRAWAL' AND CAST(NEW.amount AS REAL) >= 0)
  OR (NEW.event_type = 'ADJUSTMENT' AND CAST(NEW.amount AS REAL) = 0)
BEGIN
    SELECT RAISE(ABORT, 'PAPER account event amount has invalid sign');
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

-- Enforce the account/trade relationship at the SQLite boundary.
-- Monetary and price strings use plain decimal notation (no exponent, sign in
-- front only, at most one decimal point). Application code quantizes money to
-- 8 decimal places using ROUND_HALF_EVEN before persistence.

CREATE TRIGGER paper_account_events_amount_decimal
BEFORE INSERT ON paper_account_events
WHEN
    NEW.amount = ''
    OR NEW.amount GLOB '*[^0-9.-]*'
    OR NEW.amount NOT GLOB '*[0-9]*'
    OR instr(NEW.amount, '-') > 1
    OR (substr(NEW.amount, 1, 1) = '-' AND substr(NEW.amount, 2, 1) = '-')
    OR (instr(NEW.amount, '-') = 1 AND substr(NEW.amount, 2, 1) = '.')
    OR (instr(NEW.amount, '-') > 0 AND substr(NEW.amount, 1, 1) <> '-')
    OR (length(NEW.amount) - length(replace(NEW.amount, '.', ''))) > 1
    OR substr(NEW.amount, 1, 1) = '.'
    OR substr(NEW.amount, -1, 1) = '.'
    OR substr(NEW.amount, -1, 1) = '-'
    OR (NEW.event_type <> 'TRADE_REALIZED_PNL' AND CAST(NEW.amount AS REAL) = 0)
    OR ABS(CAST(NEW.amount AS REAL)) > 9000000000000000
BEGIN
    SELECT RAISE(ABORT, 'PAPER account event amount must be a finite plain decimal');
END;

CREATE TRIGGER paper_trades_financial_decimal_insert
BEFORE INSERT ON paper_trades
WHEN
    NEW.quantity = ''
    OR NEW.quantity GLOB '*[^0-9.-]*'
    OR NEW.quantity NOT GLOB '*[0-9]*'
    OR instr(NEW.quantity, '-') > 0
    OR (length(NEW.quantity) - length(replace(NEW.quantity, '.', ''))) > 1
    OR substr(NEW.quantity, 1, 1) = '.'
    OR substr(NEW.quantity, -1, 1) = '.'
    OR CAST(NEW.quantity AS REAL) <= 0
    OR NEW.entry_price = ''
    OR NEW.entry_price GLOB '*[^0-9.-]*'
    OR NEW.entry_price NOT GLOB '*[0-9]*'
    OR instr(NEW.entry_price, '-') > 0
    OR (length(NEW.entry_price) - length(replace(NEW.entry_price, '.', ''))) > 1
    OR substr(NEW.entry_price, 1, 1) = '.'
    OR substr(NEW.entry_price, -1, 1) = '.'
    OR CAST(NEW.entry_price AS REAL) <= 0
    OR NEW.entry_fee = ''
    OR NEW.entry_fee GLOB '*[^0-9.-]*'
    OR NEW.entry_fee NOT GLOB '*[0-9]*'
    OR instr(NEW.entry_fee, '-') > 0
    OR (length(NEW.entry_fee) - length(replace(NEW.entry_fee, '.', ''))) > 1
    OR substr(NEW.entry_fee, 1, 1) = '.'
    OR substr(NEW.entry_fee, -1, 1) = '.'
    OR CAST(NEW.entry_fee AS REAL) < 0
BEGIN
    SELECT RAISE(ABORT, 'PAPER trade financial values must be plain non-negative decimals');
END;

CREATE TRIGGER paper_trades_financial_decimal_update
BEFORE UPDATE OF quantity, entry_price, entry_fee, exit_price, exit_fee, realized_pnl
ON paper_trades
WHEN
    (NEW.quantity IS NOT NULL AND (
        NEW.quantity = '' OR NEW.quantity GLOB '*[^0-9.-]*'
        OR NEW.quantity NOT GLOB '*[0-9]*' OR instr(NEW.quantity, '-') > 0
        OR (length(NEW.quantity) - length(replace(NEW.quantity, '.', ''))) > 1
        OR substr(NEW.quantity, 1, 1) = '.' OR substr(NEW.quantity, -1, 1) = '.'
        OR CAST(NEW.quantity AS REAL) <= 0
    ))
    OR (NEW.entry_price IS NOT NULL AND (
        NEW.entry_price = '' OR NEW.entry_price GLOB '*[^0-9.-]*'
        OR NEW.entry_price NOT GLOB '*[0-9]*' OR instr(NEW.entry_price, '-') > 0
        OR (length(NEW.entry_price) - length(replace(NEW.entry_price, '.', ''))) > 1
        OR substr(NEW.entry_price, 1, 1) = '.' OR substr(NEW.entry_price, -1, 1) = '.'
        OR CAST(NEW.entry_price AS REAL) <= 0
    ))
    OR (NEW.entry_fee IS NOT NULL AND (
        NEW.entry_fee = '' OR NEW.entry_fee GLOB '*[^0-9.-]*'
        OR NEW.entry_fee NOT GLOB '*[0-9]*' OR instr(NEW.entry_fee, '-') > 0
        OR (length(NEW.entry_fee) - length(replace(NEW.entry_fee, '.', ''))) > 1
        OR substr(NEW.entry_fee, 1, 1) = '.' OR substr(NEW.entry_fee, -1, 1) = '.'
        OR CAST(NEW.entry_fee AS REAL) < 0
    ))
    OR (NEW.exit_price IS NOT NULL AND (
        NEW.exit_price = '' OR NEW.exit_price GLOB '*[^0-9.-]*'
        OR NEW.exit_price NOT GLOB '*[0-9]*' OR instr(NEW.exit_price, '-') > 0
        OR (length(NEW.exit_price) - length(replace(NEW.exit_price, '.', ''))) > 1
        OR substr(NEW.exit_price, 1, 1) = '.' OR substr(NEW.exit_price, -1, 1) = '.'
        OR CAST(NEW.exit_price AS REAL) <= 0
    ))
    OR (NEW.exit_fee IS NOT NULL AND (
        NEW.exit_fee = '' OR NEW.exit_fee GLOB '*[^0-9.-]*'
        OR NEW.exit_fee NOT GLOB '*[0-9]*' OR instr(NEW.exit_fee, '-') > 0
        OR (length(NEW.exit_fee) - length(replace(NEW.exit_fee, '.', ''))) > 1
        OR substr(NEW.exit_fee, 1, 1) = '.' OR substr(NEW.exit_fee, -1, 1) = '.'
        OR CAST(NEW.exit_fee AS REAL) < 0
    ))
    OR (NEW.realized_pnl IS NOT NULL AND (
        NEW.realized_pnl = '' OR NEW.realized_pnl GLOB '*[^0-9.-]*'
        OR NEW.realized_pnl NOT GLOB '*[0-9]*' OR instr(NEW.realized_pnl, '-') > 1
        OR (instr(NEW.realized_pnl, '-') = 1 AND substr(NEW.realized_pnl, 2, 1) = '.')
        OR (instr(NEW.realized_pnl, '-') > 1)
        OR (length(NEW.realized_pnl) - length(replace(NEW.realized_pnl, '.', ''))) > 1
        OR substr(NEW.realized_pnl, 1, 1) = '.'
        OR substr(NEW.realized_pnl, -1, 1) = '.' OR substr(NEW.realized_pnl, -1, 1) = '-'
    ))
BEGIN
    SELECT RAISE(ABORT, 'PAPER trade financial values must be plain decimals');
END;

CREATE TRIGGER paper_trades_closed_financial_immutable
BEFORE UPDATE OF quantity, entry_price, entry_fee, exit_price, exit_fee, realized_pnl
ON paper_trades
WHEN OLD.status = 'CLOSED'
BEGIN
    SELECT RAISE(ABORT, 'CLOSED PAPER trade financial values are immutable');
END;

CREATE UNIQUE INDEX idx_paper_account_realized_pnl_trade
    ON paper_account_events(reference_id)
    WHERE event_type = 'TRADE_REALIZED_PNL';

CREATE TRIGGER paper_account_realized_pnl_matches_closed_trade
BEFORE INSERT ON paper_account_events
WHEN NEW.event_type = 'TRADE_REALIZED_PNL'
 AND (
    NEW.reference_id IS NULL
    OR NOT EXISTS (
        SELECT 1
        FROM paper_trades AS trade
        WHERE trade.id = NEW.reference_id
          AND trade.paper_account_id = NEW.account_id
          AND trade.status = 'CLOSED'
          AND trade.realized_pnl = NEW.amount
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'TRADE_REALIZED_PNL must exactly match one CLOSED trade in the same account');
END;

CREATE TRIGGER paper_account_events_amount_precision
BEFORE INSERT ON paper_account_events
WHEN (instr(NEW.amount, '.') > 0 AND length(NEW.amount) - instr(NEW.amount, '.') > 8)
  OR (length(CASE WHEN instr(ltrim(NEW.amount, '-'), '.') > 0
                  THEN substr(ltrim(NEW.amount, '-'), 1, instr(ltrim(NEW.amount, '-'), '.') - 1)
                  ELSE ltrim(NEW.amount, '-') END) > 1
      AND substr(ltrim(NEW.amount, '-'), 1, 1) = '0')
BEGIN
    SELECT RAISE(ABORT, 'PAPER account event amount exceeds 8 decimals or has leading zeroes');
END;

CREATE TRIGGER paper_trades_financial_precision_insert
BEFORE INSERT ON paper_trades
WHEN
    (instr(NEW.quantity, '.') > 0 AND length(NEW.quantity) - instr(NEW.quantity, '.') > 8)
 OR (instr(NEW.entry_price, '.') > 0 AND length(NEW.entry_price) - instr(NEW.entry_price, '.') > 8)
 OR (instr(NEW.entry_fee, '.') > 0 AND length(NEW.entry_fee) - instr(NEW.entry_fee, '.') > 8)
 OR (length(CASE WHEN instr(NEW.quantity, '.') > 0 THEN substr(NEW.quantity,1,instr(NEW.quantity,'.')-1) ELSE NEW.quantity END)>1 AND substr(NEW.quantity,1,1)='0')
 OR (length(CASE WHEN instr(NEW.entry_price, '.') > 0 THEN substr(NEW.entry_price,1,instr(NEW.entry_price,'.')-1) ELSE NEW.entry_price END)>1 AND substr(NEW.entry_price,1,1)='0')
 OR (length(CASE WHEN instr(NEW.entry_fee, '.') > 0 THEN substr(NEW.entry_fee,1,instr(NEW.entry_fee,'.')-1) ELSE NEW.entry_fee END)>1 AND substr(NEW.entry_fee,1,1)='0')
BEGIN
    SELECT RAISE(ABORT, 'PAPER trade financial values exceed 8 decimals or have leading zeroes');
END;

CREATE TRIGGER paper_trades_financial_precision_update
BEFORE UPDATE OF quantity, entry_price, entry_fee, exit_price, exit_fee, realized_pnl ON paper_trades
WHEN
    (NEW.quantity IS NOT NULL AND instr(NEW.quantity, '.') > 0 AND length(NEW.quantity) - instr(NEW.quantity, '.') > 8)
 OR (NEW.entry_price IS NOT NULL AND instr(NEW.entry_price, '.') > 0 AND length(NEW.entry_price) - instr(NEW.entry_price, '.') > 8)
 OR (NEW.entry_fee IS NOT NULL AND instr(NEW.entry_fee, '.') > 0 AND length(NEW.entry_fee) - instr(NEW.entry_fee, '.') > 8)
 OR (NEW.exit_price IS NOT NULL AND instr(NEW.exit_price, '.') > 0 AND length(NEW.exit_price) - instr(NEW.exit_price, '.') > 8)
 OR (NEW.exit_fee IS NOT NULL AND instr(NEW.exit_fee, '.') > 0 AND length(NEW.exit_fee) - instr(NEW.exit_fee, '.') > 8)
 OR (NEW.realized_pnl IS NOT NULL AND instr(NEW.realized_pnl, '.') > 0 AND length(NEW.realized_pnl) - instr(NEW.realized_pnl, '.') > 8)
 OR (NEW.quantity IS NOT NULL AND length(CASE WHEN instr(NEW.quantity, '.') > 0 THEN substr(NEW.quantity,1,instr(NEW.quantity,'.')-1) ELSE NEW.quantity END)>1 AND substr(NEW.quantity,1,1)='0')
 OR (NEW.entry_price IS NOT NULL AND length(CASE WHEN instr(NEW.entry_price, '.') > 0 THEN substr(NEW.entry_price,1,instr(NEW.entry_price,'.')-1) ELSE NEW.entry_price END)>1 AND substr(NEW.entry_price,1,1)='0')
 OR (NEW.entry_fee IS NOT NULL AND length(CASE WHEN instr(NEW.entry_fee, '.') > 0 THEN substr(NEW.entry_fee,1,instr(NEW.entry_fee,'.')-1) ELSE NEW.entry_fee END)>1 AND substr(NEW.entry_fee,1,1)='0')
 OR (NEW.exit_price IS NOT NULL AND length(CASE WHEN instr(NEW.exit_price, '.') > 0 THEN substr(NEW.exit_price,1,instr(NEW.exit_price,'.')-1) ELSE NEW.exit_price END)>1 AND substr(NEW.exit_price,1,1)='0')
 OR (NEW.exit_fee IS NOT NULL AND length(CASE WHEN instr(NEW.exit_fee, '.') > 0 THEN substr(NEW.exit_fee,1,instr(NEW.exit_fee,'.')-1) ELSE NEW.exit_fee END)>1 AND substr(NEW.exit_fee,1,1)='0')
 OR (NEW.realized_pnl IS NOT NULL AND length(CASE WHEN instr(ltrim(NEW.realized_pnl, '-'), '.') > 0 THEN substr(ltrim(NEW.realized_pnl, '-'),1,instr(ltrim(NEW.realized_pnl, '-'),'.')-1) ELSE ltrim(NEW.realized_pnl, '-') END)>1 AND substr(ltrim(NEW.realized_pnl, '-'),1,1)='0')
BEGIN
    SELECT RAISE(ABORT, 'PAPER trade financial values exceed 8 decimals');
END;
