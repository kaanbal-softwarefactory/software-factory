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

Lo largo (crear, exponer, mudar de dominio, rollback) corre en segundo plano: el
agente espera con `wait_for_deploy` o sigue `deploy_status` / `stack_status`.

## Aprobación humana para lo irreversible

Restaurar una base, borrar una app, ejecutar comandos en una app o en un nodo,
integrar un PR y actualizar el core exigen un **token crítico** y, además, que
**una persona apruebe esa acción concreta**:

1. El agente pide la acción (con su `plan_id`, si tiene plan). La API no la
   ejecuta: deja una solicitud con el resumen (el comando, el respaldo, la app) y
   responde con un `approval_id`.
2. Una persona la revisa en la consola, en **Acceso → Solicitudes**, confirma su
   contraseña y la aprueba o la rechaza (con nota opcional).
3. El agente repite exactamente la misma llamada con `approval_id`. La API vuelve
   a calcular la huella de la acción: si cambió un solo argumento, no sirve. Cada
   aprobación se usa una vez y vence a los 30 minutos.

Quien opera desde la consola con su sesión ya es la persona y no pasa por la cola.
El owner puede apagarla en la política de autonomía (solo para laboratorio).

## Qué puede hacer

**Entender**

| Herramienta | Para qué | Permiso |
|---|---|---|
| `whoami` | **A qué instancia le hablas** (URL de la API, dominio, versión), con qué cuenta y token, y si es crítico. Imprescindible con varios conectores de Kaanbal | ninguno |
| `platform_capabilities` | **Todas** las herramientas (plataforma y autonomía), cada una con su tipo (consulta, plan, acción, crítica), si este token puede usarla y qué le falta | ninguno |
| `diagnose_app` | **Por qué falla una app**, en lenguaje simple, con la evidencia y la acción que lo arregla. También explica reinicios de una app sana y trae los avisos de Kubernetes | `apps.apps.diagnose` |
| `pipeline_logs` | Por qué falló el build: pasos con error y el final de su log, enmascarado | `apps.apps.diagnose` |
| `app_metrics` | CPU y memoria por pod contra sus límites, con avisos | `apps.apps.diagnose` |
| `list_revisions` | Versiones (imágenes) que corrieron en un ambiente y cuál sirve hoy | `apps.apps.diagnose` |
| `check_urls` | Si la URL pública responde, en cuánto tiempo, y cuándo vence su certificado | `apps.apps.view` |
| `wait_for_deploy` | Espera del lado del servidor a que termine lo que está en curso | `apps.apps.view` |
| `audit_platform` | Hallazgos del inventario: grupos rotos, errores de escritura, bases sin uso o sin respaldo, apps no sanas | `apps.apps.view` |
| `list_secret_requests` | Secretos pedidos para una app y si ya se capturaron | `apps.apps.diagnose` |
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
| `restart_app` | Reiniciar los pods de a uno, sin apagar ni tocar GitOps | `apps.apps.deploy` |
| `sync_app` | Sincronizar con ArgoCD | `apps.apps.deploy` |
| `repair_db_bindings` | Republicar MONGO_URI, DATABASE_URL… | `apps.apps.deploy` |
| `set_app_variable` | Agregar una variable que falta (o generarla) | `apps.variables.manage` |
| `request_secret` | Pedir a una persona una credencial que solo ella tiene; el agente nunca la ve | `apps.secrets.request` |
| `rollback_app` (plan) | Volver a una versión que ya corrió, escribiendo su tag en GitOps | `apps.releases.manage` |
| `promote_app` (plan) | Llevar la imagen exacta de staging a prod (no aplica a frontends) | `apps.releases.manage` |
| `invoke_platform_tool` | Llamar por nombre una capacidad de autonomía publicada después de cargar el cliente | `autonomy.tools.view` |

**Datos** (bases `postgres` y `mongodb`)

| Herramienta | Para qué | Permiso |
|---|---|---|
| `list_backups` | Respaldos y restauraciones: cuándo, tamaño, huella y estado | `data.backups.view` |
| `backup_database` | Respaldo completo en segundo plano, guardado fuera del disco de la base | `data.backups.create` |
| `restore_database` (plan, crítica) | Reemplaza los datos con un respaldo; antes toma uno de seguridad | `data.backups.restore`, token crítico y aprobación |
| `query_database` | Lectura: SQL de solo lectura con tope de filas, o find/count en MongoDB | `data.records.read` y token crítico |

