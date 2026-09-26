# placeholder-app — cómo trabajar en este repositorio

API creada por **Kaanbal**. Este archivo es el contrato: vale para quien
programa y para cualquier agente (Claude Code, Codex, Cursor) que abra el repo.

## La regla que lo explica todo

**La base de datos llega por variables de entorno, nunca por una URL escrita en
el código.** En local esas variables salen de `.env`; en el clúster las inyecta
Kaanbal desde Vault. Los nombres son los mismos en los dos lados, así que el
mismo código corre igual:

| Variable | En local (`.env`) | En Kaanbal |
|---|---|---|
| `MONGO_URI` / `DATABASE_URL` | tu contenedor de `docker-compose.yml` | la base vinculada a esta app |
| `CORS_ORIGINS` | `http://localhost:5173` | el dominio del sitio |
| `APP_SECRET` | lo que pongas | generado y guardado en Vault |

Kaanbal inyecta además las variables con el prefijo del nombre de la base
(`MI_BASE_URI`, `MI_BASE_HOST`, `MI_BASE_USER`...). Usa los nombres cortos:
son estables y no dependen de cómo se llame la base en cada instalación.

## Desarrollo local

```bash
cp .env.example .env
docker compose up -d                 # la base, en tu máquina
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

`GET http://localhost:8000/health` responde `{"database": true}` cuando la
conexión está viva. La documentación interactiva está en `/docs`.

## La primera vez no hace falta crear nada a mano

`db.py:Store.init()` corre en cada arranque y crea lo que falte: la base, la
colección o la tabla y sus índices. Es idempotente. **Si agregas tablas,
colecciones o índices, hazlo ahí**: así el primer despliegue en Kaanbal y el
primer `docker compose up` de tu compañero funcionan sin pasos manuales.

Nunca escribas migraciones que borren o renombren columnas en el mismo paso que
las crea: en producción la versión vieja y la nueva conviven unos segundos
durante el rollout (expand/contract).

## De local a producción

```bash
git push origin main
```

Eso dispara el pipeline: construye la imagen, la publica y actualiza el
manifiesto. ArgoCD la despliega. No edites manifiestos de Kubernetes aquí: los
gobierna Kaanbal en su repositorio `infra-gitops`.

Lo que **no** debes hacer en este repo:

- Escribir credenciales o URIs reales en el código o en commits (`.env` está en
  `.gitignore` y así debe quedarse).
- Cambiar el puerto 8000 ni la ruta `/health`: el clúster los usa para saber si
  la app está viva.
- Asumir que hay una sola réplica o disco local: el contenedor es efímero y
  puede haber varias copias. El estado va en la base.

## Si algo falla al desplegar

El error casi siempre es una variable que la app espera y nadie inyecta. En la
consola de Kaanbal, en el menú de esta app, **Reconectar base de datos**
republica los nombres estándar del motor. Y `/health` dice si el problema es la
base o la app.
