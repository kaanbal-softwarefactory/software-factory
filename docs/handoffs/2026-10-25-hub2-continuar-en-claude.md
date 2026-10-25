# Relevo HUB2: continuar desde Claude

Fecha: 2026-10-25. Autor: Codex. Estado: **checkpoint WIP, NO listo para desplegar**.

## Instrucción inmediata del usuario

Se agotaron los créditos. Guardar una versión del código, sus requisitos/prompts, el análisis y lo pendiente, publicar un relevo en el Hub y avisar a Claude para que continúe. No perder el trabajo ni presentarlo como terminado. Este checkpoint sustituye continuar implementando en esta sesión.

## Objetivo y requisitos del usuario (transcripción organizada de la conversación)

- Hub como centro del proyecto: fases, textos, instrucciones y archivos aportados por la persona; servicios del stack (frontend/backend Next.js, PostgreSQL e Identity Provider); contexto suficiente para cualquier agente.
- Dos trazas: una del proyecto del cliente y otra global `software-factory` para mejoras/fricciones de Kaanbal, con referencia al proyecto de origen. Andrés y Agustín colaboran con varios proveedores de agentes y posteriormente más personas.
- Resumen vivo breve, sesiones por persona/agente, quién trabaja en qué, tareas, bloqueos y relevos. Conservar decisiones y resúmenes útiles de conversaciones; NO prometer captura automática de chats privados de cada proveedor.
- Desarrollo continuo sobre `develop` y ambiente Dev aislado; CI, despliegue, comprobación del commit real y evidencia de funcionamiento. No confundir tarea revisada, commit en main, imagen desplegada y cambio visible.
- Dev separado de producción incluyendo base de datos, IdP y secretos. Evitar copiar datos de producción. Un stack nuevo debería disponer de ambos ambientes. Implementación actual solo empieza por Business Base; extender a todos los stacks es pendiente.
- Promoción explícita del commit comprobado de Dev a main mediante PR que revisa/fusiona la persona. Evitar acumulación de ramas desconectadas. Agentes pueden colaborar libremente en Dev.
- Actualización de la propia plataforma Kaanbal: MANUAL. El usuario quiere elegir cuándo instalar nuevos commits; no autoactualizar el core. Autorizó commits directos a main para su core, pero este checkpoint se conserva en rama WIP porque falta revisión y pruebas.
- Preparar una segunda ronda real de dos agentes en el proyecto piloto, con Codex principalmente UI/UX y Claude backend.

## Nueva ampliación del usuario: workers y GitHub por persona

El usuario propone aprovechar Kubernetes de Kaanbal para crear pods de trabajo remotos, con repos clonados y herramientas preparadas, solicitables desde MCP por Codex, Claude u otro cliente. Quiere un pool de workers/ambientes y no depender de configurar GitHub en cada computadora/proveedor. Su sesión de Kaanbal (por ejemplo Andrés) debe asociarse a su propia conexión GitHub. Consideró inicialmente un token clásico amplio para reducir fricción. MCP es el punto de entrada, con permisos del usuario. También quiere cargar PDFs, imágenes y archivos al proyecto desde MCP. Los workers trabajan y despliegan en Dev; producción se promociona por PR aprobado por una persona.

Diseño recomendado (propuesta, AÚN NO implementado):
1. Separar ambiente de ejecución del agente (worker pod) y ambiente Dev de la app (servicios persistentes). Un worker no es el despliegue de la aplicación.
2. Conexión GitHub asociada al usuario, almacenada cifrada en Vault y referenciada por identidad; preferir GitHub App con tokens breves por repo/instalación. Admitir PAT temporal como transición sin distribuir el token maestro a agentes ni mostrarlo por MCP.
3. API/MCP para solicitar/reusar worker, consultar estado, ejecutar trabajos/comandos con límites, obtener logs/artefactos y cerrar; enlazar user/project/session/task/commit. Trabajos asíncronos, cuotas, TTL y recuperación al cambiar de proveedor.
4. Pod no privilegiado con workspace persistente acotado, recursos/límites, identidad Kubernetes y red por proyecto; credenciales limitadas a los repos autorizados y Dev. Acceso a main/producción requiere flujo separado.
5. Archivos: subida MCP por upload/chunks con tamaño/MIME/checksum y permisos, guardado en fuente/; agentes escriben resultados en live/. La implementación actual de hub_write_note admite base64 pequeño pero no sustituye subida robusta de fuentes.
6. Relevo portable: guardar prompt autorizado, resumen, decisiones, rama/commit, pruebas, próximos pasos y archivos en Hub. Otro proveedor debe poder retomar desde ese punto sin necesitar esta conversación.

