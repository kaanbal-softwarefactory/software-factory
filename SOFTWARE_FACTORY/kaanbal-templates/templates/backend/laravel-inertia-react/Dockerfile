ARG PHP_VERSION={{ php_version | default('8.4') }}

FROM node:22-alpine AS frontend
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY resources ./resources
COPY vite.config.ts tsconfig.json ./
RUN npm run build

FROM composer:2 AS vendor
WORKDIR /app
COPY . .
RUN composer install --no-dev --no-interaction --prefer-dist --no-progress \
    --optimize-autoloader --no-scripts

FROM php:${PHP_VERSION}-cli-alpine AS runtime
WORKDIR /var/www/html
RUN apk add --no-cache libpq-dev \
    && docker-php-ext-install pdo_pgsql opcache
COPY --from=vendor /app /var/www/html
COPY --from=frontend /app/public/build /var/www/html/public/build
COPY docker-entrypoint.sh /usr/local/bin/kaanbal-entrypoint
RUN chmod +x /usr/local/bin/kaanbal-entrypoint \
    && chown -R www-data:www-data storage bootstrap/cache
USER www-data
EXPOSE 8000
ENTRYPOINT ["kaanbal-entrypoint"]
CMD ["php", "artisan", "serve", "--host=0.0.0.0", "--port=8000"]
