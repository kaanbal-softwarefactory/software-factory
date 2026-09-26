# Kaanbal Console

Web dashboard for **Kaanbal Engine** — the platform's UI.

Built with [Vue 3](https://vuejs.org/) + [Vite](https://vitejs.dev/) + [Tailwind CSS](https://tailwindcss.com/).

## Features

- **App management** — deploy, monitor, and delete apps from templates
- **Template catalog** — browse categories (frontend, backend, database, workflow, IoT)
- **Setup wizard** — first-run configuration for admin account and credentials
- **Environment switching** — dev / staging / prod views
- **System settings** — domain, Git, Docker Hub, Tailscale configuration
- **Real-time status** — pod health, ArgoCD sync state, resource usage

## Local Development

```bash
cd SOFTWARE_FACTORY/kaanbal-console
npm install
npm run dev
# → http://localhost:5000
```

Requires `kaanbal-api` running on port 8000 (or configure via `.env.development`).

## Build

```bash
npm run build
# Output in dist/
```

## CI/CD

Pushes to `main` trigger GitHub Actions → Docker Hub → ArgoCD auto-sync.

## License

[Apache 2.0](../../LICENSE)