Límite técnico: conectar un MCP no da automáticamente una terminal a un cliente. El servidor debe exponer las herramientas de ejecución remota y el cliente debe permitir invocarlas. Tampoco Kaanbal aporta por sí solo créditos/modelo de Codex o Claude.

## Código guardado en esta rama

Rama `codex/hub-dev-workflow`, basada en main `e6f354a`. Este commit es WIP. No fusionar/desplegar sin completar las verificaciones.

- `services/hub_workspace.py`: contexto resumido, servicios seguros, sesiones/personas, checkpoints y estados de entrega.
- `routers/hub.py`: overview/briefing enriquecidos; proyecto global; checkpoints; feedback del proyecto a plataforma con backlinks; plan/confirmación Dev con fingerprint, expiración y lease; job de preparación; PR de promoción fijado al SHA verificado; permisos de integración y verificación por tarea.
- `services/agent_hub.py`, `mcp/hub_tools.py`, `mcp/catalog.py`, `services/permissions.py`: protocolo/catálogo de checkpoint y feedback, parámetros de verificación, reglas de acceso.
- `services/hub_integration.py`: integración a rama/ambiente seleccionados, merge del SHA comprobado, rechazo de CI solo skipped y Argo sin imagen, smoke HTTP/readiness; PR de promoción fijado a SHA sin merge automático.
- `services/hub_dev.py`: prepara Dev del stack Business Base existente preservando código personalizado y develop, pipeline adicional, overlays/secretos/URLs Dev; espera Argo+SHA y smoke. NO ejecutado contra infraestructura real.
- `business_stack.py`, `business_deployer.py`, `stack_launcher.py`, `routers/stacks.py`: soporte Business Base dev/prod, overlays Dev independientes, secretos/Vault por ambiente. Evita usar ensure_env genérico que copia prod sin reescribir servicios correctamente.
- `git_provider.py`: pipeline GitHub verifica ramas/PR; publica imágenes/GitOps solo para ramas de ambiente; evita push fallido con CI verde.
- `HubWorkspace.vue`: componente de UI nuevo con resumen, servicios, fuentes/fases, Dev, promoción y feedback. **Todavía no importado/montado en HubProject**, por eso no se verá. Sesiones y formularios existentes aún requieren adaptación.
- `tests/test_hub_integration.py`: dos ajustes al contrato nuevo; pruebas nuevas pendientes.

## Verificación real hasta el checkpoint

La ejecución anterior de tests Hub tuvo 72 pruebas con 1 failure + 2 errors (SHA fijado y fixture sin Dev); se ajustaron esas expectativas/fixture, pero no se habían repetido. Error inicial de regex con lookahead Pydantic corregido. No afirmar suite verde, build completo ni despliegue real. Los resultados de la última ejecución de checkpoint, si existen, van en `2026-10-25-hub2-verificacion.txt` junto a este documento.

## Próximos pasos concretos para Claude

