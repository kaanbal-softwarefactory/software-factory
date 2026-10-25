"""
Textos que el Hub entrega para arrancar el ciclo
================================================

1. ChatGPT web (o cualquier chat) arma las fases del proyecto con la persona: imágenes,
   instrucciones, contenido validado y un plan de tareas. Las entrega como ZIP con una
   estructura que el Hub entiende.
2. La persona sube el ZIP al proyecto en Kaanbal: queda como fuente de los agentes.
3. Cada agente (Codex, Claude Code, Cursor…) arranca con un mensaje corto que apunta
   al Hub; el resto lo lee de ahí.

Sin dependencias de `app.*` para poder probarlo solo.
"""

from __future__ import annotations

CHATGPT_PHASES_PROMPT = """\
Vamos a definir un proyecto de software por fases para que lo construya un equipo de agentes de código \
(Codex, Claude Code, Cursor) coordinados en Kaanbal. Tú me ayudas a pensar y refinar la idea conmigo; \
al final de cada fase (o cuando te lo pida) me entregas un ZIP descargable con esta estructura EXACTA:

{{PROYECTO}}/
  kaanbal.hub.json                 Plan de tareas (formato abajo). Obligatorio en la fase de coordinación.
  00_BRIEF/
    BRIEF.md                       Qué es, para quién, objetivos, alcance y lo que NO entra.
    CONTENIDO_VALIDADO.md          Datos reales confirmados por la persona (textos, servicios, contacto).
                                   Lo que no esté confirmado va marcado como PROPUESTA.
  FASE_01_<nombre>/
    INSTRUCCIONES.md               Qué construir en esta fase, criterios de aceptación y rutas/pantallas.
    MATRIZ.csv                     pantalla_o_modulo,ruta,acciones,datos,owner_sugerido,prioridad
    IMAGENES/                      Mockups PNG/JPG numerados (01_portada.png …). Solo referencia visual.
    PROTOTIPO/                     (opcional) HTML estático de referencia.
  FASE_02_<nombre>/ …              Igual que la fase 1.
  FASE_NN_COORDINACION/
    00_PRIMERO_LEER.md             Cómo se reparten el trabajo los agentes, oleadas y reglas.
    MATRIZ_OWNERSHIP.csv           area,owner_sugerido,archivos_o_carpetas,notas
    CONTRATOS/                     Contratos API/tipos que deben acordarse antes de trabajar en paralelo.

Formato de kaanbal.hub.json (JSON válido, sin comentarios):
{
  "version": 1,
  "board": "Markdown corto: objetivo, estado, reglas del proyecto y enlaces a las fases.",
  "tasks": [
    {"key": "T01", "title": "Auditar el repositorio real", "area": "integración", "phase": "W0",
     "depends_on": [], "description": "Qué hacer y criterio de terminado.",
     "sources": ["FASE_05_COORDINACION/00_PRIMERO_LEER.md"]},
    {"key": "T02", "title": "Contrato de API de cotizaciones", "area": "backend", "phase": "W1",
     "depends_on": ["T01"], "description": "…", "sources": []}
  ]
}

Reglas para el plan:
- Tareas pequeñas (una por PR), con key única (T01, T02…), área (frontend, backend, diseño, integración, qa) \
y depends_on solo hacia keys del mismo plan, sin ciclos.
- Primero auditoría y contratos; después trabajo en paralelo por área sin que dos agentes toquen los mismos archivos.
- Las imágenes son referencia visual: nunca fuente de datos, precios, reseñas, clientes ni cifras.
- No incluyas contraseñas, tokens, llaves ni datos personales.
- Si una fase está incompleta, dilo en INSTRUCCIONES.md: los agentes y la persona la completan después.

Cuando agregue o cambie una fase más adelante, entrégame SOLO la carpeta de esa fase (y el kaanbal.hub.json \
actualizado si cambian tareas), con los mismos nombres, para subirla encima de la anterior.

Si tienes conectado el MCP de Kaanbal, puedes leer el estado del proyecto con hub_briefing, proponer tareas con \
hub_create_task (quedan como propuesta hasta que una persona las acepte) y dejar documentos de texto con \
hub_write_note. Los ZIP con imágenes los subo yo desde la consola.
"""


def agent_start_prompt(group: str, harness: str = "", specialty: str = "") -> str:
    """El mensaje corto con el que una persona arranca su agente en el proyecto."""
    who = f" Eres {harness}." if harness else ""
    focus = f" Tu especialidad declarada: {specialty}." if specialty else ""
    return (
        f"Trabajamos en el proyecto '{group}' coordinado en Kaanbal.{who}{focus}\n"
        f"1. Llama a hub_join(group='{group}', agent=<tu nombre corto>, harness=<codex|claude|cursor>, "
        "specialty=<en qué eres bueno>, focus=<qué vas a hacer>) y guarda el session_id.\n"
        "2. Lee lo que te devuelve: tablero, quién está en línea, tareas disponibles para ti, bloqueos y últimos "
        "relevos. Si necesitas una fuente, ábrela con hub_read_file (solo las imágenes de tu tarea).\n"
        "3. Sigue el modo del proyecto (work_mode y objective del briefing): en modo guiado propón qué tomarás y "
        "espera mi visto bueno; en modo autónomo toma con hub_claim_task y avanza sin preguntar hasta cumplir el "
        "objetivo. Si otro agente está en línea, coordínate con hub_message antes de cruzar su área.\n"
        "4. Mientras trabajas: hub_sync cada ~2 min o tras cada paso; hub_log para decisiones, bloqueos y preguntas; "
        "notas, contratos e informes en live/ con hub_write_note.\n"
        "5. Al terminar: hub_update_task (review/done, rama y PR) y hub_leave con un relevo útil para el siguiente."
    )


REPO_SNIPPET = """\
## Coordinación en Kaanbal (Hub de agentes)

Este repositorio se trabaja con varios agentes a la vez. La coordinación vive en el Hub de Kaanbal
(MCP de Kaanbal, herramientas `hub_*`), no en el chat:

- Al empezar: `hub_join` con el grupo del proyecto; lee el tablero y los relevos, no todo el histórico.
- Antes de editar: `hub_claim_task`. Una tarea = una rama = un PR. No edites archivos de otra tarea en curso.
- Durante: `hub_sync` cada ~2 min o tras cada paso; `hub_log` para decisiones, bloqueos y preguntas.
- Al terminar: `hub_update_task` con rama/PR y `hub_leave` con el relevo.
- Fuente del proyecto (fases, imágenes, contenido validado): `hub_files` / `hub_read_file` en `fuente/`.
"""
