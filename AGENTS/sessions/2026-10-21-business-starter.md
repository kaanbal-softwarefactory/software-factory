# Sesión: 2026-10-21 — Starter para sitio y paneles

## Objetivo

Dejar una opción repetible de Business Base para landing pública, equipo y clientes,
con configuración por consola/MCP y una copia lista para desarrollar.

## Trabajo realizado

- Preset starter: landing profesional responsive en /, equipo en /admin, clientes
  en /client; /workspace elige panel por membresía. APIs conservan MFA, propiedad,
  validación de membresías y RLS. El panel cliente permite crear solicitudes y
  consultar únicamente las propias; el equipo las atiende según permisos.
- Starter no siembra catálogo ni recursos y oculta su navegación. Servicios y
  Barbería conservan sus módulos. No hay eliminación de datos.
- Migración aditiva 003_starter_experience: persistencia del preset. Readiness
  espera esta migración. Bootstrap repetido conserva el preset ya persistido.
- Selector en Stacks con Starter por defecto solo en la consola; API conserva
  services como default para clientes existentes. Enum MCP admite starter. Plan
  expone URLs de las tres páginas con homepage o subdominio y origen OIDC coherente.
- Repo generado guarda business.config.json con nombre local, marca y preset.
  La base incorpora su propio .gitignore para que una copia independiente no suba
  dependencias, builds o secretos. Se agregó guía STARTER.md y referencias de agentes.

## Verificación

- API: 587 pruebas, OK (1 omitida); puente MCP: 10, OK.
- Next.js build, typecheck y 9 pruebas unitarias: OK.
- Consola: npm run build, OK.
- Copia local aislada business-starter-test, puertos 3300/8380/8325, datos ficticios.
- Bootstrap/migración inicial y segundo local:up --build: OK, datos conservados.
- Pruebas reales de integración con PostgreSQL: 12, OK (RLS, autorización, invitaciones,
  sesiones, auditoría, concurrencia y contacto persistido).
- Navegador real con Keycloak: dos corridas OK. Login cliente → /client; cliente
  denegado en /admin y en API de miembros (403); solicitud desde portal → inbox;
  cuenta owner de aceptación con MFA → /admin; asignación, mobile y logout.
- Capturas revisadas en coverage/starter; no capturas de login/MFA ni credenciales.
- HTTP público tras reconstrucción: experience=starter, 0 servicios y 0 recursos;
  /api/ready devuelve ready. Rutas root/subdominio verificadas por planes/renderer,
  no por dos despliegues DNS nuevos.
- git diff --check limpio. No cambios en el clúster ni en la demo remota existente.

## Publicación y límites

Rama codex/business-base-starter incluye el commit anterior a44cd3c pendiente,
que corrige el contrato MCP. No mezclar copias de app con la actualización del core.
La conexión GitHub conocida tiene solo lectura y gh no está autenticado. Falta
publicar rama, PR/revisión e integración, actualizar célula y aceptar un stack nuevo
por HTTPS. El correo permanece capturado; SMTP real/perfiles por cliente pendientes.
La copia local queda corriendo para revisión, sin tocar las otras copias.

```text
PRUEBA: Business Base Starter — landing, admin y clientes
FECHA: 2026-10-21
PRECONDICIONES: copia local aislada, PostgreSQL/Keycloak y cuentas ficticias
PASOS: lanzar/reconstruir; login cliente y MFA; solicitud → inbox; suite de seguridad
RESULTADO ESPERADO: tres áreas, acceso por rol, preset y datos persistentes
RESULTADO OBTENIDO: pruebas aprobadas; correo capturado; publicación remota pendiente
EVIDENCIA: suites, coverage/starter, guía STARTER.md
APROBADO: sí, alcance local; aceptación HTTPS tras integrar pendiente
```
