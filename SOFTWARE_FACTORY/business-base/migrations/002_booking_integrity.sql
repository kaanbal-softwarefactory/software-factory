CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE appointments ADD CONSTRAINT no_booking_overlap
  EXCLUDE USING gist (organization_id WITH =, resource_id WITH =, tstzrange(starts_at,ends_at,'[)') WITH &&)
  WHERE (state='confirmed');
CREATE INDEX ON requests(organization_id,created_at DESC);
CREATE INDEX ON requests(organization_id,person_id);
CREATE INDEX ON memberships(person_id) WHERE active=true;
REVOKE INSERT,UPDATE,DELETE ON schema_migrations FROM business_runtime;
ALTER TABLE sessions ADD COLUMN mfa boolean NOT NULL DEFAULT false;
CREATE TABLE logout_events(id text PRIMARY KEY, expires_at timestamptz NOT NULL);
GRANT SELECT,INSERT,DELETE ON logout_events TO business_runtime;
