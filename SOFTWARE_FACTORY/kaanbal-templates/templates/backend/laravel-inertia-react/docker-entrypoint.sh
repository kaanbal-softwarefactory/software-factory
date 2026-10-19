#!/bin/sh
set -eu

if [ -z "${APP_KEY:-}" ]; then
    echo "APP_KEY is required. Kaanbal must inject it from Vault." >&2
    exit 1
fi

php artisan package:discover --ansi

if [ -n "${DATABASE_URL:-${DB_URL:-}}" ]; then
    php artisan migrate --force --ansi
fi

php artisan config:cache --ansi
php artisan route:cache --ansi
php artisan view:cache --ansi

exec "$@"
