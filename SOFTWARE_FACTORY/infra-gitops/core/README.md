# Kaanbal Engine - Core

## 🎯 What is this?

This is the **portable core** of Kaanbal Engine. Give it to anyone and they can deploy their own instance with:

```bash
cd infra-gitops/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your credentials
terraform init && terraform apply
```

## 📁 Structure

```
infra-gitops/
├── apps/                    # Deployed applications (auto-discovered by ArgoCD)
│   ├── automation/          # n8n - Workflow automation
│   ├── broker/              # EMQX - MQTT broker
│   ├── datastore/           # MongoDB - Shared database
│   ├── kaanbal-api/           # Platform API (the brain)
│   ├── kaanbal-console/       # Platform UI (the face)
│   ├── tailscale-operator/  # Private network access
│   └── vault/               # Secrets management
│
├── argocd/                  # ArgoCD configuration
│   ├── bootstrap/           # Initial setup (App of Apps)
│   └── applicationsets/     # Auto-discovery rules
│
├── core/                    # System configuration
│   ├── config/              # ConfigMaps (editable via UI)
│   ├── schemas/             # JSON schemas for API
│   └── examples/            # Example payloads
│
└── terraform/               # Infrastructure as Code
    ├── main.tf              # AWS resources
    ├── variables.tf         # Input variables
    └── terraform.tfvars     # YOUR CREDENTIALS (git-ignored)
```

## 🔧 Required Credentials (terraform.tfvars)

```hcl
# AWS
aws_region     = "us-east-2"
key_name       = "your-ssh-key"
key_path       = "~/.ssh/your-key.pem"

# Bitbucket (for GitOps)
bitbucket_username = "YourUsername"
bitbucket_token    = "your-app-password"

# Domain
domain = "yourdomain.com"

# Tailscale (optional but recommended)
tailscale_auth_key = "tskey-auth-xxxxx"
```

## 🌐 After Deployment

| Service | URL | Access |
|---------|-----|--------|
| ArgoCD | `cd.yourdomain.com` | Public |
| kaanbal-console | `kaanbal-console.yourdomain.com` | Public |
| kaanbal-api | `kaanbal-api.yourdomain.com` | Public |
| automation (n8n) | `automation.tailnet.ts.net` | Tailscale |
| automation webhooks | `automation.yourdomain.com/webhook/*` | Public |

## 🚀 Creating Apps

### Via n8n (recommended)
1. Access n8n via Tailscale
2. Create HTTP Request node pointing to `http://kaanbal-api:8000/api/v1/apps`
3. Use payload from `core/examples/create-*.json`

### Via API
```bash
curl -X POST http://kaanbal-api:8000/api/v1/apps \
  -H "Content-Type: application/json" \
  -d @core/examples/create-minimal.json
```

### Via kaanbal-console
Coming soon in UI!

## 📋 Payload Examples

### Minimal
```json
{
  "app": {
    "name": "my-app",
    "template": "tpl-vue3-spa-standard"
  },
  "project": {
    "key": "TEST",
    "name": "Test Project"
  }
}
```

### Full (with all options)
See `core/examples/create-vue3-dashboard.json`

## 🔒 Exposure Types

| Type | Where | Use Case |
|------|-------|----------|
| `public` | `app.yourdomain.com` | Customer-facing apps |
| `private` | `app.tailnet.ts.net` | Internal tools, admin panels |
| `internal` | Cluster only | Databases, internal APIs |
| Mixed | Both with path rules | APIs with public webhooks, private admin |

## 🔗 Internal Service DNS

All apps can communicate internally:

```
datastore.default.svc.cluster.local:27017    # MongoDB
broker.default.svc.cluster.local:1883        # MQTT
automation.default.svc.cluster.local:5678    # n8n
kaanbal-api.default.svc.cluster.local:8000     # Platform API
vault.vault.svc.cluster.local:8200           # Secrets
```
