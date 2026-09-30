# MCP de Kaanbal

Conecta tu agente (Claude Code, Cursor, Codex…) a **tu** Kaanbal para que entienda
qué hay desplegado y por qué algo falla, lance apps y stacks, las conecte, las
publique en tus dominios y las opere — con el plan a la vista antes de cambiar nada,
y guiado por la propia plataforma (cómo trabajar en local, cómo desplegar).

**No hay nada que instalar.** La propia plataforma sirve el MCP por HTTP:

```
https://<la-api-de-tu-célula>/mcp
```

Se autentica con tu **token personal**. El agente ve exactamente lo que tú puedes
ver: si el token no trae un permiso, la plataforma le dice cuál falta.

## Crear el token

En la consola: **Acceso → Tokens → + Nuevo token**. Ponle un nombre que diga para
qué es ("MCP de <tu nombre>") y cópialo: se muestra una sola vez.

- **Solo lectura (recomendado para empezar):** ver apps, diagnosticar, leer logs y
  la guía. El rol **Agente** es exactamente eso.
- Para que además pueda **crear, conectar, publicar y operar**: el alcance del rol
  **Operador** (o solo los permisos de la tabla de abajo que quieras darle).
- Para reparar con comandos o proponer código: concede los permisos de autonomía,
  recursos exactos en **Acceso → Autonomía** y, para operaciones críticas, emite
  un token con **Control total** y confirmación de contraseña. Estos tokens duran
  como máximo 24 horas. Cada token muestra vigencia, revocación y actividad.

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

## Plan antes de aplicar

Las herramientas ordinarias que **crean apps o cambian lo que se ve en internet**
se piden dos veces. La primera vez devuelven el plan —qué apps se crean, qué URLs aparecen o
dejan de responder, qué variables llegan (solo nombres)— y un `plan_id`, y no toca
nada. El agente te muestra el plan; si lo apruebas, repite la llamada con el
`plan_id`. La plataforma recalcula el plan y solo aplica si sigue siendo idéntico
(si otra app tomó el nombre entre medias, no pasa nada y se pide el plan de nuevo).

Lo largo (crear, exponer, mudar de dominio) corre en segundo plano: el agente lo
sigue con `deploy_status` o `stack_status`.

Las herramientas de **Autonomía avanzada** tienen controles distintos: ACL, token,
concesión exacta del recurso y, para operaciones críticas, confirmación al emitir
el token. Al invocarlas ejecutan la acción solicitada; revisa el alcance antes.

## Qué puede hacer

**Entender**

| Herramienta | Para qué | Permiso |
|---|---|---|
| `diagnose_app` | **Por qué falla una app**, en lenguaje simple, con la evidencia y la acción que lo arregla | `apps.apps.diagnose` |
| `list_apps` / `get_app` | Apps con su dominio, URLs, exposición y operaciones en curso | `apps.apps.view` |
| `app_health` | Salud en ArgoCD por ambiente y último pipeline | `apps.apps.view` |
| `app_logs` | Últimas líneas de log de un ambiente, con credenciales enmascaradas | `apps.apps.diagnose` |
| `app_env_var_names` | **Nombres** de las variables que recibe la app | `apps.apps.diagnose` |
| `deploy_status` | En qué va una app: alta, exposición, dominio, homepage | `apps.apps.view` |
| `stack_status` | En qué pieza va el lanzamiento de un stack | `stacks.catalog.view` |
| `list_templates` / `list_stacks` / `list_domains` | Con qué se crea y dónde se publica | `*.view` |
| `platform_status` | Versión, actualizaciones, salud, Vault | `system.health.view` |
| `activity` | Bitácora: quién hizo qué y cuándo | `logs.records.view` |

**Crear** (con plan)

| Herramienta | Para qué | Permiso |
|---|---|---|
| `create_app` | Una app desde una plantilla, con los valores del Wizard; opcionalmente conectada a su base (`database=`) o, si es un frontend, a su API (`api=`) | `apps.apps.create` |
| `launch_stack` | Base + API + frontend de una vez, ya cableados, con o sin homepage | `stacks.stacks.launch` |

**Conectar** (con plan)

| Herramienta | Para qué | Permiso |
|---|---|---|
| `link_apps` / `unlink_apps` | Darle a una app las credenciales de su base (y `MONGO_URI`, `DATABASE_URL`…) o la dirección interna de otra app; quitar exactamente eso | `links.links.manage` |
| `set_exposure` | Quién llega a cada ambiente: internet, VPN, LAN, solo el clúster o apagado | `apps.apps.expose` |
| `attach_domain` | Mudar una app a otro dominio (la URL nueva se prueba antes de retirar la vieja) | `apps.apps.expose` |
| `set_homepage` | Darle a una app la raíz de su dominio | `apps.apps.expose` |

