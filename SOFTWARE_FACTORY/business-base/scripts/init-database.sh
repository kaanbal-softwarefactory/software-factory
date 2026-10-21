#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\set runtime_password `cat /bootstrap/runtime-password`
\set migration_password `cat /bootstrap/migration-password`
\set identity_password `cat /bootstrap/identity-password`
CREATE ROLE business_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'runtime_password';
CREATE ROLE business_migrator LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'migration_password';
CREATE ROLE business_identity LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'identity_password';
CREATE DATABASE business OWNER business_migrator;
CREATE DATABASE identity OWNER business_identity;
REVOKE ALL ON DATABASE business FROM PUBLIC;
GRANT CONNECT ON DATABASE business TO business_runtime;
REVOKE ALL ON DATABASE identity FROM PUBLIC;
SQL
