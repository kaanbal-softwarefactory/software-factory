# Sesión: 2026-10-20 — Business Base y organización por sistemas

## Objetivo

Construir una base funcional de negocio que pueda probarse como aplicación viva,
generar copias independientes y promoverse después a plantilla estable. Organizar
los grupos actuales por responsable sin cambiar su visibilidad.

## Implementación

- `SOFTWARE_FACTORY/business-base`: prototipo Next.js con PostgreSQL, migraciones
  SQL, identidad OIDC y un perfil local Keycloak/Compose con secretos generados en
  volúmenes separados. Login por biblioteca openid-client; el backend exige evidencia
  MFA a propietarios/administradores y membresía activa por operación.
- Landing y datos del negocio, catálogo, contacto/inbox, portal del cliente, citas
  por recurso con exclusión SQL, invitaciones, suspensión, auditoría y outbox SMTP.
- Scripts de instancias locales con nombres/puertos independientes y generador de
  copia fuente que no incluye datos, secretos, dependencias o builds.
- Sistemas: vista de consola sobre app_group, metadatos en app_groups, responsable
  validado contra cuentas activas, etapa y descripción. ACL explícita por endpoint.
  El ownership es organizativo y los stacks nuevos preservan el owner existente.
- Workflow de aceptación con pruebas unitarias, integración PostgreSQL y navegador.

## Hallazgos

- La plantilla Next.js de notas existente admite memoria y DDL en consultas; se
  conserva su contrato y la base nueva usa persistencia obligatoria y migraciones.
- Keycloak necesita referencias explícitas en los autenticadores de contraseña/OTP
  para que AMR demuestre MFA. Se copia y configura el flujo browser de forma idempotente.
  Configurar un autenticador por sí solo no basta para conceder administración.
- El secreto TOTP oculto de Keycloak no es la representación Base32 mostrada al usuario.
  La prueba usa la representación manual y espera una ventana nueva para no reutilizar
  el código consumido durante el alta.
- Se actualizó la dependencia SMTP tras comprobar avisos de seguridad con npm audit.

## Validación y pendientes

La evidencia consolidada se registra en la descripción de PR preparada y en el chat.
Pruebas de navegador con cuentas y datos ficticios, sin capturar pantallas de contraseña
o MFA. No se modificaron aplicaciones existentes ni datos de una célula.

Pendiente antes de plantilla ready: feedback de la persona, paquetes compartidos y
ensayo de actualización, identidad/roles de base aprovisionados por Kaanbal/Vault,
dependencias explícitas y Jobs de migración por GitOps, restauración y validación
en una célula. Las migraciones de aplicaciones existentes serán graduales, con
identidad verificada, copia de staging, respaldo y ensayo de corte/rollback.

GitHub: el conector rechazó crear el issue con HTTP 403; gh no tiene sesión activa.
La rama se prepara localmente sin modificar main. No se considera fusionado ni
desplegado hasta confirmar las operaciones correspondientes.
