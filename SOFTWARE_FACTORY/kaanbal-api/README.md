# Kaanbal API

Backend API for **Kaanbal Engine** — the platform's brain.

Built with [FastAPI](https://fastapi.tiangolo.com/) + MongoDB.

## What It Does

- **App lifecycle** — create, deploy, delete apps from templates
- **Template catalog** — browse categories, stacks, templates
- **GitOps integration** — creates GitHub repos, triggers CI/CD, manages ArgoCD manifests
- **DNS automation** — creates Cloudflare CNAME records on deploy
- **Vault secrets** — auto-generates and stores credentials per app/environment
- **System config** — centralized platform settings (domain, git, Docker Hub, Tailscale)

## API Endpoints

### Apps
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/apps` | Create app from template |
| GET | `/api/v1/apps` | List all apps |
| GET | `/api/v1/apps/{name}` | App details |
| DELETE | `/api/v1/apps/{name}` | Delete app (K8s + repo + DNS + Vault cleanup) |

### Templates & Catalog
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/templates` | List templates |
| GET | `/api/v1/templates/catalog/categories` | List categories |
| GET | `/api/v1/templates/catalog/stacks` | List stacks |

### Admin & Config
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/admin/settings` | Get system settings |
| PUT | `/api/v1/admin/settings` | Update system settings |
| GET | `/api/v1/admin/settings-public` | Public settings (no secrets) |
| GET | `/api/v1/health` | Health check |

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/auth/register` | Register (first user = admin) |
| POST | `/api/v1/setup/init` | Setup wizard initialization |

## Local Development

```bash
# Terminal 1: MongoDB tunnel to cluster
ssh -i "<your-key>.pem" -N -L 27017:datastore.prod.svc.cluster.local:27017 ubuntu@<server-ip>

# Terminal 2: Run API
cd nexus-api
pip install -r requirements.txt
MONGODB_URI="mongodb://localhost:27017/forge" python -m uvicorn main:app --reload --port 8000
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MONGODB_URI` | MongoDB connection string |
| `GIT_PROVIDER` | Git provider (`github`) |
| `GIT_USERNAME` | GitHub username |
| `GIT_TOKEN` | GitHub personal access token |
| `DOMAIN` | Platform domain |
| `DOCKERHUB_USERNAME` | Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |

## CI/CD

Pushes to `main` trigger GitHub Actions → Docker Hub → ArgoCD auto-sync.

## License

[Apache 2.0](../../LICENSE)
