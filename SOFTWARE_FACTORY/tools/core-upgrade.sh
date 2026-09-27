#!/usr/bin/env bash
# ==============================================================================
# core-upgrade.sh — actualiza el engine de una célula ya instalada (ADR-002)
# ==============================================================================
# Versión manual y auditable de la transacción descrita en el ADR. Se ejecuta
# EN EL NODO de la célula, nunca dentro del pod de la API: cuando le toca a
# `kaanbal-api` recibir su nueva imagen, el proceso que conduce el upgrade no
# puede ser el que muere. Ese es el mismo motivo por el que el servicio
# automático usará un Job y no el proceso de la API.
#
#   snapshot → preflight → drift → sync → build → promote → verify
#                                              └─── rollback ───┘
#
# Uso:
#   sudo KAANBAL_ORG=<org> bash core-upgrade.sh --ref main
#   sudo KAANBAL_ORG=<org> bash core-upgrade.sh --phase build
#   sudo KAANBAL_ORG=<org> bash core-upgrade.sh --ref main --adopt-upstream   # descarta deriva, con registro
#   sudo bash core-upgrade.sh --snapshot
#   sudo KAANBAL_ORG=<org> bash core-upgrade.sh --rollback <api_tag> <console_tag>
set -euo pipefail

NS=prod
# El checkout del monorepo es donde vive este script (tools/ → SOFTWARE_FACTORY → raíz).
SOURCE_DIR=${KAANBAL_SOURCE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
COMPONENTS=(kaanbal-api kaanbal-console)
# Se sincronizan desde el monorepo pero no tienen imagen: los templates base
# viven aquí y la API refresca su catálogo desde este repo cada 5 minutos.
SYNC_REPOS=("${COMPONENTS[@]}" kaanbal-templates)
KANIKO_IMAGE=gcr.io/kaniko-project/executor:v1.24.0
GIT_SECRET=kaanbal-build-git
REGISTRY_SECRET=regcred
BUILD_TIMEOUT=${BUILD_TIMEOUT:-1200}
VERIFY_TIMEOUT=${VERIFY_TIMEOUT:-420}

REF=main
PHASE=all
ORIGINAL_ARGS=("$@")

while (($#)); do
  case "$1" in
    --ref) shift; REF="${1:?--ref necesita una revisión}" ;;
    --source) shift; SOURCE_DIR="${1:?--source necesita una ruta}" ;;
    --phase) shift; PHASE="${1:?--phase necesita sync|build|promote|verify|all}" ;;
    --snapshot) PHASE=snapshot ;;
    --adopt-upstream) ADOPT_UPSTREAM=1; export ADOPT_UPSTREAM ;;
    --rollback) PHASE=rollback; ROLLBACK_API="${2:-}"; ROLLBACK_CONSOLE="${3:-}"; shift 2 || true ;;
    *) echo "Argumento desconocido: $1" >&2; exit 2 ;;
  esac
  shift || true
done

log()  { printf '[kaanbal-upgrade] %s\n' "$*"; }
warn() { printf '[kaanbal-upgrade] ⚠ %s\n' "$*" >&2; }
die()  { printf '[kaanbal-upgrade] ERROR: %s\n' "$*" >&2; exit 1; }

# Dónde vive el proyecto. Es la única mención al repo oficial en este script: si
# vuelve a mudarse, se cambia aquí y en core_release.py (DEFAULT_UPSTREAM).
DEFAULT_UPSTREAM=kaanbal-softwarefactory/software-factory
# Donde vivía antes de la v1. Se reconoce para mudar a las células que salieron de allí.
LEGACY_UPSTREAM=ProyectosUniUAEH/software-factory

# 'https://[usuario[:token]@]github.com/owner/repo[.git]' o 'git@github.com:owner/repo.git'
# -> owner/repo. Vacío si la URL no es de GitHub (un checkout local no es un repo oficial).
slug_of() {
  local url=${1:-}
  [[ "$url" == *github.com* ]] || return 0
  url=${url%.git}
  printf '%s' "${url##*github.com[:/]}"
}

origin_slug() {
  slug_of "$(git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" remote get-url origin 2>/dev/null || true)"
}

