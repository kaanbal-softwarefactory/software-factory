# Autonomía MCP — primera versión

Estado: implementación para revisión; no desplegada ni habilitada. Trabajo sin
ticket por autorización del usuario. Rama: `codex/mcp-autonomy`.

## Qué incorpora

| Capacidad | Control requerido |
|---|---|
| Descubrir herramientas nuevas | `autonomy.tools.view` |
| Comandos en la app registrada | `autonomy.apps.execute`, token crítico y concesión app + ambiente |
| Comandos root en nodo | `autonomy.host.execute`, token crítico y concesión de nodo exacto |
| Contenedor temporal para cambios | `autonomy.workspaces.manage`, política workspace y recurso autorizado |
| Contribución al core | Además `autonomy.core.contribute` y concesión `core` |
| Rama y PR | Además `autonomy.changes.propose` |
| Merge de PR de app | Además `autonomy.changes.merge`, token crítico y política merge |
| Actualizar plataforma | `core.updates.apply`, mediante el Job de actualización existente |
| Cambiar política | `autonomy.policy.manage`, sesión y confirmación de contraseña |
| Emitir token crítico | `security.tokens.elevated`, sesión, contraseña y aceptación del alcance |

Se intersectan permisos de la persona, scopes del token y concesión de recursos.
El rol owner conserva sus ACL pero tampoco omite la política de autonomía. Las
concesiones identifican usuario y opcionalmente token, recursos exactos y fecha
de vencimiento; no se admiten comodines. Los componentes de plataforma se excluyen
del ejecutor de apps. Un registro de app que apunta al upstream del core tampoco
permite eludir el flujo de contribución al core.

`agente-ingeniero` incluye diagnóstico, workspaces y propuestas de cambios. Los
permisos críticos se conceden por separado a roles/personas autorizados. La opción
de token crítico captura todos los permisos actuales de quien lo emite; un token
viejo no recibe automáticamente los permisos nuevos de una futura versión.

## Tokens y confirmación

En **Acceso → Tokens → Nuevo token**:

1. Define nombre, inicio y fin de vigencia. El navegador convierte la hora local
   a UTC. Antes del inicio figura como `programado` y no autentica.
2. Para un token normal puedes marcar **No expira nunca**, con advertencia expresa.
   Los intervalos con vencimiento admiten hasta 365 días.
3. Para una intervención crítica marca **Control total**, acepta que los comandos
   pueden leer datos/credenciales, modificar o borrar recursos y acceder como root
   a nodos autorizados. Confirma el usuario y contraseña de tu propia sesión.
   Su intervalo de vigencia tiene un máximo de 24 horas; la consola propone una hora.
4. Copia el valor mostrado una sola vez. En Mongo se conserva su hash.
5. Usa **Revocar** al terminar. Los tokens no pueden emitir otros tokens ni cambiar
   la política de autonomía mediante confirmación de contraseña.

La autenticación consulta vigencia, revocación, usuario y permisos en cada petición.
Revocar o vencer bloquea solicitudes posteriores: no deshace acciones anteriores
ni garantiza detener procesos iniciados por un comando. Los timeouts ayudan a
limitar duración, pero un usuario con ejecución root puede iniciar procesos
independientes; no son un límite de seguridad contra ese usuario.

**Actividad** muestra los últimos 100 eventos del token: método/ruta/estado HTTP,
acción, destino e identificador de operación. Las operaciones de comandos guardan
un SHA-256 del comando, no el texto que podría contener contraseñas. No se guardan
payloads ni respuestas en este historial. Los eventos se retienen 90 días mediante
TTL; el registro HTTP incluye rechazos ACL de tokens válidos. Los intentos con
credenciales inválidas no se atribuyen a un token. No es un registro inmutable
frente a quien ya tiene root o escritura directa en Mongo.

La confirmación compartida vive en `app/services/step_up.py`: verifica la contraseña
actual en la base y limita a cinco intentos por ventana de cinco minutos mediante
contador atómico en Mongo, compartido entre réplicas. No persiste la contraseña.

## Workspaces y contribuciones

