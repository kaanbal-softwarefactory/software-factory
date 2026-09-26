# Kaanbal — Blueprint de Plataforma Unificada (v1)

> DevOps + MLOps + IoT Fleet en un solo plano de control, self-hosted, open source.
>
> Estado: diseño aprobado en conversación 2026-07-02. Este documento es la fuente de
> verdad de diseño; sustituye a los briefs dispersos de la conversación.

---

## 1. Tesis — por qué esto importa en el mercado

Nadie cubre este triángulo en una sola caja open source y opinada:

| Herramienta | PaaS apps | MLOps | IoT fleet | Multi-sitio (nube+local+edge) |
|---|---|---|---|---|
| Coolify / CapRover | ✅ | ❌ | ❌ | ❌ (single-node Docker) |
| Portainer / Rancher | gestión, no ciclo de vida | ❌ | parcial (Fleet) | ✅ pero enterprise-complex |
| Kubeflow / MLflow solos | ❌ | ✅ | ❌ | ❌ |
| Balena / Mender | ❌ | ❌ | ✅ | ❌ (solo edge) |
| **Kaanbal** | ✅ | ✅ | ✅ | ✅ |

**El usuario objetivo no es un SRE.** Es una científica que ya sabe desarrollar con
agentes de IA (front, backend, BD) y quiere ir integrando MQTT, automatización (n8n)
y modelos de ML **sin fricción de infraestructura**. La propuesta de valor en una
frase: *"de la idea al edge: lanzas tu app, entrenas tu modelo, lo sirves en la nube
o en el dispositivo del cliente — desde una sola consola, en tu propio hardware."*

Filosofía existente que se mantiene intacta (ver `infra-gitops/ARCHITECTURE.md`):
GitOps first, API first, portable (un comando = plataforma completa), extensible
(templates para cualquier tecnología).

---

## 2. El insight unificador: **Site**

La conversación partió de 4 primitivos (Domain, Connection Matrix, Node Registry,
Lifecycle). El análisis del código revela que dos de ellos colapsan en uno:

> **El registro de workers y el registro de gateways IoT son la misma tabla.**

Un VPS en Contabo, tu PC con WSL2, una EC2 con GPU efímera y la Raspberry Pi de un
cliente son todos **Sites**: unidades de cómputo con identidad propia, capacidades
etiquetadas y un agente que reconcilia estado deseado desde Git/MQTT.

```python
class SiteType(str, Enum):
    CLOUD = "cloud"        # VPS, EC2 — corre k3s completo
    LOCAL = "local"        # PC/laptop del usuario — k3s en WSL2/Linux
    EDGE = "edge"          # Pi de cliente — k3s (Pi 4/5) o agente ligero (placas menores)
    EPHEMERAL = "ephemeral" # GPU cloud creada por Terraform, se destruye al terminar

class Site(BaseModel):
    id: str
    name: str                      # "vps-contabo-1", "pc-alice", "gw-cliente-acme-01"
    type: SiteType
    client_id: Optional[str]       # None = sitio de plataforma; set = edge de un tenant
    labels: Dict[str, str]         # {"gpu": "true", "region": "mx", "arch": "arm64"}
    connectivity: str              # "tailscale" | "public-ip"
    agent: str                     # "k3s+argocd" | "k3s+fleet" | "gateway-agent"
    status: str                    # online | offline | joining | draining
    resources: Dict[str, Any]      # cpu, mem, disk reportados por heartbeat
    joined_at: datetime
```

Consecuencias directas:

- **Fase 2 (worker local) y Fase 3 (fleet IoT) se vuelven el mismo desarrollo.**
- La UI de "mis workers" y la de "gateways de mis clientes" es la misma vista
  filtrada por `type` y `client_id`.
- El flujo de GPU efímera (fase 5) es solo un Site con `type=ephemeral` y un
  ciclo de vida automatizado (crear → join → entrenar → drain → destruir).
- `Client` (ya existe en `models.py`) gana la relación natural: un cliente *posee*
  sites edge, y las apps se despliegan "al site del cliente" igual que a un VPS.

---

## 3. Modelo de datos v1 (extiende `kaanbal-api/app/models.py`)

### 3.1 Domain — de config global a entidad

Hoy: `domain` es un string único en `system_config` (Mongo) y en
`core/config/system-config.yaml`. Cambio:

```python
class Domain(BaseModel):
    id: str
    fqdn: str                      # "example.com", "cliente-acme.com"
    cloudflare_zone_id: str
    tunnel_id: Optional[str]       # cada dominio puede tener su propio túnel o compartir
    is_default: bool = False
    client_id: Optional[str]       # dominios dedicados por cliente (white-label)
```

- `App` gana `domain_id: Optional[str]` (None → dominio default). Migración: el
  dominio actual del instalador se convierte en el `Domain` default — cero breaking.
- La consola agrupa apps por dominio → esto ES la vista de "apps agrupadas" pedida.
- El wizard de setup no cambia: sigue pidiendo un dominio, solo que ahora crea la
  primera fila de una tabla en vez de fijar una constante.

### 3.2 ServiceLink — la matriz de vinculación (generaliza `database_bindings`)

El código ya tiene el patrón correcto en miniatura: `database_bindings` vincula
backend→BD por ambiente e inyecta variables Vault (`{ALIAS}_URI`, `{ALIAS}_HOST`,
ver `FLOW_CONTRACT.md`). Se generaliza a cualquier par de apps:

```python
class LinkVisibility(str, Enum):
    PUBLIC = "public"          # expuesto a internet (vía cloudflared)
    VPN = "vpn"                # tailnet (tailscale operator, ya integrado)
    PRIVATE = "private"        # solo cluster (NetworkPolicy default-deny)
    APP_SCOPED = "app-scoped"  # solo las apps explícitamente vinculadas

class ServiceLink(BaseModel):
    id: str
    from_app: str; from_env: str       # consumidor
    to_app: str;   to_env: str         # proveedor
    port_name: str                     # referencia a PortDefinition existente ("mqtt", "http")
    alias: str                         # prefijo de variables inyectadas: {ALIAS}_HOST, etc.
    visibility: LinkVisibility = LinkVisibility.APP_SCOPED
```

**Una tabla, cinco artefactos generados** (este es el multiplicador de valor):

1. **NetworkPolicies** k8s — default-deny por namespace; cada link `app-scoped`
   genera el allow puntual. Seguridad real sin que el usuario escriba YAML.
2. **Variables de entorno vía Vault** — mismo mecanismo que database_bindings hoy.
3. **ACLs de EMQX** — un link hacia el puerto `mqtt` de EMQX genera la regla de
   qué app/gateway puede publicar/suscribir a qué tópicos.
4. **ACLs de Tailscale** — ya hay automatización de tags en `terraform/tailscale.tf`;
   los links `vpn` alimentan esa misma API.
5. **El diagrama de arquitectura** — la consola dibuja apps agrupadas por dominio,
   nodos por site, aristas por ServiceLink, y los bordes a Internet/VPN según
   visibilidad. No es un feature aparte: es un `SELECT` renderizado (vis.js/mermaid).

`database_bindings` queda como azúcar de UI que crea ServiceLinks con
`port_name="db"` — el código existente migra, no se tira.

### 3.3 Placement — dónde corre cada ambiente

```python
class EnvironmentPlacement(BaseModel):
    env: str                       # dev | staging | prod
    site_id: str                   # explícito en v1 (sin auto-scheduling)
    storage_class: str = "local-path"   # local-path | longhorn | (futuro: provider)
```

`App.placements: List[EnvironmentPlacement]`. Dev en el VPS barato, prod en el site
con GPU: un dropdown por ambiente. El auto-scheduling por capacidad/costo es v2 y
será aditivo (un `site_id="auto"` + scorer), no una reescritura.

### 3.4 Storage por app

Mismo patrón UX que la exposición de puertos — un dropdown, tres opciones v1:

| Opción | Backend | Caso |
|---|---|---|
| Rápido local | `local-path` (k3s built-in) | dev, caches |
| Replicado | Longhorn (snapshots → MinIO) | BDs en prod |
| Objeto S3 | MinIO (plataforma) o bucket propio | datos de modelos, media, backups |

MinIO es infraestructura core (como Vault): un tenant/bucket por app que lo pida.
Retención y tiering = lifecycle rules nativas de MinIO expuestas en la consola.
Con claves AWS en Vault, la misma plantilla provisiona S3 real — mismo contrato.

---

## 4. Topología: células federadas por Git (multi-master sin quorum frágil)

Regla de oro acordada: **nunca estirar etcd entre sitios por WAN.**