**Operar**

| Herramienta | Para qué | Permiso |
|---|---|---|
| `start_app` / `stop_app` / `scale_app` | Encender, apagar o escalar un ambiente | `apps.apps.deploy` |
| `sync_app` | Sincronizar con ArgoCD | `apps.apps.deploy` |
| `repair_db_bindings` | Republicar MONGO_URI, DATABASE_URL… | `apps.apps.deploy` |
| `set_app_variable` | Agregar una variable que falta (o generarla) | `apps.variables.manage` |

**Autonomía avanzada**

El MCP HTTP integrado anuncia estas herramientas según los permisos del token.
`platform_capabilities` devuelve el catálogo vivo y los esquemas de argumentos:
después de actualizar Kaanbal, nuevas capacidades compatibles aparecen en
`tools/list` sin reinstalar el cliente.

| Herramienta | Para qué | Permiso |
|---|---|---|
| `execute_app_command` | Ejecutar un comando dentro de la app autorizada | `autonomy.apps.execute` y token crítico |
| `execute_node_command` | Reparación root en un nodo exacto | `autonomy.host.execute` y token crítico |
| `open_app_workspace` / `open_core_workspace` | Preparar código en contenedor temporal | `autonomy.workspaces.manage` y, para core, `autonomy.core.contribute` |
| `workspace_files` / `write_workspace_file` / `run_workspace_command` | Examinar, editar o validar código | `autonomy.workspaces.manage` |
| `workspace_diff` / `publish_workspace_pr` | Revisar cambios y proponer un PR | `autonomy.changes.propose` al publicar |
| `merge_app_pr` | Integrar una app con SHA revisado y checks de GitHub | `autonomy.changes.merge` y token crítico |
| `platform_upgrade` / `platform_upgrade_status` | Job de actualización del core | `core.updates.apply` / `core.updates.view` |

La política inicia desactivada. Los workspaces usan un snapshot del commit y
publican a GitHub desde la API; no reciben la credencial GitHub. El core siempre
queda como PR borrador para revisión y merge del owner. [Flujos, límites y
activación](../docs/MCP_AUTONOMY.md).

**Guiar**

| Herramienta | Para qué | Permiso |
|---|---|---|
| `platform_guide` | Cómo funciona Kaanbal: organización, desarrollo local, despliegue, conexiones, exposición, este MCP y problemas comunes | ninguno |
| `app_contract` | Lo que una app necesita y cómo trabajar en ella: puerto, ruta de salud, variables, vínculos, URLs, ramas y pasos locales | `apps.apps.view` |

### Flujos guiados y guía

Además de las herramientas, el MCP trae **flujos guiados** (prompts; en Claude Code
aparecen como comandos `/`): `lanzar-sitio`, `nueva-app`, `diagnosticar`,
`desarrollo-local`, `publicar` y `conectar-apps`. Y la guía de la plataforma como
**recursos** (`kaanbal://guia/<tema>`) para adjuntarla al contexto.

## Lo que no puede hacer, a propósito

- **Leer el valor de un secreto mediante las herramientas ordinarias.** Ni los nombres de variables, ni el diagnóstico,
  ni los planes traen valores, y las credenciales en los logs llegan enmascaradas.
  Cuando `set_app_variable` genera un valor o `link_apps` conecta una base, el agente
  nunca lo ve.
- Aplicar un cambio visible sin plan: `plan_id` no se puede inventar.
- Pisar una variable existente, ni tocar las que gestiona la plataforma.
- Borrar apps o dominios mediante las herramientas ordinarias. La ejecución de
  comandos críticos puede afectar recursos y revelar datos en su alcance; exige
  token crítico, ACL y concesión expresa. La actualización del core reutiliza el
  Job existente cuando el token tiene `core.updates.apply`.

## Ejemplos

> «El backend de north-star-bay está en rojo, ¿por qué?»

El agente llama `diagnose_app` y recibe: *«Tu código pide la variable MONGO_URI y
la app no la recibe»*, con la línea del traceback como evidencia y la acción
`repair_db_bindings`. Si su token lo permite, lo arregla; si no, te dice qué hacer.

> «Lanza una tienda con Vue, FastAPI y Mongo en midominio.com, en la raíz.»

El agente muestra el plan de `launch_stack` (`tienda-db` → `tienda-api` →
`tienda` en `https://midominio.com`), lo aplica cuando dices que sí, sigue el
avance con `stack_status` y termina con `app_contract` para decirte cómo correr
cada pieza en tu máquina.

## Desarrollo

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
```

`tests/test_sdk_compat.py` conecta el cliente oficial del SDK de MCP al protocolo
que sirve la API (`kaanbal-api/app/mcp/`), que se implementa sin el SDK.
