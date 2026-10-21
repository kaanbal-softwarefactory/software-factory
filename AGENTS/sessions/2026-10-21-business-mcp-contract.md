# Sesión: 2026-10-21 — Contrato MCP de Business Base

## Objetivo

Validar el flujo de otra persona al lanzar/desarrollar Business Base por MCP,
la atribución del grupo y la estrategia de correo por cliente.

## Resultado

La célula instalada reporta dev-234ac49; el lanzamiento remoto del stack terminó
succeeded con sus tres componentes ready. No se modificó el despliegue durante
esta tarea. No se probó login remoto autenticado/MFA de una persona real.

Se corrigió el contrato MCP genérico que carecía de receta local, variables y
ruta de salud útiles para Business Base. Ahora declara conexiones y nombres por
proceso, distingue declaración de inspección runtime y devuelve responsable del
grupo cuando está disponible. La guía explica tokens personales, copia local,
desarrollo en el repositorio generado y límites del candidato.

Los planes muestran group_owner y lo incluyen en su validación de vigencia.
Pruebas verifican identidad autenticada, campos de owner enviados ignorados,
preservación del responsable existente e invalidación ante cambio del owner.

EMAIL_PROFILES.md propone perfiles SMTP por cliente/ambiente para Keycloak y
worker, credenciales Vault y proveedor externo. No implementa un panel, entrega
externa ni configuración de proveedor. El correo actual sigue capturado.

## Rama y publicación

- Rama: codex/business-base-mcp-contract, desde main dev-234ac49.
- GitHub conectado: pull=true, push=false. gh sin sesión. Sin PR creado.
- Los cambios requieren publicar la rama, revisión, integrar y actualizar la
  célula antes de que el MCP remoto exponga el contrato corregido.

## Verificación

- API: 584 pruebas, OK, una omitida.
- Puente MCP: 10 pruebas, OK.
- Contrato Business Base: 4 pruebas nuevas dentro de la suite, compara nombres
  declarados con los manifests generados y comprueba ausencia de valores.
- Planes: 19 pruebas, incluidas tres nuevas de ownership.
- git diff --check: limpio.
- No cambios de consola ni renderer: no se repitieron builds de imágenes/UI.

Primera corrida Windows falló por PATH de bash (WSL sin /bin/bash) y dependencias
antiguas. Corrida válida: py con PYTHONPATH apuntando a kaanbal-test-deps temporal,
Git bin antepuesto al PATH y avisos deprecados silenciados. No se leyeron .env.

```text
PRUEBA: Business Base — contrato MCP y responsable autenticado
FECHA: 2026-10-21
PRECONDICIONES: célula dev-234ac49 y stack previamente lanzado; dependencias locales
PASOS: whoami, stack_status; suite API y puente MCP; revisar diff
RESULTADO ESPERADO: stack succeeded; contrato coherente; owner del usuario autenticado
RESULTADO OBTENIDO: tres componentes ready; suites OK; contrato corregido solo local
EVIDENCIA: 584 pruebas API (1 omitida), 10 puente; rama codex/business-base-mcp-contract
APROBADO: sí, validación descrita; entrega externa y aceptación remota MFA pendientes
```
