# MCP de Kaanbal

Conecta tu agente (Claude Code, Codex, Cursor) a **tu** Kaanbal para entender qué
pasa cuando algo falla: apps, salud, logs, dominios, bitácora — y las dos
acciones que se pueden repetir sin riesgo.

Corre en tu máquina y se autentica con tu **token personal**. El agente ve
exactamente lo que tú puedes ver: si el token no trae un permiso, la API dice que
no. Nadie comparte credenciales de la plataforma.

## Instalar

```bash
pip install -r requirements.txt
```

## Crear el token

En la consola: **Acceso → Tokens → + Nuevo token**. Ponle un nombre que diga para
qué es ("MCP de <tu nombre>"), pulsa **Solo lectura (recomendado)** y cópialo: se
muestra una sola vez.

Para que además pueda sincronizar o reconectar la base, marca también
`apps.apps.deploy`. Sin eso, esas dos herramientas responden que falta el permiso.

## Configurar el agente

Claude Code (`~/.claude/mcp.json`) o Codex/Cursor, con la misma forma:

```json
{
  "mcpServers": {
    "kaanbal": {
      "command": "python",
      "args": ["-m", "kaanbal_mcp"],
      "cwd": "C:/ruta/a/software-factory/SOFTWARE_FACTORY/kaanbal-mcp",
      "env": {
        "KAANBAL_URL": "https://kaanbal-api.example.com",
        "KAANBAL_TOKEN": "kbl_..."
      }
    }
  }
}
```

Cada quien apunta a la célula que le toca (`kaanbal-api.northwindlearning.site`
para el laboratorio) con su propio token.

## Qué puede hacer

| Herramienta | Para qué | Permiso |
|---|---|---|
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

## Lo que no puede hacer, a propósito

- **Leer el valor de un secreto.** `app_env_var_names` devuelve solo los nombres.
  Es lo que hace falta para diagnosticar (`KeyError: 'MONGO_URI'`) sin exponer
  contraseñas a un modelo.
- Crear o borrar apps, tocar credenciales, actualizar el core, administrar
  accesos. Eso se hace en la consola, con una persona mirando.

## Ejemplo

> «El backend de north-star-bay está en rojo, ¿por qué?»

El agente encadena `app_health` → `app_logs` → `app_env_var_names`, ve que el
código pide `MONGO_URI` y que la app solo recibe `NORTH_STAR_BAY_BD_URI`, y
propone `repair_db_bindings`. Si su token es de solo lectura, te dice qué hacer
en vez de hacerlo.
