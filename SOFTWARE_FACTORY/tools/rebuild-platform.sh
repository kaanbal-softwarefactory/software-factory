#!/usr/bin/env bash
# Ciclo oficial de publicar cambios de plataforma al lab / célula.
#
# Preferir SIEMPRE el modo más estrecho que cubra el cambio:
#   api | console | agent | templates | installer-sync | core | wipe-full
#
# Ejemplos:
#   sudo bash tools/rebuild-platform.sh api
#   sudo bash tools/rebuild-platform.sh core          # api+console+agent
#   sudo bash tools/rebuild-platform.sh wipe-full     # limpia Ubuntu+TS + install unattended
#
# Qué va a dónde (contrato empaquetado):
#   - Código deployer/API/exposure  → repo kaanbal-api (+ imagen Docker)
#   - Templates/catalog             → repo kaanbal-templates
#   - Console UI                    → repo kaanbal-console (+ imagen)
#   - Baseline gitops overlays      → repo infra-gitops (render instalador)
#   - Instalador / unattended       → árbol local ~/kaanbal-next + install.sh
#
set -euo pipefail

# Allow override when launcher copies this script (e.g. CR-stripped copy).
ROOT="${KAANBAL_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
MODE="${1:-}"
ENV_FILE="${ENV_FILE:-/etc/kaanbal/installer.env}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/rebuild-$MODE-$STAMP.log"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "$MODE" ]] || die "uso: $0 <api|console|agent|templates|installer-sync|core|wipe-full>"
[[ "$(id -u)" -eq 0 ]] || exec sudo -n bash "$0" "$@"

tr -d '\r' <"$ENV_FILE" >/tmp/kb-rebuild.env
# shellcheck disable=SC1091
set -a; source /tmp/kb-rebuild.env; set +a

ORG="${GITHUB_ORG:-${github_org:-}}"
TOKEN="${GITOPS_TOKEN:-${GITHUB_TOKEN:-${github_token:-}}}"
DOCKER_USER="${DOCKER_USER:-${docker_user:-}}"
DOCKER_TOKEN="${DOCKER_TOKEN:-${docker_token:-}}"

[[ -n "$ORG" && -n "$TOKEN" ]] || die "faltan GITHUB_ORG / GITHUB_TOKEN en $ENV_FILE"
[[ -n "$DOCKER_USER" && -n "$DOCKER_TOKEN" ]] || die "faltan DOCKER_* en $ENV_FILE"

sync_tree() {
  # Copia selectiva desde checkout de desarrollo si existe
  local src="${KAANBAL_SRC:-/home/alice/kaanbal-next}"
  log "sync OK (working tree $src)"
}

push_and_build() {
  local component="$1"   # kaanbal-api | kaanbal-console | kaanbal-agent
  log "=== rebuild component=$component ==="
  cd "$ROOT/installer"
  COMPONENT="$component" ORG="$ORG" TOKEN="$TOKEN" DOCKER_USER="$DOCKER_USER" DOCKER_TOKEN="$DOCKER_TOKEN" \
  python3 - <<'PY'
import os, sys, tempfile, shutil
sys.path.insert(0, os.getcwd())
import gitops_publish, corebuild
from server import run, kubectl, apply_yaml

comp = os.environ["COMPONENT"]
token, org = os.environ["TOKEN"], os.environ["ORG"]
docker_user, docker_token = os.environ["DOCKER_USER"], os.environ["DOCKER_TOKEN"]
src_root = os.path.dirname(os.getcwd())
src = os.path.join(src_root, comp)
assert os.path.isdir(src), src

# Force republish source (overwrite remote with local tree for core repos)
work = tempfile.mkdtemp(prefix=f"rebuild-{comp}-")
clone = os.path.join(work, "repo")
auth = gitops_publish.auth_url(token, org, comp)
rc, out = run(f"git clone --depth 1 '{auth}' '{clone}'", timeout=180)
if rc != 0:
    # empty repo — seed
    run(f"mkdir -p '{clone}' && cd '{clone}' && git init && git checkout -b main", timeout=30)
else:
    # replace tracked files with local source (keep .git)
    for name in os.listdir(clone):
        if name == ".git":
            continue
        p = os.path.join(clone, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
# copy local
for name in os.listdir(src):
    if name in (".git", "node_modules", "__pycache__", ".venv", "dist", ".pytest_cache"):
        continue
    s, d = os.path.join(src, name), os.path.join(clone, name)
    if os.path.isdir(s):
        shutil.copytree(
            s, d, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "node_modules", ".venv"),
        )
    else:
        shutil.copy2(s, d)

rc, out = run(
    f"cd '{clone}' && git config user.email 'rebuild@kaanbal.local' "
    f"&& git config user.name 'Kaanbal Rebuild' && git add -A "
    f"&& (git diff --cached --quiet || git commit -m 'rebuild: {comp} from lab sync') "
    f"&& git push -u origin HEAD:main",
    timeout=180,
)
print(out or "", flush=True)
if rc != 0:
    raise SystemExit(f"push {comp} failed: {out}")

rc, sha = run(f"cd '{clone}' && git rev-parse HEAD")
sha = (sha or "").strip()
tag = f"prod-{sha[:7]}"
print(f"building {comp}:{tag}", flush=True)
corebuild.build_core_images(
    kubectl, apply_yaml,
    github_org=org, github_token=token,
    docker_user=docker_user, docker_token=docker_token,
    tags={comp: tag},
    components=[c for c in corebuild.CORE_COMPONENTS if c["name"] == comp],
    log_fn=lambda m, l="info": print(f"[{l}] {m}", flush=True),
)

# bump infra-gitops overlay tag
infra = tempfile.mkdtemp(prefix="infra-bump-")
iclone = os.path.join(infra, "infra")
auth_i = gitops_publish.auth_url(token, org, "infra-gitops")
rc, out = run(f"git clone --depth 1 '{auth_i}' '{iclone}'", timeout=120)
if rc != 0:
    raise SystemExit(out)
import re
kust = os.path.join(iclone, f"apps/{comp}/overlays/prod/kustomization.yaml")
if os.path.isfile(kust):
    text = open(kust, encoding="utf-8").read()
    text = re.sub(r"newTag:\s*\S+", f"newTag: {tag}", text)
    text = re.sub(r"newName:\s*\S+", f"newName: {docker_user}/{comp}", text, count=1)
    open(kust, "w", encoding="utf-8").write(text)
    run(
        f"cd '{iclone}' && git config user.email 'rebuild@kaanbal.local' "
        f"&& git config user.name 'Kaanbal Rebuild' && git add -A "
        f"&& (git diff --cached --quiet || git commit -m 'deploy(prod): {comp} {tag}') "
        f"&& git push origin main",
        timeout=120,
    )
print(f"REBUILD_OK {comp} {tag}", flush=True)
PY
}

