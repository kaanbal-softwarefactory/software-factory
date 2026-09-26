# AGENTS

Memoria de trabajo para asistentes de código. Complementa a [`AGENTS.md`](../AGENTS.md), que
es el contrato, con lo que cambia de una sesión a otra.

| Ruta | Para qué |
|---|---|
| [`STATE.md`](STATE.md) | Snapshot operativo: qué está en curso, qué se sabe roto y qué sigue. |
| [`sessions/`](sessions/) | Una nota por sesión de trabajo. Copia `TEMPLATE.md`. |
| [`labs/`](labs/) | Sandbox: único lugar para scripts y archivos desechables. No se versiona. |

Reglas:

- Nada de secretos, datos de clientes ni direcciones reales de servidores en estos archivos.
- Al cerrar una sesión: actualiza `STATE.md` si cambió el sistema y limpia `labs/`.
