#!/usr/bin/env bash
# Wipe TOTAL de Kaanbal en esta máquina Ubuntu (conserva installer.env para reinstall).
# ANTES de tumbar k3s: limpia devices Tailscale tag:k8s* (no dejar sucio el admin MagicDNS).
set -euo pipefail

log() { printf '\033[1;36m[kaanbal-wipe]\033[0m %s\n' "$*"; }
[[ "${EUID}" -eq 0 ]] || { echo "sudo required"; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_BAK="/tmp/kaanbal-installer.env.wipebak"
if [[ -f /etc/kaanbal/installer.env ]]; then
  cp -a /etc/kaanbal/installer.env "$ENV_BAK"
  log "Backup credenciales -> $ENV_BAK"
fi

log "=== 0) Tailscale cloud: borrar devices tag:k8s* (remanentes) ==="
if [[ -f "$ROOT/tools/cleanup-tailscale-orphans.py" && -f /etc/kaanbal/installer.env ]]; then
  python3 "$ROOT/tools/cleanup-tailscale-orphans.py" --apply --wipe-all-tagged --env /etc/kaanbal/installer.env \
    || log "AVISO: cleanup Tailscale falló (sigue el wipe local)"
else
  log "AVISO: no hay cleanup-tailscale-orphans.py o installer.env — limpia a mano en admin Tailscale"
fi

log "=== 1) reset-local oficial ==="
bash "$ROOT/tools/reset-local.sh" --yes --preserve-credentials

log "=== 2) limpieza extra de rastros locales ==="
# servicios / procesos
systemctl disable --now kaanbal-installer 2>/dev/null || true
systemctl disable --now k3s 2>/dev/null || true
pkill -f 'kaanbal' 2>/dev/null || true
pkill -f 'k3s' 2>/dev/null || true
fuser -k 3000/tcp 4600/tcp 8080/tcp 6443/tcp 2>/dev/null || true

# k3s residual
rm -rf /etc/rancher /var/lib/rancher /var/lib/kubelet /etc/cni /opt/cni \
  /var/lib/cni /run/k3s /run/flannel /var/log/containers /var/log/pods \
  /usr/local/bin/k3s /usr/local/bin/kubectl /usr/local/bin/crictl \
  /usr/local/bin/k3s-uninstall.sh /usr/local/bin/k3s-killall.sh 2>/dev/null || true
rm -f /etc/systemd/system/k3s*.service /etc/systemd/system/kaanbal*.service 2>/dev/null || true

# estado kaanbal (conservar installer.env)
rm -rf /var/lib/kaanbal-installer /run/kaanbal-installer /var/lib/kaanbal \
  /tmp/kaanbal-* /tmp/kb-* /tmp/app-of-apps*.yaml /tmp/n8n-* /tmp/fix-* \
  /tmp/wipe-* /tmp/diag-* /tmp/seed-* /tmp/status-* /tmp/restore-* 2>/dev/null || true
mkdir -p /etc/kaanbal
if [[ -f "$ENV_BAK" ]]; then
  cp -a "$ENV_BAK" /etc/kaanbal/installer.env
  chmod 600 /etc/kaanbal/installer.env
fi

# docker imágenes del engine / lab (si docker existe)
if command -v docker >/dev/null 2>&1; then
  log "Limpiando contenedores/imágenes docker locales relacionadas..."
  docker ps -aq 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' 2>/dev/null \
    | awk '/kaanbal|lab-|acme-dockerhub|n8nio\/n8n|emqx\/emqx|mongo:|postgres:/{print $2}' \
    | sort -u | xargs -r docker rmi -f 2>/dev/null || true
fi

# kube config del usuario alice
for h in /home/alice /root; do
  rm -rf "$h/.kube" "$h/.kaanbal" 2>/dev/null || true
done

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

log "=== 3) verificación (debe estar vacío / ausente) ==="
echo "--- which k3s ---"
command -v k3s || echo "(ausente) OK"
echo "--- systemctl k3s ---"
systemctl is-active k3s 2>&1 || true
echo "--- kaanbal paths ---"
ls -la /etc/kaanbal/ 2>&1 || true
ls /var/lib/kaanbal 2>&1 || echo "(ausente) OK"
ls /var/lib/rancher 2>&1 || echo "(ausente) OK"
echo "--- listening 6443/3000 ---"
ss -lntp 2>/dev/null | grep -E ':6443|:3000|:8080' || echo "(ninguno) OK"

if [[ -f /etc/kaanbal/installer.env ]]; then
  echo "CREDENTIALS_PRESERVED=yes"
else
  echo "CREDENTIALS_PRESERVED=no"
fi
echo "WIPE_UBUNTU_DONE"
