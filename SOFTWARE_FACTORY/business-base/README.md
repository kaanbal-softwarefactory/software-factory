# Kaanbal Business Base — prototipo funcional

Base Next.js/PostgreSQL con identidad OIDC, organizaciones, permisos, landing,
catálogo, contacto/inbox, portal, reservas, equipo, auditoría y notificaciones.
La implementación vive aquí y se conserva aunque detengas una copia de prueba.
Estado y alcance: `business.manifest.json`.

**Starter: landing + administración + clientes.** Elige `starter` para una base
sin catálogo ni agenda de ejemplo. Sitio en `/`, equipo en `/admin`, clientes en
`/client`, en el dominio raíz o subdominio del lanzamiento. Sigue [STARTER.md](STARTER.md)
para lanzar, desarrollar y probar tu copia. Servicios y Barbería siguen disponibles.

El [contrato del stack](KAANBAL_STACK.md) describe el candidato `business-base-demo`
para Kaanbal: PostgreSQL, identidad y app por GitOps. Requiere integrar y actualizar
la versión del core que lo incorpora antes de aparecer en el catálogo.

## Probar la referencia

Requisitos: Docker Desktop/Engine con Compose, Node.js 24 y npm. En esta carpeta:

```sh
npm ci
npm run local:up
```

- Aplicación: http://localhost:3100
- Identidad: http://localhost:8180
- Buzón de correo de prueba: http://localhost:8125

En **tu propia terminal**, `npm run local:access` muestra las credenciales
generadas para `owner`, `customer` y `local-admin`. No las pegues en chats.
El owner configura su autenticador al primer acceso. Después usa «Verificar MFA»
para iniciar una sesión con contraseña y OTP verificados si el alta inicial no
incluyó ese factor en el token. Espera a que el autenticador cambie de código para
evitar reutilizar el código de alta. El cliente accede sin permisos administrativos.

Los secretos son aleatorios y viven en volúmenes Docker separados. La aplicación
no recibe las credenciales de PostgreSQL administrador, migraciones o administración
de Keycloak. No se genera ni se necesita un archivo .env.

## Lanzar otra instancia, conservando la base

```sh
npm run local:up -- --name business-barber-test --port 3200 --identity-port 8280 --mail-port 8225 --preset barber --title "Barbería Demo"
```

Cada nombre crea bases, usuarios de identidad, secretos y volúmenes propios.
Dos proyectos no comparten usuarios aunque tengan los mismos nombres de prueba.
No cambies los puertos de un proyecto ya inicializado: sus callbacks OIDC se
registran con esos puertos. Para otra configuración, usa otro nombre.

Detener una prueba preservando sus datos:

```sh
npm run local:stop -- --name business-barber-test
```

Para reanudarla usa el comando de lanzamiento original. Un reinicio no vuelve
a sembrar datos ni cambia su nombre de negocio. El bootstrap se puede repetir.
El repositorio de la base es independiente del ciclo de vida de estos contenedores.

La eliminación permanente debe hacerse únicamente tras confirmar el proyecto
y sus volúmenes en Docker Desktop. No hay un botón de «borrar todo» en los scripts.

## Generar una aplicación con código independiente

```sh
npm run copy -- --output ../business-copies/barber-demo --name business-barber-demo --preset barber --title "Barbería Demo" --port 3200 --identity-port 8280 --mail-port 8225
cd ../business-copies/barber-demo
npm ci
npm run local:up
```

El destino debe ser nuevo y estar fuera de la carpeta fuente. No se copian bases,
secretos, node_modules ni builds. business.config.json guarda marca, preset,
puertos y nombre del proyecto; business.manifest.json registra la versión de origen.
Inicializa un repositorio propio para el nuevo sistema cuando empieces a desarrollarlo.

En esta etapa la copia es código independiente; todavía no existe un registro de
paquetes ni una actualización automática de copias. La extracción a paquetes y el
flujo de actualización por PR forman parte de la promoción a plantilla estable.

## Recorrido manual

1. Abre la landing y envía una solicitud.
2. Accede como owner, configura/verifica MFA y abre Solicitudes.
3. Asigna la solicitud y ciérrala; comprueba el evento en Auditoría.
4. Como customer, envía otra solicitud estando autenticado y consulta Mis solicitudes.
5. Reserva un servicio dentro del horario piloto; intenta reservar el mismo recurso
   al mismo tiempo desde otra cuenta y comprueba que se rechaza el solape.
6. Invita un colaborador con un enlace privado: solo el correo verificado destinatario
   puede aceptarlo. Para administradores, configura MFA en su cuenta del IdP.