1. Leer AGENTS.md, docs/CONTEXT_MAP.yaml, visión, AGENTS/STATE.md y CONTRIBUTING.md; inspeccionar diff del checkpoint contra e6f354a. Consultar Hub global software-factory, tarea HUB2 y este relevo. Coordinar con claude-andres antes de cruzar T09 del piloto.
2. Completar UI: montar HubWorkspace en HubProject con overview.workspace y files; pestaña/resumen sesiones/personas; enlace global en landing; ajustes de modo a Dev/develop; etiquetas de tareas distinguen revisión/despliegue/verificación/aceptación visual. Sincronizar promotion en contexto después de refresh.
3. Revisar carreras y errores: promesas UI al navegar de grupo, job Dev/lease/reintentos, excepciones GitHub/CI que podrían dejar estado checking; locks de integración solo por proceso. Persistencia/reanudación de jobs tras reinicio pendiente.
4. Revisar servicio_cards root domain y etiquetas de otros ambientes; validar manifest Dev antes de escribir si image inesperada; comprobar existencia namespace Dev por GitOps; no copiar overlays Prod genéricos.
5. Tests significativos: permisos/ownership, feedback doble traza, checkpoints acotados, plans caducados/actor incorrecto, leases, promoción rechaza SHA no verificado, no merge; Dev conserva Prod byte a byte/secretos separados/código personalizado y ramas; CI solo skipped, imagen faltante, branch móvil, Argo wrong env, readiness y marcador; pipeline YAML deploy solo ramas configuradas.
6. API suite completa + build/pruebas consola + MCP/instalador aplicables. Navegador móvil/desktop y teclado para modales. Playwright está disponible en node_modules del repo piloto, Chromium del sistema `/usr/bin/chromium` (descarga browser bloqueada).
7. Actualizar guías/prompts MCP para nuevos tools y flujo Dev. Implementar nueva ampliación workers/GitHub personal/subida de fuentes en entregas revisables posteriores; actualmente son diseño, no funcionalidad.
8. Mantener actualización del core manual: publicar cambios revisados, dar al usuario versión exacta para actualizar. Solo después provisionar Dev real y comprobar SHA/URL/servicios antes de afirmar segunda ronda lista. No marcar tarea done por solo hacer commit.

## Contexto operativo portable

- Repos del core y piloto son independientes. El piloto tiene main `9511c7e`, PRs 1–3 integrados y prod-9511c7e, landing sin cambios porque lo integrado era base/contratos/refactor. T06/T08 son funcionalidad visible pendiente; T09 Claude API en review, rama claude/t09-quotes-api f216977. No modificar esas tareas sin coordinar.
- Hub global: group `software-factory`, tarea HUB2 id `a4e5bf8770284f1a`. Sesión saliente Codex `d703bf66de624948`, agente `codex-uiux`. El siguiente agente debe hub_join y usar SU session_id, no reutilizar esta.
- Desde esta máquina MCP se usa con `/workspace/.venvs/kaanbal-mcp/bin/python /workspace/.kaanbal-setup/mcp_call.py TOOL` y JSON por stdin. Helper usa KAANBAL_TOKEN del entorno, no guardado en repo. Otro proveedor configura su propio MCP/credenciales.
- Git clone/push funciona con credenciales del entorno. api.github.com está bloqueado en este runtime; no es prueba de falta de permiso GitHub. No exponer tokens ni leer .env/keys. Nueva conexión GitHub por persona no está implementada.
- API Python: `/workspace/.venvs/kaanbal-api/bin/python`; consola node_modules ya instalado. Mantener proxy y CA heredados. No SSH ni cambios manuales de cluster.

## Prompt para retomar

Continúa HUB2 desde la rama codex/hub-dev-workflow. Lee este relevo y las notas live/ del Hub software-factory. El checkpoint es WIP, no terminado: completa UI y pruebas del flujo proyecto/contexto global/Dev aislado/promoción explícita antes de desplegar. Conserva la actualización manual de Kaanbal. Integra como siguiente alcance workers Kubernetes solicitables por MCP, GitHub asociado al usuario y archivos fuente por MCP. Coordínate con los agentes del piloto y deja checkpoints portables al cambiar de proveedor. No afirmes despliegue o cambios visibles sin comprobar SHA, salud y URL.

## Resultado actualizado de la comprobación del checkpoint

`python -m unittest discover -s tests -p 'test_hub*.py'`: 48 tests, 2 errores, exit 1. Ambos provienen del nuevo `_workspace_context` llamando `domain_service.resolve_for_app` que usa un `db` no configurado en el fixture (`AttributeError: NoneType ... system_config`). Corregir la inyección/mock de dominio y repetir la suite, comprobando también comportamiento real ante configuración faltante. Evidencia completa en `2026-10-25-hub2-verificacion.txt`. No se corrió suite completa ni build de consola en este checkpoint.

El prompt literal más reciente está en `2026-10-25-hub2-prompt-usuario.md`.