publish_templates() {
  log "=== publish kaanbal-templates (overwrite) ==="
  cd "$ROOT"
  ORG="$ORG" TOKEN="$TOKEN" ROOT="$ROOT" python3 - <<'PY'
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.join(os.environ["ROOT"], "installer"))
import gitops_publish
from server import run
token, org = os.environ["TOKEN"], os.environ["ORG"]
src = os.path.join(os.environ["ROOT"], "kaanbal-templates")
work = tempfile.mkdtemp(prefix="tpl-")
clone = os.path.join(work, "repo")
auth = gitops_publish.auth_url(token, org, "kaanbal-templates")
rc, out = run(f"git clone --depth 1 '{auth}' '{clone}'", timeout=120)
if rc != 0:
    run(f"mkdir -p '{clone}' && cd '{clone}' && git init && git checkout -b main", timeout=30)
for name in list(os.listdir(clone)):
    if name == ".git":
        continue
    p = os.path.join(clone, name)
    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
for name in os.listdir(src):
    if name == ".git":
        continue
    s, d = os.path.join(src, name), os.path.join(clone, name)
    shutil.copytree(s, d, dirs_exist_ok=True) if os.path.isdir(s) else shutil.copy2(s, d)
rc, out = run(
    f"cd '{clone}' && git config user.email 'rebuild@kaanbal.local' "
    f"&& git config user.name 'Kaanbal Rebuild' && git add -A "
    f"&& (git diff --cached --quiet || git commit -m 'chore: templates surfaces fase3') "
    f"&& git push -u origin HEAD:main",
    timeout=180,
)
print(out or "", flush=True)
raise SystemExit(0 if rc == 0 else 1)
PY
}

case "$MODE" in
  api) push_and_build kaanbal-api ;;
  console) push_and_build kaanbal-console ;;
  agent) push_and_build kaanbal-agent ;;
  templates) publish_templates ;;
  installer-sync)
    log "Installer/unattended already live in $ROOT — no image build"
    log "Tip: changes in installer/ apply on next install.sh / wipe-full"
    ;;
  core)
    push_and_build kaanbal-api
    push_and_build kaanbal-console
    push_and_build kaanbal-agent
    publish_templates
    ;;
  wipe-full)
    log "=== wipe-full: Tailscale orphans + Ubuntu wipe + unattended reinstall ==="
    python3 "$ROOT/tools/cleanup-tailscale-orphans.py" --apply --wipe-all-tagged --env "$ENV_FILE" || true
    bash "$ROOT/tools/wipe-ubuntu-kaanbal.sh"
    bash "$ROOT/install.sh" --reset-remote --preserve-credentials --unattended --env /home/alice/kaanbal-reinstall.env
    ;;
  *) die "modo desconocido: $MODE" ;;
esac

log "DONE mode=$MODE log=$LOG"
echo "DONE mode=$MODE"