- Cada Site tipo `cloud`/`local` = **célula**: k3s completo + ArgoCD propio, todos
  reconciliando **el mismo repo `infra-gitops`**. La estructura actual ya lo permite:
  basta un directorio `sites/<site-id>/` (o labels de ApplicationSet) para que cada
  célula tome solo lo suyo.
- **El "cerebro" (kaanbal-api + console + Mongo) es solo otra app** que corre en la
  célula primaria. Espejo = célula secundaria con réplica de Mongo (replica set
  cross-site sobre Tailscale, prioridad 0 → no vota, solo replica). Si muere la
  primaria: promover réplica + mover DNS del túnel. RPO minutos, RTO minutos,
  cero componentes exóticos.
- Los despliegues NUNCA dependen del cerebro para seguir vivos: si kaanbal-api cae,
  ArgoCD de cada célula sigue reconciliando Git. El cerebro solo escribe commits.
- Sites `edge` no corren ArgoCD completo: Rancher Fleet (Pi con k3s) o
  `gateway-agent` (placas menores) reconcilian por pull vía MQTT
  (`gw/{id}/desired-state` / `gw/{id}/status`), mismo principio, peso mínimo.

---

## 5. Red: tres tiers, dos túneles, cero puertos abiertos

| Tier | Mecanismo | Estado en el código |
|---|---|---|
| `public` | Cloudflare Tunnel | Control plane ✅ (`setup.py:/tunnel` crea túnel+ingress+DNS). **Data plane ❌: falta el Deployment de `cloudflared`** |
| `vpn` | Tailscale Operator | ✅ integrado (operator + terraform ACL) |
| `private`/`app-scoped` | NetworkPolicies desde ServiceLinks | ❌ nuevo en v1 |

**Gap #1 a cerrar (desbloquea VPS y local por igual):** manifiesto
`infra-gitops/apps/cloudflared/` — Deployment (2 réplicas, imagen
`cloudflare/cloudflared`, `tunnel run --token $TUNNEL_TOKEN`), token desde
Secret/Vault. El ingress del túnel ya apunta a `*.{dominio}` → wildcard al
ingress-controller: toda app nueva es públicamente alcanzable sin tocar el túnel.

**Esto hace que una PC doméstica sirva a internet igual que un VPS**: cloudflared
solo abre conexiones salientes (QUIC 7844), funciona detrás de CGNAT/router casero
sin port-forwarding. La instalación local tiene la MISMA UX de dominio que la nube.

---

## 6. MLOps: el mismo ciclo de vida, aplicado a modelos

Stack elegido (decidido, no abierto): **Argo Workflows + MLflow + MinIO**, empacado
como un template compuesto `mlops-stack` (igual que EMQX es hoy un template).
Airflow queda como template alternativo para quien lo prefiera. Spark: template
opcional cuando haya volumen real que lo justifique — no en v1.

```
Recolectar → Limpiar → Entrenar (N configs paralelas) → Evaluar → Registrar
   └────────────── Argo Workflow (cada paso = pod) ──────────────┘
                                                          │
                              MLflow Model Registry (staging → production)
                                                          │ webhook
                              kaanbal-api despliega template "ml-inference"
                              (FastAPI + ONNX, modelo desde MinIO s3://models/...)
```

- **Cero conceptos nuevos para el usuario**: un modelo en producción ES una app
  Kaanbal — con placements, ServiceLinks, visibilidad y dominio como cualquier
  backend. El frontend de la científica, su ESP32 vía EMQX o un n8n la consumen
  igual que a cualquier API.
- **Selección de recursos al entrenar**: el Workflow declara `nodeSelector` por
  labels de Site (`gpu=true`). Con la tabla Site poblada, "elegir capacidad" es un
  dropdown que lee sites disponibles.
- **GPU efímera (fase 5)**: workflow con tres pasos de sistema — Terraform crea
  instancia (Site `ephemeral`, auto-join k3s vía token) → corre el entrenamiento →
  `exit handler` SIEMPRE destruye (éxito o fallo). El costo muere con el job.
- **IDE**: no construir uno. Template `jupyterlab` (imagen oficial + PVC + tier
  `vpn` por default) con credenciales MLflow/MinIO pre-inyectadas vía ServiceLink.
  Un notebook que ya puede loggear a MLflow al abrirse: eso es "IDE integrado" real
  con esfuerzo de un template.
- Caso piloto: el proyecto Shop (datos ya organizados + gráficas) — primer pipeline
  real de la plataforma: sus datos → features → modelo → inferencia consumida por
  su propio frontend.

---

