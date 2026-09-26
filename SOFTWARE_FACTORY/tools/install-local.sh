#!/usr/bin/env bash
# ==============================================================================
# Kaanbal — Instalador perfil LOCAL (WSL2 / Linux)   [BLUEPRINT RFC-0001 §8]
# ==============================================================================
# Convierte esta máquina en una célula Kaanbal completa: k3s + ArgoCD
# reconciliando tu repo infra-gitops, con salida a internet vía Cloudflare
# Tunnel (sin abrir puertos, sin tocar el router).
#
# Uso:
#   GITOPS_REPO_URL=https://github.com/<org>/infra-gitops.git \
#   GITOPS_REPO_TOKEN=<PAT si es privado> \
#   TUNNEL_TOKEN=<token cloudflare, opcional> \
#   bash tools/install-local.sh
#
# Diferencias vs perfil VPS: no provisiona servidor (ya estás dentro), nunca
# asume IP pública (CGNAT), autostart vía systemd de WSL2.
# ==============================================================================
set -euo pipefail

GITOPS_REPO_URL="${GITOPS_REPO_URL:-}"
GITOPS_REPO_TOKEN="${GITOPS_REPO_TOKEN:-}"
TUNNEL_TOKEN="${TUNNEL_TOKEN:-}"
SITE_NAME="${SITE_NAME:-$(hostname | tr '[:upper:]' '[:lower:]')}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"

log()  { echo -e "\033[1;36m[kaanbal]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✔\033[0m $*"; }
warn() { echo -e "\033[1;33m  ⚠\033[0m $*"; }
die()  { echo -e "\033[1;31m  ✖\033[0m $*" >&2; exit 1; }

# ------------------------------------------------------------------ checks ---
log "Verificando requisitos del sistema..."

[[ "$(uname -s)" == "Linux" ]] || die "Este instalador es para Linux/WSL2. En Windows: ejecutar dentro de WSL2."

if grep -qi microsoft /proc/version 2>/dev/null; then
    ok "WSL2 detectado"
    SYSD_STATE="$(systemctl is-system-running 2>/dev/null || true)"
    case "$SYSD_STATE" in
        running|degraded) ok "systemd activo ($SYSD_STATE)" ;;
        *) die "systemd no está activo. Agrega a /etc/wsl.conf:\n[boot]\nsystemd=true\n...y ejecuta 'wsl --shutdown' desde Windows." ;;
    esac
fi

MEM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
CPUS=$(nproc)
DISK_GB=$(df -BG / | awk 'NR==2 {gsub("G","",$4); print $4}')
[[ "$MEM_GB" -ge 4 ]]  || die "RAM insuficiente: ${MEM_GB}GB (mínimo 4GB). En WSL2 ajusta .wslconfig [wsl2] memory=6GB"
[[ "$CPUS" -ge 2 ]]    || die "CPUs insuficientes: ${CPUS} (mínimo 2)"
[[ "$DISK_GB" -ge 15 ]] || warn "Disco justo: ${DISK_GB}GB libres (recomendado 20GB+)"
ok "Recursos: ${MEM_GB}GB RAM, ${CPUS} CPUs, ${DISK_GB}GB disco libre"

command -v curl >/dev/null || die "curl no está instalado: sudo apt-get install -y curl"
command -v git  >/dev/null || die "git no está instalado: sudo apt-get install -y git"

# --------------------------------------------------------------------- k3s ---
if command -v k3s >/dev/null 2>&1 && sudo k3s kubectl get node >/dev/null 2>&1; then
    ok "k3s ya instalado — se omite"
else
    log "Instalando k3s (Kubernetes ligero, el mismo del VPS)..."
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644 --node-name ${SITE_NAME}" sh -
    ok "k3s instalado"
fi

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
KUBECTL="k3s kubectl"

log "Esperando a que el nodo esté Ready..."
for i in $(seq 1 60); do
    if $KUBECTL get node 2>/dev/null | grep -q " Ready"; then ok "Nodo Ready"; break; fi
    [[ $i -eq 60 ]] && die "El nodo no llegó a Ready en 5 minutos. Revisa: sudo journalctl -u k3s"
    sleep 5
done

# ------------------------------------------------------------------ ArgoCD ---
if $KUBECTL get namespace argocd >/dev/null 2>&1; then
    ok "ArgoCD ya presente — se omite instalación"
