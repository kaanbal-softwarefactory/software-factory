#!/usr/bin/env bash
# Public entry point. Download this file first; never execute a partial curl pipe.
set -Eeuo pipefail
# KAANBAL_REPO permite instalar desde un fork o un espejo.
REPO="${KAANBAL_REPO:-https://github.com/kaanbal-softwarefactory/software-factory.git}"
REVISION="main"
DESTINATION="${HOME}/kaanbal-source"
INSTALL_MODE="--lan"
RESET=false
CUSTOM_DESTINATION=false
die() { printf '[kaanbal] ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --ref) shift; (($#)) || die '--ref necesita una revisión'; REVISION="$1" ;;
    --dir) shift; (($#)) || die '--dir necesita una ruta'; DESTINATION="$1"; CUSTOM_DESTINATION=true ;;
    --reset) RESET=true ;;
    --lan) INSTALL_MODE="--lan" ;;
    --tailscale) INSTALL_MODE="--tailscale" ;;
    --ssh-tunnel) INSTALL_MODE="--ssh-tunnel" ;;
    -h|--help)
      printf 'Uso: bash install.sh [--ref commit|tag|branch] [--dir directorio-nuevo] [--reset] [--lan|--tailscale|--ssh-tunnel]\n'
      printf '  --reset elimina la instalación local administrada por Kaanbal y sus credenciales.\n'
      printf 'Reanudar: sudo bash <directorio>/SOFTWARE_FACTORY/install.sh\n'
      exit 0 ;;
    *) die "Opción desconocida: $1" ;;
  esac
  shift
done
[[ "$(uname -s)" == Linux ]] || die 'Ejecuta este comando dentro del servidor Ubuntu por SSH.'
[[ "$REVISION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]*$ ]] || die 'Revisión Git inválida.'
if $RESET && $CUSTOM_DESTINATION; then
  die '--reset sólo admite el destino seguro predeterminado ~/kaanbal-source.'
fi
if ! $RESET; then
  [[ ! -e "$DESTINATION" && ! -L "$DESTINATION" ]] || die "Ya existe $DESTINATION. Reanuda su instalador o vuelve a ejecutar con --reset."
fi
command -v systemctl >/dev/null || die 'Se requiere Ubuntu Server con systemd.'
if ((EUID != 0)); then
  command -v sudo >/dev/null || die 'Se requiere sudo.'
  printf '[kaanbal] Introduce personalmente la contraseña sudo si se solicita.\n'
  sudo -v
fi
as_root() { if ((EUID == 0)); then "$@"; else sudo "$@"; fi; }
if ! command -v git >/dev/null || ! command -v python3 >/dev/null || ! command -v curl >/dev/null; then
  as_root apt-get update
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 curl ca-certificates
fi
CHECKOUT="$DESTINATION"
if $RESET; then
  CHECKOUT="${DESTINATION}.incoming.$$"
  [[ ! -e "$CHECKOUT" && ! -L "$CHECKOUT" ]] || die "Ya existe el staging temporal $CHECKOUT."
fi

# Descargar antes de borrar permite validar red y revisión sin destruir una instalación útil.
mkdir -p "$(dirname "$CHECKOUT")"
mkdir -m 700 "$CHECKOUT"
git -C "$CHECKOUT" init --quiet
git -C "$CHECKOUT" remote add origin "$REPO"
GIT_TERMINAL_PROMPT=0 git -C "$CHECKOUT" fetch --depth 1 origin "$REVISION" \
  || die 'No se pudo descargar la revisión pública. El directorio parcial se conserva para diagnóstico; no se ejecutó el instalador.'
git -C "$CHECKOUT" checkout --quiet --detach FETCH_HEAD
printf '[kaanbal] Revisión descargada: '
git -C "$CHECKOUT" rev-parse HEAD

if $RESET; then
  printf '[kaanbal] Reinicio limpio solicitado: eliminando la instalación local anterior.\n'
  as_root bash "$CHECKOUT/SOFTWARE_FACTORY/tools/reset-local.sh" --yes --wipe-credentials
  # DESTINATION está fijado arriba y --dir se rechaza junto con --reset.
  as_root rm -rf -- "$DESTINATION"
  mv -- "$CHECKOUT" "$DESTINATION"
fi

[[ -f "$DESTINATION/SOFTWARE_FACTORY/install.sh" ]] || die 'Esta revisión no contiene el instalador.'
as_root bash "$DESTINATION/SOFTWARE_FACTORY/install.sh" "$INSTALL_MODE"
