# Credencial de notificaciones de una aplicación Business Base

`request_secret`/captura privada admite `CONNECT_NOTIFICATIONS_TOKEN` para una
aplicación gestionada Business Base en prod. El valor debe ser una credencial
de proyecto emitida por Kaanbal Connect. La persona la captura en privado; los
agentes no leen su valor. No se usa el escritor genérico de variables.

El core conserva el valor en `secret/prod/{app}/providers/kaanbal-connect/{name}`
y un Secret runtime independiente. El descriptor GitOps `connect-credential.json`
incluye proveedor, nombre y clave del Secret, y `delivery_enabled:false` como
indicación de que **la captura sola** no activa entrega. No representa el estado
actual del SMTP ni del servicio. La referencia SendGrid existente permanece en
su archivo y ruta originales.

Para activarla, un cambio GitOps revisable añade al trabajador del negocio
`CONNECT_NOTIFICATIONS_URL=https://connect.example.com/api/v1/notificaciones`
y la variable `CONNECT_NOTIFICATIONS_TOKEN` mediante `secretKeyRef` del descriptor.
No se inyecta en el web ni en Keycloak. Las plantillas y la habilitación del
proyecto se administran en Connect. La aplicación consumidora debe implementar
este contrato; capturar una clave no modifica su código ni garantiza entrega.

La rotación exige confirmar reemplazo. La captura no revoca la clave anterior
en Connect ni elimina Secrets anteriores; primero completar solicitudes pendientes.
Los secretos de base, contraseñas de usuarios y MFA quedan fuera de este cambio.
