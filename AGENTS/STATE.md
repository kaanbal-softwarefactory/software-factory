# Estado operativo

Actualizado: 2026-10-21 · Versión: 1.3.0

## Resumen

Primera versión pública. Este repositorio empieza aquí una historia nueva; el proyecto vivía
antes en `ProyectosUniUAEH/software-factory` (ver `docs/guides/MIGRATION.md`).

La 1.3.0 convierte el MCP en una herramienta de administración: identidad del conector,
capacidades completas por token, versiones y rollback, datos de las bases, auditoría y
aprobación humana para lo irreversible. El avance por capacidad vive en
[`ROADMAP.md`](ROADMAP.md).

## En curso

- **GitHub personal y repos propios por MCP** — en `main` (2026-10-25), sin instalar en la célula todavía. Cada persona conecta su GitHub en Conectar → Tu GitHub; sus agentes usan `github_repos`, `open_repo_workspace` y `push_workspace` (rama nueva, o la principal con «Push directo» en la política). Pruebas offline en verde; falta probarlo en la célula con un repo real. Guía: `SOFTWARE_FACTORY/docs/MCP_AUTONOMY.md`.

- **HUB2: continuidad entre proveedores y Dev** — contexto y prompts guardados en main; código todavía WIP en `codex/hub-dev-workflow` (`6ea71a0`). Leer [punto de continuación](../docs/guides/HUB_CONTINUITY.md) antes de tocar Hub/ambientes. Incluye nuevos requisitos de workers Kubernetes vía MCP, GitHub por usuario y archivos fuente. Checkpoint: 48 pruebas Hub, 2 errores; UI aún sin montar; nada desplegado. Actualización del core manual.

- **Hub de agentes** — en `main` (5f25d32) e instalado en la célula de laboratorio: coordinación de Codex/Claude/Cursor/ChatGPT
  por grupo (sesiones con latido, traza proyecto → día → agente, tareas con dependencias y
  toma atómica, mensajes, tablero, drive `fuente/` + `live/` en GridFS, plan
  `kaanbal.hub.json`, secretario con y sin IA). 19 herramientas `hub_*` en el MCP, vistas
  `/hub` y `/hub/:group`, permisos `hub.*`. Pruebas offline: API 615+ con recorrido de dos
  agentes sobre Mongo en memoria y extracción de ZIP reales de fases; consola build. En la
  célula, subidas de 1, 5 y 20 MB funcionan (~0.6 MB/s); un ZIP de ~42 MB en una sola
  petición no llega a guardarse (probable corte del proxy): hace falta subida por partes.
  Falta probarlo con el proyecto piloto y dos agentes reales. Guía:
  `SOFTWARE_FACTORY/docs/AGENT_HUB.md`.

- **Business Base módulos y calendario** — rama `codex/business-base-modules-calendar`:
  selector consola/MCP para contacto, catálogo y citas; citas incluye catálogo.
  Selección persistida por organización y aplicada en API; `[]` deja solo la base.
  Calendario semanal del equipo con zona horaria del negocio, límites y aislamiento.
  Migración aditiva 004 conserva defaults de copias anteriores; bootstrap no
  reconfigura organizaciones existentes. Nueva demo remota del Starter publicado
  quedó ready; esta mejora todavía requiere publicación/integración/actualización.
  GitHub conectado solo permite lectura del core; CLI sin autenticación.

- **Business Base Starter** — rama `codex/business-base-starter`, incluye el contrato
  MCP pendiente de la rama anterior. Agrega preset starter con landing en `/`,
  panel del equipo `/admin` y portal `/client`, selección consola/MCP y URLs en
  plan para homepage/subdominio. Migración aditiva conserva la experiencia al
  reiniciar; repos generados guardan preset/marca para local:up. Guía STARTER.md.
  Probado en copia local aislada con Keycloak/PostgreSQL y navegador real; pendiente
  publicar/integrar/actualizar célula, GitHub conectado sin push. La demo remota
  existente no recibe estos cambios automáticamente.

- **Business Base stack candidato** — rama `codex/business-base-stack`: catálogo
  `business-base-demo`, PostgreSQL/Keycloak/app con worker, credenciales Vault
  fuera de Git, bootstrap idempotente y espera real de readiness. Pruebas:
  API 577 (1 omitida), 13 contratos de credenciales/stack/Kustomize, consola build, 7 unitarias
  de negocio, 33 GitOps y bootstrap con IdP en modo producción/PostgreSQL reales.
  Integrado e instalado en célula dev-234ac49; primera demo remota con tres
  componentes ready y lanzamiento succeeded. HTTPS, health, ready y redirección
  OIDC comprobados; aceptación remota autenticada/MFA aún pendiente. Correo
  capturado, sin entrega externa. Contrato:
  `SOFTWARE_FACTORY/business-base/KAANBAL_STACK.md`.

- **Business Base y Sistemas** — rama `codex/business-base-systems`: prototipo local
  Next.js/PostgreSQL/Keycloak con login OIDC, MFA verificado, aislamiento por organización,
  landing, catálogo, contacto/inbox, portal, citas, equipo y auditoría. La consola agrega
  responsables y etapas a los grupos existentes. Integrado con stack beta, aún
  candidato sin aceptación empresarial. Guía: `SOFTWARE_FACTORY/business-base/README.md`.
- **Contrato MCP Business Base** — rama `codex/business-base-mcp-contract`:
  corrige receta genérica, declara conexiones por proceso y muestra responsable
  del grupo en el plan. SMTP por cliente documentado como propuesta en
  `SOFTWARE_FACTORY/business-base/EMAIL_PROFILES.md`, aún sin panel ni integración.
- **MCP de administración (1.3.0)** — en `main`, con pruebas offline (524 pruebas de la
  API, 10 del puente, build de consola). Falta: publicar la release `v1.3.0` y validarlo
  en una célula real (ciclo de aprobación, rollback, reinicio). Detalle en
  `sessions/2026-10-04-mcp-administracion.md`.
- **Plantilla Next.js full-stack y sus dos stacks (1.3.0)** — construida y probada fuera
  del clúster (`npm run build`, servidor `standalone` respondiendo `/api/health`, alta y
  lectura de notas en memoria). Falta: el ciclo `draft → validating → ready` en una célula
  y una prueba con la base vinculada de verdad.

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
