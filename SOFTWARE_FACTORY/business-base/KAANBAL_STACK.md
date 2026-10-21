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
   Servicios/Barbería y opcionalmente nombre comercial/homepage.
3. Confirmar el plan. Se prepara base → identidad → app y se espera readiness
   real, incluyendo inicialización, worker y build inicial.
4. En **Sistemas**, asignar responsable. Es organización del trabajo; no cambia
   permisos de Kaanbal ni cuentas del negocio.

Por MCP: `launch_stack(stack="business-base-demo", base_name="business-demo",
business_name="Estudio Demo", business_preset="services")`. Primero devuelve
plan, URLs y SHA de origen; se aplica con el `plan_id` aprobado y se sigue con
`stack_status`. Un cliente con esquema antiguo puede usar `invoke_platform_tool`
para los argumentos añadidos después de conectarse.

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