7. Suspende un miembro y comprueba que pierde acceso en la siguiente operación.
8. Reinicia app y base; comprueba que los registros siguen existiendo.
9. Comprueba el aviso de contacto en el buzón local; no se envía a direcciones reales.

Las solicitudes anónimas quedan en el inbox del equipo; no se vinculan por correo
a una cuenta posterior, para evitar apropiación de datos. Las solicitudes creadas
con sesión pertenecen a ese usuario. La vinculación verificada de invitados es una
evolución pendiente.

## Arquitectura y pruebas

- OIDC Authorization Code + PKCE, state/nonce y biblioteca openid-client.
- Identidad por issuer+subject, cookies HttpOnly, sesión opaca de 30 minutos,
  protección de origen y backchannel logout firmado con prevención de replay.
- Permisos por recurso en servidor y RLS PostgreSQL; rol runtime sin propiedad,
  superusuario ni BYPASSRLS. Migraciones y credenciales de ejecución separadas.
- Reservas por recurso, bloqueo transaccional y restricción de exclusión SQL.
- Outbox de correo con workers, reintentos y entrega al menos una vez; auditoría
  no editable con el rol de ejecución. No equivale a un registro resistente a un DBA.
- Probes independientes de proceso y de disponibilidad de dependencias/esquema.

```sh
npm test
npm run build
docker compose -p business-reference run --rm --no-deps migrate npm run test:integration
npx playwright install chromium
npm run test:browser
```

Después de lanzar también `business-barber-test` con el comando anterior, ejecuta
`npm run test:copies`: verifica identidades, organizaciones y catálogos separados,
incluyendo sesiones simultáneas en un mismo navegador. Las cookies de las apps
se nombran por instancia porque los navegadores no separan cookies por puerto.

Las pruebas de integración crean datos ficticios en la instancia de prueba.
Las de navegador crean su propia cuenta administrativa para probar MFA y no
alteran el autenticador del owner. Las capturas se guardan en coverage/browser.
Nunca se capturan pantallas de contraseña o configuración del autenticador.

## Promover a plantilla de Kaanbal

La consola incorpora **Sistemas**, una vista sobre los grupos existentes, con
responsable, etapa y aplicaciones. El responsable es organización del trabajo,
no una restricción de visibilidad. Los stacks nuevos asignan como responsable
inicial a quien los lanza sin sobrescribir un responsable existente.

Este prototipo aún no aparece como plantilla ready. Antes de publicarlo faltan:

1. Validar la experiencia con una persona en dos copias independientes.
2. Extraer el núcleo y módulos compartidos versionados y ensayar una actualización.
3. Integrar un contrato de identidad en Kaanbal: emisor público HTTPS, cliente por
   ambiente, referencias Vault y configuración de MFA/SSO empresarial probada.
4. Provisionar PostgreSQL con roles runtime y migración separados, y describir
   tareas de migración/bootstrap mediante GitOps. No ejecutar este Compose en el clúster.
5. Extender el lanzador a componentes con IDs y dependencias explícitas, reintentos
   seguros y estado persistente por paso.
6. Registrar candidato, ejecutar draft → validating → ready y validar restauración,
   actualización y rollback compatible en una célula de prueba.

Para producción: imágenes mantenidas y revisadas, TLS, IdP en modo producción,
SMTP real con TLS, respaldo/restauración del negocio y de identidad, revisión de
seguridad y carga. La referencia comprueba funcionalidad, no certifica disponibilidad.

## Migración de aplicaciones existentes

Se realiza por sistema, en una copia de staging: inventario de datos y permisos,
mapa de identidades verificadas, adaptadores/importación, pruebas de negocio,
respaldo, ensayo de corte y rollback. Empieza por una app pequeña de servicios.
Conserva los IDs y relaciones de los datos y planifica los rehashes o recuperación
de contraseña cuando el proveedor anterior no permita migrar credenciales.
No concedas acceso solo por coincidencia de correo. La plataforma puede desplegar
la base nueva sin obligar a reescribir a la vez las aplicaciones existentes.

## Referencias

Arquitectura contrastada con [Next.js Authentication](https://nextjs.org/docs/app/guides/authentication),
[openid-client](https://github.com/panva/openid-client),
[Keycloak quickstarts](https://github.com/keycloak/keycloak-quickstarts) y
[PostgreSQL RLS](https://www.postgresql.org/docs/16/ddl-rowsecurity.html).
Se reutilizan las bibliotecas con sus licencias; no se ha copiado un starter
completo ni importado su login de contraseñas al lado de OIDC.
