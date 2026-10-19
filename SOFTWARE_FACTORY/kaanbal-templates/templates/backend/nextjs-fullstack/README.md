# placeholder-app

Aplicación full-stack generada por Kaanbal con Next.js 16 (App Router), React 19
y TypeScript. El mismo proyecto sirve las páginas y la API: no hay un frontend y
un backend separados que vincular.

## Primera ejecución

Requiere Node.js 20.9 o superior (la imagen usa Node 22).

```bash
npm install
npm run dev
```

Queda en `http://localhost:3000`. `GET /api/health` es la prueba de humo que
usan Kaanbal y Kubernetes; responde sin tocar la base, para que una base caída
no reinicie el pod.

Sin base de datos la aplicación arranca igual: guarda las notas en memoria y lo
dice en pantalla. Es lo que permite ver la demo funcionando el primer minuto.

## Base de datos

Al vincular una base, Kaanbal inyecta su conexión con los nombres
convencionales del motor. `lib/notes.ts` los lee en este orden:

| Motor | Variables que busca |
|---|---|
| MongoDB | `MONGODB_URI`, `MONGO_URI`, `MONGODB_URL`, `MONGO_URL`, o `DATABASE_URL` si es `mongodb://` |
| PostgreSQL | `POSTGRES_URI`, `POSTGRES_URL`, `DATABASE_URL`, o `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` |

No hace falta configurar nada ni escribir credenciales en el repositorio: al
vincular la base desde la consola o con el MCP, la app la detecta al arrancar.
La colección o tabla `notes` se crea y se siembra sola la primera vez.

Para desarrollo local, copia `.env.example` a `.env.local` y descomenta la
variable del motor que uses.

## Estructura

- `app/page.tsx` — página renderizada en el servidor; lee los datos directo.
- `app/api/notes/route.ts` — API REST del ejemplo (`GET`, `POST`).
- `app/api/health/route.ts` — salud del proceso.
- `components/NoteForm.tsx` — componente de cliente que escribe por la API.
- `lib/notes.ts` — capa de datos: elige Mongo, PostgreSQL o memoria.

## Producción

`npm run build` genera la salida `standalone`: el `Dockerfile` copia solo ese
servidor Node y los archivos estáticos, y corre como usuario sin privilegios en
el puerto 3000.