El broker mantiene la credencial GitHub configurada en la API. Lee el commit de la
rama predeterminada y descarga su ZIP; no lo inyecta en el pod. El pod crea un Git
local con un commit base para calcular cambios. No incluye historial, submódulos
ni materialización de Git LFS. El código se edita mediante herramientas de archivos
o comandos del workspace. Puede usarse para cambios en el MCP, API y consola.

Flujo para el agente:

1. `platform_capabilities` devuelve el catálogo actualizado y sus esquemas.
2. `open_app_workspace` con app/ambiente, o `open_core_workspace` para Kaanbal.
3. Consulta `get_workspace`; cuando el pod esté `Running`, ejecuta
   `initialize_workspace`.
4. Lee/escribe archivos con `workspace_files` y `write_workspace_file`. `content=null`
   elimina un archivo. `run_workspace_command` permite editar o validar localmente.
5. Revisa `workspace_diff`. Para publicar envía su `digest` como `expected_digest`
   a `publish_workspace_pr`, con título y descripción. La API comprueba otra vez
   el diff y fija el commit publicado antes de crear la rama y el PR.
6. Si se pierde una respuesta de GitHub, vuelve a consultar el workspace. Reintentar
   la publicación reconcilia la rama y PR existentes sin sobrescribir otra versión.
7. Para apps, `merge_app_pr` requiere el `published_sha` revisado y que GitHub indique
   el PR abierto, sin borrador y con estado de merge limpio. Mantén las protecciones
   de rama y checks requeridos en GitHub: el servidor respeta su decisión.
8. El core se publica como borrador y siempre requiere merge del owner en GitHub.
   El broker no ofrece merge del core. Cierra el workspace al terminar.

El core usa `core_upstream` ya existente. Si la credencial no puede publicar ramas
allí, el owner configura `core_fork` (`owner/repo`) y el broker comprueba que es un
fork del upstream y que tiene escritura. No crea forks automáticamente. Para apps,
la credencial debe poder crear ramas y PRs en su repositorio registrado.

Cada workspace pertenece a usuario + token y vuelve a comprobar ACL/política en
cada llamada. Un token nuevo no hereda el workspace del anterior. Se serializan las
mutaciones mediante lease en Mongo; publicado el commit, las escrituras se bloquean.
La limpieza de expirados corre cada minuto y el pod tiene `activeDeadlineSeconds`.

Límites de esta versión:

- ZIP de hasta 25 MiB, contenido extraído hasta 100 MiB y 10 000 archivos.
- Edición/publicación de texto UTF-8: 1 MiB por archivo, 100 archivos y 2 MiB por PR.
- No se leen/publican rutas `.git`, `.env*`, `*.pem`, `*.key`, symlinks ni traversal.
- Se rechazan patrones conocidos de credenciales y los tokens GitHub de plataforma
  antes de publicar; esto no detecta todos los secretos posibles. Revisa el diff.
- Comandos: hasta 120 segundos; salida hasta 64 KiB. La app necesita `/bin/sh` y
  `timeout`. El comando usa los permisos y acceso de su contenedor.
- El workspace vive una hora por defecto, configurable entre cinco minutos y cuatro horas.
- No existe una herramienta universal para crear usuarios de cualquier app: el
  comando de reparación debe usar el mecanismo de autenticación propio de esa app,
  incluido hash, expiración y cambio obligatorio de la contraseña temporal cuando
  corresponda. No modificar usuarios sin entender ese esquema.

## Preparación de infraestructura por el owner

Ninguna capacidad se activa durante esta implementación. Política inicial: todas
las funciones deshabilitadas y cero concesiones.

El addon optativo `infra-gitops/addons/agent-autonomy` incluye únicamente workspaces:
namespace con Pod Security `restricted`, cuota de cuatro pods, RBAC limitado a ese
namespace y NetworkPolicy con ingress/egress vacíos. No está agregado al despliegue
base. Revisa el namespace del ServiceAccount `kaanbal-api` en el RoleBinding si tu
instalación difiere de `prod`. La red requiere un CNI que aplique NetworkPolicy.

