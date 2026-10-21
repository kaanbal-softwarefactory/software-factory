# Starter: sitio, equipo y clientes

Una aplicación Next.js con tres áreas, una base PostgreSQL y una instancia de
identidad Keycloak. No necesitas crear ni conectar tres repositorios de frontend.
Este preset sigue siendo candidato de prueba; el correo se captura, no se entrega
externamente. No incluye datos ni credenciales de clientes reales.

| Ruta | Para quién | Incluye |
| --- | --- | --- |
| `/` | Público | Marca, presentación, cómo funciona, contacto y acceso |
| `/admin` | Owner, admin y colaboradores | Resumen, inbox y seguimiento; equipo, auditoría y ajustes según permisos |
| `/client` | Membresías cliente | Resumen personal, solicitudes y notificaciones; alta de solicitud en la organización pública |
| `/workspace` | Cuenta autenticada | Entrada automática al panel permitido por sus membresías |

Administradores requieren MFA verificado para consultar/modificar datos. El servidor
filtra membresías para cada panel y las APIs vuelven a validar rol, organización y
propiedad. Una cuenta cliente no entra al panel administrativo cambiando la URL.
Una cuenta del equipo necesita una membresía cliente para usar el portal de clientes.

## Lanzarlo desde Kaanbal

Para habilitar esta opción en una célula que aún no la incluye: publica e integra
el cambio del core, actualiza Kaanbal y vuelve a cargar el catálogo/MCP. Después
lanza una copia nueva. Actualizar el core no cambia automáticamente el código ni
el preset de las apps que ya existen.

En **Stacks → Business Base · Demo**, selecciona **Starter · Landing + Admin + Clientes**.
Elige nombre del sistema y nombre comercial. Selecciona un dominio registrado:

- Con homepage: `https://example.com/`, `/admin` y `/client`.
- Sin homepage: `https://mi-sistema.example.com/`, `/admin` y `/client`.

La identidad conserva su propio subdominio y el callback usa el origen real de la
app. No se admiten instalaciones bajo un prefijo como `/mi-app` en este candidato.
Si la raíz está ocupada, el plan se rechaza; no reemplaza otro sitio automáticamente.

Pedido para un agente conectado con tu propio token MCP:

> Prepara business-base-demo llamado mi-sistema con business_preset starter y
> business_name Estudio Ejemplo. Quiero subdominio, no homepage. Verifica mi identidad
> y capacidades; muéstrame responsable, grupo y URLs antes de aplicar el plan.
> Después espera stack_status y dame el repositorio y app_contract sin secretos.

El grupo nuevo queda a nombre del usuario autenticado. El acceso a GitHub y las
cuentas de negocio se conceden aparte; no comparten las credenciales de Kaanbal.

## Desarrollar una copia

Clona el repositorio generado de tu app. Con Node.js 24 y Docker con Compose:

```sh
npm ci
npm run local:up
```

El repo generado contiene `business.config.json` con nombre local, marca y preset
del lanzamiento. Los puertos por defecto son app 3100, identidad 8180 y correo 8125.
Si tienes otra copia corriendo, elige puertos distintos desde el primer arranque:

```sh
npm run local:up -- --name business-starter-local --port 3300 --identity-port 8380 --mail-port 8325
```

Para probar desde este monorepo sin una copia generada, agrega `--preset starter`
y opcionalmente `--title "Estudio Ejemplo"` al comando. Conserva los mismos argumentos
al reconstruir. En tu terminal privada, `npm run local:access -- --name business-starter-local`
muestra las cuentas ficticias de ese proyecto. No las pegues en chats. El owner
configura el autenticador; customer sirve para probar el portal.

| Qué quieres cambiar | Dónde |
| --- | --- |
| Composición y textos públicos | `components/StarterLanding.tsx` |
| Colores, tipografía, responsive | `app/globals.css` |
| Paneles y navegación | `components/Workspace.tsx` |
| Reglas de negocio | `lib/business.ts` |
| Autorización | `lib/policy.ts`, `lib/session.ts`, `lib/dashboard.ts` |
| Esquema de datos | Una migración nueva en `migrations/` |

Nombre y presentación del sitio se editan en **Mi negocio** con permisos. Cambiar
`business.config.json` no reescribe una organización ya inicializada. El preset
se elige al crearla; repetir bootstrap conserva datos y experiencia existente.
Starter no siembra catálogo ni profesionales, y oculta su navegación. Los módulos
de servicios siguen disponibles en el código para futuras extensiones; no es una
restricción adicional de seguridad ni un botón para borrar módulos/datos.

Antes del PR: `npm test` y `npm run build`. Integrar `main` ejecuta el CI de esa
app y actualiza su despliegue. No actualiza otras copias ni el código base.

## Aceptación local

Con la instancia anterior corriendo:

```sh
npm run test:browser -- --project business-starter-local --origin http://localhost:3300 --identity http://localhost:8380 --starter
```

La prueba usa cuentas ficticias y una cuenta MFA creada para aceptación; no
configura el autenticador del owner. Valida entrada por rol, denegación de admin
al cliente, solicitud → inbox, asignación, responsive y logout. Nunca captura
contraseñas ni pantallas de configuración MFA. Las capturas de las áreas de la app
se guardan en `coverage/browser/`.

Para detener: `npm run local:stop -- --name business-starter-local`. Conserva los
volúmenes. Antes de clientes reales faltan las aceptaciones de producción descritas
en [KAANBAL_STACK.md](KAANBAL_STACK.md), incluido [correo real](EMAIL_PROFILES.md).
