# 🌱 Acuaponsito Framework — Sistema de video interactivo dirigido por LLM

> Un personaje hecho de **clips de 10 segundos** que un modelo de IA controla en
> tiempo real: el LLM responde texto **+ metadata de comportamiento**, y el
> reproductor encadena los clips con crossfade para que nunca se noten los cortes.
>
> Este framework es independiente de Kaanbal: sirve para cualquier proyecto
> donde quieras un asistente visual vivo (kioscos, apps, dashboards, juegos).

---

## 1. La idea en 30 segundos

```
   evento / mensaje del usuario
              │
              ▼
   LLM  ←  catálogo compacto (id + descripción de cada clip)
              │
              ▼  responde SOLO JSON
   { "say": "¡Hola! Ya desperté…", "state": "greet", "clip": "greet__saludo" }
              │
              ▼
   Reproductor: crossfade al clip → burbuja typewriter con el texto
```

El LLM **no genera video**: elige del repertorio. Tú generas 3 clips al día,
el repertorio crece, y el personaje se vuelve más expresivo sin tocar código.

---

## 2. Los archivos

```
animacion/
├── catalog.json              ← LA fuente de verdad (clips + estados + reglas)
├── ACUAPONSITO_FRAMEWORK.md  ← este documento
└── *.mp4                     ← los clips (10s, misma escena, mismo encuadre)
```

El reproductor (instalador Kaanbal u otra app) consume `catalog.json` vía HTTP.
Agregar un clip = **copiar el .mp4 aquí + añadir una entrada al JSON**. Nada más.

---

## 3. El árbol de estados

Todo clip pertenece a UN estado. Los estados forman un árbol de *fallbacks*:
si un estado no tiene clips todavía, el reproductor sube por la cadena hasta
encontrar uno (así el sistema **nunca se rompe** aunque falten videos).

```
sleep ──(despiertan)──▶ wake ──▶ greet ──▶ idle ◀─────────────┐
                                            │                  │
                          ┌─────────────────┼──────────────┐   │
                          ▼                 ▼              ▼   │
                       listen ──▶ think ──▶ speak ─────────────┘
                                    │
                          ┌─────────┼─────────┐
                          ▼         ▼         ▼
                      celebrate   warn ──▶ error
                          │
                          ▼
                        rest ──▶ sleep  (el ciclo se cierra)
```

| Estado | Cuándo | Fallback si no hay clip |
|---|---|---|
| `sleep` | sistema sin configurar / inactividad larga | `idle` |
| `wake` | acaba de ser activado (ej. API key válida) — observa, no habla | `greet` |
| `greet` | bienvenida, hola, reencuentro | `idle` |
| `idle` | neutral por defecto, entre interacciones | `greet` |
| `listen` | el usuario escribe/dicta | `idle` |
| `think` | procesando, cargando, analizando | `listen` |
| `speak` | el LLM está "diciendo" su respuesta | `idle` |
| `work` | ejecutando una tarea visible (instalar, desplegar) | `think` |
| `celebrate` | éxito, festejo | `greet` |
| `warn` | precaución, validación fallida recuperable | `think` |
| `error` | algo salió mal de verdad | `warn` |
| `rest` | despedida, bajar energía | `sleep` |

**Variedad**: un estado puede tener N clips (`listen__atento-serio`,
`listen__curioso`, `listen__tomando-notas`…). El reproductor elige al azar
entre ellos — más clips = menos repetitivo, cero cambios de código.

---

## 4. `catalog.json` — anatomía de una entrada

```jsonc
{
  "id": "listen__atento-serio",        // único: estado__variante-detalle
  "file": "escuchando-al-final-serio.mp4",
  "state": "listen",                   // uno del árbol de arriba
  "title": "Escucha atenta que termina seria",
  "description": "Cuándo usarlo: el usuario escribe algo importante...",
  "energy": "media",                   // baja | media | alta (matiz para el LLM)
  "loop": true,                        // ¿se puede repetir mientras dura el estado?
  "tags": ["escucha", "transicion-a-think"],
  "added": "2026-07-03"
}
```

La `description` es **para el LLM**: escribe ahí cuándo usarlo, qué transmite,
y con qué estado conecta bien al final. Un modelo pequeño (Haiku) elige bien
si la descripción es clara.

`wishlist` (al final del catálogo): estados que aún no tienen clip, con el
`prompt_hint` listo para generarlos — tu lista de pendientes de cada día.

---

## 5. ✍️ Agregar un video — versión humana simple (3 pasos)

1. **Copia** tu `mi-clip.mp4` a esta carpeta. Nombre sugerido:
   `estado__variante.mp4` (kebab-case, sin espacios — el sistema tolera
   espacios, pero no te acostumbres 😄).
2. **Abre `catalog.json`** y duplica una entrada de `clips`. Cambia `id`,
   `file`, `state`, `title` y sobre todo la `description` (di CUÁNDO usarlo).
3. **Guarda.** Refresca la app. Ya está en el repertorio y el LLM ya puede
   elegirlo. No hay paso 4.

> Si el estado es nuevo, agrégalo también a `states` con su `fallback`.

---

## 6. 🤖 El contrato con el LLM

### System prompt (plantilla)

