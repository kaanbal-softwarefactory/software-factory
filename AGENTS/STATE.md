# Estado operativo

Actualizado: 2026-09-27 · Versión: 1.1.0

## Resumen

Primera versión pública. Este repositorio empieza aquí una historia nueva; el proyecto vivía
antes en `ProyectosUniUAEH/software-factory` (ver `docs/guides/MIGRATION.md`).

## En curso

Nada registrado todavía. Anota aquí el trabajo que quede a medias entre sesiones.

## Conocido y pendiente

Las limitaciones de la versión están en el [README](../README.md#status-and-known-limitations).
En resumen:

- Instalación completa en Ubuntu 26.04 sin validar de punta a punta.
- Versiones de K3s, Argo CD y Tailscale sin fijar.
- Vault sin auto-unseal; el token raíz sembrado en la API es la credencial actual.
- Docker Hub obligatorio; sin builder local con registro alternativo.
- Sin `CODE_OF_CONDUCT.md`: falta elegir un canal de contacto.

## Cómo mantener este archivo

Una lista corta, no un diario: lo que la próxima persona debe saber antes de tocar algo.
El detalle de cada sesión va en `sessions/`.
