---
name: cerrar-sesion
description: Cierra una sesión de Kaanbal con evidencia, actualiza AGENTS/STATE.md y deja una nota en AGENTS/sessions/. Usar cuando la persona dice "cierra sesión".
---

# Cerrar sesión

## Pasos

1. `git status` — no debe quedar nada sin subir a una rama.
2. Si hubo pull request: confirma el estado del CI.
3. Crea `AGENTS/sessions/YYYY-MM-DD-HHMM-tema.md` a partir de `AGENTS/sessions/TEMPLATE.md`.
4. Actualiza `AGENTS/STATE.md` si cambió lo que se sabe del sistema.
5. Limpia `AGENTS/labs/`: elimina los scripts desechables.
6. Responde: "Sesión cerrada" y la ruta de la nota.

## No hacer

- Incluir secretos, datos de clientes ni direcciones reales de servidores en la nota.
