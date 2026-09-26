<div align="center">

# Kaanbal

**Una plataforma auto-hospedada para desplegar y operar aplicaciones en tu propio
servidor, con GitHub, GitOps y Kubernetes.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v1.0.0-informational.svg)](CHANGELOG.md)

[English](README.md) · [Guía de instalación](docs/guides/INSTALL_UBUNTU.md) · [Changelog](CHANGELOG.md) · [Seguridad](SECURITY.md) · [Contribuir](CONTRIBUTING.md)

</div>

---

## ¿Qué es Kaanbal?

Kaanbal convierte un servidor Ubuntu, o un VPS, en una pequeña plataforma como
servicio. Lo instalas con un comando, completas una configuración guiada en el
navegador y, desde una consola web, lanzas aplicaciones: frontend, API, base de datos,
flujos de trabajo.

Cada aplicación recibe su propio repositorio de GitHub y su pipeline de CI. Lo que
corre se describe con manifiestos de Kubernetes versionados en un repositorio GitOps y
reconciliados por Argo CD: el estado de tu plataforma siempre está en Git. Los
secretos viven en Vault, nunca en Git.

Cada aplicación puede ser accesible **en tu red local**, **de forma privada por una VPN
Tailscale** o **públicamente mediante un túnel de Cloudflare**, según la aplicación y el
ambiente.

## Qué incluye

- **Instalación con un comando.** Un script de arranque y un asistente web. El instalador
  usa solo la biblioteca estándar de Python: no hay que instalar nada con `pip` en el servidor.
- **Consola web.** Aplicaciones, plantillas, stacks, dominios, vínculos entre servicios,
  sites, bitácora, actualizaciones y control de acceso.
- **Plantillas.** Vue 3, React, FastAPI, MongoDB, PostgreSQL, n8n y EMQX de serie, y una
  [especificación](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) para plantillas de la comunidad.
- **Stacks.** Lanza base de datos, API y frontend juntos y ya conectados: la API queda
  vinculada a su base y el frontend se construye con la URL real de su API. Un stack puede
  ocupar la raíz de un dominio como su homepage.
- **GitOps por defecto.** Un repositorio y un pipeline por app, manifiestos generados y
  sincronización con Argo CD. `infra-gitops` es la fuente de verdad de lo que corre.
- **Varios dominios por instalación.** Cada dominio tiene su propio sitio: un homepage y
  las APIs y bases de datos que le pertenecen.
- **Control de exposición.** Interna, LAN, VPN o pública, por ambiente.
- **Secretos en Vault**, generados por app. Los vínculos inyectan los nombres de variable
  que tu código ya espera: `MONGO_URI`, `DATABASE_URL`, `PGHOST`, `REDIS_URL`…
- **Control de acceso.** Roles, permisos por endpoint que niegan por defecto (un endpoint
  sin regla queda bloqueado), excepciones por persona y tokens personales que nunca pueden
  más que su dueño.
- **Actualizaciones seguras del core.** Se aplican desde la consola como un Job de
  Kubernetes que verifica el resultado y revierte solo si algo falla.
- **Servidor MCP.** Deja que Claude Code, Codex o Cursor inspeccionen tu plataforma —
  apps, salud, logs, *nombres* de variables— con un token acotado y de solo lectura.
- **Acuaponsito.** Un runtime de agente embebible con un personaje vivo, donde cada acción
  requiere aprobación humana.

## Inicio rápido

**Necesitas**

- Un Ubuntu Server dedicado (22.04 o superior) con OpenSSH y `sudo`, al menos 4 GB de RAM
  (el instalador se niega con menos) y acceso a Internet.
- Un usuario u organización de GitHub y un token de acceso personal (classic, con `repo`,
  `workflow` y `read:org`). Kaanbal crea allí los repositorios.