# El proyecto se mudó. En un nodo, `origin` de este checkout sigue apuntando al repo
# anterior: sin mudarlo, la siguiente actualización volvería a bajar de allí. Solo se
# toca si es EXACTAMENTE el repo anterior, y KAANBAL_KEEP_ORIGIN=1 lo impide.
migrate_origin() {
  [[ "${KAANBAL_KEEP_ORIGIN:-0}" == 1 ]] && return 0
  [[ "${UPSTREAM_SLUG,,}" == "${LEGACY_UPSTREAM,,}" ]] || return 0
  local owner as_owner=()
  owner=$(stat -c %U "$SOURCE_DIR")
  if [[ $EUID -eq 0 && "$owner" != root ]]; then
    as_owner=(runuser -u "$owner" --)
    command -v runuser >/dev/null || as_owner=(sudo -u "$owner")
  fi
  log "El proyecto se mudó a $DEFAULT_UPSTREAM: origin deja de apuntar a $LEGACY_UPSTREAM"
  "${as_owner[@]}" git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" \
    remote set-url origin "https://github.com/$DEFAULT_UPSTREAM.git" \
    || warn "No se pudo mudar origin. Hazlo a mano: git -C $SOURCE_DIR remote set-url origin https://github.com/$DEFAULT_UPSTREAM.git"
}

# ── Candado: un solo upgrade a la vez ────────────────────────────────────────
# El botón de la consola (un Job) y este script en el nodo son dos caminos
# independientes. Si corren a la vez, los dos sincronizan los mismos repos y
# cada uno recalcula los tags leyendo el HEAD remoto: uno puede promover una
# imagen que construyó el otro, o una que nadie construyó. El candado es un
# ConfigMap que solo existe mientras dura un upgrade; crearlo es atómico.
LOCK_NAME=kaanbal-upgrade-lock
LOCK_TTL_SECONDS=${LOCK_TTL_SECONDS:-5400}
LOCK_HOLDER=""

acquire_upgrade_lock() {
  local holder=${KAANBAL_UPGRADE_HOLDER:-"$(hostname)-$$"} out since age current
  if out=$(kubectl create configmap "$LOCK_NAME" -n "$NS" \
      --from-literal=holder="$holder" --from-literal=since="$(date -u +%s)" 2>&1); then
    LOCK_HOLDER=$holder
    trap release_upgrade_lock EXIT
    log "Candado de upgrade tomado ($holder)"
    return 0
  fi
  if [[ "$out" == *AlreadyExists* || "$out" == *"already exists"* ]]; then
    current=$(kubectl get configmap "$LOCK_NAME" -n "$NS" -o jsonpath='{.data.holder}' 2>/dev/null || true)
    since=$(kubectl get configmap "$LOCK_NAME" -n "$NS" -o jsonpath='{.data.since}' 2>/dev/null || true)
    [[ "$since" =~ ^[0-9]+$ ]] || since=0
    age=$(( $(date -u +%s) - since ))
    if (( age > LOCK_TTL_SECONDS )); then
      warn "El candado de ${current:-?} tiene ${age}s: se da por abandonado y se libera"
      kubectl delete configmap "$LOCK_NAME" -n "$NS" >/dev/null 2>&1 || true
      acquire_upgrade_lock
      return
    fi
    die "Ya hay un upgrade en curso (${current:-?}, desde hace $((age / 60)) min). Espera a que termine; si se colgó, el candado caduca solo en $(( (LOCK_TTL_SECONDS - age) / 60 )) min."
  fi
  # Sin permiso para crearlo (una célula cuyo RBAC aún no lo trae): el upgrade
  # que entrega ese permiso no puede exigirlo.
  warn "No se pudo tomar el candado de upgrade; se continúa sin él: ${out}"
}

release_upgrade_lock() {
  [[ -n "$LOCK_HOLDER" ]] || return 0
  local current
  current=$(kubectl get configmap "$LOCK_NAME" -n "$NS" -o jsonpath='{.data.holder}' 2>/dev/null || true)
  if [[ "$current" == "$LOCK_HOLDER" ]]; then
    kubectl delete configmap "$LOCK_NAME" -n "$NS" >/dev/null 2>&1 || true
  fi
}

