# Roadmap del MCP y la operación por agentes

Actualizado: 2026-10-04 · Versión: 1.3.0

Qué se propuso, en qué estado está y qué falta para darlo por terminado. Es la lista
que retoma la próxima sesión: mueve cada fila de estado en el mismo PR que la cambia.

## Estados

| Estado | Significa |
|---|---|
| 💡 Idea | Propuesto, sin diseño ni código. |
| 🧭 Diseñado | Hay decisión de cómo hacerlo; falta el código. |
| 🛠️ En desarrollo | Hay una rama con trabajo a medias. |
| ✅ Desarrollado | Código y pruebas offline en una rama o en `main`; **sin validar en un clúster real**. |
| 🔒 Bloqueado | Hecho del lado del código, pero falta una decisión o un permiso del owner. |
| 🚀 En producción | Validado en al menos una célula real (anota cuál, sin datos reales, en la sesión). |
| ❌ Descartado | Se decidió no hacerlo; queda el motivo. |

## Seguridad e identidad

| Capacidad | Estado | Dónde | Falta |
|---|---|---|---|
| `whoami`: instancia, cuenta, token, versión | ✅ Desarrollado | `app/mcp/admin_tools.py` | Probar detrás del túnel que `X-Forwarded-Host` da la URL pública. |
| `platform_capabilities` completo (plataforma + autonomía, con lo que falta) | ✅ Desarrollado | `app/mcp/admin_tools.py` | — |
| `invoke_platform_tool` (se anunciaba y no existía) | ✅ Desarrollado | `app/mcp/admin_tools.py` | — |
| Saber los permisos antes de intentar (`GET /autonomy/access`) | ✅ Desarrollado | `app/routers/autonomy.py` | — |
| `platform_upgrade` como capacidad crítica | ✅ Desarrollado | `autonomy_catalog.py`, `routers/core.py` | — |
| Aprobación humana para lo irreversible (cola + consola) | ✅ Desarrollado | `app/services/approvals.py`, `AgentRequests.vue` | Probar el ciclo completo con un token crítico real. |
| Unificar los conectores duplicados de una misma instancia | 💡 Idea | — | Es configuración del cliente: documentar un nombre por célula (`kaanbal-<célula>`). |
| MFA con app autenticadora (TOTP) | 🧭 Diseñado | `docs/MCP_AUTONOMY.md` | Alta con QR, login en dos fases, recuperación. |

## Operación y recuperación

| Capacidad | Estado | Dónde | Falta |
|---|---|---|---|
| `restart_app` (rollout restart) | ✅ Desarrollado | `app/services/app_operations.py` | Desplegar el RBAC base con `patch` y probar. |
| `list_revisions` / `rollback_app` (tag en GitOps) | ✅ Desarrollado | `app_operations.py`, `routers/operations.py` | Probar con una app real con pipeline. |
| `promote_app` staging → prod | ✅ Desarrollado | idem | Solo backends; los frontends se promueven fusionando la rama. |
| `pipeline_logs` (CI con log enmascarado) | ✅ Desarrollado | `admin_tools.py` | Confirmar el formato de los pasos con GitHub Actions. |
| `app_metrics` | ✅ Desarrollado | `app_operations.py` | Requiere metrics-server (K3s lo trae). |
| `check_urls` (HTTP + certificado) | ✅ Desarrollado | `app/services/url_probe.py` | — |
| `diagnose_app` explica reinicios y trae eventos | ✅ Desarrollado | `app/services/diagnosis.py` | — |
| `wait_for_deploy` (esperar del lado del servidor) | ✅ Desarrollado | `admin_tools.py` | — |
| Notificaciones push al terminar un despliegue (webhook/SSE) | 💡 Idea | — | El MCP es sin estado; evaluar webhooks salientes configurables. |
| Latencia y errores 5xx por app | 💡 Idea | — | Necesita métricas del ingress (Traefik/Prometheus). |

## Datos

| Capacidad | Estado | Dónde | Falta |
|---|---|---|---|
| `backup_database` / `list_backups` (GridFS, últimos 10) | 🔒 Bloqueado | `app/services/data_operations.py` | El owner decide conceder `pods/exec` a `kaanbal-api` en los namespaces de apps (ver `docs/MCP_AUTONOMY.md`, «Datos de las bases»). |
| `restore_database` (plan, aprobación, respaldo de seguridad) | 🔒 Bloqueado | idem | idem; probar en una base de prueba antes que en prod. |
| `query_database` (solo lectura) | 🔒 Bloqueado | idem | idem |
| Respaldos programados (diarios) | 💡 Idea | — | Un loop o CronJob que llame a la misma función. |
| Estado de migraciones de esquema | ❌ Descartado | — | Las plantillas no usan un framework de migraciones común; no hay qué leer. |

## Desarrollo

| Capacidad | Estado | Dónde | Falta |
|---|---|---|---|
| Workspace desde la rama del ambiente / `base_branch` | ✅ Desarrollado | `app/services/autonomy.py` | — |
| `request_secret` (la persona pega el valor en la consola) | ✅ Desarrollado | `app/services/agent_requests.py`, `AgentRequests.vue` | — |
| Ambientes de vista previa por PR | 💡 Idea | — | Pipeline por rama, overlay efímero y limpieza al hacer merge. |

## Gobierno del inventario

| Capacidad | Estado | Dónde | Falta |
|---|---|---|---|
| `audit_platform` | ✅ Desarrollado | `app/services/platform_audit.py` | — |
| `set_app_group` / `set_display_name` | ✅ Desarrollado | `admin_tools.py` (REST ya existía) | — |
| `delete_app` (plan, respaldo previo, aprobación) | ✅ Desarrollado | `admin_tools.py`, `routers/apps.py` | Probar con una app de prueba. |
| Renombrar el nombre interno de una app | ❌ Descartado | — | Es la identidad en repo, clúster, DNS y Vault; `set_display_name` cubre el caso. |

## Experiencia del agente

| Capacidad | Estado | Dónde | Falta |
|---|---|---|---|
| Inventario como recursos MCP (`kaanbal://inventario/...`) | ✅ Desarrollado | `app/mcp/inventory.py` | — |
| Flujos guiados nuevos: auditar, volver versión, cuidar datos, cambiar código | ✅ Desarrollado | `app/mcp/prompts.py` | — |
| Avisar al cliente que cambió la lista de herramientas (`listChanged`) | 💡 Idea | — | Requiere sesión/SSE en el MCP. |