```
Eres Acuaponsito, asistente robótico tierno de una plataforma open source.
Respondes SIEMPRE un único JSON válido, sin markdown, con esta forma:
{"say": "<texto breve y cálido en español>", "state": "<estado>", "clip": "<id opcional>"}

Estados disponibles: sleep, wake, greet, idle, listen, think, speak, work,
celebrate, warn, error, rest.

Repertorio actual (elige "clip" solo de esta lista, o omítelo y el sistema
elegirá uno del estado):
- sleep__siesta: Dormido con Zzz, recargando. Estado inicial.
- greet__saludo: Levanta la mano y saluda cálido. Bienvenidas.
- listen__atento-serio: Escucha con mano al oído; termina serio. Conecta con think.
- think__esfuerzo: Procesa con concentración y esfuerzo. Operaciones largas.

El repertorio CRECE con el tiempo: si recibes un catálogo más largo en el
futuro, úsalo igual. Si dudas del clip, indica solo "state".
```

### Reglas de resolución (las implementa el reproductor, no el LLM)

1. ¿`clip` existe en el catálogo? → úsalo.
2. Si no: ¿el `state` tiene clips? → elige uno al azar.
3. Si no: sube por la cadena de `fallback` del estado hasta encontrar clips.
4. Último recurso: primer clip del catálogo. **Nunca pantalla negra.**

### Por qué funciona con modelos pequeños

- Una sola decisión (estado) + una opcional (clip).
- Descripciones en lenguaje natural, sin jerga.
- El JSON es plano, sin anidación.
- Equivocarse es barato: los fallbacks siempre resuelven.

---

## 7. 🎬 Guía de generación de clips (continuidad)

Aprendido en producción con Gemini/Veo (¡y funciona!):

- **Escena ADN** (inclúyela en cada prompt): *"Robot blanco redondo con brote
  de hoja verde en la cabeza, cara oscura con ojos cian, hexágono con hoja en
  el pecho. Fondo degradado azul profundo, cámara frontal fija, iluminación
  suave cian. Estilo 3D tierno."*
- **10 segundos**, cámara fija, mismo encuadre y escala siempre.
- **El último segundo QUIETO** (pose estable): ahí ocurre el crossfade y por
  eso no se notan los cortes.
- Para loops (idle, sleep): primer y último frame casi idénticos.
- Boca al hablar: **luz-waveform abstracta cian, jamás lip-sync humano** — así
  el TTS de cualquier voz encaja encima.
- Adjunta un frame del clip anterior al generar el siguiente: continuidad.
- Con 3 clips/día: prioriza la `wishlist` del catálogo (wake y speak primero:
  son los que completan el ciclo conversacional).

---

## 8. El reproductor de referencia (crossfade + rotación)

Implementado en `SOFTWARE_FACTORY/installer/static/acuabot.js` (standalone,
`window.AcuaBot`) — lo usan el instalador y la Consola del Agente:

- **Dos `<video>` superpuestos**: el nuevo clip carga oculto y se desvanece el
  anterior (450ms, tenue). Con el último segundo quieto, el corte es invisible.
- **Rotación de variantes** ⭐: si un estado tiene varios clips (durmiendo,
  durmiendo-2, durmiendo-3…), el reproductor alterna entre ellos con crossfade
  *justo antes* de que el clip termine — ni el loop ni el cambio se notan, y
  el personaje se siente vivo. Un solo clip → loop invisible del mismo.
- Widget **flotante y arrastrable**, sin etiquetas de estado (el estado se
  *ve*, no se lee). `draggable(stage, onTap)` distingue arrastre de toque.
- Burbuja **typewriter** para el `say` del LLM (lista para TTS encima).
- Consume `GET /api/catalog` — servido directo desde esta carpeta: tirar un
  mp4 aquí + registrar la entrada **ya lo hace disponible** sin redeploy.
  (La Consola del Agente tiene UI para registrarlo, con descripción propuesta
  por el propio LLM.)

Para reusarlo en otro proyecto: copia `acuabot.js` + el markup del widget,
sirve esta carpeta por HTTP, y dale al LLM el system prompt de la sección 6.

## 8b. La Consola del Agente (capa operativa reutilizable)

`installer/static/console.html` — el personaje deja de ser avatar y se vuelve
**agente de plataforma**. Pestañas: Agente (chat con flujos de trabajo y roles),
Sistema (mapa real de nodos/pods), Memoria (bitácora JSONL amigable para IA),
Estudio (skills + subagentes por rol + tablero de automejora), Clips (tabla
master editable), Accesos (scopes + modos asistido/dev/staging/prod).
El backend que necesita cualquier app que quiera replicarla:
`/api/catalog`, `/api/observe`, `/api/memory`, `/api/ai/chat`, `/api/agent/config`.

---

## 9. Roadmap

- [ ] Voz: TTS sobre `say`, sincronizado con clips `speak` (boca-waveform lista).
- [ ] `duration_hint` por clip para encadenar secuencias (wake → greet → idle).
- [ ] Precarga inteligente: al entrar a un estado, pre-cargar sus vecinos del árbol.
- [ ] Multi-personaje: N carpetas, N catálogos, mismo motor.