# ── Checkout del nodo: exactamente la revisión pedida ────────────────────────
# El checkout es de una persona, pero si alguna vez algo lo tocó como root (un
# `sudo git pull`), git —que corre como su dueño— no puede reescribir esos
# archivos: el checkout termina a medias y el upgrade publicaba la versión vieja
# de ellos sin avisar.
reclaim_checkout() {
  local owner=$1 stray
  stray=$(find "$SOURCE_DIR" -not -user "$owner" -print -quit 2>/dev/null || true)
  [[ -z "$stray" ]] && return 0
  log "Hay archivos del checkout que no son de $owner (p. ej. ${stray#"$SOURCE_DIR"/}): se le devuelven"
  chown -R "$owner": "$SOURCE_DIR"
}

# Lo que difiere de la revisión: archivos del repo distintos (git no pudo
# escribirlos o alguien los editó) y archivos sueltos dentro de lo que se publica.
checkout_drift() {
  local -a git_cmd=("$@" git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR")
  local component
  "${git_cmd[@]}" status --porcelain --untracked-files=no
  for component in "${SYNC_REPOS[@]}"; do
    "${git_cmd[@]}" status --porcelain --untracked-files=all -- "SOFTWARE_FACTORY/$component" | grep '^??' || true
  done
}

# La primera pasada de sync solo actualiza el checkout y se relanza: el candado lo
# toma la segunda, que es la que escribe. Mirar el estado no necesita candado.
needs_upgrade_lock() {
  [[ "$PHASE" == verify || "$PHASE" == snapshot ]] && return 1
  if [[ ( "$PHASE" == all || "$PHASE" == sync ) && -z "${KAANBAL_UPGRADE_REEXEC:-}" ]]; then
    return 1
  fi
  return 0
}

command -v kubectl >/dev/null || die "kubectl no está en PATH"

snapshot() {
  kubectl get deploy "${COMPONENTS[@]}" -n "$NS" \
    -o jsonpath='{range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image}{"\n"}{end}'
}

log "Estado actual:"
snapshot | sed 's/^/  /'
[[ "$PHASE" == snapshot ]] && exit 0

ORG=${KAANBAL_ORG:-}
[[ -n "$ORG" ]] || die "Exporta KAANBAL_ORG con la org de GitHub de esta célula (ej: northwindlearning)"

TOKEN=$(kubectl get secret "$GIT_SECRET" -n "$NS" -o jsonpath='{.data.token}' | base64 -d)
[[ -n "$TOKEN" ]] || die "No se pudo leer el Secret $GIT_SECRET"

DOCKER_USER=$(kubectl get deploy kaanbal-api -n "$NS" \
  -o jsonpath='{.spec.template.spec.containers[0].image}' | cut -d/ -f1)
[[ -n "$DOCKER_USER" ]] || die "No se pudo deducir el usuario de Docker Hub del Deployment"

# SHA publicado en cada repo standalone → tag, igual al que produciría el CI.
component_tag() {
  local repo=$1 sha
  sha=$(git ls-remote "https://x-access-token:$TOKEN@github.com/$ORG/$repo.git" refs/heads/main | cut -f1)
  [[ -n "$sha" ]] || die "No se pudo leer el HEAD de $ORG/$repo"
  printf 'prod-%s' "${sha:0:7}"
}

# ¿Ya está publicada? Reusa corebuild.image_exists del instalador. La credencial
# viaja por stdin desde el Secret, nunca como argumento visible en `ps`. Ante la
# duda responde "no": reconstruir es seguro, dar por buena una imagen que no
# existe no.
image_exists() {
  local repo=$1 tag=$2
  kubectl get secret "$REGISTRY_SECRET" -n "$NS" -o jsonpath='{.data.\.dockerconfigjson}' 2>/dev/null \
  | base64 -d 2>/dev/null \
  | PYTHONPATH="$SOURCE_DIR/SOFTWARE_FACTORY/installer" python3 -c '
import base64, json, sys
import corebuild
repo, tag, user = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    auths = json.load(sys.stdin).get("auths", {})
except ValueError:
    sys.exit(1)
password = ""
for entry in auths.values():
    password = entry.get("password", "")
    if not password and entry.get("auth"):
        password = base64.b64decode(entry["auth"]).decode().split(":", 1)[-1]
    if password:
        break
sys.exit(0 if corebuild.image_exists(user, repo, tag, password) else 1)
' "$repo" "$tag" "$DOCKER_USER"
}

# Tag que corre hoy cada Deployment. Es el punto de retorno del rollback.
running_tag() {
  kubectl get deploy "$1" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].image}' | awk -F: '{print $NF}'
}

