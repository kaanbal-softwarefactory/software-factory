# Comms Lab — central de llamadas integrable

Comms Lab es un **producto aparte** (agentes de voz por teléfono, SMS y, después, WhatsApp y correo) que
vive en sus propios repositorios y se integra con cualquier sistema de Kaanbal por API. No es parte del
núcleo de la plataforma: Kaanbal lo hospeda y lo opera como a cualquier otro stack, y los negocios
(una polarizadora, una barbería, una tienda) le dan sus datos por contrato.

## Por qué no está dentro del núcleo

- El núcleo exige permiso por endpoint, instalador solo con biblioteca estándar y migraciones
  expand/contract. La telefonía trae WebSockets, webhooks y proveedores externos que cambian a su ritmo.
- Si falla, no debe tumbar la consola ni el MCP.
- Una plantilla de Kaanbal es un andamio con el código dentro de este repositorio: copiar Comms Lab aquí
  crearía dos copias que se desfasan. Por eso **no hay una plantilla ni un stack "Comms Lab" en el catálogo**:
  lanzaría apps en blanco.
- Al hablar por API, la central puede moverse a su propio servidor sin tocar a los negocios que la usan.

## Cómo se despliega

Tres apps de un mismo grupo, con la forma del stack `vue-fastapi-postgres`:

| App | Plantilla | Exposición | Repositorio |
|---|---|---|---|
| `comms-lab-db` | `postgres` | interna | — |
| `comms-lab-api` | `fastapi-api` | pública (Twilio necesita alcanzarla) | `comms-lab-api` |
| `comms-lab` | `vue3-spa` | pública | `comms-lab` |

El código llega por `git push` a `main` de cada repositorio: el pipeline construye y ArgoCD despliega. La API
migra su base sola al arrancar (migraciones aditivas, versionadas); el Dockerfile y el puerto 8000 con `/health`
siguen el contrato de `fastapi-api`.

## Variables de la API

Todas llegan por variables de entorno; **nunca van en el repositorio**. Se crean con el MCP, sin ver valores:
`set_app_variable` (con `generate=true` para las internas) y `request_secret` para lo que solo tiene una persona.

| Variable | Qué es | Cómo se crea |
|---|---|---|
| `APP_SECRET`, `DATABASE_URL` | la plataforma las genera al vincular la base | automática |
| `ADMIN_EMAIL` | correo del administrador inicial | `set_app_variable` |
| `ADMIN_PASSWORD` | contraseña temporal del administrador | `set_app_variable` con `generate=true` |
| `ADMIN_CAMBIO_OBLIGATORIO` | `true`: en el primer ingreso solo puede cambiar la contraseña | `set_app_variable` |
| `PUBLIC_BASE_URL` | URL pública de la API (la que Twilio llama) | `set_app_variable` |
| `CORS_ORIGINS` | URL del frontend | `set_app_variable` |
| `IDENTIDAD_SMS_MODO` | `demo` (códigos en pantalla) o `twilio` (SMS reales) | `set_app_variable` |
| `TWILIO_PERMITIR_COMPRAS` | `false`: no comprar números sin querer | `set_app_variable` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | cuenta y número de Twilio | `request_secret` |
| `DEEPSEEK_API_KEY` | modelo de conversación, supervisor y resúmenes | `request_secret` |
| `FLUJO_*` | URLs y claves de las APIs del negocio (agenda, directorio…) | según el negocio |

Para mantener limpio Vault: `delete_app_variable` quita una variable que ya no se usa y `cleanup_orphan_secrets`
borra los secretos de apps que ya no existen. Las dos muestran su plan primero y exigen token crítico y aprobación
humana, porque el valor no se recupera.

## Cómo se integra un negocio

El negocio no instala nada dentro de Comms Lab: expone rutas y Comms Lab las llama. Lo que cambia de un negocio
a otro es solo la URL en la configuración del flujo (módulos HTTP y adaptador de identidad).

**Directorio de clientes** (adaptador `directorio`) — cuatro rutas:

- `GET /clientes?telefono=+52…` o `?q=<nombre>` → `{items: [{id, nombre, roles, telefonos: [{numero, principal}]}]}`
- `POST /clientes` `{nombre, telefono}` — alta, solo después de validar el código.
- `POST /clientes/{id}/telefonos` `{numero}` — vincular un número validado.
- `GET /roles` — catálogo de roles (opcional).

Si el directorio no responde, Comms Lab usa su última copia y nunca inventa una ficha. El código de
verificación lo genera y valida Comms Lab; el directorio nunca lo ve. Si el sistema del negocio prefiere
generar y validar el código él mismo, existe el adaptador HTTP completo (siete operaciones, descritas en la
documentación de `comms-lab-api`).

**Herramientas del negocio** (agenda, cotizaciones, pedidos): módulos HTTP del flujo con sus datos y plantillas.

## Seguridad que no se configura por negocio

- Cada herramienta declara quién puede usarla: cualquiera, el número de un cliente reconocido o un cliente
  validado con código. Solo el servidor sube ese nivel; el modelo nunca puede marcar a alguien como validado.
- Los SMS salen únicamente al teléfono de la llamada y con un tope por llamada.
- Los códigos se ocultan en transcripciones, eventos e historial.
- La contraseña temporal del administrador debe cambiarse en el primer ingreso; mientras tanto el servidor
  bloquea el resto de la API.

## Probar

1. Entra a la URL del frontend con `ADMIN_EMAIL` y la contraseña de `ADMIN_PASSWORD` (se lee en Vault).
2. Cambia la contraseña cuando lo pida.
3. Crea un proyecto y un flujo, y conecta un número de Twilio desde **Números**: la API configura sola los
   webhooks de voz a partir de `PUBLIC_BASE_URL`.
4. Llama y sigue la conversación en el monitor en vivo (actividad y contexto).
