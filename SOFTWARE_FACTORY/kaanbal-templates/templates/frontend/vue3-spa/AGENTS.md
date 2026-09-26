# placeholder-app — cómo trabajar en este repositorio

Frontend creado por **Kaanbal**. Este archivo es el contrato: vale para quien
programa y para cualquier agente (Claude Code, Codex, Cursor) que abra el repo.

## La regla que lo explica todo

**La URL de la API llega por `VITE_API_URL`, nunca escrita en el código.** Vite
resuelve esa variable *al construir*, y hay una por entorno:

| Archivo | Lo usa | Apunta a |
|---|---|---|
| `.env.development` | `npm run dev` | tu API local (`http://localhost:8000`) |
| `.env.production` | `npm run build`, que corre el pipeline | la API que Kaanbal publicó |

Por eso el mismo `App.vue` funciona en tu máquina y en el clúster. Si la
variable está vacía, se asume el mismo origen.

## Desarrollo local

```bash
npm install
npm run dev            # http://localhost:5173
```

Levanta también la API (su repo tiene `docker compose up -d` para la base). Si
el navegador se queja de CORS, agrega `http://localhost:5173` a `CORS_ORIGINS`
en el `.env` de la API.

## De local a producción

```bash
git push origin main
```

El pipeline construye la imagen con `.env.production` dentro y ArgoCD la
despliega. No edites manifiestos de Kubernetes aquí: los gobierna Kaanbal en su
repositorio `infra-gitops`.

Lo que **no** debes hacer en este repo:

- Escribir la URL de la API en el código o inventar rutas nuevas de despliegue.
- Guardar secretos: todo lo que entra en un build de frontend queda visible
  para quien abra la página. Las credenciales viven en la API.
- Cambiar el puerto 80 del contenedor ni `nginx.conf`: el clúster los usa.

## Qué trae la plantilla

`src/App.vue` consulta `/health` de la API y muestra si la base responde, y
guarda y lista elementos contra `/items`. Es el ejemplo mínimo de la cadena
completa (navegador → API → base); bórralo cuando empieces tu pantalla real.