desired_pairs() {
  local c
  for c in "${COMPONENTS[@]}"; do printf '%s=%s\n' "$c" "$(component_tag "$c")"; done
}

# ── Manifiestos estáticos del core ───────────────────────────────────────────
# Un upgrade que solo mueve tags no puede entregar manifiestos nuevos (RBAC, un
# Service). Se sincronizan los archivos base del core que NO son plantilla: los
# que tienen ${KAANBAL_*} o @kaanbal:if necesitan el contexto con el que se
# instaló la célula y se dejan como están. Se detectan con las mismas marcas que
# usa installer/gitops_render.py.
sync_static_manifests() {
  local repo=$1 c src dst rel synced=0 skipped=()
  for c in "${COMPONENTS[@]}"; do
    src="$SOURCE_DIR/SOFTWARE_FACTORY/infra-gitops/apps/$c/base"
    dst="$repo/apps/$c/base"
    [[ -d "$src" && -d "$dst" ]] || continue
    while IFS= read -r -d '' f; do
      rel=${f#"$src/"}
      if grep -qE '\$\{KAANBAL_[A-Z0-9_]+\}|@kaanbal:(if|else|endif)' "$f"; then
        skipped+=("$c/base/$rel")
        continue
      fi
      if ! cmp -s "$f" "$dst/$rel" 2>/dev/null; then
        mkdir -p "$(dirname "$dst/$rel")"
        cp "$f" "$dst/$rel"
        log "  manifiesto $c/base/$rel actualizado"
        synced=$((synced + 1))
      fi
    done < <(find "$src" -type f -print0)
  done
  ((synced == 0)) && log "  manifiestos estáticos al día"
  ((${#skipped[@]})) && log "  plantillas no sincronizadas (requieren contexto de instalación): ${skipped[*]}"
  return 0
}

# Revierte exactamente el commit de promoción de este upgrade, por SHA: aunque
# alguien haya commiteado después, solo se deshace lo nuestro (tags y
# manifiestos). Si el revert choca, se escriben los tags anteriores a mano.
rollback_promotion() {
  local fallback_pairs=("$@") W
  if [[ -z "${PROMOTED_SHA:-}" ]]; then
    promote_tags "rollback: restaurar core" "${fallback_pairs[@]}"
    return
  fi
  W=$(mktemp -d)
  git clone --quiet "https://x-access-token:$TOKEN@github.com/$ORG/infra-gitops.git" "$W/repo"
  cd "$W/repo"
  git config user.email "kaanbal@localhost"
  git config user.name "Kaanbal Upgrade"
  if git revert --no-edit "$PROMOTED_SHA" >/dev/null 2>&1; then
    git commit --amend --quiet -m "rollback: revertir ${PROMOTED_SHA:0:7} [skip ci]"
    git push --quiet origin HEAD:main
    cd /; rm -rf "$W"
    log "  revertido ${PROMOTED_SHA:0:7} (tags y manifiestos)"
    local app
    for app in "${COMPONENTS[@]}"; do
      kubectl annotate application "${app}-prod" -n argocd \
        argocd.argoproj.io/refresh=hard --overwrite >/dev/null 2>&1 || true
    done
  else
    git revert --abort >/dev/null 2>&1 || true
    cd /; rm -rf "$W"
    warn "El revert de ${PROMOTED_SHA:0:7} chocó con otro cambio; se restauran solo los tags"
    SYNC_MANIFESTS=0 promote_tags "rollback: restaurar core" "${fallback_pairs[@]}"
  fi
}

# ── Promoción: escribe tags explícitos en un solo commit ─────────────────────
# Un commit por componente daría ventanas con versiones mezcladas. Y el rollback
# escribe los tags anteriores en vez de hacer `git revert HEAD`: el último commit
# de infra-gitops puede ser de otro (el deploy de una app) y revertirlo desharía
# trabajo ajeno.
promote_tags() {
  local message=$1; shift
  local W pair c tag f
  W=$(mktemp -d)
  git clone --quiet "https://x-access-token:$TOKEN@github.com/$ORG/infra-gitops.git" "$W/repo"
  cd "$W/repo"
  git config user.email "kaanbal@localhost"
  git config user.name "Kaanbal Upgrade"

  for pair in "$@"; do
    c=${pair%%=*}; tag=${pair#*=}
    f="apps/$c/overlays/prod/kustomization.yaml"
    [[ -f "$f" ]] || { cd /; rm -rf "$W"; die "No existe $f en infra-gitops"; }
    sed -i "s|^\( *newTag:\).*|\1 $tag|" "$f"
    log "  $c → $tag"
  done
  [[ "${SYNC_MANIFESTS:-0}" == 1 ]] && sync_static_manifests "$W/repo"
  git add -A
  PROMOTED_SHA=""
  if git diff --cached --quiet; then
    log "infra-gitops ya está al día"
    cd /; rm -rf "$W"; return 0
  fi
  git commit --quiet -m "$message [skip ci]"
  git push --quiet origin HEAD:main
  PROMOTED_SHA=$(git rev-parse HEAD)
  cd /; rm -rf "$W"

  # Forzar reconciliación en vez de esperar el poll de ArgoCD.
  local app
  for app in "${COMPONENTS[@]}"; do
    kubectl annotate application "${app}-prod" -n argocd \
      argocd.argoproj.io/refresh=hard --overwrite >/dev/null 2>&1 || true
  done
}

# ── Procedencia: la célula registra qué commit quedó aplicado ────────────────
# Se escribe solo tras verificar. Sin esto la consola seguiría ofreciendo como
# pendientes commits que ya están corriendo.
record_provenance() {
  local upstream=$1 api_tag console_tag api_sha console_sha
  api_tag=$(component_tag kaanbal-api); console_tag=$(component_tag kaanbal-console)
  api_sha=$(git ls-remote "https://x-access-token:$TOKEN@github.com/$ORG/kaanbal-api.git" refs/heads/main | cut -f1)
  console_sha=$(git ls-remote "https://x-access-token:$TOKEN@github.com/$ORG/kaanbal-console.git" refs/heads/main | cut -f1)
  local out
  if ! out=$(kubectl exec -n "$NS" deploy/kaanbal-api -- python -c '
import asyncio, sys
from app import db as dbmod
from app.services import core_release
upstream, api_tag, api_sha, console_tag, console_sha, docker_user, upstream_slug = sys.argv[1:8]
async def main():
    await dbmod.connect_db()
    current = await core_release.read_provenance()
    components = dict(current.get("components") or {})
    components["kaanbal-api"] = {"image": f"{docker_user}/kaanbal-api", "tag": api_tag, "repo_sha": api_sha}
    components["kaanbal-console"] = {"image": f"{docker_user}/kaanbal-console", "tag": console_tag, "repo_sha": console_sha}
    kwargs = dict(
        version=f"dev-{upstream[:7]}", upstream_sha=upstream, components=components,
        channel="dev", applied_by="core-upgrade.sh",
    )
    if upstream_slug:
        kwargs["upstream"] = upstream_slug
    try:
        await core_release.write_provenance(**kwargs)
    except TypeError:
        # API anterior a la procedencia con repo de origen: se registra sin él.
        kwargs.pop("upstream", None)
        await core_release.write_provenance(**kwargs)
    print("procedencia:", f"dev-{upstream[:7]}")
asyncio.run(main())
' "$upstream" "$api_tag" "$api_sha" "$console_tag" "$console_sha" "$DOCKER_USER" "${UPSTREAM_SLUG:-}" 2>&1); then
    warn "El upgrade quedó aplicado pero no se pudo registrar la procedencia:"
    printf '%s\n' "$out" | tail -5 | sed 's/^/    /' >&2
    return 0
  fi
  printf '%s\n' "$out" | grep -v "Connected to MongoDB" | sed 's/^/  /'
}

# ── Verificación: la imagen debe llegar Y el pod quedar listo ────────────────
# Recibe pares componente=tag: tras un rollback lo esperado son los tags viejos,
# no los del repo. Compararlos contra lo nuevo reportaría fallo justo cuando el
# rollback funcionó.
verify() {
  local deadline=$((SECONDS + VERIFY_TIMEOUT)) pair c want ok=1
  local got=""
  for pair in "$@"; do
    c=${pair%%=*}; want=${pair#*=}
    got=""
    log "Esperando $c → $want"
    while ((SECONDS < deadline)); do
      got=$(kubectl get deploy "$c" -n "$NS" \
        -o jsonpath='{.spec.template.spec.containers[0].image}' | awk -F: '{print $NF}')
      [[ "$got" == "$want" ]] && break
      sleep 10
    done
    if [[ "$got" != "$want" ]]; then
      warn "$c sigue en $got: ArgoCD no aplicó el tag nuevo"
      ok=0; continue
    fi
    if ! kubectl rollout status "deploy/$c" -n "$NS" --timeout=180s >/dev/null 2>&1; then
      warn "$c no alcanzó Ready con la imagen nueva"
      ok=0
    else
      log "  $c listo en $want"
    fi
  done
  return $((1 - ok))
}

needs_upgrade_lock && acquire_upgrade_lock

if [[ "$PHASE" == rollback ]]; then
  # --rollback api_tag console_tag: los tags que imprime el snapshot de cada upgrade.
  [[ -n "${ROLLBACK_API:-}" && -n "${ROLLBACK_CONSOLE:-}" ]] \
    || die "Uso: --rollback <api_tag> <console_tag> (los imprime el snapshot del upgrade)"
  log "Restaurando api=$ROLLBACK_API console=$ROLLBACK_CONSOLE"
  pairs=("kaanbal-api=$ROLLBACK_API" "kaanbal-console=$ROLLBACK_CONSOLE")
  promote_tags "rollback: restaurar core" "${pairs[@]}"
  verify "${pairs[@]}" && log "✅ Rollback verificado." || die "El rollback no verifica. Revisa 'kubectl get pods -n $NS'."
  exit 0
fi

# ── Preflight + sync ─────────────────────────────────────────────────────────
UPSTREAM=""
UPSTREAM_SLUG=""
if [[ "$PHASE" == all || "$PHASE" == sync ]]; then
  [[ -d "$SOURCE_DIR/SOFTWARE_FACTORY" ]] || die "No hay checkout del monorepo en $SOURCE_DIR"
  # El checkout reescribe este mismo archivo mientras bash lo ejecuta, y bash lee
  # los scripts por tramos: seguiría leyendo el archivo nuevo desde un offset del
  # viejo. Todo el bloque se parsea antes de correr y termina en `exec` de la
  # versión recién descargada, así que el upgrade corre con la lógica más nueva.
  if [[ -z "${KAANBAL_UPGRADE_REEXEC:-}" ]]; then
    log "Actualizando el checkout a $REF"
    # Git se ejecuta como el dueño del checkout: corrido como root dejaba objetos
    # de .git con dueño root y el siguiente `git fetch` del usuario fallaba con
    # "unpack-objects failed" (pasó en laboratorio). En el Job el checkout es de root.
    owner=$(stat -c %U "$SOURCE_DIR")
    if [[ $EUID -eq 0 && "$owner" != root ]]; then
      as_owner=(runuser -u "$owner" --)
      command -v runuser >/dev/null || as_owner=(sudo -u "$owner")
      reclaim_checkout "$owner"
    else
      as_owner=()
    fi
    "${as_owner[@]}" git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" fetch --depth 50 origin "$REF" >/dev/null 2>&1 \
      || die "No se pudo descargar $REF del monorepo (¿archivos de .git con otro dueño? chown -R $owner $SOURCE_DIR)"
    "${as_owner[@]}" git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" checkout --quiet --detach FETCH_HEAD \
      || die "No se pudo actualizar el checkout"
    drift=$(checkout_drift "${as_owner[@]}")
    [[ -z "$drift" ]] || die "El checkout no quedó igual a $REF, y desplegarlo publicaría otra cosa:
$(printf '%s\n' "$drift" | head -10 | sed 's/^/       /')
     Deja el checkout limpio (git -C $SOURCE_DIR status) y vuelve a correr."
    export KAANBAL_UPGRADE_REEXEC=1 KAANBAL_SOURCE="$SOURCE_DIR"
    exec bash "$SOURCE_DIR/SOFTWARE_FACTORY/tools/core-upgrade.sh" "${ORIGINAL_ARGS[@]}"
  fi
  UPSTREAM=$(git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" rev-parse HEAD)
  log "Monorepo en ${UPSTREAM:0:7}"
  # De qué repo salió este commit es lo que se registra como procedencia, así que se
  # lee ANTES de mudar el remoto: el SHA de esta corrida viene del repo de origen.
  UPSTREAM_SLUG=$(origin_slug)
  migrate_origin

  POD=$(kubectl get pod -n "$NS" -l app=kaanbal-api -o jsonpath='{.items[0].metadata.name}')
  log "Preflight de imports dentro de $POD"
  kubectl cp "$SOURCE_DIR/SOFTWARE_FACTORY/kaanbal-api/app" "$NS/$POD:/tmp/pf-app" >/dev/null
  kubectl cp "$SOURCE_DIR/SOFTWARE_FACTORY/kaanbal-api/main.py" "$NS/$POD:/tmp/pf-main.py" >/dev/null
  kubectl exec -n "$NS" "$POD" -- sh -c '
    set -e; rm -rf /tmp/pf; mkdir -p /tmp/pf
    mv /tmp/pf-app /tmp/pf/app; cp /tmp/pf-main.py /tmp/pf/main.py
    cd /tmp/pf && python -c "
import importlib, sys
sys.path.insert(0, \"/tmp/pf\")
for m in [\"app.routers.core\",\"app.routers.apps\",\"app.routers.domains\",\"app.services.app_deployer\",\"main\"]:
    importlib.import_module(m)
print(\"preflight ok\")
"
    rm -rf /tmp/pf /tmp/pf-main.py
  ' || die "El código nuevo no importa contra las dependencias reales. No se despliega nada."

  # Deriva: nunca pisar código local en silencio. Se recorre desde HEAD: todo
  # commit que aparezca antes del último commit propio (instalador o upgrade)
  # es un cambio hecho a mano sobre el repo. Contar commits no sirve: cada
  # upgrade suma uno y la guarda terminaría bloqueando siempre.
  for c in "${SYNC_REPOS[@]}"; do
    foreign=$(curl -sf -H "Authorization: Bearer $TOKEN" \
      "https://api.github.com/repos/$ORG/$c/commits?per_page=100" | python3 -c '
import json, sys
OURS = ("bootstrap:", "upgrade: sync")
try:
    commits = json.load(sys.stdin)
except ValueError:
    print("?  no se pudo leer la historia"); sys.exit()
found_ours = False
for commit in commits:
    message = commit["commit"]["message"]
    if message.startswith(OURS):
        found_ours = True
        break
    print(commit["sha"][:7], message.splitlines()[0][:70])
if not found_ours:
    print("?  ningún commit del instalador en los últimos 100: historia desconocida")
') || die "No se pudo consultar la historia de $ORG/$c"
    if [[ -n "$foreign" ]]; then
      if [[ "${ADOPT_UPSTREAM:-0}" == 1 ]]; then
        # ADR-002 "adoptar upstream": decisión explícita de descartar lo local.
        # Queda escrito en el log qué se descartó; el historial del repo lo
        # conserva, así que se puede recuperar si hiciera falta.
        warn "$ORG/$c: se adopta el monorepo y se descartan estos commits (siguen en el historial de git):"
        printf '%s\n' "$foreign" | sed 's/^/       /' >&2
      else
        die "$ORG/$c tiene cambios hechos fuera de Kaanbal:
$(printf '%s\n' "$foreign" | sed 's/^/       /')
     Resuelve la deriva antes de sobrescribirlo (ver ADR-002), o vuelve a
     ejecutar con --adopt-upstream si esos cambios ya están en el monorepo."
      fi
    fi
  done

  for c in "${SYNC_REPOS[@]}"; do
    W=$(mktemp -d)
    git clone --quiet "https://x-access-token:$TOKEN@github.com/$ORG/$c.git" "$W/repo"
    find "$W/repo" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    ( cd "$SOURCE_DIR/SOFTWARE_FACTORY/$c" \
      && tar --exclude=.git --exclude=node_modules --exclude=dist \
             --exclude=__pycache__ --exclude='*.pyc' -cf - . ) \
    | ( cd "$W/repo" && tar -xf - )
    cd "$W/repo"
    git config user.email "kaanbal@localhost"
    git config user.name "Kaanbal Upgrade"
    git add -A
    if git diff --cached --quiet; then
      log "$c: sin cambios"
    else
      # [skip ci]: la promoción la hace esta transacción. Si CI también
      # promoviera, podría volver a subir una versión que el rollback acaba de
      # retirar. CI queda para los push directos al repo (flujo custom).
      git commit --quiet -m "upgrade: sync desde software-factory@${UPSTREAM:0:7} [skip ci]"
      git push --quiet origin HEAD:main
      log "$c publicado en $ORG/$c → $(git rev-parse HEAD | cut -c1-7)"
    fi
    cd /; rm -rf "$W"
  done
fi

# ── Build ────────────────────────────────────────────────────────────────────
if [[ "$PHASE" == all || "$PHASE" == build ]]; then
  kubectl create secret generic "$GIT_SECRET" -n "$NS" \
    --from-literal=token="$TOKEN" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  for c in "${COMPONENTS[@]}"; do
    TAG=$(component_tag "$c")
    if image_exists "$c" "$TAG"; then
      log "$c:$TAG ya está en Docker Hub — no se reconstruye"
      continue
    fi
    JOB="kaanbal-build-${c}-${TAG#prod-}"
    log "Construyendo $c:$TAG (Job $JOB)"
    kubectl delete job "$JOB" -n "$NS" --ignore-not-found >/dev/null 2>&1

    kubectl apply -f - >/dev/null <<JOBEOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB
  namespace: $NS
  labels:
    kaanbal-engine.io/component: builder
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 1800
  template:
    metadata:
      labels:
        kaanbal-engine.io/component: builder
    spec:
      restartPolicy: Never
      containers:
      - name: kaniko
        image: $KANIKO_IMAGE
        args:
        - --context=git://github.com/$ORG/$c.git#refs/heads/main
        - --dockerfile=Dockerfile
        - --destination=index.docker.io/$DOCKER_USER/$c:$TAG
        - --single-snapshot
        - --verbosity=info
        env:
        - name: GIT_USERNAME
          value: x-access-token
        - name: GIT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: $GIT_SECRET
              key: token
        resources:
          requests: {cpu: 500m, memory: 1Gi}
          limits: {cpu: "4", memory: 4Gi}
        volumeMounts:
        - name: docker-config
          mountPath: /kaniko/.docker
      volumes:
      - name: docker-config
        secret:
          secretName: $REGISTRY_SECRET
          items:
          - key: .dockerconfigjson
            path: config.json
JOBEOF

    if ! kubectl wait --for=condition=complete "job/$JOB" -n "$NS" \
         --timeout="${BUILD_TIMEOUT}s" >/dev/null 2>&1; then
      warn "El build de $c no completó. Últimas líneas:"
      kubectl logs "job/$JOB" -n "$NS" --tail=25 2>&1 | sed 's/^/    /' || true
      die "Build fallido: no se promueve nada. La célula sigue en su versión anterior."
    fi
    log "  $c:$TAG publicado en Docker Hub"
  done
fi

# ── Promote + verify, con rollback automático ────────────────────────────────
if [[ "$PHASE" == all || "$PHASE" == promote ]]; then
  before=()
  for c in "${COMPONENTS[@]}"; do before+=("$c=$(running_tag "$c")"); done
  mapfile -t wanted < <(desired_pairs)
  (( ${#wanted[@]} == ${#COMPONENTS[@]} )) || die "No se pudieron resolver los tags de todos los componentes"

  log "Promoviendo tags y manifiestos en infra-gitops"
  SYNC_MANIFESTS=1 promote_tags "upgrade: promover core del monorepo@${UPSTREAM:0:7}" "${wanted[@]}"

  if verify "${wanted[@]}"; then
    log "✅ Upgrade verificado."
    if [[ -n "$UPSTREAM" ]]; then
      record_provenance "$UPSTREAM"
    else
      UPSTREAM=$(git -c safe.directory="$SOURCE_DIR" -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)
      [[ -z "$UPSTREAM_SLUG" ]] && UPSTREAM_SLUG=$(origin_slug)
      [[ -n "$UPSTREAM" ]] && record_provenance "$UPSTREAM"
    fi
    snapshot | sed 's/^/  /'
  else
    warn "La verificación falló — restaurando ${before[*]}"
    rollback_promotion "${before[@]}"
    if verify "${before[@]}"; then
      die "Se revirtió a la versión anterior y quedó sana. Revisa los logs del build."
    fi
    die "Rollback aplicado pero la célula no verifica. Revisa 'kubectl get pods -n $NS'."
  fi
fi

if [[ "$PHASE" == verify ]]; then
  mapfile -t wanted < <(desired_pairs)
  (( ${#wanted[@]} == ${#COMPONENTS[@]} )) || die "No se pudieron resolver los tags de todos los componentes"
  verify "${wanted[@]}" && log "✅ Verificado." || die "No verifica."
fi
