# Business Base como stack de Kaanbal

Estado: candidato beta `business-base-demo`. La integración GitOps y la
aceptación de la célula real son verificaciones distintas. Compilar no declara
este candidato como plantilla empresarial ready.

## Qué se lanza

Un lanzamiento crea un grupo con responsable inicial igual a quien lo lanza y
tres aplicaciones administrables:

| App | Función | Exposición |
|---|---|---|
| `<nombre>-db` | PostgreSQL persistente, roles runtime/migración/identidad separados | Interna |
| `<nombre>-identity` | Keycloak producción, OIDC/PKCE y MFA | HTTPS para realms y login; admin interno |
| `<nombre>` | Landing, portal, inbox, reservas, equipo y auditoría | HTTPS |

El repositorio de la app opera también worker y Mailpit interno. El correo se
captura: no hay envío externo ni buzón público. Cada sistema recibe su propia
base, identidad, credenciales, catálogo y repositorio. Solo permite `prod` en
este candidato; para otra prueba se crea otro nombre.

El stack es una receta de creación; el grupo/Sistema organiza lo creado.
La app individual sigue disponible para Vue, React, FastAPI, Next.js y otras
plantillas. Los componentes especiales de Business Base se ofrecen desde
Stacks porque necesitan su contrato completo; no reemplazan esas plantillas.

## Lanzar una demo

1. Integrar el PR y actualizar Kaanbal: API, consola, catálogo y Role de secretos.
2. En **Stacks → Business Base · Demo**, elegir nombre, dominio, preset
   Starter/Servicios/Barbería y opcionalmente nombre comercial/homepage.
3. Confirmar el plan. Se prepara base → identidad → app y se espera readiness
   real, incluyendo inicialización, worker y build inicial.
4. En **Sistemas**, comprobar responsable: un grupo nuevo toma el usuario autenticado
   que lo lanzó (también por token MCP); uno existente conserva su responsable.
   Es organización del trabajo; no cambia
   permisos de Kaanbal ni cuentas del negocio.

Por MCP: `launch_stack(stack="business-base-demo", base_name="business-demo",
business_name="Estudio Demo", business_preset="services")`. Primero devuelve
plan, URLs y SHA de origen; se aplica con el `plan_id` aprobado y se sigue con
`stack_status`. Un cliente con esquema antiguo puede usar `invoke_platform_tool`
para los argumentos añadidos después de conectarse.

`business_preset="starter"` ofrece landing `/`, administración `/admin` y clientes
`/client`, sin catálogo ni agenda de ejemplo. Las rutas usan el mismo origen de
la app, con o sin homepage. El plan muestra sus URLs. El repo conserva la elección
para el desarrollo local. Recorrido de personalización: [STARTER.md](STARTER.md).

## Trabajo de otra persona mediante MCP

Cada persona conecta su propio token y comprueba `whoami` y
`platform_capabilities`. Compartir el token de otra persona atribuye el lanzamiento
a esa otra cuenta. El nombre del token no es la identidad del responsable.
El plan muestra `group_owner`; cambiar el responsable después de preparar el plan
invalida ese plan. La asignación no concede acceso al repositorio ni crea una
cuenta administradora en Keycloak.

Un pedido posible es: «Prepara Business Base para Taller Ejemplo, preset Servicios,
nombre taller-ejemplo. Muéstrame el grupo, responsable y URLs antes de lanzarlo».
El agente consulta `platform_guide`, prepara `launch_stack` y aplica el plan
aprobado. Si vence la conexión, consulta los lanzamientos existentes antes de repetir.

Después usa `app_contract` sobre la app. El contrato declara conexiones, variables
por proceso, probes y reglas de seguridad; no afirma haber inspeccionado valores
del runtime. No se deben reemplazar esas conexiones con `link_apps`, reparaciones
genéricas de bindings o variables manuales.

