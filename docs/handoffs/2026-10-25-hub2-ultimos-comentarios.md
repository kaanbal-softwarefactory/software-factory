# Últimos comentarios del usuario: retomar sin trasladar contexto

Fecha: 2026-10-25. Complementa el relevo HUB2 y su prompt original.

## Pedido literal

> esto justo es el problema tal vez inluso en el software kanbal puedes dejar el prompt para retomar o algo asi
> estamos seguro ahora d elos cambios si quieres peudes temirnar y ya dejar en main en software factory para que tenga todas etas mejoras y lo que vamos a implementar sobre ambientes
> entiendo que el mcp igual podria conectarse directo al ambiente dime si es optimo realmente,  y esque realmente quiero aterrziar la forma mas facil para los usuario, veo que puedo incluso crear un entorno en claude codes cursor pero confirma con ssh y otros modos. pero bueno esto como arte de la iea para que lo dejes com ode los ultimos comentarios igual pero saber igual si podemos guardar en main de la software factory o no es necesario apra hora para no olvidar aqui nada de contexto y eguir trabajando en otra maquina

## Decisión aplicada para conservar el trabajo

- Contexto, prompts y guía de continuación se publican en main y en el Hub. Un clone de main debe descubrir el trabajo pendiente mediante AGENTS/STATE.md y docs/CONTEXT_MAP.yaml, sin necesitar esta máquina ni esta conversación.
- El código WIP sigue publicado en codex/hub-dev-workflow, checkpoint 6ea71a0. No hace falta fusionarlo a main para retomar desde otro proveedor. Su rama remota contiene todos sus archivos; el siguiente agente debe hacer fetch y crear su rama de continuación desde ella.
- No se presenta HUB2 como terminado: falta montar UI, corregir dos errores en pruebas y completar validaciones de Dev/producción. El usuario autorizó main; esa autorización no convierte el WIP en funcionalidad verificada.
- No se despliega ni actualiza automáticamente la instalación de Kaanbal. La actualización del core sigue siendo una decisión manual del usuario.

## Experiencia objetivo

En cada proyecto: **Continuar con otro agente**. Mostrar punto guardado (fecha, autor, tarea, versión), resumen corto, siguientes acciones y botón **Copiar instrucciones**. El texto visible para la persona debe ser simple: «Continúa el trabajo de este proyecto desde el último punto guardado en Kaanbal». El agente obtiene por MCP el detalle técnico, no la persona.

El punto debe contener objetivo/prompt autorizado, decisiones, archivos fuente necesarios, repo/rama/SHA, tarea y dependencias, estado real de pruebas/despliegues, pendientes y requisitos del entorno. Versionado y permisos del proyecto. No almacenar secretos ni afirmar que se copiaron conversaciones privadas completas; guardar solo lo expresamente aportado o resumido por el agente.

La solución disponible hoy usa el tablero existente y live/relevos/ por MCP. El botón específico y la generación automática de un punto portable son comportamiento propuesto, aún no implementado.

## Ambientes: recomendación técnica

Preferir MCP HTTPS de Kaanbal como entrada común. El servidor autentica a la persona, resuelve su proyecto y asigna un worker con repos y permisos adecuados. Herramientas MCP ejecutan trabajos remotos asíncronos y devuelven estado/logs/resultados. No abrir un MCP independiente por pod como requisito para cada usuario; agregaría URLs/tokens y problemas al reciclar pods. Un MCP dentro del worker puede existir como adaptador interno, sin cambiar la entrada pública.

Separar tres cosas:

1. **Worker:** espacio donde se modifica código y corren CLI/herramientas. Vida limitada; workspace/relevo persistentes cuando corresponda.
2. **Dev:** aplicación desplegada con sus propios servicios, datos, IdP, secretos y URL; verificable aun sin worker activo.
3. **Producción:** recibe un commit comprobado mediante PR/promoción explícita. No hereda automáticamente permisos del worker.

Modos posibles de acceso al mismo worker:

| Modo | Uso | Límite |
| --- | --- | --- |
| MCP HTTPS + herramientas de ejecución | Agente en un cliente con herramientas MCP | Hay que implementar ejecución, archivos y trabajos; MCP conectado no implica terminal |
| CLI en el worker, desde terminal SSH o web | Ejecutar Claude Code/Codex donde ya están los repos | Requiere autenticación del proveedor del modelo y conectividad; no aporta suscripción/créditos |
| IDE compatible con Remote SSH | Desarrollo interactivo sobre archivos remotos | Requiere servidor SSH y transporte autorizado; compatibilidad concreta del editor debe probarse |
| Dev Container / editor web | Entorno reproducible e interfaz sin instalación local | Imagen/configuración, autenticación y persistencia por implementar |
| Entorno cloud propio del proveedor | Capacidades administradas por ese proveedor | No asumir que puede incorporar un pod arbitrario de Kaanbal como su entorno nativo |

Conexión GitHub del usuario en Vault. Preferir GitHub App y tokens de corta duración acotados al repo/instalación; un PAT temporal puede ser transición. No dar el token maestro al agente ni incluirlo en logs/artefactos. Conservar cuotas/TTL/identidad por proyecto y usuario. No usar pods privilegiados, credenciales globales o acceso Kubernetes general para la ejecución ordinaria.

## Fuentes consultadas y alcance de la comprobación

Lectura realizada el 2026-10-25:

- [Documentación oficial de VS Code Remote SSH](https://github.com/microsoft/vscode-docs/blob/main/docs/remote/ssh.md): confirma apertura de carpetas remotas por SSH en máquina, VM o contenedor con servidor SSH.
- [Claude Code, repositorio oficial](https://github.com/anthropics/claude-code): confirma la herramienta de línea de comandos. No se probó un login ni sesión real de Claude en un worker.
- [Codex CLI, repositorio oficial](https://github.com/openai/codex): confirma la CLI; no se probó autenticación ni ejecución dentro de un worker Kaanbal.

Las páginas de documentación de Cursor y Claude Remote Control no fueron accesibles desde la política de red de este entorno. No se verificó su versión instalada, compatibilidad con un pod particular ni importación de un worker en el servicio cloud del proveedor. No se abrió conexión SSH ni se modificó infraestructura.
