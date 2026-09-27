# MCP de Kaanbal

Conecta tu agente (Claude Code, Cursor, Codex…) a **tu** Kaanbal para que entienda
qué hay desplegado y por qué algo falla, y pueda arreglar lo que es seguro
arreglar: apps, salud, diagnóstico, logs, dominios, bitácora y tres acciones.

**No hay nada que instalar.** La propia plataforma sirve el MCP por HTTP:

```
https://<la-api-de-tu-célula>/mcp
```

Se autentica con tu **token personal**. El agente ve exactamente lo que tú puedes
ver: si el token no trae un permiso, la plataforma le dice cuál falta.

## Crear el token

En la consola: **Acceso → Tokens → + Nuevo token**. Ponle un nombre que diga para
qué es ("MCP de <tu nombre>") y cópialo: se muestra una sola vez.

- **Solo lectura (recomendado para empezar):** ver apps, diagnosticar, leer logs.
- Para que además pueda **sincronizar** o **reconectar la base**: `apps.apps.deploy`.
- Para que pueda **agregar variables que faltan** (p. ej. generar `ADMIN_PASSWORD`):
  `apps.variables.manage`.

## Conectar el agente

**Claude Code:**

```bash
claude mcp add --transport http kaanbal https://kaanbal-api.example.com/mcp --header "Authorization: Bearer kbl_..."
```

**Cursor** (`~/.cursor/mcp.json`) y otros clientes con soporte HTTP, con la misma forma:

```json
{
  "mcpServers": {
    "kaanbal": {
      "url": "https://kaanbal-api.example.com/mcp",
      "headers": { "Authorization": "Bearer kbl_..." }
    }
  }
}
```

**Codex** y cualquier cliente que acepte un servidor MCP por URL: la misma URL y el
encabezado `Authorization: Bearer <token>`. Cada quien apunta a la célula que le
toca, con su propio token.

### Clientes que solo hablan stdio

Este paquete es un puente mínimo: lanza un proceso local que reenvía cada mensaje
a `/mcp`. Solo necesita `httpx`.

```json
{
  "mcpServers": {
    "kaanbal": {
      "command": "python",
      "args": ["-m", "kaanbal_mcp"],
      "cwd": "C:/ruta/a/software-factory/SOFTWARE_FACTORY/kaanbal-mcp",
      "env": { "KAANBAL_URL": "https://kaanbal-api.example.com", "KAANBAL_TOKEN": "kbl_..." }
    }
  }
}
```

## Qué puede hacer

| Herramienta | Para qué | Permiso |
|---|---|---|
| `diagnose_app` | **Por qué falla una app**, en lenguaje simple, con la evidencia y la acción que lo arregla | `apps.apps.diagnose` |
| `list_apps` | Apps con su dominio, URL y estado | `apps.apps.view` |
| `get_app` | Detalle de una app | `apps.apps.view` |
| `app_health` | Salud en ArgoCD por ambiente y último pipeline | `apps.apps.view` |
| `app_logs` | Últimas líneas de log de los pods | `apps.apps.diagnose` |
| `app_env_var_names` | **Nombres** de las variables que recibe la app | `apps.apps.diagnose` |
| `list_domains` | Dominios registrados | `domains.domains.view` |
| `list_stacks` | Catálogo de stacks y últimos lanzamientos | `stacks.catalog.view` |
| `platform_status` | Versión, actualizaciones, salud, Vault | `system.health.view` |
| `activity` | Bitácora: quién hizo qué y cuándo | `logs.records.view` |
| `sync_app` | **Acción**: sincronizar con ArgoCD | `apps.apps.deploy` |
| `repair_db_bindings` | **Acción**: republicar MONGO_URI, DATABASE_URL… | `apps.apps.deploy` |
| `set_app_variable` | **Acción**: agregar una variable que falta (o generarla) | `apps.variables.manage` |

## Lo que no puede hacer, a propósito

- **Leer el valor de un secreto.** Ni los nombres de variables ni el diagnóstico
  traen valores, y las contraseñas en los logs llegan enmascaradas. Cuando
  `set_app_variable` genera un valor, el agente nunca lo ve.
- Pisar una variable existente sin `overwrite`, ni tocar las que gestiona la
  plataforma (la conexión a la base).
- Crear o borrar apps, tocar las credenciales de la plataforma, actualizar el core
  o administrar accesos. Eso se hace en la consola, con una persona mirando.

## Ejemplo

> «El backend de north-star-bay está en rojo, ¿por qué?»

El agente llama `diagnose_app` y recibe: *«Tu código pide la variable MONGO_URI y
la app no la recibe»*, con la línea del traceback como evidencia y la acción
`repair_db_bindings`, y además que la versión nueva no arranca mientras la anterior
sigue atendiendo. Si su token lo permite, lo arregla; si no, te dice qué hacer.

## Desarrollo

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
```

`tests/test_sdk_compat.py` conecta el cliente oficial del SDK de MCP al protocolo
que sirve la API (`kaanbal-api/app/mcp/`), que se implementa sin el SDK.
