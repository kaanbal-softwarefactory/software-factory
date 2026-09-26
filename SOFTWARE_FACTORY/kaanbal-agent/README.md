# Kaanbal Agent

Command-center UI for the platform-wide agent (**Acuaponsito**).

> **Status: prototype.** The interface is currently driven by sample data
> (`src/data/commandCenter.js`) and is not wired to a live agent yet. The agent runtime itself
> lives in [`../acuaponsito`](../acuaponsito).

Built with [Vue 3](https://vuejs.org/) + [Vite](https://vitejs.dev/) + [Tailwind CSS](https://tailwindcss.com/).

## Local development

```bash
cd SOFTWARE_FACTORY/kaanbal-agent
npm install
npm run dev
```

Requires `kaanbal-api` running on port 8000 (or configure the URL in `.env.development`).

## Build

```bash
npm run build
# Output in dist/
```

## CI/CD

Pushes to `main` of the standalone `kaanbal-agent` repository trigger GitHub Actions →
Docker Hub → Argo CD auto-sync.

## License

[Apache 2.0](../../LICENSE)
