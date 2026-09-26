# AGENTS/labs — sandbox

El único lugar donde un asistente puede crear scripts, pruebas, diagnósticos y archivos
temporales. **Su contenido no se versiona** (solo este README): si algo merece conservarse,
muévelo a su lugar definitivo en el repositorio y agrégale pruebas.

## Reglas

- Todo script o archivo temporal de una sesión va aquí.
- Al cerrar la sesión, elimina lo desechable.
- No crees archivos fuera de esta carpeta salvo en las rutas previstas de cada componente.
- Nada de credenciales, ni siquiera de prueba.

## Ejemplos de lo que va aquí

- Scripts de diagnóstico de un solo uso (`kubectl`, `curl`).
- Comprobaciones de conectividad.
- Borradores antes de moverlos al repositorio.
