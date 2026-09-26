"""Constructor de las imágenes del core de Kaanbal durante el bootstrap.

Problema que resuelve: en una célula recién nacida no existe todavía ninguna
imagen de `kaanbal-api` ni de `kaanbal-console`, así que ArgoCD no tiene nada
que desplegar y el instalador terminaría entregando una consola muerta. Los
workflows de GitHub Actions que viajan en esos repos sí construyen la imagen,
pero solo a partir del segundo push — y dependen de que el runner de GitHub
esté disponible.

Este módulo levanta un builder efímero dentro del propio cluster (Kaniko como
Job de Kubernetes) que construye la imagen desde el repo que el instalador
acaba de publicar y la sube a Docker Hub con el mismo tag que usaría el CI
(`prod-<sha7>`). A partir de ahí, GitHub Actions toma el relevo: la primera
imagen la pone el instalador, las siguientes el pipeline.

No requiere Docker en el nodo — solo containerd, que k3s ya trae.
Solo stdlib.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

# Kaniko construye sin daemon y sin privilegios de root sobre el host.
KANIKO_IMAGE = "gcr.io/kaniko-project/executor:v1.24.0"
BUILD_NAMESPACE = "prod"
# Secret dockerconfigjson que el instalador ya crea para que el kubelet pueda
# hacer pull; Kaniko lo reutiliza para el push.
REGISTRY_SECRET = "regcred"
GIT_SECRET = "kaanbal-build-git"

# Un push rechazado por rate limit no debe tumbar toda la instalación.
BUILD_ATTEMPTS = 3
BUILD_RETRY_WAIT = 30

# Componentes del engine que el instalador debe dejar construidos.
CORE_COMPONENTS = (
    {"name": "kaanbal-api", "repo": "kaanbal-api", "dockerfile": "Dockerfile"},
    {"name": "kaanbal-console", "repo": "kaanbal-console", "dockerfile": "Dockerfile"},
    {"name": "kaanbal-agent", "repo": "kaanbal-agent", "dockerfile": "Dockerfile"},
)


class BuildError(Exception):
    pass


def _docker_hub_token(repository, username="", password=""):
    """Token de solo lectura para consultar manifests en Docker Hub."""
    url = ("https://auth.docker.io/token?service=registry.docker.io"
           f"&scope=repository:{repository}:pull")
    req = urllib.request.Request(url)
    if username and password:
        import base64
        basic = base64.b64encode(f"{username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {basic}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode()).get("token", "")
    except Exception:
        return ""


def image_exists(docker_user, repo, tag, docker_token=""):
    """¿Ya está publicada esa imagen?

    Permite que una reinstalación sobre el mismo commit no vuelva a construir.
    Ante la duda (red caída, token inválido) devuelve False: reconstruir es
    seguro, dar por buena una imagen inexistente no.
    """
    repository = f"{docker_user}/{repo}"
    token = _docker_hub_token(repository, docker_user, docker_token)
    if not token:
        return False
    url = f"https://registry-1.docker.io/v2/{repository}/manifests/{urllib.parse.quote(tag)}"
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", ", ".join([
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]))
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def build_job_manifest(component, github_org, docker_user, tag, branch="main",
                       job_name=None, kaniko_image=KANIKO_IMAGE):
    """Job de Kaniko que clona el repo en GitHub y publica en Docker Hub."""
    name = job_name or f"kaanbal-build-{component['name']}"
    repo = component["repo"]
    context = f"git://github.com/{github_org}/{repo}.git#refs/heads/{branch}"
    destination = f"index.docker.io/{docker_user}/{repo}"

    return f"""apiVersion: batch/v1
kind: Job
metadata:
  name: {name}
  namespace: {BUILD_NAMESPACE}
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
        image: {kaniko_image}
        args:
        - --context={context}
        - --dockerfile={component['dockerfile']}
        - --destination={destination}:{tag}
        - --destination={destination}:latest
        - --single-snapshot
        - --verbosity=info
        env:
        - name: GIT_USERNAME
          value: x-access-token
        - name: GIT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {GIT_SECRET}
              key: token
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: "4"
            memory: 4Gi
        volumeMounts:
        - name: docker-config
          mountPath: /kaniko/.docker
      volumes:
      - name: docker-config
        secret:
          secretName: {REGISTRY_SECRET}
          items:
          - key: .dockerconfigjson
            path: config.json