- Una cuenta de Docker Hub y un token de acceso. Hoy las imágenes se publican allí.
- Opcional: un dominio en Cloudflare para exposición pública y una tailnet de Tailscale
  para exposición privada.

**Instala**, desde una sesión SSH en el servidor:

```bash
( set -e; if ! command -v curl >/dev/null; then sudo apt-get update; sudo apt-get install -y curl ca-certificates; fi; revision=main; script=$(mktemp); trap 'rm -f "$script"' EXIT; curl --fail --show-error --location "https://raw.githubusercontent.com/kaanbal-softwarefactory/software-factory/${revision}/install.sh" --output "$script"; bash "$script" --ref "$revision" --lan )
```

El comando descarga el script completo antes de ejecutarlo e imprime una URL temporal
como `http://192.168.1.50:3000/?token=…`. Ábrela en el navegador de un equipo de la misma
red, crea el administrador e introduce tus credenciales de proveedores en el asistente,
nunca en un chat ni en un archivo. Al confirmar el acceso final, el instalador revoca su
token y se apaga solo.

- Usa `--tailscale` en lugar de `--lan` si el servidor ya está en tu tailnet, o
  `--ssh-tunnel` si la red local no es de confianza.
- Sustituye `main` por un SHA o una etiqueta para repetir exactamente el mismo código.
  `main` se mueve.
- Para instalar desde un fork o un espejo: `KAANBAL_REPO=https://github.com/<tú>/<fork>.git bash install.sh …`
- `--reset` elimina una instalación anterior de Kaanbal en esa máquina, con sus datos y
  credenciales. Úsalo solo para repetir instalaciones de prueba limpias.

El recorrido completo —claves SSH, túnel, proveedores, recuperación de Vault y reinicio—
está en la [guía de instalación](docs/guides/INSTALL_UBUNTU.md).

## Documentación

| | |
|---|---|
| [Guía de instalación](docs/guides/INSTALL_UBUNTU.md) | Ubuntu, SSH, proveedores, Vault, reinicio |
| [Migración desde el repositorio anterior](docs/guides/MIGRATION.md) | Para instalaciones anteriores a v1.0.0 |
| [Arquitectura](docs/architecture/KAANBAL_LOCAL_V0.md) · [Blueprint](SOFTWARE_FACTORY/BLUEPRINT.md) · [GitOps](SOFTWARE_FACTORY/infra-gitops/ARCHITECTURE.md) | Cómo encajan las piezas |
| [Decisiones de arquitectura](docs/adr/) | Por qué las actualizaciones del core funcionan así |
| [Especificación de plantillas](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) | Cómo escribir una plantilla |
| [Servidor MCP](SOFTWARE_FACTORY/kaanbal-mcp/README.md) | Conecta un agente de IA a tu plataforma |

Consulta el [README en inglés](README.md) para el diagrama de arquitectura, la estructura
del repositorio y los comandos de desarrollo.

## Estado y limitaciones conocidas

v1.0.0 es la primera versión pública de una plataforma que sus mantenedores operan ellos
mismos. No es un producto empresarial endurecido: léelo antes de depender de ella.

- No se ha validado de punta a punta una instalación completa en Ubuntu 26.04, y las
  versiones de K3s, Argo CD y Tailscale que descarga el instalador no están fijadas.
- Vault se desbloquea a mano tras un reinicio; no hay auto-unseal. El instalador guarda
  el material de recuperación en el servidor y tú debes respaldarlo en otro lugar.
- La API se inicializa con un token raíz de Vault. Sustituirlo por una credencial de
  alcance limitado y renovable está pendiente.
- Hoy Docker Hub es obligatorio; aún no existe un builder local con registro alternativo.
- No ha habido una revisión de seguridad independiente. Reporta vulnerabilidades en
  privado como se describe en [SECURITY.md](SECURITY.md).

## Licencia

Kaanbal se distribuye bajo la [licencia Apache 2.0](LICENSE). Consulta [NOTICE](NOTICE).
