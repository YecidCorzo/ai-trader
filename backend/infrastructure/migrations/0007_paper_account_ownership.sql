-- Add immutable, verified-principal ownership to newly created PAPER accounts.
-- Existing accounts remain explicitly unowned and are never auto-claimed.
ALTER TABLE paper_accounts ADD COLUMN owner_issuer TEXT;
ALTER TABLE paper_accounts ADD COLUMN owner_subject TEXT;

CREATE INDEX idx_paper_accounts_owner_created
    ON paper_accounts(owner_issuer, owner_subject, created_at DESC);

CREATE TRIGGER paper_accounts_require_owner_on_insert
BEFORE INSERT ON paper_accounts
WHEN NEW.owner_issuer IS NULL OR length(trim(NEW.owner_issuer)) = 0
  OR NEW.owner_subject IS NULL OR length(trim(NEW.owner_subject)) = 0
BEGIN
    SELECT RAISE(ABORT, 'New PAPER accounts require a verified owner');
END;

CREATE TRIGGER paper_accounts_owner_pair_valid
BEFORE UPDATE OF owner_issuer, owner_subject ON paper_accounts
WHEN (NEW.owner_issuer IS NULL) <> (NEW.owner_subject IS NULL)
  OR (NEW.owner_issuer IS NOT NULL AND length(trim(NEW.owner_issuer)) = 0)
  OR (NEW.owner_subject IS NOT NULL AND length(trim(NEW.owner_subject)) = 0)
BEGIN
    SELECT RAISE(ABORT, 'PAPER account owner issuer and subject must be set together');
END;

CREATE TRIGGER paper_accounts_owner_immutable
BEFORE UPDATE OF owner_issuer, owner_subject ON paper_accounts
WHEN OLD.owner_issuer IS NOT NEW.owner_issuer
  OR OLD.owner_subject IS NOT NEW.owner_subject
BEGIN
    SELECT RAISE(ABORT, 'PAPER account ownership is immutable');
END;
