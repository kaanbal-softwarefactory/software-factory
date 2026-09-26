#!/usr/bin/env bash
set -Eeuo pipefail

YES=false
PRESERVE=true
SERVICE="kaanbal-installer"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/kaanbal/${STAMP}"

log() { printf '\033[1;36m[kaanbal-reset]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[kaanbal-reset] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --yes) YES=true ;;
    --preserve-credentials) PRESERVE=true ;;
    --wipe-credentials) PRESERVE=false ;;
    -h|--help)
      echo "Uso: sudo tools/reset-local.sh [--yes] [--preserve-credentials|--wipe-credentials]"
      exit 0
      ;;
    *) die "Opción desconocida: $1" ;;
  esac
  shift
done

[[ "${EUID}" -eq 0 ]] || die "Ejecuta con sudo."
[[ "$(uname -s)" == "Linux" ]] || die "Solo Linux."

if ! $YES; then
  echo "Esto eliminará k3s, ArgoCD y servicios Kaanbal LOCALES."
  echo "No tocará GitHub, Cloudflare, Docker Hub ni Tailscale."
  read -r -p "Escribe RESET para continuar: " answer
  [[ "$answer" == "RESET" ]] || die "Cancelado."
fi

install -d -m 700 "$BACKUP"
if $PRESERVE; then
  log "Respaldando credenciales y agente en ${BACKUP}"
  [[ -f /etc/kaanbal/installer.env ]] && cp -a /etc/kaanbal/installer.env "$BACKUP/"
  [[ -d /var/lib/kaanbal/.acuaponsito ]] && cp -a /var/lib/kaanbal/.acuaponsito "$BACKUP/"
else
  log "Modo wipe: también se eliminarán credenciales locales."
fi

systemctl disable --now "$SERVICE" 2>/dev/null || true
systemctl disable --now kaanbal-vault-unseal.timer 2>/dev/null || true
rm -f /etc/systemd/system/kaanbal-vault-unseal.service /etc/systemd/system/kaanbal-vault-unseal.timer
fuser -k 3000/tcp 4600/tcp 8080/tcp 2>/dev/null || true
pkill -f '/installer/server.py' 2>/dev/null || true
pkill -f 'python3 installer/server.py' 2>/dev/null || true
pkill -f '/acuaponsito/server.py' 2>/dev/null || true
pkill -f 'kubectl.*port-forward.*argocd-server' 2>/dev/null || true

if [[ -x /usr/local/bin/k3s-uninstall.sh ]]; then
  log "Desinstalando k3s con el script oficial..."
  /usr/local/bin/k3s-uninstall.sh
elif command -v k3s >/dev/null 2>&1; then
  log "k3s existe pero no hay uninstall script; deteniendo servicio."
  systemctl disable --now k3s 2>/dev/null || true
  rm -rf /etc/rancher/k3s /var/lib/rancher/k3s
fi

# Desinstalar k3s destruye el PVC de Vault. Las claves de recuperación que se
# conserven abrirían datos que ya no existen, y el bootstrap se negaría (con
# razón) a inicializar un Vault nuevo mientras las vea. Se apartan al respaldo
# en vez de borrarse: nunca se descarta material de recuperación.
if $PRESERVE && [[ -f /etc/kaanbal/vault-recovery.json ]]; then
  mv /etc/kaanbal/vault-recovery.json "$BACKUP/vault-recovery.orphaned.json"
  log "Claves de Vault de la instalación anterior apartadas en ${BACKUP} (sus datos se eliminaron con k3s)"
fi

rm -rf /var/lib/kaanbal-installer /run/kaanbal-installer
rm -rf /tmp/kaanbal-* /tmp/kaanbal-gitops
rm -f "/etc/systemd/system/${SERVICE}.service"

if ! $PRESERVE; then
  rm -rf /etc/kaanbal /var/lib/kaanbal /var/backups/kaanbal
fi

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

log "Reset local completado."
if $PRESERVE; then
  log "Credenciales conservadas en /etc/kaanbal/installer.env y backup ${BACKUP}"
fi
log "Recursos externos conservados: GitHub, Cloudflare, Docker Hub y Tailscale."
