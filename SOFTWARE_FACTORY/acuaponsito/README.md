# 🌱 Acuaponsito Agent Runtime

> El "Cursor de los científicos" — un agente de IA con personaje vivo que se
> embebe en CUALQUIER app con un solo `<script>`, vive en SU propia capa
> (jamás toca el flujo del usuario), y tiene el poder del sistema donde corre
> — con aprobación humana para cada acción.
>
> Separado por diseño: este motor no sabe nada de Kaanbal. Kaanbal lo usa;
> tu otra app también puede.

## Correr

```bash
# proceso directo (cero dependencias, solo Python 3.10+)
python3 server.py
# imprime: Panel, Demo y el snippet de embebido con tu token

# como servicio systemd
# [Service] ExecStart=/usr/bin/python3 /opt/acuaponsito/server.py
#           Environment=ACUA_TOKEN=tu-token  KAANBAL_ANIM_DIR=/opt/animacion

# como contenedor
docker build -t acuaponsito .
docker run -p 4600:4600 -v $PWD/../../animacion:/anim -v acua-data:/data \
  -e ACUA_TOKEN=tu-token acuaponsito
```

## Embeber en tu app (la parte mágica)

```html
<script src="http://TU-HOST:4600/embed.js" data-token="TU-TOKEN"></script>
```

Eso es TODO. Aparece el botón flotante con el personaje en video (estado real).
Clic → panel medio → expandir a pantalla completa **encima** de tu UI.
Shadow DOM + iframe: ni tu CSS ni tu JS se enteran. Cerrar el panel devuelve
al usuario exactamente donde estaba — continuidad total.

Prueba la historia completa con la app demo: `http://HOST:4600/demo?token=…`

## La historia del primer uso

1. **Crea al guardián** — primer usuario admin (login interno privado: vive en
   tu VPS/PC, nunca en la nube de nadie).
2. **Despiértalo** — conecta el proveedor de IA (DeepSeek/Claude/OpenAI).
   La clave queda en `~/.acuaponsito/agent.config.json` (chmod 600).
3. El agente saluda por WebSocket y ya: chat privado, chat de equipo,
   acciones, automatización.

## Arquitectura

```
┌─ App anfitriona (cualquiera) ──────────────────────────┐
│  <script embed.js>  ← Shadow DOM, capa fija, cero roce │
│     └── iframe /panel  ←→  WebSocket                   │
└────────────────────────────┬───────────────────────────┘
                             │ HTTP + WS (token + sesión)
┌─ Agent Runtime (este repo) ▼ ──────────────────────────┐
│ server.py (stdlib puro)                                │
│  • Login interno: admin / member / observer            │
│  • WS hub: presencia, chat, estado del bot sincronizado│
│  • Canales: dm:<usuario> (privado) + team (equipo)     │
│  • LLM: contrato {say, state, clip, action}            │
│  • Acciones bash → COLA DE APROBACIÓN (admin aprueba)  │
│  • Vida propia: idle → descanso → propuestas (tips)    │
│  • Schedules (cron-lite) + Webhooks POST /hook/<id>    │
│  • Memoria JSONL + chats persistentes (~/.acuaponsito) │
│  • Catálogo de clips del Acuaponsito Framework         │
└────────────────────────────────────────────────────────┘
```

## Seguridad (modelo de 3 capas)

1. **Token de runtime** (`ACUA_TOKEN`): nadie sin él llega a la API.
2. **Identidad por persona**: sesiones con usuario/contraseña propios; roles
   `admin` (aprueba acciones, configura), `member` (usa), `observer` (mira).
   El canal privado de cada quien es suyo (el admin puede auditar).
3. **Acciones con aprobación humana**: el LLM solo PROPONE comandos
   (`action.tool=bash`); quedan en cola visible y un admin decide. Salida
   truncada, timeout 90s. `auto_approve` existe pero es opt-in explícito.

## Identidad y comportamiento

Todo en Ajustes (o `agent.config.json`): nombre, personalidad, meta,
responde-en-equipo (solo mención / siempre), minutos de idle antes de
descansar, modo descanso (no propone), auto-aprobación.

Multiusuario real: en el canal **Equipo** las personas se ven entre sí y el
agente participa cuando lo mencionan (`@nombre`) — un chat de navegador con
el poder de un agente de sistema.

## Roadmap

- [ ] Herramientas MCP estándar (el esquema `action.tool` ya lo contempla)
- [ ] Marketplace de skills/características
- [ ] TTS sincronizado con clips `speak`
- [ ] Grafo de conocimiento sobre la memoria JSONL
- [ ] Flujos científicos empaquetados (validación DOI, bitácora de experimentos)
