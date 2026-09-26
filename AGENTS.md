# Kaanbal — Instrucciones para agentes

Este archivo lo leen los asistentes de código (Claude Code, Codex, Cursor…) al abrir el
repositorio. Es el contrato: qué leer, qué reglas no se negocian y cómo verificar un cambio.

## Lee antes de trabajar

1. `README.md` — qué es Kaanbal y cómo está organizado el repositorio.
2. `docs/CONTEXT_MAP.yaml` — qué documento cargar según el área que vas a tocar.
3. `docs/vision/KAANBAL_VISION.md` — visión resumida.
4. `AGENTS/STATE.md` — snapshot operativo: qué está en curso y qué se sabe roto.
5. `CONTRIBUTING.md` — ramas, commits y pull requests.

## Reglas obligatorias

- **Nunca escribas secretos.** Ni en código, ni en commits, ni en issues, ni en el chat. Usa
  `CHANGE_ME` como marcador. No leas `.env`, `*.pem`, `*.key` ni `_private/`, salvo `.env.example`.
- **Nada de datos reales** de clientes, dominios o servidores en tests y documentación: usa
  `example.com`, `192.168.1.x` o `203.0.113.x`.
- **Una tarea, una rama, un PR.** Nunca modifiques `main` directamente ni fuerces un push.
- **Cada endpoint nuevo de la API necesita regla de acceso** en
  `SOFTWARE_FACTORY/kaanbal-api/app/services/permissions.py`. Sin regla, la API lo bloquea y un
  test falla.
- **GitOps es la fuente de despliegue.** No parches un clúster a mano: cambia la plantilla o el
  instalador y vuelve a renderizar.
- **El instalador usa solo la biblioteca estándar de Python.** No agregues paquetes de `pip`.
- **Migraciones expand/contract.** Una release no elimina ni renombra lo que la anterior lee.
- **Comandos destructivos** (`kubectl delete`, `rm -rf`, `git push --force`, formatear discos)
  requieren aprobación explícita de la persona en ese momento.
- **Agentes en la nube:** solo código, pull requests y documentación. Sin acceso SSH a servidores.

## Cómo verificar un cambio

```bash
# API
cd SOFTWARE_FACTORY/kaanbal-api && python -m unittest discover -s tests -p 'test_*.py'
# Instalador
python -m unittest discover -s SOFTWARE_FACTORY/installer -p 'test_*.py'
bash -n install.sh && bash -n SOFTWARE_FACTORY/install.sh
node --check SOFTWARE_FACTORY/installer/static/app.js
# Consola
cd SOFTWARE_FACTORY/kaanbal-console && npm run build
# MCP
cd SOFTWARE_FACTORY/kaanbal-mcp && python -m unittest discover -s tests
```

## Skills del flujo

| Cuándo | Skill |
|---|---|
| Iniciar una sesión de trabajo | `.cursor/skills/abrir-sesion/` |
| Cerrar una sesión | `.cursor/skills/cerrar-sesion/` |
| Empezar una tarea (issue) | `.cursor/skills/tarea-iniciar/` |
| Terminar una tarea | `.cursor/skills/tarea-cerrar/` |

## Pruebas manuales

Documéntalas en el chat, y en el pull request, con este formato:

```text
PRUEBA: <tarea> — título
FECHA:
PRECONDICIONES:
PASOS:
RESULTADO ESPERADO:
RESULTADO OBTENIDO:
EVIDENCIA: (comando, captura, URL — sin credenciales)
APROBADO: sí/no
```

## Subagentes recomendados

| Subagente | Cuándo |
|---|---|
| `explore` | Mapear código que no conoces |
| Revisor de PR | Revisar un cambio antes de fusionarlo |
| Investigador de CI | Diagnosticar un CI fallido |
