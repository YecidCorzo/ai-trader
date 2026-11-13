-- Persist caller idempotency for account-scoped PAPER entries.
-- Existing legacy trades remain with NULL keys and retain their audit history.
ALTER TABLE paper_trades ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX idx_paper_trades_account_idempotency
    ON paper_trades(paper_account_id, idempotency_key)
    WHERE paper_account_id IS NOT NULL AND idempotency_key IS NOT NULL;