else
    log "Instalando ArgoCD (GitOps controller)..."
    $KUBECTL create namespace argocd
    # --server-side: el CRD de ApplicationSets excede el límite de 262KB de la
    # anotación last-applied-configuration con apply clásico (visto en WSL2/k3s 1.36)
    $KUBECTL apply --server-side -n argocd -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
fi

log "Esperando a argocd-server..."
$KUBECTL -n argocd rollout status deployment/argocd-server --timeout=300s || die "argocd-server no arrancó. Revisa: k3s kubectl -n argocd get pods"
ok "ArgoCD listo"

# ------------------------------------------------- repo GitOps + bootstrap ---
if [[ -n "$GITOPS_REPO_URL" ]]; then
    if [[ -n "$GITOPS_REPO_TOKEN" ]]; then
        log "Registrando credenciales del repo GitOps en ArgoCD..."
        $KUBECTL -n argocd apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: kaanbal-infra-gitops-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: ${GITOPS_REPO_URL}
  username: kaanbal
  password: ${GITOPS_REPO_TOKEN}
EOF
        ok "Credenciales de repo registradas"
    fi

    log "Aplicando bootstrap app-of-apps (la célula reconcilia el repo)..."
    TMP_DIR=$(mktemp -d)
    CLONE_URL="$GITOPS_REPO_URL"
    [[ -n "$GITOPS_REPO_TOKEN" ]] && CLONE_URL="${GITOPS_REPO_URL/https:\/\//https://kaanbal:${GITOPS_REPO_TOKEN}@}"
    git clone --depth 1 "$CLONE_URL" "$TMP_DIR/infra-gitops" 2>/dev/null || die "No se pudo clonar $GITOPS_REPO_URL (¿token correcto?)"
    if [[ -f "$TMP_DIR/infra-gitops/argocd/bootstrap/app-of-apps.yaml" ]]; then
        $KUBECTL apply -f "$TMP_DIR/infra-gitops/argocd/bootstrap/app-of-apps.yaml"
        ok "app-of-apps aplicado — ArgoCD desplegará la plataforma completa"
    else
        warn "No existe argocd/bootstrap/app-of-apps.yaml en el repo; aplica tus Applications manualmente"
    fi
    rm -rf "$TMP_DIR"
else
    warn "GITOPS_REPO_URL no definido — célula instalada sin bootstrap (puedes aplicarlo después)"
fi

# ------------------------------------------------------- Cloudflare Tunnel ---
if [[ -n "$TUNNEL_TOKEN" ]]; then
    log "Configurando secret del Cloudflare Tunnel (tier público)..."
    $KUBECTL get namespace prod >/dev/null 2>&1 || $KUBECTL create namespace prod
    $KUBECTL -n prod create secret generic cloudflared-secrets \
        --from-literal=TUNNEL_TOKEN="$TUNNEL_TOKEN" \
        --dry-run=client -o yaml | $KUBECTL apply -f -
    ok "Secret cloudflared-secrets creado — ArgoCD desplegará apps/cloudflared y esta PC servirá tu dominio a internet"
else
    warn "TUNNEL_TOKEN no definido — sin tier público por ahora (VPN/local siguen disponibles)"
    warn "Genera el túnel desde la consola Kaanbal (setup → Cloudflare) y re-ejecuta con TUNNEL_TOKEN=..."
fi

# ----------------------------------------------------------------- resumen ---
ARGO_PWD=$($KUBECTL -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo "<ya rotado>")
echo ""
log "🎉 Célula Kaanbal '${SITE_NAME}' instalada"
echo ""
echo "  ArgoCD UI :  k3s kubectl -n argocd port-forward svc/argocd-server 8080:443"
echo "               → https://localhost:8080  (admin / ${ARGO_PWD})"
echo "  Nodo      :  $($KUBECTL get node --no-headers | awk '{print $1" "$2}')"
echo "  Kubeconfig:  /etc/rancher/k3s/k3s.yaml"
echo ""
echo "  Siguientes pasos:"
echo "   1. Registrar este site en el cerebro:  POST /api/v1/sites  {\"name\": \"${SITE_NAME}\", \"type\": \"local\"}"
echo "   2. Autostart WSL2: agregar a /etc/wsl.conf → [boot] command = \"systemctl start k3s\""
echo "   3. Ver apps sincronizando:  k3s kubectl -n argocd get applications"
