#!/bin/bash
set -eu
export KC_DB=postgres
export KC_DB_URL=jdbc:postgresql://database:5432/identity
export KC_DB_USERNAME=business_identity
export KC_DB_PASSWORD="$(cat /bootstrap/identity-password)"
export KC_BOOTSTRAP_ADMIN_USERNAME=local-admin
export KC_BOOTSTRAP_ADMIN_PASSWORD="$(cat /bootstrap/admin-password)"
export KC_HEALTH_ENABLED=true
export KC_HOSTNAME="http://localhost:${IDENTITY_PORT:-8180}"
mkdir -p /opt/keycloak/data/import
cp /bootstrap/realm.json /opt/keycloak/data/import/realm.json
exec /opt/keycloak/bin/kc.sh start-dev --import-realm
