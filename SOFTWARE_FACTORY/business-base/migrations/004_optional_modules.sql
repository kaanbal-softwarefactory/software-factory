-- Expand only: old copies keep their preset defaults until explicitly configured.
ALTER TABLE organizations ADD COLUMN enabled_modules text[];
ALTER TABLE organizations ADD CONSTRAINT organizations_modules_valid CHECK (
  enabled_modules IS NULL OR (
    enabled_modules <@ ARRAY['contact','catalog','appointments']::text[]
    AND (NOT ('appointments' = ANY(enabled_modules)) OR 'catalog' = ANY(enabled_modules))
  )
);
