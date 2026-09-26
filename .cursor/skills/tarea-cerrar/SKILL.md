---
name: tarea-cerrar
description: Cierra una tarea con pull request, evidencia en el issue y bloque PRUEBA en el chat. Usar al terminar la implementación de un issue.
---

# Tarea cerrar

## Entrada

- Número del issue: `#123`
- Rama con los commits listos

## Pasos

1. Ejecuta las pruebas de la tarea (automáticas y manuales; comandos en `AGENTS.md`).
2. Abre el pull request contra `main`, con la plantilla del repositorio. Título: `tipo(alcance): resumen`.
3. Comenta en el issue con:
   - la rama y los commits;
   - la URL del pull request;
   - las pruebas ejecutadas;
   - riesgos y cómo revertir.
4. Pega en **este chat** el bloque PRUEBA.

## Plantilla PRUEBA

```text
PRUEBA: #123 — título
FECHA: YYYY-MM-DD
PRECONDICIONES:
PASOS:
RESULTADO ESPERADO:
RESULTADO OBTENIDO:
EVIDENCIA: (comando, captura, URL — sin credenciales)
APROBADO: sí/no
```