## 7. IoT fleet (Site edge, multi-tenant)

Ya diseñado en conversación; se consolida aquí:

- Gateway = Site con `client_id` (tenant-scoped), identidad propia (clave Tailscale
  o mTLS por dispositivo — nunca credenciales compartidas entre clientes).
- **Pull, no push**: el gateway reconcilia `desired-state` publicado por el cerebro
  (catálogo de apps del cliente, versión de dashboard, config). Resiliente a
  conectividad intermitente por diseño.
- Rollout por fleet (grupo de sites de un cliente) con canario: primero un gateway,
  telemetría OK → el resto. Mismo espíritu dev→staging→prod.
- Pi 4/5: evaluar k3s + Rancher Fleet (reconciliación/rollout gratis). Placas
  menores: `gateway-agent` (el PoC `D:\dev\iot-edge-gateway` ya implementa
  heartbeat+comandos; le falta desired-state y auth por dispositivo).
- Kiosco: app más del catálogo (imagen Chromium fullscreen apuntando al dashboard
  del cliente) — se gestiona y actualiza como cualquier otra app del fleet.
- ESP32: sin cambios — MQTT al Mosquitto local del gateway, nunca directo a internet.

---

## 8. v1 en tu PC (WSL2) — veredicto y plan

**Veredicto: SÍ es instalable. Hardware y OS verificados hoy (2026-07-02):**

| Check | Resultado | Requisito |
|---|---|---|
| WSL2 Ubuntu | 26.04 LTS ✅ | Ubuntu 22.04+ |
| systemd | habilitado ✅ (crítico: k3s corre como servicio normal) | requerido |
| RAM asignada | 7.7 GiB ✅ | 4 GiB |
| CPUs | 8 ✅ | 2 |
| Docker Desktop | corriendo ✅ (no estorba: k3s usa containerd propio) | — |

Estandarizar a Linux es correcto: WSL2 ES Ubuntu — el mismo `install.sh` del VPS
aplica, con un **perfil `local`** que ajusta lo que no aplica en laptop:

