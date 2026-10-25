# Retomar trabajo desde otra máquina o proveedor

Kaanbal es el punto de encuentro; el historial de un chat no debe ser requisito para continuar.

## Punto actual: HUB2

- Proyecto Hub: `software-factory`. Tarea: `HUB2`, abierta para continuar.
- [Relevo completo](../handoffs/2026-10-25-hub2-continuar-en-claude.md).
- [Prompt original: workers, GitHub y archivos](../handoffs/2026-10-25-hub2-prompt-usuario.md).
- [Últimos comentarios: continuidad visible, MCP y acceso remoto](../handoffs/2026-10-25-hub2-ultimos-comentarios.md).
- [Resultado de pruebas del checkpoint](../handoffs/2026-10-25-hub2-verificacion.txt).
- Código WIP publicado: rama `codex/hub-dev-workflow`, commit `6ea71a0`.

El contexto está guardado en main; el código incompleto está en la rama remota. Estar en una rama publicada es suficiente para cambiar de máquina sin perderlo. Ninguno de estos documentos significa que la funcionalidad esté desplegada.

## Desde el Hub o MCP

Abre el proyecto y lee «Contexto y acuerdos» en Resumen. Los documentos están en Archivos → live/relevos/. Un agente usa hub_join y lee su briefing/tablero/relevos; conserva su nuevo session_id. Puede consultar hub_briefing sin abrir sesión. No reutilizar session_id de otro agente.

Instrucción breve para la persona:

> Continúa el trabajo de software-factory desde el último punto guardado en Kaanbal. Lee el tablero y sus relevos antes de modificar código.

Instrucción guardada para el siguiente agente:

> Entra al Hub del proyecto software-factory con tu propia identidad. Lee el tablero y live/relevos/2026-10-25-hub2-continuar-en-claude.md, el prompt original y live/relevos/2026-10-25-hub2-ultimos-comentarios.md. Consulta el estado actual de HUB2 y coordínate antes de tomarla. Recupera la rama remota codex/hub-dev-workflow, checkpoint 6ea71a0, y comprueba si hay commits posteriores. Completa primero UI y pruebas de contexto compartido, Dev aislado y promoción explícita. Después avanza el diseño de workers por MCP, conexión GitHub por usuario y subida de fuentes. Mantén manual la actualización del core. No confundas revisión, merge, despliegue y cambio visible. Conserva un nuevo punto portable al salir.

## Desde Git en otra máquina

Con acceso ya configurado al repositorio:

```bash
git fetch origin
git switch -c continuar-hub2 origin/codex/hub-dev-workflow
```

Usar otro nombre de rama si ya existe. Antes de editar, leer AGENTS.md, esta guía y el relevo. Las credenciales, entornos virtuales y herramientas de la máquina anterior no viajan en el commit; usar las propias conexiones del nuevo entorno. No copiar tokens ni publicar archivos de secretos.

## Qué guardar al cambiar de agente

Guardar en live/ objetivo autorizado, decisiones, archivos útiles, tarea, repo/rama/SHA, pruebas realmente ejecutadas, despliegue real, bloqueos y siguientes pasos. Actualizar el tablero con un enlace corto al último punto. Publicar el código en Git, avisar por hub_message y dejar hub_leave. No marcar done por guardar un checkpoint.

El botón dedicado «Continuar con otro agente» y la asignación de workers son alcance pendiente, documentado en los últimos comentarios. Hoy esta guía utiliza el tablero y las herramientas existentes.