"""


def _job_status(kubectl, name):
    """(succeeded, failed, active) del Job."""
    rc, out = kubectl(
        f"-n {BUILD_NAMESPACE} get job {name} "
        "-o jsonpath='{.status.succeeded}|{.status.failed}|{.status.active}'",
        stream=False,
    )
    if rc != 0:
        return 0, 0, 0
    parts = (out or "").strip().strip("'").split("|")
    parts += ["", "", ""]

    def num(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    return num(parts[0]), num(parts[1]), num(parts[2])


def _job_logs(kubectl, name):
    rc, out = kubectl(
        f"-n {BUILD_NAMESPACE} logs job/{name} --tail=-1", stream=False, timeout=40
    )
    return out if rc == 0 else ""


def _pod_trouble(kubectl, name):
    """Motivo por el que el pod del build no arranca (ImagePullBackOff, etc.)."""
    rc, out = kubectl(
        f"-n {BUILD_NAMESPACE} get pods -l job-name={name} "
        "-o jsonpath='{.items[*].status.containerStatuses[*].state.waiting.reason}'",
        stream=False,
    )
    return (out or "").strip().strip("'") if rc == 0 else ""


# Fallos del registro que se resuelven solos: el push compite con el rate limit
# de Docker Hub o con un token que caducó a mitad de la subida. Reintentar el
# build completo es más barato que dejar la instalación a medias.
TRANSIENT_MARKERS = (
    "UNAUTHORIZED",
    "authentication required",
    "TOOMANYREQUESTS",
    "toomanyrequests",
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "i/o timeout",
    "connection reset by peer",
    "unexpected EOF",
)


def is_transient(detail):
    return any(marker in (detail or "") for marker in TRANSIENT_MARKERS)


def summarize_failure(detail, limit=300):
    """Extrae la línea que explica el fallo del ruido del clone y del build.

    Kaniko emite cientos de líneas de progreso; mostrarlas tal cual esconde el
    único renglón que dice qué pasó.
    """
    noise = ("Compressing objects", "Receiving objects", "Resolving deltas",
             "Counting objects", "remote:", "Enumerating objects",
             "Total ", "Unpacking objects")
    interesting = []
    for line in (detail or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(noise):
            continue
        interesting.append(stripped)
    if not interesting:
        return (detail or "").strip()[:limit] or "(sin logs)"
    # Los errores de Kaniko van al final; la última línea útil es la causa.
    for line in reversed(interesting):
        if "error" in line.lower() or "denied" in line.lower():
            return line[:limit]
    return interesting[-1][:limit]


def wait_for_job(kubectl, name, log_fn=None, timeout=1500, poll=6):
    """Espera al Job reenviando los logs de Kaniko a la bitácora del wizard."""
    deadline = time.time() + timeout
    emitted = 0
    last_trouble = ""

    while time.time() < deadline:
        succeeded, failed, _active = _job_status(kubectl, name)

        logs = _job_logs(kubectl, name)
        if logs:
            lines = logs.splitlines()
            for line in lines[emitted:]:
                if line.strip() and log_fn:
                    log_fn(f"  {line.strip()[:220]}")
            emitted = max(emitted, len(lines))

        if succeeded:
            return True, ""
        if failed:
            tail = "\n".join(logs.splitlines()[-15:]) if logs else "(sin logs)"
            return False, tail

        trouble = _pod_trouble(kubectl, name)
        if trouble and trouble != last_trouble:
            last_trouble = trouble
            if log_fn:
                log_fn(f"  pod del build: {trouble}", "warn")
            if "InvalidImageName" in trouble or "ErrImagePull" in trouble:
                # Kaniko mismo no se puede descargar: reintentar no ayuda.
                return False, f"No se pudo descargar el builder ({trouble})"

        time.sleep(poll)

    return False, f"El build de {name} superó {timeout // 60} minutos"


def ensure_git_secret(kubectl, apply_yaml, github_token):
    """Secret con el PAT que Kaniko usa para clonar los repos privados."""
    import base64
    encoded = base64.b64encode(github_token.encode()).decode()
    manifest = (
        "apiVersion: v1\nkind: Secret\nmetadata:\n"
        f"  name: {GIT_SECRET}\n  namespace: {BUILD_NAMESPACE}\n"
        "type: Opaque\ndata:\n"
        f"  token: {encoded}\n"
    )
    return apply_yaml(manifest, f"{GIT_SECRET}.yaml")


def resolve_pinned(docker_user, docker_token, version, components=CORE_COMPONENTS):
    """Resuelve una versión ya publicada del engine. Devuelve (tags, faltantes).

    Desplegar una release verificada es lo correcto en producción: la célula del
    cliente no gasta CPU compilando y dos instalaciones de la misma versión
    producen exactamente el mismo cluster. Construir desde fuente queda para
    quien desarrolla el propio engine.

    Si falta alguna imagen se devuelve la lista: es preferible parar a desplegar
    en silencio una versión distinta de la que se pidió.
    """
    tags, missing = {}, []
    for component in components:
        if image_exists(docker_user, component["repo"], version, docker_token):
            tags[component["name"]] = version
        else:
            missing.append(f"{docker_user}/{component['repo']}:{version}")
    return tags, missing


def build_core_images(kubectl, apply_yaml, github_org, github_token, docker_user,
                      docker_token, tags, log_fn=None, force=False,
                      components=CORE_COMPONENTS, branch="main"):
    """Construye y publica las imágenes del engine. Devuelve {componente: tag}.

    `tags` mapea nombre de componente → tag a publicar (normalmente
    `prod-<sha7>` del commit que el instalador acaba de empujar, para que
    coincida exactamente con lo que produciría GitHub Actions).
    """
    def say(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    if not (github_org and github_token):
        raise BuildError("Faltan credenciales de GitHub para construir el core")
    if not (docker_user and docker_token):
        raise BuildError("Faltan credenciales de Docker Hub para publicar el core")

    err = ensure_git_secret(kubectl, apply_yaml, github_token)
    if err:
        raise BuildError(f"No pude preparar el acceso Git del builder: {err}")

    published = {}
    for component in components:
        name = component["name"]
        tag = tags[name]

        if not force and image_exists(docker_user, component["repo"], tag, docker_token):
            say(f"{name}:{tag} ya está en Docker Hub — no hace falta reconstruir", "ok")
            published[name] = tag
            continue

        job_name = f"kaanbal-build-{name}"
        target = f"{docker_user}/{component['repo']}:{tag}"
        manifest = build_job_manifest(component, github_org, docker_user, tag, branch=branch)

        for attempt in range(1, BUILD_ATTEMPTS + 1):
            kubectl(f"-n {BUILD_NAMESPACE} delete job {job_name} --ignore-not-found=true",
                    stream=False)
            err = apply_yaml(manifest, f"{job_name}.yaml")
            if err:
                raise BuildError(f"No pude lanzar el build de {name}: {err}")

            suffix = f" (intento {attempt} de {BUILD_ATTEMPTS})" if attempt > 1 else ""
            say(f"Construyendo {name} → {target}…{suffix}")
            ok, detail = wait_for_job(kubectl, job_name, log_fn=say)
            if ok:
                break

            reason = summarize_failure(detail)
            if attempt < BUILD_ATTEMPTS and is_transient(detail):
                say(f"El registro rechazó el push de {name}: {reason}. "
                    f"Reintentando en {BUILD_RETRY_WAIT}s…", "warn")
                time.sleep(BUILD_RETRY_WAIT)
                continue
            raise BuildError(f"Falló el build de {name}: {reason}")

        say(f"{name} publicado en Docker Hub como {tag}", "ok")
        published[name] = tag

    return published
