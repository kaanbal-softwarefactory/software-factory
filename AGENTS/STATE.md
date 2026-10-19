# Estado operativo

Actualizado: 2026-10-19 · Versión: 1.3.0

## Resumen

Primera versión pública. Este repositorio empieza aquí una historia nueva; el proyecto vivía
antes en `ProyectosUniUAEH/software-factory` (ver `docs/guides/MIGRATION.md`).

La 1.3.0 convierte el MCP en una herramienta de administración: identidad del conector,
capacidades completas por token, versiones y rollback, datos de las bases, auditoría y
aprobación humana para lo irreversible. El avance por capacidad vive en
[`ROADMAP.md`](ROADMAP.md).

## En curso

- **MCP de administración (1.3.0)** — en `main`, con pruebas offline (524 pruebas de la
  API, 10 del puente, build de consola). Falta: publicar la release `v1.3.0` y validarlo
  en una célula real (ciclo de aprobación, rollback, reinicio). Detalle en
  `sessions/2026-10-04-mcp-administracion.md`.

## Conocido y pendiente

Las limitaciones de la versión están en el [README](../README.md#status-and-known-limitations).
En resumen:

- Instalación completa en Ubuntu 26.04 sin validar de punta a punta.
- Versiones de K3s, Argo CD y Tailscale sin fijar.
- Vault sin auto-unseal; el token raíz sembrado en la API es la credencial actual.
- Docker Hub obligatorio; sin builder local con registro alternativo.
- Sin `CODE_OF_CONDUCT.md`: falta elegir un canal de contacto.
- Respaldos, restauración y consultas de bases (`data.*`) necesitan que el owner conceda
  `pods/exec` a `kaanbal-api` en los namespaces de apps por GitOps. Sin eso, esas
  herramientas responden qué falta. Ver `SOFTWARE_FACTORY/docs/MCP_AUTONOMY.md`.
- Los tokens críticos emitidos antes de la 1.3.0 no tienen los permisos nuevos
  (`data.*`, `apps.releases.manage`): hay que emitir uno nuevo.

## Cómo mantener este archivo

Una lista corta, no un diario: lo que la próxima persona debe saber antes de tocar algo.
El detalle de cada sesión va en `sessions/`; el estado de cada capacidad, en `ROADMAP.md`.
