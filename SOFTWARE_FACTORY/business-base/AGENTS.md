# Business Base — contrato del prototipo

Lee README.md y business.manifest.json antes de cambiar el sistema. Esta aplicación
es una base de referencia en evaluación: todavía no es una plantilla ready.
Para la experiencia landing/admin/clientes, lee STARTER.md. El preset starter se
selecciona al crear la organización; no reescribas su preset ni borres datos en bootstrap.
La copia generada conserva business.config.json y .gitignore para desarrollo local.

- Identidad: OIDC con openid-client. No implementes otro almacén de contraseñas.
- Autorización: lib/policy.ts y lib/session.ts. Una organización viene de una
  membresía validada; nunca de un header confiado ciegamente.
- Los administradores necesitan evidencia MFA en su sesión. No confíes en un
  campo enviado por el navegador o en un rol contenido en el correo.
- Negocio: lib/business.ts. Mantén los servicios independientes de las páginas.
- Persistencia obligatoria. No agregues fallback a memoria.
- Usa inOrganization para transacciones de negocio; el contexto se limita a
  cada transacción. Nunca uses credenciales de migración en el proceso web.
- Migraciones SQL versionadas: no edites una migración publicada ni ejecutes
  DDL desde consultas HTTP. Expand/contract y rollback de imagen compatible.
- Citas: recurso de capacidad uno, lunes-viernes 09–18 en la zona del negocio.
  Reserva bajo bloqueo del recurso y conserva la exclusión SQL contra solapes.
- No borres datos cuando deshabilites una pantalla o detengas una instancia.
- Correo: outbox con reintentos; SMTP ofrece entrega al menos una vez. Un
  Message-ID estable ayuda a correlacionar, no garantiza deduplicación externa.
- El perfil compose es exclusivamente local, con puertos loopback y Keycloak
  start-dev. No publiques este perfil como instalación empresarial.
- El candidato GitOps usa business-base-demo: lee KAANBAL_STACK.md. Los secretos
  se materializan desde Vault fuera de Git. Mantén runtime/init separados.
  compose.acceptance.yaml prueba el bootstrap con IdP producción sin puertos públicos.
- No inspecciones ni imprimas valores secretos en el chat. local:access es una
  acción manual de la persona en su terminal. Las pruebas usan credenciales en
  memoria, sin registrarlas ni capturar pantallas de autenticación.
- Una copia es un proyecto independiente. Propón al origen las correcciones
  comunes; no sobrescribas personalizaciones al actualizarlo.

Verificación: npm ci; npm test; npm run build; npm run local:up;
docker compose -p business-reference run --rm --no-deps migrate npm run test:integration;
npm run test:browser. La última prueba crea una cuenta ficticia separada para
MFA; no configura el autenticador del owner que usará la persona.
