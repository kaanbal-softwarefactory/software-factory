# Kaanbal Template Spec v1 — contrato de templates (comunidad)

> El template es la unidad de contribución de la comunidad. Este contrato define
> qué debe declarar un template para ser aceptado en un catálogo Kaanbal.
> El ciclo de validación ya existe en la plataforma (`CustomTemplate`:
> draft → validating → ready, con test-apps efímeras por ambiente).

## Estructura mínima

```
templates/<category>/<template-id>/
├── template.json        # este contrato
├── Dockerfile.tpl       # opcional si la imagen es oficial (ej: n8n, emqx)
├── pipeline.yml.tpl     # CI para construir la imagen (si aplica)
└── src/                 # scaffold de código (creation_mode: scaffold)
```

## template.json

```jsonc
{
  "id": "fastapi-api",                  // slug único en el catálogo
  "name": "FastAPI",
  "description": "Python FastAPI backend",
  "category": "backend",                // frontend|backend|database|automation|iot|mlops|monitoring
  "stack": ["python", "fastapi"],
  "environments": ["dev", "staging", "prod"],
  "creation_modes": ["scaffold", "empty", "upload", "config-only"],

  // --- Puertos: la base de la matriz de vinculación ---
  "ports": [
    { "name": "http", "port": 8000, "protocol": "TCP", "description": "API REST" }
    // multi-puerto (ej. EMQX): mqtt/1883, dashboard/18083, ws/8083...
  ],
  "default_exposure": "private",        // public|vpn|private|app-scoped

  // --- Qué VARIABLES espera recibir vía ServiceLinks (consumidor) ---
  // La consola las ofrece al vincular; el deployer las inyecta {ALIAS}_*
  "consumes": [
    { "kind": "database", "optional": true },
    { "kind": "mqtt", "optional": true },
    { "kind": "s3", "optional": true }
  ],

  // --- Recursos y salud ---
  "resources_preset": "small",          // minimal|small|medium|large
  "health_check_path": "/health",
  "storage": { "required": false, "default_class": "local-path" },

  // --- Validación automática (pipeline de aceptación) ---
  "validation": {
    "smoke_path": "/health",            // 200 = healthy
    "environments": ["dev"]             // dónde se prueba el test-app efímero
  }
}
```

## Reglas de aceptación

1. `id` único, slug DNS-safe (el nombre de app deriva subdominios).
2. Todo puerto expuesto DEBE estar declarado en `ports` — sin puertos implícitos:
   la matriz de vinculación y las NetworkPolicies se generan de aquí.
3. Sin secretos en el template: credenciales llegan por ServiceLinks/Vault.
4. La imagen base debe ser multi-arch (amd64 + arm64) o declarar
   `"arch": ["amd64"]` — los sites edge son ARM.
5. Debe pasar el ciclo `draft → validating → ready` (test-app efímera healthy).

## Catálogos federados (v2)

Un catálogo es un repo Git con `catalog.json` (índice de templates). La
instalación agrega catálogos por URL; el oficial es solo el primero.