| Paso del instalador | Perfil `vps` | Perfil `local` |
|---|---|---|
| Provisionar servidor (Terraform/SSH) | ✅ | ⏭️ skip (ya estás dentro) |
| k3s + ArgoCD + Mongo + api + console | ✅ | ✅ idéntico |
| Exposición pública | túnel CF | túnel CF **idéntico** (por eso el gap #1 es primero) |
| IP pública / DNS directo | opcional | nunca (CGNAT) |
| Autostart | systemd boot | `wsl.conf` [boot] command o tarea programada |

Nota operativa: el checkout local (`D:\SOFTWARE_FACTORY_SECRETS\SOFTWARE_FACTORY`)
no incluye `softwarefactory/install.sh` ni `kaanbal-templates` — clonar de la org
antes del Milestone 1.

### Milestones v1 (cada uno termina en demo verificable, estilo FLOW_CONTRACT)

1. **Túnel completo + install local** — manifiesto `cloudflared` en infra-gitops;
   `install.sh --profile local` en WSL2; demo: `https://kaanbal-console.<dominio-pruebas>`
   servido DESDE TU PC. *(Cierra el gap del data plane también para el VPS.)*
2. **Domain + ServiceLink + diagrama** — entidades §3.1/§3.2, NetworkPolicies
   generadas, vista de diagrama en consola; demo: dos apps vinculadas app-scoped,
   una tercera NO puede alcanzarlas, el diagrama lo muestra.
3. **Site registry + join** — tabla Site, flujo "agregar site" (token k3s + registro
   en API), tu PC aparece como site del cerebro VPS; demo: app con dev→VPS y
   prod→PC local desde la consola.
4. **Fleet edge mínimo** — PoC iot-edge-gateway registrado como Site edge de un
   cliente demo, desired-state por MQTT; demo: cambiar el catálogo del cliente en
   consola → el gateway lo aplica solo.
5. **MLOps stack** — template `mlops-stack` (Argo WF + MLflow + MinIO) + template
   `ml-inference` + template `jupyterlab`; demo: pipeline con datos tipo Shop,
   promover en MLflow → endpoint de inferencia vivo consumido desde un frontend.

Regla de alcance v1: **NO** auto-scheduling, **NO** Spark, **NO** IDE propio,
**NO** Karmada/federación formal, **NO** marketplace — todo eso es v2 y el modelo
de datos ya deja el espacio.

---

## 9. Open source y comunidad

- Licencia Apache 2.0 ya definida ✅. Monorepo público cuando Milestone 1-2 estén
  estables (que el primer `git clone` de un externo funcione a la primera).
- **El template es la unidad de contribución comunitaria.** `CustomTemplate` ya
  tiene ciclo de validación (draft → validating → ready) con test-apps efímeras:
  eso ES el pipeline de aceptación de un template comunitario. Formalizar el
  contrato (spec JSON: puertos, env-schema, health, pipeline, dockerfile) en
  `kaanbal-templates/SPEC.md` y el catálogo se vuelve un índice federado — v2:
  "agregar catálogo por URL de repo Git".
- Decisiones grandes como ADRs en `docs/adr/` (este blueprint es el RFC-0001).
- English-first en docs públicas (alcance global); consola bilingüe.
- North star público: *"Una científica digitaliza su experimento — apps, datos,
  modelos e inferencia en el edge — sin escribir un solo YAML."*

## 10. Estado de implementación (2026-07-02)

Primer incremento v1 construido y validado (tests en verde):

| Pieza | Archivo(s) | Estado |
|---|---|---|
| Modelos: Domain, ServiceLink, Site, EnvironmentPlacement | `kaanbal-api/app/models.py` | ✅ + App/AppCreate extendidos (no-breaking) |
| Generador: NetworkPolicies + {ALIAS}_* + diagrama | `kaanbal-api/app/services/link_service.py` | ✅ puro, 6 tests |
| Router multi-dominio (con auto-seed desde system_config) | `kaanbal-api/app/routers/domains.py` | ✅ |
| Router matriz de vinculación + /diagram + /manifests | `kaanbal-api/app/routers/links.py` | ✅ |
| Router sites (registro unificado + heartbeat + desired-state) | `kaanbal-api/app/routers/sites.py` | ✅ publica retained vía EMQX REST si está configurado |
| cloudflared data plane (gap #1) | `infra-gitops/apps/cloudflared/` | ✅ manifiestos; falta crear el Secret en el cluster |
| Instalador perfil local WSL2 | `tools/install-local.sh` | ✅ sintaxis validada; pendiente ejecución end-to-end |
| Edge pull-reconciliation | `iot-edge-gateway/` (agent v0.2.0 + bridge + compose) | ✅ desired-state retenido, status, last-will |
| Tests del generador | `kaanbal-api/tests/test_link_service.py` | ✅ 6/6 PASS |

**Siguiente cableado (en orden):**
1. Deployer consume `GET /links/env-literals/{app}/{env}` al generar secretGenerator (junto a database_bindings) y escribe `netpol-<app>.yaml` de `GET /links/manifests/{env}` en los overlays al hacer push a infra-gitops.
2. Setup crea el Secret `cloudflared-secrets` automáticamente tras `POST /setup/tunnel` (vía kubectl del cluster o Vault).
3. Consola: vista de matriz (tabla editable), vista de diagrama (render de `/links/diagram`), vista de sites.
4. Ejecutar `install-local.sh` end-to-end en esta PC (Milestone 1 demo).
5. `apply_desired_state` del gateway-agent: aplicar apps con Docker SDK (hoy ACKea y reporta).

## 11. Registro de decisiones

| # | Decisión | Racional |
|---|---|---|
| D1 | Site unifica worker + gateway + GPU efímera | Una tabla, una UI, tres fases colapsan |
| D2 | Federación por Git, no etcd multi-sitio | Sin quorum WAN frágil; ArgoCD ya lo hace |
| D3 | Cerebro = app ordinaria + Mongo réplica prioridad-0 | HA simple, promoción manual v1 |
| D4 | Argo Workflows default; Airflow como template opt-in | Ya somos familia Argo; menos piezas |
| D5 | MLflow Registry como ciclo de vida de modelos | No reinventar; webhook → deploy |
| D6 | MinIO core + Longhorn opt-in + S3 passthrough | Independencia de nube, contrato único |
| D7 | Placement explícito v1, auto-scheduling v2 | Predecible; el modelo de datos ya lo admite |
| D8 | Cloudflare Tunnel = tier público universal (VPS y local) | Cero puertos, misma UX en laptop |
| D9 | ServiceLink generaliza database_bindings | Reusa Vault-vars + per-port exposure existentes |
| D10 | Linux/WSL2 como estándar v1; Windows nativo no soportado | VPS ya son Ubuntu; WSL2 verificado |
