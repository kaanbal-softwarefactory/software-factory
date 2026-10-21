-- Additive: previous application revisions continue to read the same columns.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS experience text NOT NULL DEFAULT 'services';
