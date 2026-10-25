# Updates: diagnóstico y corrección

Reporte del usuario: parece que el último upgrade quedó pegado; no permite forzar el último commit.

## Evidencia

Consultas de solo lectura a la API de la célula y Git:

- Último Job: `succeeded`; procedencia instalada `dev-e6f354a`.
- Upstream `main`: `3766eca`, un commit por delante; `touches_engine=false`, `update_available=false`.
- Ese commit solo conserva contexto/documentación. La implementación HUB2 sigue WIP en `codex/hub-dev-workflow`, checkpoint `6ea71a0`; un upgrade de main no la incorpora.
- Sin deriva local. No había candado de upgrade atascado ni error de GitHub en la consulta comprobada.

## Cambio

Updates explica commits fuera del engine, consulta fallida y estado desconocido. Muestra el error HTTP de la comprobación y descarta el resultado anterior para evitar acciones sobre datos obsoletos. El canal Dev ofrece reaplicación manual de la revisión comprobada, con confirmación, SHA fijado y sin saltar la protección de deriva o el Job en curso. No actualiza la plataforma automáticamente.

`platform_status` del MCP antes leía campos que ya no existen (`available` y `commits` en la raíz), devolviendo null/0 aunque hubiera commits. Ahora lee `update_available` y `upstream.ahead_by`, conserva estado desconocido si falla la consulta e incluye los detalles de upstream.

## Verificación

- API completa: 661 pruebas, OK, una omitida.
- Consola: 6 pruebas de estados, OK; `npm run build`, OK. `npm test` añadido al CI de consola.
- MCP: 10 pruebas, OK.
- Instalador: suite completa OK con directorio de estado temporal escribible (el valor predeterminado apunta al home de solo lectura de este entorno).
- Sintaxis: ambos install.sh y JavaScript del instalador, OK.

PRUEBA: UPDATES1 — consulta y reaplicación manual
FECHA: 2026-10-25
PRECONDICIONES: Vite local, Chromium del sistema, API simulada con datos reservados; no se envían cambios al clúster.
PASOS: mostrar docs-only; abrir reaplicación; confirmar después de que main cambie; intentar con deriva; simular GitHub 403 y HTTP 503.
RESULTADO ESPERADO: distinguir commits/engine/error; no POST sin confirmación; enviar SHA seleccionado; bloquear deriva; no mantener revisión obsoleta ante HTTP fallido.
RESULTADO OBTENIDO: todos los casos aprobados, sin excepciones de navegador. Comprobación en viewport 639×716.
EVIDENCIA: pruebas de consola en tests/coreUpdates.test.mjs y API en tests/test_mcp_tools.py; comprobación manual con Playwright. Captura y script temporal no se versionan.
APROBADO: sí (código local). Instalación real de la corrección pendiente del upgrade manual de la persona.
