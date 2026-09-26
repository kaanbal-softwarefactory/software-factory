---
name: tarea-iniciar
description: Inicia el trabajo en un issue. Lee el issue, carga las reglas del área y crea la rama de trabajo. Usar con "inicia #123" o al empezar una implementación.
---

# Tarea iniciar

## Entrada

- Número del issue: `#123`

## Pasos

1. Lee el issue completo (con `gh issue view 123`, o pide que peguen su descripción).
2. Verifica los criterios de aceptación y los archivos que están en alcance.
3. Carga las reglas del área según `docs/CONTEXT_MAP.yaml` → `by_area`.
4. Crea la rama desde `main`: `git checkout -b feat/123-slug-corto` (o `fix/…`, `docs/…`).
5. Comenta en el issue que empezó el trabajo, con el nombre de la rama.
6. Confirma el plan a la persona antes de editar archivos.

## Formato de commit

`tipo(alcance): descripción`

Tipos: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.
