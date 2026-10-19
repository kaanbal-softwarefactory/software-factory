# placeholder-app — contrato para agentes

Esta aplicación fue creada por Kaanbal. Es un proyecto Next.js 16 con App
Router: las páginas y la API viven juntas.

## Reglas

- Nunca escribas secretos ni los dejes en `.env`; Kaanbal inyecta la conexión de
  la base desde Vault al vincularla.
- Mantén `GET /api/health` y el puerto `3000`: Kubernetes los usa para saber si
  la aplicación está viva. La salud no debe consultar la base.
- La detección de base vive en `lib/notes.ts` y se basa en los nombres
  convencionales de cada motor. Si agregas un motor, agrégalo ahí, no en las
  páginas.
- `output: "standalone"` en `next.config.ts` es lo que hace pequeña la imagen:
  si agregas una dependencia que se carga en tiempo de ejecución por `import()`
  dinámico, decláralo en `outputFileTracingIncludes`.
- Componentes de servidor por defecto; `"use client"` solo donde haya estado o
  eventos.

## Desarrollo

```bash
npm install
npm run dev
npm run build
```
