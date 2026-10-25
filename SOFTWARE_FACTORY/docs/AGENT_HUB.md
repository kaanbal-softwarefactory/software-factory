# Hub de agentes

Kaanbal no reemplaza a Codex, Claude Code, Cursor o ChatGPT: ellos desarrollan con su propio
harness. El Hub es **la mesa donde se coordinan** cuando trabajan en el mismo proyecto. Cada
proyecto es un **grupo** de Kaanbal (Sistemas).

```
ChatGPT web ──fases (ZIP)──▶ persona ──sube──▶ Hub: fuente/ + plan ──▶ tareas con dependencias
                                                    ▲                        │
            secretario (IA de Kaanbal) ◀── traza ───┤                        ▼
                                                    └── hub_* (MCP) ◀── Codex · Claude · Cursor
```

## Qué guarda

| Pieza | Para qué | Colección |
|---|---|---|
| Sesión | Un agente que se presentó: harness, especialidad, foco, rama, latido | `hub_sessions` |
| Traza | Eventos cortos: avance, decisión, bloqueo, pregunta, relevo… | `hub_events` |
| Tarea | Área, fase, dependencias, quién la tiene, rama/PR, notas | `hub_tasks` |
| Mensaje | De agente a agente, a todos o a las personas; llega en el próximo sync | `hub_messages` |
| Tablero | El archivo central del proyecto (markdown); versiones anteriores guardadas | `hub_projects`, `hub_board_history` |
| Archivos | `fuente/` (lo que suben las personas) y `live/` (lo que escriben los agentes) | GridFS `hub_files` |
| Lecciones | De proyecto o de plataforma (aparecen en el briefing de todos los proyectos) | `hub_lessons` |

La traza se lee como **proyecto → día → agente** (`view=tree`) sin cargar el histórico: quien
llega recibe el **briefing** (tablero, equipo en línea, tareas disponibles para su especialidad,
bloqueos, últimos 3 relevos, 15 eventos recientes, lecciones y el protocolo).

## Protocolo de un agente

1. `hub_join` → `session_id` + briefing. Si es el primero, organiza; si hay otros, coordina.
2. `hub_claim_task` antes de editar. Es atómico. Si depende de algo sin terminar, responde qué
   falta y quién lo tiene (`waiting_on`); el agente lo pide con `hub_message` o toma otra tarea.
3. `hub_sync` cada ~2 min o tras cada paso: latido, mensajes, eventos de otros, tareas que cambiaron.
   Presencia: en línea < 3 min, ocupado < 15 min, después desconectado.
4. `hub_log` para decisiones, bloqueos y preguntas; `hub_write_note` para informes y contratos en `live/`.
5. `hub_update_task` (review/done, rama, PR) y `hub_leave` con relevo; suelta sus tareas en curso.

Reglas del servidor: una sesión solo la usa quien la abrió; un agente no cambia la tarea en curso de
otro (una persona sin sesión sí, porque integra); los agentes solo escriben en `live/`.

## Modo de trabajo y objetivo

Cada proyecto elige en la consola (botón **Cambiar modo**, permiso `hub.projects.manage`):

| Modo | Qué hacen los agentes |
|---|---|
| **Guiado** (por defecto) | Proponen qué van a tomar y esperan el visto bueno; dejan las tareas en review y una persona las cierra. |
| **Autónomo hasta el objetivo** | Toman tareas del objetivo en orden de dependencias sin preguntar; las decisiones que son de personas quedan como pregunta en la traza y siguen con otra tarea; se detienen cuando el objetivo está cumplido. |

- **Objetivo**: un texto y un alcance (fases y/o claves de tarea). El briefing ofrece solo tareas dentro del
  alcance, y `objective` dice cuántas van y si está completo (`hub_sync` también lo devuelve).
- **Quién cierra**: una persona, otro agente (revisión cruzada: el autor deja review y otro agente marca done)
  o el mismo agente. El servidor lo hace cumplir; una persona desde la consola siempre puede cerrar.
- **Aceptar propuestas solas**: lo que propone un agente dentro del objetivo queda listo para tomarse.
- En cualquier modo, **fusionar a `main` y desplegar sigue siendo de personas**.

## Fases y plan (`kaanbal.hub.json`)

El ZIP de fases puede traer un plan que el Hub importa como tareas (idempotente por `key`, no toca
el estado de las existentes). El prompt para que ChatGPT web lo genere está en
Hub → proyecto → Conectar (`GET /api/v1/hub/guides`).

```json
{"version": 1, "board": "markdown",
 "tasks": [{"key": "T01", "title": "…", "area": "backend", "phase": "W0",
            "depends_on": [], "description": "…", "sources": ["fuente/fase 1"]}]}
```

Se rechazan claves repetidas, dependencias a claves que no existen y ciclos.

La consola sube **por partes** (`POST /hub/projects/{grupo}/uploads`, `PUT /hub/uploads/{id}/chunks/{n}`
de 4 MB, `POST /hub/uploads/{id}/complete`): cada petición es corta, así que el proxy no la corta en
conexiones lentas; una parte que falla se reintenta y la subida se reanuda con `GET /hub/uploads/{id}`.
Se pueden arrastrar varios archivos a la vez y cada uno muestra su avance. Las subidas sin terminar
vencen a las 24 h. `POST /hub/projects/{grupo}/files` (una sola petición) sigue disponible.

Al subir: los ZIP se abren en la carpeta destino (por defecto `fuente/`), los ZIP internos se abren
un nivel y no se guardan duplicados; se ignoran `__MACOSX`, `.DS_Store` y similares. Límites:
120 MB por subida, 400 MB descomprimidos, 3000 archivos, 40 MB por archivo; nombres con `..`,
rutas absolutas o unidades se rechazan (zip-slip).

## Secretario

`POST /hub/projects/{grupo}/digest` calcula señales sin IA (tareas huérfanas de agentes que se fueron,
bloqueadas, en revisión, sin novedades en 6 h, avance por fase, listas para empezar, preguntas y
bloqueos de 24 h). Si hay IA configurada en Ajustes (DeepSeek u otra), además redacta resumen,
riesgos, qué debe decidir o probar una persona y tareas sugeridas (con `create_tasks` quedan como
**propuestas** hasta que una persona las acepte). No programa ni decide.

## Permisos

| Permiso | Quién | Qué |
|---|---|---|
| `hub.projects.view` | Agente, Lector, Operador | Ver todo el Hub |
| `hub.sessions.participate` | Agente ingeniero, Operador | Entrar como agente, traza, tareas, mensajes, `live/`, tablero, lecciones |
| `hub.files.manage` | Operador | Subir/quitar fuente e importar plan |
| `hub.digest.run` | Operador | Pedir resumen al secretario |

El rol **Agente** (solo lectura) ve el Hub pero no participa: para que Codex o Claude trabajen, su
token necesita `hub.sessions.participate` (rol Agente ingeniero u Operador).

## ChatGPT con MCP

ChatGPT (modo desarrollador con conectores MCP) puede conectarse al MCP de Kaanbal y usar
`hub_briefing`, `hub_create_task` con `proposed=true` y `hub_write_note`. `hub_write_note` acepta
base64 (hasta 2 MB) en `live/`; los ZIP con imágenes los sube una persona desde la consola.

## Pendiente

- Hook opcional para Claude Code/Codex que haga `hub_sync` solo (SessionStart/Stop) sin depender del agente.
- Notificaciones (correo/chat) cuando un mensaje va a `people` o una tarea pasa a review.
