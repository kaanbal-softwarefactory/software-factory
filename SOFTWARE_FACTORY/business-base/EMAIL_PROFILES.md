# Correo por cliente: propuesta de siguiente iteración

Estado: diseño, no funcionalidad implementada ni pantalla existente en Kaanbal.

## Estado actual

El stack candidato usa Mailpit privado para capturar tanto correos de Keycloak
(recuperación y verificación) como los del worker de negocio. No entrega correo
externo. Agregar un cliente en Software Factory no configura un remitente.
La configuración SMTP del worker y la de Keycloak son distintas: una variable
en la web no cambia ninguna de ellas. El renderer gestionado todavía fija el
modo captura. No usar variables genéricas para introducir credenciales SMTP:
esa ruta histórica puede escribir valores literales en GitOps.

### Captura privada de SendGrid (sin activación automática)

Para `business-base`, `request_secret`/la pantalla de solicitudes admite
`SENDGRID_API_KEY` mediante una ruta gestionada: Vault separado del sistema,
Secret runtime inmutable y descriptor `provider-credential.json` en el overlay.
El descriptor solo contiene proveedor, nombre/clave del Secret y estado de entrega
deshabilitada. Nunca contiene el valor. Reemplazar requiere `overwrite` explícito.
Los componentes gestionados rechazan otras variables genéricas para proteger sus
credenciales originales. No cambia el comportamiento de otras plantillas.

Guardar la clave no activa correo externo ni inyecta credenciales en la web.
La instalación debe conectar explícitamente el Secret referenciado al bootstrap
de identidad y al worker, junto con remitente autenticado y SMTP/TLS. El perfil
de correo completo y su pantalla siguen pendientes. Si falla Vault o la
materialización, no hay fallback a literales de Git. Una rotación crea otro Secret;
no elimina credenciales ni referencias anteriores durante la captura.

## Estrategia

Usar un proveedor transaccional mediante SMTP con TLS. Resend es una primera
opción compatible con ambos consumidores: exige un dominio verificado y una
clave; admite credenciales con permisos de envío y restricción de dominio.
La elección final depende del proveedor/cuenta que decida operar el equipo.
No instalar un servidor SMTP saliente por cada stack en esta etapa.

Referencias oficiales:
- [SMTP de Resend](https://resend.com/docs/send-with-smtp)
- [Permisos y dominios de claves](https://resend.com/docs/dashboard/api-keys/introduction)
- [Verificar dominios](https://resend.com/docs/dashboard/domains/introduction)

## Modelo propuesto

Un perfil por cliente y ambiente, enlazado explícitamente al grupo, contiene:
proveedor, dominio verificado, remitente permitido, reply-to, host/puerto/TLS,
cuota, modo captura/real, estado de verificación y referencia de secreto en Vault.
Las credenciales se ingresan privadamente y no aparecen en el contrato MCP, Git,
logs ni chat. Usar claves de envío por cliente/dominio; nunca distribuir una
clave maestra entre todas las apps. Las claves separadas no garantizan por sí
solas aislamiento de reputación o cuotas de la cuenta del proveedor.

Primera versión: cada copia sirve a un cliente y tiene un perfil de correo.
Si una sola copia sirve a varias organizaciones, el SMTP global actual no elige
remitentes por organización. Eso exige resolución de perfil en el worker y un
diseño separado de identidad; no está soportado hoy.

## Configuración y aceptación propuestas

1. En el proveedor, verificar un dominio o subdominio del cliente, por ejemplo
   `avisos.example.com`, y publicar los registros de autenticación DNS indicados.
2. En una futura sección **Correo / Perfiles por cliente**, registrar el perfil
   y la credencial mediante captura privada hacia Vault.
3. Al preparar el stack, seleccionar el perfil autorizado para ese cliente.
   El plan muestra remitente, consumidores y modo, sin valores secretos.
4. Renderizar referencias GitOps del worker y configurar el realm Keycloak
   con SMTP/TLS autenticado. Respetar credenciales independientes y evitar
   sobreescribir configuraciones ajenas en un bootstrap repetido.
5. Tras autorización del destinatario de prueba, comprobar recuperación de
   contraseña y una notificación del worker, reintentos sin duplicados, TLS y
   separación entre clientes. Nunca registrar enlaces o tokens de recuperación.
6. Integrar eventos verificados del proveedor para rebotes, quejas y supresión;
   agregar límites, alertas y rotación antes de ampliar clientes reales.

La consola y el MCP deben consumir la misma configuración gestionada; al pedir
un stack, el agente elige un perfil existente, sin solicitar contraseñas en chat.
Mantener captura local para desarrollo y pruebas. Los buzones humanos como
`equipo@example.com` son un servicio distinto (correo de oficina); esta propuesta
cubre envíos automáticos de las aplicaciones.
