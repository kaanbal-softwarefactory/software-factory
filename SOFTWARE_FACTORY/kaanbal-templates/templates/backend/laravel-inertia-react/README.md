# placeholder-app

Aplicación full-stack generada por Kaanbal con Laravel 13, PHP 8.4, React 19,
TypeScript e Inertia 3.

## Primera ejecución

Requiere PHP 8.4, Composer 2 y Node.js 22+.

```bash
composer install
composer initialize
composer dev
```

`composer initialize` crea `.env`, genera `APP_KEY`, prepara SQLite, ejecuta
las migraciones e instala/compila las dependencias JavaScript. La aplicación
queda en `http://localhost:8000`; `GET /health` es la prueba de humo usada por
Kaanbal y Kubernetes.

También puede ejecutarse con contenedores:

```bash
cp .env.example .env
docker compose run --rm app php artisan key:generate
docker compose up --build
```

## Base de datos en Kaanbal

Al vincular PostgreSQL, Kaanbal inyecta `DATABASE_URL` desde Vault. El
entrypoint detecta esa variable y ejecuta `php artisan migrate --force` de
forma idempotente antes de servir la aplicación. No escribas credenciales en
el repositorio.

## MVVM

- `app/ViewModels`: transforma modelos/dominio en props serializables.
- `app/Http/Controllers`: coordina la petición y entrega el ViewModel a Inertia.
- `resources/js/view-models`: estado y acciones de la vista React.
- `resources/js/pages`: componentes visuales sin reglas de infraestructura.

Laravel conserva sus convenciones MVC; esta capa MVVM evita acoplar las vistas
Inertia a Eloquent o a detalles HTTP.

## Pruebas

```bash
composer test
npm run types:check
```

La prueba `HealthTest` confirma `/health`, el runtime PHP/Laravel, la conexión
de prueba y el renderizado Inertia de la página principal.