El desarrollador clona **el repositorio generado de su app**, instala Node.js 24 y
Docker con Compose, ejecuta `npm ci` y `npm run local:up -- --name taller-local`.
La receta crea base, identidad y correo locales. Otras copias necesitan nombres y
puertos diferentes desde su primer arranque. `local:access` se consulta solamente
en su terminal. Modifica pantallas en `app/` y `components/`, reglas en `lib/` y
agrega migraciones en `migrations/`. Comprueba `npm test` y `npm run build`,
reconstruye con los mismos argumentos de `local:up` y publica una rama/PR.
El CI de `main` actualiza únicamente esa copia. Acceso a GitHub y roles del negocio
se conceden aparte del owner del grupo.

El diseño de entrega real de correo está en [EMAIL_PROFILES.md](EMAIL_PROFILES.md).

Las cuentas ficticias iniciales son `owner` y `customer`. Las contraseñas
aleatorias se consultan privadamente en Vault: `secret/prod/<nombre>`, claves
`OWNER_PASSWORD` y `CUSTOMER_PASSWORD`. Nunca se envían al agente o al chat.
El owner configura su autenticador y verifica MFA; customer no administra.

## Qué se automatiza

- Nombres, grupo, URLs y vínculos antes de crear recursos.
- Copia byte a byte del SHA completo instalado del monorepo oficial, sin
  interpolar TypeScript o correos de fixtures. Guarda `source_sha` en la copia.
- PostgreSQL con roles separados. Runtime no es superusuario, propietario de
  tablas ni BYPASSRLS.
- Credenciales creadas con CAS en Vault: reintentar no rota ni pisa valores.
  La API materializa Secrets runtime inmutables. GitOps solo lleva referencias,
  nunca valores, literals o secretGenerator.
- Init container para migraciones, IdP y fixtures explícitas de demo. Repetir
  conserva contraseñas, MFA, sujetos y datos.
- Web y worker solo reciben sus claves; no montan ServiceAccount tokens.
- GitOps, NetworkPolicies, probes, repositorio y CI. La imagen publicada se
  actualiza en app, init container y worker conjuntamente.

Vault debe estar configurado y abierto. El Role nuevo autoriza get/create de
Secrets en `prod`, sin borrado. El namespace existe como parte de la plataforma.
Se requieren GitHub, registro y permisos normales del lanzador de Kaanbal.

## Validación y ciclo de vida

La aceptación en la célula debe comprobar HTTPS, login/MFA, cliente, inbox,
reservas concurrentes, correo capturado, reinicio y segunda copia independiente.
Las pruebas locales del prototipo siguen disponibles. Para probar bootstrap
con PostgreSQL y Keycloak reales en modo producción, sin puertos externos:

```sh
docker compose -p business-managed-acceptance -f compose.acceptance.yaml up -d --build acceptance
docker compose -p business-managed-acceptance -f compose.acceptance.yaml logs acceptance
docker compose -p business-managed-acceptance -f compose.acceptance.yaml stop
```

La prueba repite bootstrap y comprueba sujetos estables, una organización,
dos personas y RLS. Captura salidas de procesos; solo publica resultados.

Si falla una pieza, se conservan datos y recursos. Todavía no hay botón para
reanudar todo el stack tras reiniciar la API; se diagnostica la pieza antes de
reintentar o cambiar de nombre. Tampoco hay pausa conjunta: detener la app no
detiene worker, base o identidad. Sus Deployments asociados se operan por separado.
La eliminación necesita aprobación por app; el PVC usa `Prune=false,Delete=false`.

Las copias conservan código y datos; actualizar Kaanbal no regenera ni pisa
personalizaciones. Paquetes compartidos versionados y actualización automática
de copias son una etapa posterior.

Para producción faltan SMTP real/TLS, alta inicial de personas reales, rotación
y recuperación de secretos, backups/restauración, carga y revisión de seguridad.
Migrar apps existentes requiere ensayar importación y rollback en staging.