Requieren que la API pueda ejecutar en los pods de las bases (ver
[Datos de las bases](../docs/MCP_AUTONOMY.md#datos-de-las-bases)).

**Administrar**

| Herramienta | Para qué | Permiso |
|---|---|---|
| `set_app_group` / `set_display_name` | Ordenar el inventario sin tocar el nombre interno | `apps.apps.expose` |
| `delete_app` (plan, crítica) | Borrar una app; el plan muestra quién depende de ella y una base exige respaldo de las últimas 24 h | `apps.apps.delete`, token crítico y aprobación |

**Autonomía avanzada**

El MCP HTTP integrado anuncia estas herramientas según los permisos del token.
`platform_capabilities` devuelve el catálogo vivo y los esquemas de argumentos:
después de actualizar Kaanbal, nuevas capacidades compatibles aparecen en
`tools/list` sin reinstalar el cliente.

| Herramienta | Para qué | Permiso |
|---|---|---|
| `autonomy_access` | Qué concede la política a este token: capacidades, apps, ambientes y nodos | `autonomy.tools.view` |
| `get_approval` | Si una persona aprobó o rechazó una acción pendiente | `autonomy.tools.view` |
| `execute_app_command` | Ejecutar un comando dentro de la app autorizada | `autonomy.apps.execute`, token crítico y aprobación |
| `execute_node_command` | Reparación root en un nodo exacto | `autonomy.host.execute`, token crítico y aprobación |
| `open_app_workspace` / `open_core_workspace` | Preparar código en contenedor temporal, desde la rama del ambiente (`develop`, `staging`, `main`) o `base_branch` | `autonomy.workspaces.manage` y, para core, `autonomy.core.contribute` |
| `workspace_files` / `write_workspace_file` / `run_workspace_command` | Examinar, editar o validar código | `autonomy.workspaces.manage` |
| `workspace_diff` / `publish_workspace_pr` | Revisar cambios y proponer un PR hacia la rama del ambiente | `autonomy.changes.propose` al publicar |
| `merge_app_pr` | Integrar una app con SHA revisado y checks de GitHub | `autonomy.changes.merge`, token crítico y aprobación |
| `platform_upgrade` / `platform_upgrade_status` | Job de actualización del core | `core.updates.apply` con token crítico y aprobación / `core.updates.view` |

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
`desarrollo-local`, `publicar`, `conectar-apps`, `auditar-plataforma`,
`volver-version`, `cuidar-datos` y `cambiar-codigo`.

Como **recursos** para adjuntar al contexto: la guía (`kaanbal://guia/<tema>`), el
inventario (`kaanbal://inventario/apps`) y, por plantilla de URI, el detalle y el
contrato de cada app (`kaanbal://inventario/apps/{name}` y `.../{name}/contrato`).

## Lo que no puede hacer, a propósito

- **Leer el valor de un secreto.** Ni los nombres de variables, ni el diagnóstico,
  ni los planes traen valores, y las credenciales en los logs (de la app y del
  pipeline) llegan enmascaradas. Cuando `set_app_variable` genera un valor,
  `link_apps` conecta una base o una persona responde un `request_secret`, el
  agente nunca lo ve.
- Aplicar un cambio visible sin plan: `plan_id` no se puede inventar.
- Hacer algo irreversible sin una persona: restaurar, borrar, ejecutar comandos,
  integrar un PR o actualizar el core esperan una aprobación en la consola.
- Escribir en una base con `query_database`: corre en transacción de solo lectura
  (Postgres) o solo `find`/`count` (MongoDB), sin operadores que ejecuten código.
- Pisar una variable existente sin `overwrite`, ni tocar las que gestiona la plataforma.
- Tocar accesos, roles, tokens o las credenciales de la plataforma, ni borrar dominios.

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

> «El último despliegue de la API rompió el checkout; vuelve a la versión de ayer.»

El agente confirma con `diagnose_app` y `pipeline_logs`, lista las versiones con
`list_revisions`, te muestra el plan de `rollback_app` (de `prod-3f2a…` a
`prod-9c1d…`) y, si dices que sí, lo aplica y espera con `wait_for_deploy`.

> «Borra la base vieja de pruebas.»

El agente pide el plan de `delete_app`: le falta un respaldo reciente, así que
propone `backup_database`; con el respaldo listo te muestra quién depende de ella.
Al aplicar, la API deja la solicitud en **Acceso → Solicitudes**; cuando la
apruebas, el agente repite la llamada con el `approval_id` y se borra.

## Desarrollo

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
```

`tests/test_sdk_compat.py` conecta el cliente oficial del SDK de MCP al protocolo
que sirve la API (`kaanbal-api/app/mcp/`), que se implementa sin el SDK.
