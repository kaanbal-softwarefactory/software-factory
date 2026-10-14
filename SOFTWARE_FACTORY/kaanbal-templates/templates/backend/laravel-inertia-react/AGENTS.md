# placeholder-app — contrato para agentes

Esta aplicación fue creada por Kaanbal. Usa Laravel 13, React e Inertia y está
organizada con una capa MVVM.

## Reglas

- Nunca escribas secretos ni copies `.env`; Kaanbal inyecta `APP_KEY` y
  `DATABASE_URL` desde Vault.
- Mantén `GET /health` y el puerto `8000`: Kubernetes los usa para comprobar
  que la aplicación funciona.
- Los controladores coordinan; la transformación de datos vive en
  `app/ViewModels` y el estado de UI en `resources/js/view-models`.
- Las migraciones deben ser idempotentes y seguir expand/contract. El
  entrypoint ejecuta `php artisan migrate --force` cuando hay base vinculada.
- Gestiona paquetes PHP con Composer y paquetes del frontend con npm.

## Desarrollo

```bash
composer install
composer initialize
composer dev
composer test
```

Lee `README.md` para la estructura y el flujo de base de datos.
