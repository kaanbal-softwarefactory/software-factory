CREATE TABLE organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), slug text UNIQUE NOT NULL,
  name text NOT NULL, description text NOT NULL DEFAULT '', whatsapp text NOT NULL DEFAULT '',
  timezone text NOT NULL DEFAULT 'UTC', public boolean NOT NULL DEFAULT false
);
CREATE TABLE people (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), issuer text NOT NULL, subject text NOT NULL,
  email text NOT NULL, email_verified boolean NOT NULL DEFAULT false, name text NOT NULL,
  disabled boolean NOT NULL DEFAULT false, UNIQUE(issuer,subject)
);
CREATE TABLE memberships (
  organization_id uuid NOT NULL REFERENCES organizations, person_id uuid NOT NULL REFERENCES people,
  role text NOT NULL CHECK(role IN ('owner','admin','staff','customer')), active boolean NOT NULL DEFAULT true,
  PRIMARY KEY (organization_id,person_id)
);
CREATE TABLE sessions (
  id text PRIMARY KEY, person_id uuid NOT NULL REFERENCES people, sid text,
  expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON sessions(person_id);
CREATE TABLE auth_flows (
  id text PRIMARY KEY, verifier text NOT NULL, state text NOT NULL, nonce text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalog (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations,
  name text NOT NULL, description text NOT NULL DEFAULT '', price_cents integer NOT NULL CHECK(price_cents>=0),
  duration_minutes integer NOT NULL CHECK(duration_minutes BETWEEN 5 AND 480),
  active boolean NOT NULL DEFAULT true, UNIQUE(organization_id,id)
);
CREATE TABLE requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations,
  person_id uuid REFERENCES people, name text NOT NULL, email text NOT NULL, message text NOT NULL,
  state text NOT NULL DEFAULT 'new' CHECK(state IN ('new','assigned','closed')),
  assigned_to uuid REFERENCES people, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(organization_id,id)
);
CREATE TABLE audit (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations,
  actor_id uuid REFERENCES people, action text NOT NULL, resource text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE invitations (
  id text PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations, email text NOT NULL,
  role text NOT NULL CHECK(role IN ('admin','staff','customer')),
  expires_at timestamptz NOT NULL DEFAULT now()+interval '48 hours', used_at timestamptz
);
CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations,
  person_id uuid REFERENCES people, title text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations,
  recipient text NOT NULL, title text NOT NULL, message text NOT NULL,
  attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz, failed boolean NOT NULL DEFAULT false
);
CREATE TABLE public_limits (
  organization_id uuid PRIMARY KEY REFERENCES organizations, window_start timestamptz NOT NULL DEFAULT now(),
  count integer NOT NULL DEFAULT 0
);
CREATE TABLE resources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations,
  name text NOT NULL, UNIQUE(organization_id,id)
);
CREATE TABLE appointments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations,
  person_id uuid NOT NULL REFERENCES people, resource_id uuid NOT NULL, service_id uuid NOT NULL,
  starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL,
  state text NOT NULL DEFAULT 'confirmed' CHECK(state IN ('confirmed','cancelled')),
  CHECK(ends_at>starts_at),
  FOREIGN KEY(organization_id,resource_id) REFERENCES resources(organization_id,id),
  FOREIGN KEY(organization_id,service_id) REFERENCES catalog(organization_id,id)
);
CREATE INDEX ON appointments(organization_id,resource_id,starts_at) WHERE state='confirmed';

-- Runtime cannot own tables or bypass these policies. Membership is checked by the server before setting the context.
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['catalog','requests','audit','invitations','notifications','outbox','public_limits','resources','appointments'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY organization_scope ON %I USING (organization_id = nullif(current_setting(''app.organization_id'',true),'''')::uuid) WITH CHECK (organization_id = nullif(current_setting(''app.organization_id'',true),'''')::uuid)', t);
  END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO business_runtime;
REVOKE UPDATE,DELETE ON audit FROM business_runtime;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO business_runtime;
GRANT USAGE ON SCHEMA public TO business_runtime;