Construye la imagen de `kaanbal-workbench/Dockerfile`, publícala con versión o digest
y configura `workbench_image`. Incluye en la imagen las dependencias necesarias
para validar tus proyectos: estos pods no descargan paquetes ni se conectan a
GitHub, bases de datos o servicios del clúster. La API transporta el código y publica
los cambios. Los pods no montan tokens de ServiceAccount ni volúmenes del host,
ejecutan como UID 10001, eliminan capabilities y tienen raíz de solo lectura.

La instalación del addon, imagen, políticas y concesiones debe revisarse por GitOps.
No se incluyen RBAC amplios de `pods/exec` en producción ni un namespace privilegiado
para root. La revisión automática de este entorno rechazó esos manifiestos por
alcance amplio; hace falta concretar los destinos Kubernetes antes de su activación.
Los adaptadores de ejecución app/root están implementados y probados con simulaciones,
pero requieren esa preparación adicional de permisos/admisión para funcionar.

Root usa un Job sin reintentos automáticos, sobre el nodo concedido, con `hostPID`,
contenedor privilegiado y `nsenter`. El host necesita `timeout` y `/bin/sh`.
Este alcance permite controlar el nodo y puede alcanzar datos o credenciales del
clúster: la concesión del nodo no aísla otros recursos frente a root.

Si un comando devuelve resultado incierto, consulta el estado antes de repetirlo.
Los Jobs root guardan su nombre antes del lanzamiento para recuperar el estado con
`get_operation`. El timeout o un error de transporte no garantizan que un cambio no
se haya ejecutado. La redacción de salida es parcial: un comando crítico puede
retornar información sensible que no coincida con los patrones conocidos.

## Actualizar herramientas y plataforma

`platform_upgrade(ref)` reutiliza el Job de actualización existente del core y
`platform_upgrade_status(name)` consulta su progreso. El merge y el despliegue son
pasos separados. Usa la referencia revisada y conserva GitOps como fuente de despliegue.

Para añadir una capacidad compatible con el puente actual, incorpora su endpoint,
regla ACL y entrada en `autonomy_catalog.py`. El cliente consulta el catálogo vivo
en cada invocación y solo admite rutas relativas `/autonomy`, `/apps` y `/core`,
métodos conocidos y argumentos declarados. La API genera `input_schema` desde
OpenAPI. Tras actualizar el servidor, el agente puede descubrir y llamar esa nueva
capacidad sin reinstalar MCP. Cambios al protocolo de transporte requieren una
versión nueva del cliente; no se instala código remoto arbitrario en la máquina del agente.

## MFA con app autenticadora — siguiente versión

Es posible exigir TOTP con aplicaciones autenticadoras. El diseño propuesto:

1. Alta desde sesión confirmada: generar un secreto por usuario, custodiarlo cifrado
   o en Vault, mostrar QR y confirmar un primer código antes de activar MFA.
2. Login en dos fases: contraseña → desafío MFA breve → código válido → sesión
   completa. El desafío no debe permitir llamar endpoints normales.
3. Reutilizar `step_up.confirm` para pedir un código reciente al emitir un token
   crítico, cambiar política u otras acciones seleccionadas. La comprobación se
   hace en el backend y queda ligada a la acción y sesión.
4. Limitar intentos, impedir reuso de códigos ya aceptados, admitir una ventana
   pequeña de desfase y entregar códigos de recuperación de un solo uso, guardados
   como hashes. El reset de MFA necesita un flujo administrativo independiente.

Esta versión prepara el punto central de confirmación; no implementa alta, QR,
segundo factor de login ni recuperación. Referencia del protocolo:
[RFC 6238 (TOTP)](https://www.rfc-editor.org/rfc/rfc6238).

## Evidencia local

La versión original se validó con 85 pruebas offline y build de consola. Esta
adaptación de Kaanbal 1.2.1 amplía el MCP HTTP integrado y requiere su propia
verificación de CI. El workflow existente `.github/workflows/ci.yml` ejecuta
la suite completa, los contratos `tests/contract_autonomy.py`,
`tests/contract_autonomy_api.py`, `tests/contract_autonomy_flow.py` en procesos
separados, y construye la consola. El flujo
simulado usa Git real en un directorio temporal con Mongo, Kubernetes y GitHub
simulados. No demuestra despliegue real, conectividad, admisión de pods, funcionamiento
de NetworkPolicy ni merge/despliegue contra una instalación existente.
