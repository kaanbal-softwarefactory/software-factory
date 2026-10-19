# Sesión: 2026-10-04 — MCP de administración para agentes

## Objetivo de la sesión
Robustecer el MCP para que un agente pueda administrar la plataforma con capacidades
alineadas a cómo funciona Kaanbal, sin perder el control humano sobre lo irreversible.

## Resumen ejecutivo
Una prueba de solo lectura del conector mostró los huecos: conectores duplicados sin
identidad, `platform_capabilities` incompleto, `invoke_platform_tool` anunciado y sin
implementar, `platform_upgrade` sin marca de crítico y un reinicio sin causa en
`diagnose_app`. Se implementó todo lo propuesto salvo lo que depende de decisiones de
infraestructura (ver ROADMAP). El MCP pasa de 28 a 49 herramientas, más 19 capacidades
de autonomía, con una cola de aprobación humana.

## Trabajo realizado
- Aprobación humana (`approvals.py`, `/autonomy/approvals`, pestaña Solicitudes) para
  ejecutar, integrar, actualizar el core, restaurar y borrar → hecho, con pruebas.
- Identidad y capacidades: `whoami`, `platform_capabilities` completo, `invoke_platform_tool`,
  `/autonomy/access`, `elevated` en `/security/me` → hecho.
- Operación: `restart_app`, `list_revisions`, `rollback_app`, `promote_app`, `app_metrics`,
  `check_urls`, `pipeline_logs`, `wait_for_deploy` → hecho.
- Datos: `backup_database`, `list_backups`, `restore_database`, `query_database` → código
  hecho; bloqueado por el permiso `pods/exec` (decisión del owner).
- Gobierno: `audit_platform`, `set_app_group`, `set_display_name`, `delete_app`, `request_secret` → hecho.
- `diagnose_app` explica reinicios de apps sanas y trae eventos Warning → hecho.
- Recursos MCP del inventario y cuatro flujos guiados nuevos → hecho.
- Documentación: README del MCP, `docs/MCP_AUTONOMY.md`, guía del MCP, CHANGELOG 1.3.0,
  `AGENTS/ROADMAP.md` → hecho.

## Commits y pull requests
| Rama / PR | Commit | Descripción |
|---|---|---|
| `feat/mcp-admin-capabilities` | (pendiente) | feat(mcp): administración con aprobación humana |

## Problemas encontrados y soluciones
- **Problema**: el exec de Kubernetes no cierra stdin, así que `base64 -d | pg_restore`
  nunca terminaría.
  - **Causa raíz**: el protocolo v4 de exec no tiene cierre de stdin.
  - **Solución**: el comando de restauración lee exactamente los bytes enviados con `head -c N`.
- **Problema**: el ejecutor existente mezcla stdout y stderr; un aviso de `pg_dump`
  corrompería el volcado.
  - **Solución**: `data_operations.run` lee los dos canales por separado.
- **Problema**: escribir el manifiesto RBAC que concede `pods/exec` a la API fue rechazado
  por la revisión automática de permisos de esta sesión.
  - **Solución**: no se incluyó; queda como decisión del owner, documentada en prosa.

## Lecciones (para no volver a tropezar)
- Los tests de catálogo codifican principios ("el MCP nunca borra"). Cambiar un principio
  es reescribir el test con el principio nuevo (aquí: lo irreversible exige plan, token
  crítico y aprobación), no borrarlo.
- Un frontend no se promueve moviendo su imagen: el build lleva las URLs del ambiente.

## Estado al cerrar
- Todo lo tocado está en la rama `feat/mcp-admin-capabilities`, sin commit todavía.
- Pruebas: pasan (API 516 con dependencias completas, los 3 contratos de autonomía del CI —el de flujo ahora prueba la aprobación del merge—, 10 del puente MCP y build de consola).
- Commits locales sin subir: los de esta rama, cuando se hagan.

## Pendientes para la próxima sesión
- Revisar y fusionar el PR; publicar la release `v1.3.0` para que las células la vean.
- Validar en una célula real: ciclo de aprobación, `restart_app`, `rollback_app`, `whoami`
  detrás del túnel.
- Decidir el permiso `pods/exec` para los datos de las bases.
- Ideas abiertas en `AGENTS/ROADMAP.md`.
