# Kaanbal — Arquitectura de una instalación local

Instalación reproducible en un Ubuntu Server de un solo nodo.

## Qué incluye

- K3s, Argo CD e ingress
- Kaanbal API y consola
- GitOps (`infra-gitops`)
- Cloudflare Tunnel y Tailscale, según el acceso que elijas
- Vault
- Las aplicaciones que despliegues desde la consola

## Vista simplificada

```text
Personas y agentes → Consola · MCP · las aplicaciones que despliegues
                          ↓
Plano de control de Kaanbal (API, plantillas, GitOps, DNS, secretos, accesos)
                          ↓
K3s + Argo CD + ingress + Cloudflare Tunnel + Tailscale
                          ↓
Cargas de trabajo: tus apps, generadas desde plantillas
```

## Modelo de repositorios

El **monorepo de distribución** (este repositorio) contiene el instalador. Al instalar, el sistema
materializa repositorios separados en la organización o el usuario de GitHub de la instalación:

| Repositorio | Rol |
|---|---|
| `kaanbal-api` | Backend FastAPI |
| `kaanbal-console` | Consola Vue |
| `kaanbal-templates` | Catálogo de plantillas |
| `infra-gitops` | Manifiestos de Kubernetes y Argo CD |
| `{nombre-de-la-app}` | Un repositorio por aplicación desplegada, con su propio CI |

Flujo de una app: `AppDeployer` crea el repositorio → genera el CI → se construye y publica la imagen
en Docker Hub → se parchea el overlay en `infra-gitops` → Argo CD sincroniza.

`infra-gitops/` del monorepo es una **plantilla**: `.kaanbal-baseline` declara qué rutas se publican
en el repositorio de cada instalación y el instalador las renderiza con la configuración real.

## Instalador web

`SOFTWARE_FACTORY/installer/server.py` — solo biblioteca estándar de Python, puerto 3000, protegido
por un token de sesión temporal que se revoca al confirmar el acceso final.

Pasos: sistema → k3s → nodo → argocd → IA → regcred → tailscale → cloudflared → gitops → acceso.

Guía de uso: [Instalar Kaanbal en Ubuntu Server](../guides/INSTALL_UBUNTU.md).
