"""
La guía de Kaanbal, para agentes y personas
===========================================

Lo que un agente necesita saber para trabajar bien sobre la plataforma sin
adivinar: cómo se llaman las cosas, cómo llega el código a producción, cómo se
conecta una app con su base, cómo se publica en un dominio y qué hacer cuando
algo falla. La sirven la herramienta platform_guide y los recursos
kaanbal://guia/<tema>, con el mismo texto.

Este módulo no importa nada de `app.*`: el test de compatibilidad lo carga solo.
"""

from __future__ import annotations

from typing import Dict, List

TOPICS: Dict[str, Dict[str, str]] = {
    "plataforma": {
        "title": "Qué es Kaanbal y cómo se organiza",
        "description": "Apps, ambientes, grupos, dominios y stacks: el mapa para no perderse.",
        "text": """\
# Kaanbal en una página

Kaanbal es una plataforma propia (self-hosted) para lanzar y operar aplicaciones:
Kubernetes (K3s) + ArgoCD + Vault + Cloudflare Tunnel + Tailscale, gobernado por
GitOps. Todo lo que despliega vive en un repositorio `infra-gitops`; ArgoCD aplica
lo que hay ahí.

## Las piezas

- **App**: una pieza desplegable (un frontend, una API, una base, n8n…). Su nombre
  es su identidad en todo el sistema: repositorio, Deployment, Service, aplicación
  de ArgoCD y ruta de secretos en Vault. Por eso es único en toda la plataforma.
- **Plantilla**: de qué está hecha una app (vue3-spa, react-spa, fastapi-api,
  mongodb, postgres, n8n, emqx…). `list_templates` muestra las disponibles.
- **Ambientes**: dev, staging y prod. Prod siempre existe; cada ambiente es un
  despliegue aparte con sus propias variables.
- **Grupo**: etiqueta para ordenar apps que van juntas (el sitio, su API, su base).
- **Dominio**: cada app pública vive en un dominio registrado en la plataforma.
  Uno es el default. Un dominio puede tener un **homepage**: la app que responde
  en la raíz (`https://midominio.com`).
- **Stack**: un sistema completo de una vez, ya cableado: base → API vinculada a la
  base → frontend que apunta a la API. `list_stacks` muestra los disponibles.

## URLs

- prod: `https://<app>.<dominio>` (o `https://<dominio>` si es el homepage)
- dev y staging: `https://<ambiente>-<app>.<dominio>`
- Por VPN (Tailscale): `<ambiente>-<app>` en la tailnet.

## Qué usar para qué

- Un sitio completo nuevo → `launch_stack` (con o sin homepage).
- Una pieza suelta (otra API, un n8n, una base) → `create_app`.
- Conectar piezas que ya existen → `link_apps`.
- Publicar, mudar de dominio o dar la raíz → `set_exposure`, `attach_domain`, `set_homepage`.
- Algo falla → `diagnose_app` primero, siempre.
""",
    },
    "desarrollo-local": {
        "title": "Trabajar en local igual que en la plataforma",
        "description": "El mismo código corre en tu máquina y en el clúster: variables, base local y migraciones.",
        "text": """\
# Desarrollo local

La regla que lo explica todo: **la configuración llega por variables de entorno,
nunca escrita en el código**. En local salen de un `.env`; en Kaanbal las inyecta
la plataforma. Los nombres son los mismos en los dos lados, así que el mismo código
corre igual. `app_contract` te dice qué variables recibe cada app (solo nombres).

## API (fastapi-api)

```bash
cp .env.example .env
docker compose up -d                 # la base, en tu máquina
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

- La base llega por `MONGO_URI` / `DATABASE_URL` (y `PGHOST`, `MONGO_DATABASE`…).
  En local apuntan a tu contenedor; en Kaanbal, a la base vinculada.
- `GET /health` dice si la base responde. No cambies el puerto 8000 ni esa ruta:
  el clúster los usa para saber si la app está viva.
- Si el frontend corre en `http://localhost:5173`, agrégalo a `CORS_ORIGINS` en `.env`.

## Frontend (vue3-spa, react-spa)

```bash
npm install
npm run dev            # http://localhost:5173
```

- La URL de la API llega por `VITE_API_URL`: `.env.development` apunta a tu API
  local; `.env.production` (el que usa el pipeline) a la API publicada.
- Todo lo que entra en un build de frontend lo ve quien abre la página: nunca
  pongas secretos ahí. Las credenciales viven en la API.

## Cambios en la base (migraciones)

- Crea colecciones, tablas e índices en el arranque de la app, de forma idempotente
  (en la plantilla de API: `db.py`, `Store.init()`). Así el primer despliegue y el
  primer `docker compose up` de otra persona funcionan sin pasos manuales.
- Expandir y después contraer: agrega columnas o campos nuevos en un despliegue y
  borra los viejos en otro posterior. Durante un despliegue conviven unos segundos
  la versión vieja y la nueva.

## Datos

- Cada ambiente tiene su propia base y sus propios datos; prod no se toca para probar.
- Para copiar datos entre tu máquina y una base de la plataforma se usan las
  herramientas del motor (`mongodump`/`mongorestore`, `pg_dump`/`psql`) con acceso
  por VPN: expón la base por Tailscale en ese ambiente (`set_exposure`) y pide las
  credenciales a quien administra la plataforma (el MCP nunca las muestra).

## Nunca

- Credenciales o URIs reales en el código o en commits (`.env` va en `.gitignore`).
- Editar manifiestos de Kubernetes en el repo de la app: los gobierna Kaanbal en
  `infra-gitops`.
- Suponer una sola réplica o disco local: el contenedor es efímero. El estado va en la base.
""",
    },
    "desplegar": {
        "title": "Cómo llega el código a producción",
        "description": "Ramas, pipeline, ArgoCD y cómo seguir o deshacer un despliegue.",
        "text": """\
# Del commit al clúster

Cada app con código tiene su repositorio y su pipeline. Cada ambiente escucha
una rama:

| Ambiente | Rama |
|---|---|
| dev | `develop` |
| staging | `staging` |
| prod | `main` |

```bash
git push origin main      # → prod
```

El pipeline construye la imagen, la publica y actualiza su etiqueta en
`infra-gitops`; ArgoCD la despliega. No hay que tocar nada más.

## Seguir un despliegue

- `deploy_status(name)`: en qué va la app (alta, cambios de exposición, dominio,
  homepage) y sus últimos pasos.
- `app_health(name)`: estado en ArgoCD por ambiente y resultado del último pipeline.
- `stack_status(run_id)`: en qué pieza va un stack.
- Si no arranca: `diagnose_app(name, env)`.

## Deshacer

Todavía no hay un botón de rollback: revierte el commit (`git revert`) y empuja;
el pipeline despliega la versión anterior. Mientras tanto, la versión vieja sigue
sirviendo si la nueva no llega a estar sana (el despliegue es gradual).

## Plantillas sin código

Las bases y los servicios de imagen oficial (mongodb, postgres, n8n, emqx) no
tienen repositorio ni pipeline: se despliegan directo desde su imagen oficial.
""",
    },
    "conectar": {
        "title": "Conectar apps: bases, servicios y variables",
        "description": "Vínculos con bases y con otras apps, variables propias y el frontend con su API.",
        "text": """\
# Conectar piezas

## Una app con su base

`link_apps(name=<api>, to=<base>)` le da a la API las credenciales de la base,
por ambiente (dev con dev, prod con prod):

- Con el prefijo del vínculo: `TIENDA_DB_URI`, `TIENDA_DB_HOST`, `TIENDA_DB_USER`…
- Y los nombres estándar del motor, si faltan: `MONGO_URI`, `DATABASE_URL`,
  `PGHOST`, `REDIS_URL`… Tu código debería usar estos: no dependen de cómo se
  llame la base en cada instalación.

Nadie ve los valores: ni el agente ni la respuesta. La app se reinicia sola con
las variables nuevas. Crear la app ya conectada: `create_app(..., database=<base>)`.

## Una app con otra (tráfico interno)

`link_apps(name=<worker>, to=<api>)` le da `PAGOS_API_HOST`, `PAGOS_API_PORT` y
`PAGOS_API_URL`: la dirección de la otra app dentro del clúster. No pasa por
internet ni depende de cómo esté expuesta la otra app.

`unlink_apps` quita exactamente lo que puso el vínculo.

## Un frontend con su API

La URL de la API va **dentro del build** del frontend (`VITE_API_URL`), así que
tiene que ser una URL pública: el navegador de quien abre la página no ve la red
interna. `create_app(template=vue3-spa, api=<api pública>)` la deja configurada;
los stacks lo hacen solos.

## Variables propias

`set_app_variable` agrega lo que la app pide y nadie le da (`ADMIN_PASSWORD`, la
clave de un servicio externo…). Con `generate=true` la plataforma crea un valor
aleatorio que nadie ve. No pisa una variable existente sin `overwrite=true` y no
toca las que gestiona la plataforma (las de la base).
""",
    },
    "exponer": {
        "title": "Exposición, dominios y homepage",
        "description": "Quién puede llegar a cada ambiente, en qué dominio vive y quién ocupa la raíz.",
        "text": """\
# Quién llega a una app

Cada ambiente de cada app tiene un modo:

| Modo | Quién llega |
|---|---|
| `public` | internet, por Cloudflare, en su dominio |
| `tailscale` | solo quien está en la VPN |
| `both` | rutas públicas + el resto por VPN (se configura en la consola) |
| `lan` | la red local del nodo |
| `internal` | solo otras apps del clúster |
| `off` | nadie: el ambiente se apaga (0 réplicas) |

Lo típico: prod `public`, dev y staging `tailscale`, bases `internal`.

- `set_exposure(name, per_env={"dev": "tailscale"})` cambia el modo por ambiente.
- `attach_domain(name, domain)` muda una app pública a otro dominio: la URL nueva
  se prueba antes de retirar la vieja.
- `set_homepage(name)` le da la raíz de su dominio. Solo uno por dominio, y su prod
  tiene que ser pública.

Los tres muestran primero el plan (qué URLs aparecen y cuáles dejan de responder)
y corren en segundo plano: el resultado se ve con `deploy_status`.
""",
    },
    "mcp": {
        "title": "Cómo trabajar con este MCP",
        "description": "Plan antes de aplicar, permisos del token y lo que el MCP nunca hace.",
        "text": """\
# Trabajar con el MCP de Kaanbal

## Plan antes de aplicar

Todo lo que crea algo o cambia lo que se ve en internet se pide dos veces:

1. Sin `plan_id`: la herramienta devuelve el **plan** (qué se crea, qué URLs
   cambian, qué variables llegan) y un `plan_id`. No se aplica nada.
2. Se le muestra el plan a la persona. Si lo aprueba, se repite la llamada con los
   mismos argumentos y `plan_id`.

Si algo cambió entre medias (otra app tomó el nombre, la app cambió de estado), el
plan ya no coincide y no se toca nada: se pide el plan de nuevo. Aplica a
`create_app`, `launch_stack`, `link_apps`, `unlink_apps`, `set_exposure`,
`attach_domain` y `set_homepage`.

Lo demás actúa directo: `sync_app`, `repair_db_bindings`, `set_app_variable`,
`start_app`, `stop_app` y `scale_app`. Igual se confirma con la persona antes.

## Permisos

El token decide qué puede hacer el agente: cada herramienta dice qué permiso
necesita. Un token de solo lectura puede diagnosticar y guiar, pero no crear ni
cambiar. Los tokens se crean en la consola, en **Acceso → Tokens**.

## Lo que el MCP nunca hace

- Mostrar el valor de un secreto (ni variables, ni credenciales de bases).
- Borrar apps o dominios, tocar las credenciales de la plataforma o actualizar el
  core: eso se hace en la consola, con una persona mirando.

## Por dónde empezar

- "No funciona" → `diagnose_app`.
- "Quiero lanzar algo" → `platform_guide(plataforma)` y `list_stacks` / `list_templates`.
- "¿Cómo trabajo en local?" → `app_contract`.
""",
    },
    "problemas": {
        "title": "Cuando algo falla",
        "description": "Síntomas comunes, qué significan y con qué herramienta se resuelven.",
        "text": """\
# Cuando algo falla

Empieza siempre por `diagnose_app(name, env)`: dice en lenguaje simple qué pasa,
con la evidencia (sin secretos) y la acción que lo arregla.

| Síntoma | Causa típica | Qué hacer |
|---|---|---|
| Se reinicia en bucle y el log pide una variable | nadie le inyecta esa variable | `set_app_variable` o `link_apps` |
| "authentication failed" contra la base | credenciales que no coinciden con los datos guardados | lo que proponga `diagnose_app` (a veces requiere a una persona) |
| La app pide `MONGO_URI`/`DATABASE_URL` y no está | app creada antes de los nombres estándar | `repair_db_bindings` |
| Se queda "desplegando" | la versión nueva no arranca y la vieja sigue sirviendo | `diagnose_app` y `app_logs` |
| No baja la imagen | el pipeline no publicó esa etiqueta | revisa el pipeline (`app_health`) |
| Responde 502/404 en su URL | exposición o DNS a medias | `deploy_status` y `set_exposure` |
| Se cae sin error | memoria insuficiente (OOMKilled) | `diagnose_app` lo confirma; el límite de memoria vive en su overlay de `infra-gitops` |

`activity` muestra quién cambió qué y cuándo: útil para saber qué pasó justo antes.
""",
    },
}

DEFAULT_TOPIC = "plataforma"


def topic_names() -> List[str]:
    return list(TOPICS)


def text(topic: str) -> str:
    if topic not in TOPICS:
        raise KeyError(topic)
    return TOPICS[topic]["text"]


def resource_uri(topic: str) -> str:
    return f"kaanbal://guia/{topic}"


def resources() -> List[Dict[str, str]]:
    """Lo que ve el cliente en resources/list."""
    return [
        {
            "uri": resource_uri(name),
            "name": name,
            "title": item["title"],
            "description": item["description"],
            "mimeType": "text/markdown",
        }
        for name, item in TOPICS.items()
    ]


def read_resource(uri: str) -> Dict[str, str]:
    prefix = "kaanbal://guia/"
    if not uri.startswith(prefix) or uri[len(prefix):] not in TOPICS:
        raise KeyError(uri)
    return {"uri": uri, "mimeType": "text/markdown", "text": TOPICS[uri[len(prefix):]]["text"]}
