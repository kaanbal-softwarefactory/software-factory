#!/usr/bin/env python3
"""
Kaanbal Web Installer — backend (BLUEPRINT RFC-0001 §8, experiencia guiada)
===========================================================================
Cero dependencias: solo stdlib. Un comando lo levanta en VPS o laptop:

    python3 installer/server.py            # puerto 3000, imprime URL con token

Seguridad estilo Contabo: token de sesión impreso en la terminal; toda la
API lo exige. Los pasos son idempotentes: detectan k3s/ArgoCD ya instalados
y los marcan completados, así el instalador también funciona como panel de
verificación del estado real de la célula.
"""
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corebuild            # noqa: E402  builder in-cluster de las imágenes core
import gitops_publish       # noqa: E402  publicación idempotente de los repos
import vault_bootstrap
import gitops_render        # noqa: E402  render del baseline con el dominio real

PORT = int(os.environ.get("KAANBAL_INSTALLER_PORT", "3000"))
TOKEN = os.environ.get("KAANBAL_INSTALLER_TOKEN") or secrets.token_urlsafe(18)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATE_DIR = os.environ.get("KAANBAL_INSTALLER_STATE_DIR") or os.path.expanduser("~/.kaanbal/installer")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CREDENTIALS_FILE = os.environ.get("KAANBAL_CREDENTIALS_FILE") or os.path.expanduser("~/.kaanbal/env")
PRIVILEGED = getattr(os, "geteuid", lambda: -1)() == 0 or os.environ.get("KAANBAL_INSTALLER_PRIVILEGED") == "1"
TOKEN_REVOKED = False
os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)

# Carpeta del Framework Acuaponsito (catálogo + clips). El repertorio crece
# sin redeploy: tirar un mp4 + editar catalog.json ya lo hace disponible.
_ANIM_CANDIDATES = [
    os.environ.get("KAANBAL_ANIM_DIR", ""),
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "animacion")),
]
ANIM_DIR = next((p for p in _ANIM_CANDIDATES if p and os.path.isdir(p)), None)

# Fallback si no existe carpeta animacion: los 3 clips empacados en static/media
_BUILTIN_CATALOG = {
    "version": 0, "character": "Acuaponsito",
    "states": {
        "sleep": {"desc": "dormido", "fallback": "greet"},
        "greet": {"desc": "saluda", "fallback": "idle"},
        "idle": {"desc": "neutral", "fallback": "greet"},
        "listen": {"desc": "escucha", "fallback": "idle"},
        "think": {"desc": "procesa", "fallback": "listen"},
    },
    "clips": [
        {"id": "greet__saludo", "file": "media/clip_welcome.mp4", "state": "greet",
         "description": "Saluda con la mano, bienvenida", "loop": True},
        {"id": "listen__atento", "file": "media/clip_listening.mp4", "state": "listen",
         "description": "Escucha con mano al oído", "loop": True},
        {"id": "think__proceso", "file": "media/clip_processing.mp4", "state": "think",
         "description": "Procesa información", "loop": True},
    ],
}


def load_catalog():
    """Catálogo del framework: animacion/catalog.json, o el built-in de respaldo."""
    if ANIM_DIR:
        try:
            with open(os.path.join(ANIM_DIR, "catalog.json"), encoding="utf-8") as f:
                cat = json.load(f)
            for clip in cat.get("clips", []):
                clip["url"] = "/anim/" + urllib.parse.quote(clip["file"])
            cat["source"] = "animacion"
            return cat
        except Exception as e:
            print(f"[catalog] error leyendo animacion/catalog.json: {e}")
    cat = json.loads(json.dumps(_BUILTIN_CATALOG))
    for clip in cat["clips"]:
        clip["url"] = "/" + clip["file"]
    cat["source"] = "builtin"
    return cat

# ------------------------------------------------- memoria del agente ------
# Bitácora local en formato amigable para IA: JSONL, un evento por línea.
# {ts, source, kind, ...}. Base de conocimiento que crece con TODO lo que
# pasa en el sistema (instalación, consola, acciones del usuario).
MEMORY_FILE = os.path.expanduser("~/.kaanbal/memory.jsonl")
os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
MEMORY_LOCK = threading.Lock()


def remember(source, kind, **detail):
    event = {"ts": round(time.time(), 2), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
             "source": source, "kind": kind, **detail}
    try:
        with MEMORY_LOCK, open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return event


def recall(limit=120):
    try:
        with MEMORY_LOCK, open(MEMORY_FILE, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        return []


# ----------------------------------------------------------------- estado ---
STATE_LOCK = threading.Lock()
EVENTS = []           # historial de eventos SSE (replay con ?since=)
EVENT_Q = queue.Queue()
INSTALLING = False
INSTALL_REQUEST_LOCK = threading.Lock()
PORT_FORWARD_PROC = None

STEP_IDS = ["sistema", "k3s", "nodo", "argocd", "ia", "cloudflared",
            "repos", "imagenes", "gitops", "plataforma", "acceso"]

# Subdominios del engine. Todo el núcleo vive bajo el prefijo "kaanbal-" para
# que una app de usuario (shop, shop-api…) no pueda ocupar por accidente el
# nombre de un servicio del control plane.
CORE_HOSTS = {
    "console": "kaanbal-console",   # UI para desplegar aplicaciones
    "api": "kaanbal-api",           # API del engine
    "argocd": "kaanbal-argo",       # ArgoCD
    "agent": "kaanbal-agent",       # Acuaponsito, el agente global
}
# Atajo cómodo hacia la consola. El nombre canónico es kaanbal-console.
CONSOLE_SHORTCUT = "kaanbal"
# Nombre anterior de ArgoCD: se sigue enrutando para no romper enlaces guardados.
LEGACY_ARGOCD_HOST = "argocd"
STATE = {
    "steps": {sid: {"status": "pending", "detail": ""} for sid in STEP_IDS},
    "phase": "idle",          # idle | installing | done | error
    "handoff": {},            # argocd_url, password, kubeconfig, node
    "sysinfo": {},
}

# Las claves se comparan en MAYÚSCULAS: un .env escrito a mano mezcla estilos
# (`domain=`, `github_org=`, `DOCKER_USER=`) y descartar una credencial por la
# caja de sus letras produce instalaciones a medias muy difíciles de explicar.
ENV_TO_CONFIG = {
    "DOMAIN": "domain", "KB_DOMAIN": "domain",
    "CF_TOKEN": "cf_token", "KB_CLOUDFLARE_TOKEN": "cf_token",
    "CLOUDFLARE_TOKEN": "cf_token",
    "CF_ACCOUNT_ID": "cf_account", "KB_CLOUDFLARE_ACCOUNT_ID": "cf_account",
    "CLOUDFLARE_ACCOUNT_ID": "cf_account",
    "TUNNEL_TOKEN": "tunnel_token",
    "GITOPS_URL": "gitops_url",
    "GITOPS_TOKEN": "gitops_token", "KB_GIT_TOKEN": "gitops_token",
    "GITHUB_TOKEN": "gitops_token", "GH_TOKEN": "gitops_token",
    "GITHUB_ORG": "github_org", "KB_GIT_ORG": "github_org",
    "GITHUB_WORKSPACE_ORG": "github_org",
    "GITHUB_LOGIN": "github_login", "GITHUB_USER": "github_login",
    "DOCKER_USER": "docker_user", "KB_DOCKER_USER": "docker_user",
    "DOCKERHUB_USER": "docker_user", "DOCKERHUB_USERNAME": "docker_user",
    "DOCKER_TOKEN": "docker_token", "KB_DOCKER_TOKEN": "docker_token",
    "DOCKERHUB_TOKEN": "docker_token",
    "TAILSCALE_CLIENT_ID": "tailscale_id", "KB_TAILSCALE_CLIENT_ID": "tailscale_id",
    "TAILSCALE_CLIENT_SECRET": "tailscale_secret", "KB_TAILSCALE_CLIENT_SECRET": "tailscale_secret",
    "TAILSCALE_DNS_SUFFIX": "tailscale_dns", "TAILSCALE_DNS_MAGIC": "tailscale_dns",
    "TAILSCALE_DNS": "tailscale_dns",
    "KAANBAL_ADMIN_USER": "admin_user",
    "KAANBAL_ADMIN_PASS": "admin_pass",
    # El primer usuario de la consola es también con quien habla Acuaponsito,
    # así que `agente-*` y `admin_*` nombran la misma cuenta.
    "AGENTE_USER": "admin_user", "AGENTE-USER": "admin_user",
    "AGENT_USER": "admin_user",
    "AGENTE_PASSWORD": "admin_pass", "AGENTE-PASSWORD": "admin_pass",
    "AGENT_PASSWORD": "admin_pass",
    # Forma de operar la célula: el wizard las pregunta, en desatendido vienen
    # del archivo.
    "KAANBAL_MODE": "mode", "MODE": "mode",
    "KAANBAL_CONSOLE_EXPOSURE": "console_exposure",
    "CONSOLE_EXPOSURE": "console_exposure",
    "KAANBAL_API_EXPOSURE": "api_exposure",
    "API_EXPOSURE": "api_exposure",
    "KAANBAL_AGENT_EXPOSURE": "agent_exposure",
    "AGENT_EXPOSURE": "agent_exposure",
    # Vacío = construir las imágenes del engine desde el código fuente.
    "KAANBAL_CORE_VERSION": "core_version", "CORE_VERSION": "core_version",
    # Claves de los proveedores de IA del agente.
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
}
CONFIG_TO_ENV = {
    "domain": "DOMAIN", "cf_token": "CF_TOKEN", "cf_account": "CF_ACCOUNT_ID",
    "tunnel_token": "TUNNEL_TOKEN", "gitops_url": "GITOPS_URL",
    "gitops_token": "GITOPS_TOKEN", "github_org": "GITHUB_ORG",
    "github_login": "GITHUB_LOGIN",
    "docker_user": "DOCKER_USER", "docker_token": "DOCKER_TOKEN",
    "tailscale_id": "TAILSCALE_CLIENT_ID", "tailscale_secret": "TAILSCALE_CLIENT_SECRET",
    "tailscale_dns": "TAILSCALE_DNS_SUFFIX", "admin_user": "KAANBAL_ADMIN_USER",
    "admin_pass": "KAANBAL_ADMIN_PASS",
    "mode": "KAANBAL_MODE", "console_exposure": "KAANBAL_CONSOLE_EXPOSURE",
    "api_exposure": "KAANBAL_API_EXPOSURE", "agent_exposure": "KAANBAL_AGENT_EXPOSURE",
    "core_version": "KAANBAL_CORE_VERSION",
    "deepseek_api_key": "DEEPSEEK_API_KEY", "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
}
SECRET_CONFIG_KEYS = {
    "cf_token", "tunnel_token", "gitops_token", "docker_token",
    "tailscale_secret", "admin_pass",
    "deepseek_api_key", "openai_api_key", "anthropic_api_key",
}

# Clave del archivo que guarda la API key de cada proveedor de IA soportado.
AI_KEY_CONFIG = {
    "deepseek": "deepseek_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}


def _state_snapshot():
    """Estado recuperable sin credenciales ni contraseñas de handoff."""
    snapshot = json.loads(json.dumps(STATE))
    snapshot.pop("ai_providers", None)
    if "handoff" in snapshot:
        snapshot["handoff"].pop("argocd_password", None)
    return snapshot


def persist_state():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state_snapshot(), f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"[state] no se pudo persistir: {e}", file=sys.stderr)


def load_persisted_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            STATE.update({k: v for k, v in saved.items() if k in STATE})
            if STATE.get("phase") == "installing":
                STATE["phase"] = "error"
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def parse_env_text(text):
    values = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[7:].strip()
        key = key.upper()
        value = value.strip().strip("'\"")
        config_key = ENV_TO_CONFIG.get(key)
        if config_key and value:
            values[config_key] = value
    return values


def load_credentials():
    try:
        with open(CREDENTIALS_FILE, encoding="utf-8") as f:
            return parse_env_text(f.read())
    except FileNotFoundError:
        return {}


def save_credentials(config):
    current = load_credentials()
    current.update({k: str(v) for k, v in config.items() if k in CONFIG_TO_ENV and v is not None})
    os.makedirs(os.path.dirname(CREDENTIALS_FILE), mode=0o700, exist_ok=True)
    tmp = CREDENTIALS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Kaanbal installer credentials - root only\n")
        for key, env_name in CONFIG_TO_ENV.items():
            value = current.get(key, "")
            safe = str(value).replace("\n", "").replace("\r", "")
            f.write(f"{env_name}={safe}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CREDENTIALS_FILE)
    return current


def credentials_status():
    creds = load_credentials()
    return {
        "configured": sorted(k for k, v in creds.items() if v),
        "secret_configured": sorted(k for k in SECRET_CONFIG_KEYS if creds.get(k)),
        "values": {k: v for k, v in creds.items() if k not in SECRET_CONFIG_KEYS},
    }


load_persisted_state()


def emit(kind, **payload):
    """Registrar evento para SSE (log de terminal o cambio de paso)."""
    event = {"kind": kind, "ts": round(time.time(), 2), **payload}
    with STATE_LOCK:
        EVENTS.append(event)
    EVENT_Q.put(event)
    # persistir en la memoria del agente (sin el ruido de stdout crudo)
    if not (kind == "log" and payload.get("level") in ("out", "cmd")):
        remember("installer", kind, **payload)
    persist_state()


def log(line, level="info"):
    emit("log", line=redact(line), level=level)


def set_step(step_id, status, detail=""):
    with STATE_LOCK:
        STATE["steps"][step_id] = {"status": status, "detail": detail}
    emit("step", step=step_id, status=status, detail=detail)


def set_phase(phase):
    with STATE_LOCK:
        STATE["phase"] = phase
    emit("phase", phase=phase)


# ------------------------------------------------------------ shell helpers ---
def redact(value):
    text = str(value or "")
    candidates = [TOKEN]
    try:
        creds = load_credentials()
        candidates.extend(creds.get(k, "") for k in SECRET_CONFIG_KEYS)
    except Exception:
        pass
    for secret in sorted((s for s in candidates if s), key=len, reverse=True):
        text = text.replace(secret, "***")
        text = text.replace(urllib.parse.quote(secret, safe=""), "***")
    text = re.sub(r"(https://[^:/@\s]+:)[^@\s]+(@)", r"\1***\2", text)
    return text


def run(cmd, timeout=120, stream=False):
    """Ejecutar comando; si stream=True, mandar stdout línea a línea al log."""
    log(f"$ {redact(cmd)}", "cmd")
    proc = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    lines = []
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line:
                lines.append(line)
                if stream:
                    log(line, "out")
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Timeout ({timeout}s): {redact(cmd)}")
    return proc.returncode, redact("\n".join(lines))


def kubectl(args, timeout=60, stream=False):
    return run(f"k3s kubectl {args}", timeout=timeout, stream=stream)


# ------------------------------------------------------------- validaciones ---
def http_json(url, headers=None, data=None, auth=None, timeout=15, method=""):
    req = urllib.request.Request(url, headers=headers or {})
    if auth:
        import base64
        cred = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    if data is not None:
        req.data = data.encode() if isinstance(data, str) else data
        req.method = "POST"
    if method:
        req.method = method
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def validate_cloudflare(token, account_id):
    """Mismas comprobaciones que kaanbal-api /setup/validate/cloudflare."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    status, acc = http_json(f"https://api.cloudflare.com/client/v4/accounts/{account_id}", headers)
    if status == 0:
        return {"valid": False, "message": f"Sin conexión a Cloudflare: {acc.get('error')}"}
    if status in (401, 403):
        return {"valid": False, "message": "Token inválido o sin permiso 'Account Settings: Read'."}
    if status != 200:
        return {"valid": False, "message": f"Cuenta '{account_id}' no accesible (HTTP {status}). Verifica el Account ID."}
    name = acc.get("result", {}).get("name", account_id)
    t_status, _ = http_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel?is_deleted=false&per_page=1", headers)
    z_status, zones = http_json(
        f"https://api.cloudflare.com/client/v4/zones?account.id={account_id}&per_page=5", headers)
    zone_names = [z.get("name", "") for z in zones.get("result", [])] if z_status == 200 else []
    if t_status == 200 and z_status == 200:
        zonas = ", ".join(zone_names) if zone_names else "sin zonas aún"
        return {"valid": True, "message": f"Cuenta '{name}' OK. Túneles ✓ DNS ✓. Zonas: {zonas}.", "zones": zone_names}
    if t_status == 200:
        return {"valid": True, "message": f"Cuenta '{name}' OK. Túneles ✓. Falta confirmar permiso DNS."}
    return {"valid": False, "message": f"Cuenta '{name}' encontrada pero faltan permisos Tunnel/DNS en el token."}


# ── Cloudflare CONTROL PLANE: crear túnel + ingress + DNS (portado de setup.py) ──
# Ésta es la pieza que hace que el DOMINIO cobre vida. El túnel abre una conexión
# SALIENTE al edge de Cloudflare (sin IP pública, sin abrir puertos): mientras la
# máquina esté encendida, Cloudflare enruta *.dominio hacia el Traefik de k3s.
def _cf(method, url, token, body=None, timeout=30):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, headers=headers, method=method)
    if body is not None:
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def create_cloudflare_tunnel(token, account_id, domain, hostname, log_fn=None):
    """Crea (o reutiliza) el túnel, configura ingress y DNS wildcard.
    Devuelve {tunnel_id, tunnel_token, dns:[...], zone_id} o {error}."""
    import base64 as _b64
    say = log_fn or (lambda *a, **k: None)
    cf = "https://api.cloudflare.com/client/v4"
    tunnel_name = f"kaanbal-{hostname}".lower().replace(" ", "-")[:60]

    # ¿ya existe un túnel con ese nombre? reutilizar (idempotente en re-instalación)
    st, lst = _cf("GET", f"{cf}/accounts/{account_id}/cfd_tunnel?name={urllib.parse.quote(tunnel_name)}&is_deleted=false", token)
    tunnel_id = tunnel_token = None
    if st == 200 and lst.get("result"):
        tunnel_id = lst["result"][0]["id"]
        stt, tk = _cf("GET", f"{cf}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token", token)
        tunnel_token = tk.get("result") if stt == 200 else None
        say(f"Túnel existente reutilizado: {tunnel_name}", "info")
    if not tunnel_id:
        secret = _b64.b64encode(secrets.token_bytes(32)).decode()
        st, cr = _cf("POST", f"{cf}/accounts/{account_id}/cfd_tunnel", token,
                     {"name": tunnel_name, "tunnel_secret": secret})
        if st != 200:
            errs = cr.get("errors", [])
            return {"error": errs[0].get("message") if errs else f"HTTP {st} al crear el túnel"}
        tunnel_id = cr["result"]["id"]
        tunnel_token = cr["result"].get("token")
        say(f"Túnel creado en Cloudflare: {tunnel_name}", "ok")

    # ArgoCD necesita regla propia porque habla HTTPS con certificado interno;
    # el resto del dominio entra por Traefik, que ya enruta por Ingress.
    traefik = "http://traefik.kube-system.svc.cluster.local:80"
    argocd_backend = {
        "service": "https://argocd-server.argocd.svc.cluster.local:443",
        "originRequest": {"noTLSVerify": True},
    }
    ingress = [
        {"hostname": f"{CORE_HOSTS['argocd']}.{domain}", **argocd_backend},
        {"hostname": f"{LEGACY_ARGOCD_HOST}.{domain}", **argocd_backend},
        {"hostname": f"*.{domain}", "service": traefik},
        {"hostname": domain, "service": traefik},
        {"service": "http_status:404"},
    ]
    st, _ = _cf("PUT", f"{cf}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", token,
                {"config": {"ingress": ingress}})
    if st == 200:
        say("Reglas de ingress configuradas (*.dominio → Traefik, argocd.dominio → ArgoCD)", "ok")

    # DNS: wildcard + raíz + argocd como CNAME al túnel (proxied → HTTPS de Cloudflare)
    st, zr = _cf("GET", f"{cf}/zones?name={domain}", token)
    zone_id = (zr.get("result") or [{}])[0].get("id") if st == 200 else None
    dns = []
    if zone_id:
        target = f"{tunnel_id}.cfargotunnel.com"
        for name in [f"*.{domain}", domain,
                     f"{CORE_HOSTS['argocd']}.{domain}",
                     f"{LEGACY_ARGOCD_HOST}.{domain}"]:
            ste, ex = _cf("GET", f"{cf}/zones/{zone_id}/dns_records?type=CNAME&name={urllib.parse.quote(name)}", token)
            recs = ex.get("result", []) if ste == 200 else []
            rec = {"type": "CNAME", "name": name, "content": target, "proxied": True}
            if recs:
                _cf("PUT", f"{cf}/zones/{zone_id}/dns_records/{recs[0]['id']}", token, rec)
            else:
                _cf("POST", f"{cf}/zones/{zone_id}/dns_records", token, rec)
            dns.append(name)
        say(f"DNS apuntado a tu célula: {', '.join(dns)}", "ok")
    else:
        say(f"⚠ No encontré la zona '{domain}' en Cloudflare — ¿ya la agregaste y está Active?", "warn")
    return {"tunnel_id": tunnel_id, "tunnel_token": tunnel_token, "dns": dns, "zone_id": zone_id}


# Sin llaves de flujo YAML a propósito: este texto se escribe tal cual, no pasa
# por str.format(), y unas llaves dobles heredadas de una plantilla producían un
# manifiesto inválido que kubectl rechazaba en silencio.
CLOUDFLARED_DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudflared
  namespace: prod
  labels:
    app: cloudflared
    app.kubernetes.io/part-of: kaanbal
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cloudflared
  template:
    metadata:
      labels:
        app: cloudflared
    spec:
      containers:
        - name: cloudflared
          image: cloudflare/cloudflared:latest
          args: ["tunnel", "--no-autoupdate", "--metrics", "0.0.0.0:2000", "run"]
          env:
            - name: TUNNEL_TOKEN
              valueFrom:
                secretKeyRef:
                  name: cloudflared-secrets
                  key: TUNNEL_TOKEN
          ports:
            - containerPort: 2000
              name: metrics
          resources:
            requests:
              cpu: 10m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
          livenessProbe:
            httpGet:
              path: /ready
              port: 2000
            initialDelaySeconds: 10
            periodSeconds: 10
            failureThreshold: 3
"""


def _github_headers(token):
    """Classic PAT (ghp_…) y fine-grained (github_pat_…) usan prefijos distintos."""
    t = (token or "").strip()
    auth = f"token {t}" if t.startswith(("ghp_", "gho_", "ghu_", "ghs_", "ghr_")) else f"Bearer {t}"
    return {
        "Authorization": auth,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# Raíz SOFTWARE_FACTORY (installer/..) — fuente local para bootstrap de repos core
SF_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def tunnel_id_from_token(token):
    """Id del túnel contenido en un token de cloudflared, o "".

    El token es base64 de {"a": cuenta, "t": túnel, "s": secreto}. Se decodifica
    solo para leer "t"; el secreto nunca se registra.
    """
    import base64 as _b64
    raw = (token or "").strip()
    if not raw:
        return ""
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(_b64.b64decode(padded).decode("utf-8"))
        return str(data.get("t") or "")
    except Exception:
        return ""


def upstream_sha():
    """Commit del monorepo desde el que corre este instalador, o "".

    install.sh deja el checkout como repo git, así que el SHA está disponible.
    Es la procedencia que la célula guarda para poder compararse con upstream
    (ADR-002). Si no se puede leer, se reporta vacío en vez de inventarlo: una
    procedencia falsa haría que la célula se creyera al día para siempre.
    """
    repo_root = os.path.normpath(os.path.join(SF_ROOT, ".."))
    try:
        # El instalador corre como root sobre un checkout de otro usuario; sin
        # safe.directory git aborta con "dubious ownership" y la célula nacería
        # sin procedencia.
        out = subprocess.run(
            ["git", "-c", f"safe.directory={repo_root}", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def slug_from_remote(url):
    """'https://[credenciales@]github.com/owner/repo[.git]' o 'git@github.com:owner/repo.git'
    -> 'owner/repo'. Vacío si no es un remoto de GitHub."""
    text = (url or "").strip()
    if "github.com" not in text:
        return ""
    text = text.rsplit("github.com", 1)[1].lstrip(":/")
    if text.endswith(".git"):
        text = text[: -len(".git")]
    parts = text.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 and all(parts[:2]) else ""


def upstream_slug():
    """Repo (owner/repo) del que salió el checkout de este instalador, o "".

    Junto con el SHA es la procedencia completa: un SHA solo no dice contra qué
    historial compararlo, y el proyecto ya cambió de casa una vez.
    """
    repo_root = os.path.normpath(os.path.join(SF_ROOT, ".."))
    try:
        out = subprocess.run(
            ["git", "-c", f"safe.directory={repo_root}", "-C", repo_root, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=15,
        )
        return slug_from_remote(out.stdout) if out.returncode == 0 else ""
    except Exception:
        return ""


# Fuente de verdad GitOps: repos mínimos que la célula reconcilia vía ramas/overlays
GITHUB_CORE_REPOS = (
    ("infra-gitops", True),
    ("kaanbal-api", True),
    ("kaanbal-console", True),
    ("kaanbal-agent", True),
    ("kaanbal-templates", True),
)


def _github_api(method, path, token, body=None, timeout=25):
    headers = _github_headers(token)
    url = f"https://api.github.com{path}"
    data = None
    if body is not None:
        headers = {**headers, "Content-Type": "application/json"}
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, headers=headers, data=data, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode() or "{}"
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _github_can_bootstrap(token, org, login):
    """¿Puede crear repos en la org/cuenta elegida?"""
    if org.lower() == login.lower():
        return True, "cuenta personal"
    st, mem = _github_api("GET", f"/user/memberships/orgs/{org}", token)
    if st == 200 and mem.get("state") == "active":
        role = mem.get("role", "member")
        return role == "admin", role
    return False, "sin membresía activa"


def _scan_github_core_repos(token, org):
    existing, missing = [], []
    headers = _github_headers(token)
    for name, required in GITHUB_CORE_REPOS:
        st, _ = http_json(f"https://api.github.com/repos/{org}/{name}", headers)
        local_ok = os.path.isdir(os.path.join(SF_ROOT, name))
        if st == 200:
            existing.append(name)
        elif required or local_ok:
            missing.append(name)
    return existing, missing


def _push_local_repo(token, org, repo_name, local_path, log_fn=None):
    import tempfile
    work = tempfile.mkdtemp(prefix=f"kaanbal-bootstrap-{repo_name}-")
    try:
        ignore = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv")
        shutil.copytree(local_path, os.path.join(work, "src"), ignore=ignore)
        auth = urllib.parse.quote(token, safe="")
        auth_url = f"https://x-access-token:{auth}@github.com/{org}/{repo_name}.git"
        steps = [
            f"cd '{work}/src' && git init -b main",
            f"cd '{work}/src' && git config user.email 'kaanbal@local'",
            f"cd '{work}/src' && git config user.name 'Kaanbal Installer'",
            f"cd '{work}/src' && git add -A",
            f"cd '{work}/src' && git commit -m 'bootstrap: kaanbal {repo_name} from installer'",
            f"cd '{work}/src' && git remote add origin '{auth_url}'",
            f"cd '{work}/src' && git push -u origin main",
        ]
        for cmd in steps:
            rc, out = run(cmd, timeout=300)
            if "commit" in cmd and rc != 0 and ("nothing to commit" in out or "nothing added" in out):
                continue
            if rc != 0:
                return f"Falló push de {repo_name}: {(out or '')[:400]}"
        if log_fn:
            log_fn(f"Código inicial publicado en {org}/{repo_name}", "ok")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def bootstrap_github_core(token, org, login, log_fn=None, create_only=False):
    """Crea los repos core que falten en GitHub.

    Con `create_only` se limita a crearlos vacíos: el contenido lo publica
    después `gitops_publish`, que sabe distinguir entre sembrar un repo nuevo y
    refrescar el baseline de uno que ya está en uso.
    """
    def say(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    existing, missing = _scan_github_core_repos(token, org)
    if not missing:
        return {"ok": True, "created": [], "existing": existing, "missing": []}

    can, role = _github_can_bootstrap(token, org, login)
    if not can:
        return {
            "ok": False,
            "error": (f"Faltan repos en {org} ({', '.join(missing)}) y tu token no puede crearlos "
                      f"(rol: {role}). Usa PAT classic con scope repo como admin de la org."),
            "missing": missing,
        }

    is_org = org.lower() != login.lower()
    created = []
    for name in missing:
        local = os.path.join(SF_ROOT, name)
        if not os.path.isdir(local):
            say(f"⚠ {name}: sin fuente local en el instalador — se omite", "warn")
            continue
        say(f"Creando repo {org}/{name}…")
        path = f"/orgs/{org}/repos" if is_org else "/user/repos"
        st, body = _github_api("POST", path, token, {
            "name": name,
            "private": True,
            "auto_init": False,
            "description": f"Kaanbal core — {name} (GitOps source of truth)",
        })
        if st not in (200, 201):
            msg = body.get("message", "") if isinstance(body, dict) else ""
            if st != 422:
                return {"ok": False, "error": f"No pude crear {org}/{name} (HTTP {st}): {msg}", "missing": missing}
            say(f"Repo {org}/{name} ya existía — publicando código…", "info")
        else:
            created.append(name)
            say(f"Repo creado: {org}/{name}", "ok")
        if create_only:
            continue
        err = _push_local_repo(token, org, name, local, log_fn=say)
        if err:
            return {"ok": False, "error": err, "missing": missing, "created": created}

    return {"ok": True, "created": created, "existing": existing, "missing": []}


def _github_namespaces(token, login, user):
    """Cuenta personal + organizaciones visibles para el token."""
    headers = _github_headers(token)
    namespaces = [{
        "login": login,
        "type": "user",
        "avatar_url": user.get("avatar_url", ""),
        "label": f"{login} (personal)",
    }]
    st_orgs, orgs = http_json("https://api.github.com/user/orgs?per_page=100", headers)
    if st_orgs == 200 and isinstance(orgs, list):
        for org in orgs:
            name = org.get("login", "")
            if name and name.lower() != login.lower():
                namespaces.append({
                    "login": name,
                    "type": "org",
                    "avatar_url": org.get("avatar_url", ""),
                    "label": name,
                })
    elif st_orgs in (401, 403):
        return namespaces, "El token no puede listar organizaciones — agrega scope read:org (classic) o acceso a la org (fine-grained)."
    return namespaces, None


def validate_github(token, org="", repo="infra-gitops"):
    token = (token or "").strip()
    if not token:
        return {"valid": False, "message": "Pega tu Personal Access Token de GitHub."}

    headers = _github_headers(token)
    status, user = http_json("https://api.github.com/user", headers)
    if status != 200:
        hint = ""
        if status == 401:
            hint = " Token inválido o expirado."
        elif status == 403:
            hint = " Token sin permisos suficientes."
        return {"valid": False, "message": f"GitHub rechazó el token (HTTP {status}).{hint}"}

    login = user.get("login", "?")
    email = user.get("email")
    if not email:
        st2, emails = http_json("https://api.github.com/user/emails", headers)
        if st2 == 200 and isinstance(emails, list):
            primary = next((e["email"] for e in emails if e.get("primary")), None)
            email = primary or (emails[0]["email"] if emails else None)

    namespaces, org_warn = _github_namespaces(token, login, user)
    email_bit = f" · {email}" if email else ""
    org = (org or "").strip()
    repo = (repo or "infra-gitops").strip() or "infra-gitops"

    if not org:
        msg = f"Conectado como '{login}'{email_bit}. Elige la org donde instalar Kaanbal core."
        if org_warn:
            msg += f" {org_warn}"
        return {
            "valid": False,
            "needs_org": True,
            "message": msg,
            "login": login,
            "email": email,
            "namespaces": namespaces,
        }

    existing, missing = _scan_github_core_repos(token, org)
    core_repos = [{"name": n, "status": "ok"} for n in existing] + [{"name": n, "status": "missing"} for n in missing]
    gitops_url = f"https://github.com/{org}/{repo}.git"
    scope = "organización" if org.lower() != login.lower() else "cuenta personal"
    base = {
        "login": login,
        "email": email,
        "org": org,
        "is_org": org.lower() != login.lower(),
        "gitops_url": gitops_url,
        "repo": repo,
        "namespaces": namespaces,
        "core_repos": core_repos,
        "existing_repos": existing,
        "missing_repos": missing,
    }

    if not missing:
        st_repo, repo_info = http_json(f"https://api.github.com/repos/{org}/{repo}", headers)
        branch = repo_info.get("default_branch", "main") if st_repo == 200 else "main"
        return {
            **base,
            "valid": True,
            "bootstrap_needed": False,
            "default_branch": branch,
            "message": (f"GitOps listo en {scope} {org}: {len(existing)} repos core presentes. "
                        f"Conectado como {login}{email_bit}."),
        }

    can_bootstrap, role = _github_can_bootstrap(token, org, login)
    if can_bootstrap:
        return {
            **base,
            "valid": True,
            "bootstrap_needed": True,
            "can_create_repos": True,
            "message": (f"Org {org} OK — faltan {len(missing)} repos core "
                        f"({', '.join(missing)}). Se crearán al instalar la célula."),
        }

    return {
        **base,
        "valid": False,
        "needs_org": True,
        "bootstrap_needed": True,
        "can_create_repos": False,
        "message": (f"Faltan repos en {org}: {', '.join(missing)}. "
                    f"Tu token no puede crearlos (rol: {role}). "
                    "Usa PAT classic con scope repo como admin de la org, o créalos manualmente."),
    }


# ── Agent Studio: flujos de trabajo y roles (replicables en cualquier app) ──
WORKFLOWS = {
    "general": {
        "name": "Asistente general", "icon": "🌱",
        "instructions": "Ayuda al usuario con su plataforma. Sé claro, breve y práctico.",
    },
    "ciencia": {
        "name": "Validación científica", "icon": "🔬",
        "instructions": ("Modo científico riguroso: exige evidencia, distingue hecho de hipótesis, "
                         "sugiere validar afirmaciones con DOI/fuentes primarias y di explícitamente "
                         "cuando NO tengas certeza. Nivel de conservadurismo: {conservadurismo}/10 "
                         "(a mayor nivel, más escéptico y más pedirás fuentes)."),
    },
    "infra": {
        "name": "Vigilancia de infraestructura", "icon": "📡",
        "instructions": ("Analiza el estado del cluster (nodos, pods, fases) del contexto adjunto. "
                         "Detecta anomalías (restarts, pods no Ready) y propone diagnóstico y siguiente paso."),
    },
    "dev": {
        "name": "Desarrollo asistido", "icon": "⚙️",
        "instructions": ("Modo dev estilo pair-programming: propone cambios concretos con criterios de "
                         "aceptación. NUNCA asumas que puedes aplicar cambios: tu modo de operación actual "
                         "es {modo}; si no es 'dev' o superior, solo propones."),
    },
    "mejora": {
        "name": "Registrar mejora", "icon": "📋",
        "instructions": ("Skill de automejora de la plataforma: convierte la idea del usuario en una ficha "
                         "de desarrollo. Tu 'say' DEBE tener este formato con saltos de línea:\n"
                         "IDEA: <resumen 1 línea>\nIMPACTO: <quién se beneficia>\n"
                         "TAREAS:\n1. ...\n2. ...\n3. ...\nRIESGOS: <1 línea>\n"
                         "ROLES: <subagentes sugeridos>\nACEPTACIÓN: <criterio verificable>"),
    },
}

ROLES = {
    "orquestador": {"name": "Orquestador", "icon": "🧠", "desc": "Contexto completo; decide y delega. No ejecuta directo."},
    "arquitecto": {"name": "Arquitecto", "icon": "🏗️", "desc": "Diseño de sistema, trade-offs, deuda técnica."},
    "seguridad": {"name": "Seguridad", "icon": "🛡️", "desc": "Amenazas, secretos, permisos, superficies expuestas."},
    "qa": {"name": "QA / Tester", "icon": "🧪", "desc": "Casos de prueba, criterios de aceptación, regresiones."},
    "frontend": {"name": "Dev Frontend", "icon": "🎨", "desc": "UI/UX, componentes, accesibilidad."},
    "backend": {"name": "Dev Backend", "icon": "🔌", "desc": "APIs, datos, contratos, rendimiento."},
    "devops": {"name": "DevOps", "icon": "☸️", "desc": "Pipelines, GitOps, clusters, observabilidad."},
    "datos": {"name": "Data / ML", "icon": "📊", "desc": "Datos, features, entrenamientos, métricas de modelos."},
    "cientifico": {"name": "Científico", "icon": "🔬", "desc": "Rigor metodológico, DOI, reproducibilidad."},
}

# ── Agente IA: proveedores LLM (parte del instalador Y del sistema) ──────────
AI_PROVIDERS = {
    "deepseek": {
        "base": "https://api.deepseek.com", "models_path": "/models",
        "chat_path": "/chat/completions", "default_model": "deepseek-chat", "style": "openai",
    },
    "openai": {
        "base": "https://api.openai.com", "models_path": "/v1/models",
        "chat_path": "/v1/chat/completions", "default_model": "gpt-4o-mini", "style": "openai",
    },
    "anthropic": {
        "base": "https://api.anthropic.com", "models_path": "/v1/models",
        "chat_path": "/v1/messages", "default_model": "claude-haiku-4-5-20251001", "style": "anthropic",
    },
}


def _ai_headers(provider, api_key):
    if AI_PROVIDERS[provider]["style"] == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def validate_ai(provider, api_key):
    """Valida la API key listando modelos del proveedor."""
    if provider not in AI_PROVIDERS:
        return {"valid": False, "message": f"Proveedor desconocido: {provider}"}
    p = AI_PROVIDERS[provider]
    status, resp = http_json(p["base"] + p["models_path"], _ai_headers(provider, api_key))
    if status == 200:
        models = [m.get("id", "") for m in resp.get("data", [])][:6]
        with STATE_LOCK:
            existing = [x for x in STATE.setdefault("ai_providers", []) if x["provider"] != provider]
            STATE["ai_providers"] = existing + [{"provider": provider, "api_key": api_key,
                                                 "model": p["default_model"]}]
        return {"valid": True, "message": f"✓ {provider} conectado. Modelos: {', '.join(models[:4])}…",
                "models": models, "default_model": p["default_model"]}
    if status in (401, 403):
        return {"valid": False, "message": f"API key de {provider} inválida (HTTP {status})."}
    return {"valid": False, "message": f"{provider} respondió HTTP {status}: {str(resp)[:140]}"}


def _catalog_for_llm():
    """Catálogo compacto para el system prompt (id + descripción)."""
    cat = load_catalog()
    states = ", ".join(cat.get("states", {}).keys())
    lines = [f'- {c["id"]}: {c.get("description", c.get("title", ""))[:140]}' for c in cat.get("clips", [])]
    return states, "\n".join(lines)


def _ai_call(provider, api_key, model, system, messages, max_tokens=700):
    """Llamada genérica de chat a cualquier proveedor. Devuelve (texto, error)."""
    p = AI_PROVIDERS[provider]
    model = model or p["default_model"]
    if p["style"] == "anthropic":
        body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                           "messages": messages})
        status, resp = http_json(p["base"] + p["chat_path"], _ai_headers(provider, api_key), data=body, timeout=60)
        if status != 200:
            return None, f"{provider} HTTP {status}: {str(resp)[:200]}"
        return resp.get("content", [{}])[0].get("text", ""), None
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": system}] + messages})
    status, resp = http_json(p["base"] + p["chat_path"], _ai_headers(provider, api_key), data=body, timeout=60)
    if status != 200:
        return None, f"{provider} HTTP {status}: {str(resp)[:200]}"
    return resp.get("choices", [{}])[0].get("message", {}).get("content", ""), None


def _parse_contract(text):
    """Extrae el contrato JSON {say, state, clip} de la respuesta del LLM."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if match:
        try:
            out = json.loads(match.group(0))
            return {"say": out.get("say", text), "state": out.get("state", "idle"),
                    "clip": out.get("clip"), "raw": text}
        except json.JSONDecodeError:
            pass
    return {"say": (text or "").strip(), "state": "speak", "clip": None, "raw": text}


def _observe_cache():
    return getattr(_observe_cache, "data", None)


def observe():
    """Snapshot REAL del sistema para el agente: nodos, pods, fases. Cache 6s."""
    cached = getattr(observe, "_cache", None)
    if cached and time.time() - cached[0] < 6:
        return cached[1]
    snap = {"ts": round(time.time(), 2), "nodes": [], "namespaces": {}, "totals": {}}
    rc, out = run("k3s kubectl get nodes -o json 2>/dev/null", timeout=25)
    if rc == 0 and out.strip().startswith("{"):
        try:
            for n in json.loads(out).get("items", []):
                conds = {c["type"]: c["status"] for c in n["status"].get("conditions", [])}
                snap["nodes"].append({
                    "name": n["metadata"]["name"],
                    "ready": conds.get("Ready") == "True",
                    "cpu": n["status"].get("capacity", {}).get("cpu"),
                    "memory": n["status"].get("capacity", {}).get("memory"),
                    "version": n["status"].get("nodeInfo", {}).get("kubeletVersion"),
                })
        except Exception:
            pass
    rc, out = run("k3s kubectl get pods -A -o json 2>/dev/null", timeout=30)
    running = total = 0
    if rc == 0 and out.strip().startswith("{"):
        try:
            for p in json.loads(out).get("items", []):
                ns = p["metadata"]["namespace"]
                phase = p["status"].get("phase", "?")
                restarts = sum(cs.get("restartCount", 0) for cs in p["status"].get("containerStatuses", []))
                snap["namespaces"].setdefault(ns, []).append({
                    "name": p["metadata"]["name"], "phase": phase, "restarts": restarts,
                })
                total += 1
                running += phase == "Running"
        except Exception:
            pass
    snap["totals"] = {"pods": total, "running": running, "namespaces": len(snap["namespaces"])}
    with STATE_LOCK:
        snap["phase"] = STATE["phase"]
    observe._cache = (time.time(), snap)
    return snap


def _observe_summary():
    s = observe()
    nodes = "; ".join(f'{n["name"]} Ready={n["ready"]} cpu={n["cpu"]} {n["version"]}' for n in s["nodes"]) or "sin nodos"
    ns_lines = []
    for ns, pods in s["namespaces"].items():
        bad = [p for p in pods if p["phase"] != "Running" or p["restarts"] > 3]
        line = f"{ns}: {len(pods)} pods"
        if bad:
            line += " (atención: " + ", ".join(f'{p["name"]}={p["phase"]}/r{p["restarts"]}' for p in bad[:4]) + ")"
        ns_lines.append(line)
    return f"Nodos: {nodes}. Pods {s['totals']['running']}/{s['totals']['pods']} Running. " + " | ".join(ns_lines)


def ai_chat(body):
    """Chat del agente con flujo de trabajo, rol, scopes y contexto real."""
    providers = STATE.get("ai_providers") or []
    entry = None
    if body.get("provider") and body.get("api_key"):
        entry = {"provider": body["provider"], "api_key": body["api_key"], "model": body.get("model", "")}
    elif providers:
        entry = providers[0]
    if not entry:
        return {"error": "sin-proveedor", "message": "Conecta un proveedor de IA primero (paso Agente IA del instalador)."}

    wf = WORKFLOWS.get(body.get("workflow", "general"), WORKFLOWS["general"])
    role = ROLES.get(body.get("role", "orquestador"), ROLES["orquestador"])
    scopes = body.get("scopes", {})
    modo = body.get("modo", "asistido")
    conservadurismo = body.get("conservadurismo", 7)

    states, clips = _catalog_for_llm()
    context_blocks = []
    if scopes.get("infra", True):
        context_blocks.append("INFRAESTRUCTURA REAL AHORA: " + _observe_summary())
    if scopes.get("actividad", True):
        tail = recall(25)
        acts = "; ".join(f'{e.get("iso", "?")[-8:]} {e.get("source")}/{e.get("kind")} {e.get("step", e.get("line", ""))[:60]}'
                         for e in tail[-12:])
        context_blocks.append("ACTIVIDAD RECIENTE (memoria JSONL): " + (acts or "sin eventos"))
    context_blocks.append(f"CONTEXTO DE UBICACIÓN: consola del agente Kaanbal, célula '{socket.gethostname().lower()}', "
                          f"modo de operación '{modo}' (asistido=solo propones; dev=puedes proponer cambios aplicables en dev; "
                          f"staging/prod requieren aprobación explícita).")

    system = (
        f"Eres Acuaponsito, el agente de plataforma de Kaanbal (open source, para científicos y makers). "
        f"Rol activo: {role['name']} — {role['desc']}\n"
        f"Flujo de trabajo: {wf['name']}. Instrucciones del flujo: "
        + wf["instructions"].format(conservadurismo=conservadurismo, modo=modo) + "\n\n"
        + "\n".join(context_blocks) + "\n\n"
        "Respondes SIEMPRE un único JSON válido sin markdown:\n"
        '{"say": "<respuesta útil en español; puede ser multilínea>", "state": "<estado>", "clip": "<id opcional>"}\n'
        f"Estados: {states}.\nRepertorio de clips:\n{clips}\n"
        "Elige state/clip acorde a tu respuesta (think si analizas, warn si alertas, celebrate si hay éxito)."
    )
    messages = [{"role": m["role"], "content": m["content"]} for m in body.get("messages", [])][-12:]
    if not messages:
        return {"error": "sin-mensajes", "message": "Envía al menos un mensaje."}
    text, err = _ai_call(entry["provider"], entry["api_key"], entry.get("model", ""), system, messages)
    if err:
        return {"error": "proveedor", "message": err}
    result = _parse_contract(text)
    result["provider"] = entry["provider"]
    remember("console", "chat", workflow=body.get("workflow", "general"), role=body.get("role", "orquestador"),
             user=messages[-1]["content"][:160], agent=str(result.get("say", ""))[:160])
    return result


def ai_greet(provider, api_key, model, hostname):
    """Primera interacción: el LLM saluda Y elige su clip (contrato del framework)."""
    if provider not in AI_PROVIDERS:
        return {"error": f"Proveedor desconocido: {provider}"}
    p = AI_PROVIDERS[provider]
    model = model or p["default_model"]
    states, clips = _catalog_for_llm()
    system = (
        "Eres Acuaponsito, asistente robótico tierno de Kaanbal, una plataforma open source "
        "de DevOps/MLOps/IoT. Acabas de ser despertado por primera vez.\n"
        "Respondes SIEMPRE un único JSON válido, sin markdown ni texto extra, con esta forma:\n"
        '{"say": "<texto breve y cálido en español, máximo 2 frases>", "state": "<estado>", "clip": "<id opcional>"}\n'
        f"Estados disponibles: {states}.\n"
        f"Repertorio de clips (elige 'clip' SOLO de aquí, u omítelo):\n{clips}\n"
        "El repertorio crece con el tiempo; si dudas, indica solo 'state'."
    )
    user_msg = (
        f"El usuario acaba de activarte dentro del instalador de Kaanbal en la máquina '{hostname}'. "
        "Salúdalo por primera vez: di que ya despertaste y que lo acompañarás a cultivar su plataforma."
    )
    try:
        if p["style"] == "anthropic":
            body = json.dumps({"model": model, "max_tokens": 300, "system": system,
                               "messages": [{"role": "user", "content": user_msg}]})
            status, resp = http_json(p["base"] + p["chat_path"], _ai_headers(provider, api_key), data=body, timeout=45)
            text = resp.get("content", [{}])[0].get("text", "") if status == 200 else ""
        else:
            body = json.dumps({"model": model, "max_tokens": 300,
                               "messages": [{"role": "system", "content": system},
                                            {"role": "user", "content": user_msg}]})
            status, resp = http_json(p["base"] + p["chat_path"], _ai_headers(provider, api_key), data=body, timeout=45)
            text = resp.get("choices", [{}])[0].get("message", {}).get("content", "") if status == 200 else ""
        if status != 200:
            return {"error": f"{provider} HTTP {status}: {str(resp)[:200]}"}
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                out = json.loads(match.group(0))
                return {"say": out.get("say", text), "state": out.get("state", "greet"),
                        "clip": out.get("clip"), "model": model, "raw": text}
            except json.JSONDecodeError:
                pass
        return {"say": text.strip() or "¡Hola! Ya desperté 🌱", "state": "greet", "clip": None, "model": model}
    except Exception as e:
        return {"error": str(e)}


TAILSCALE_OPERATOR_TAG = "tag:k8s-operator"
# Tags que Kaanbal necesita en el tailnet. El operador usa k8s-operator/k8s;
# database/iot los asignan apps expuestas por VPN (mismo patrón que terraform/tailscale.tf).
TAILSCALE_PLATFORM_TAGS = {
    "tag:k8s-operator": ["autogroup:admin"],
    "tag:k8s": ["tag:k8s-operator"],
    "tag:database": ["tag:k8s-operator"],
    "tag:iot": ["tag:k8s-operator"],
}
# Sin este grant, los devices tag:k8s aparecen en MagicDNS pero los miembros
# del tailnet no pueden abrir TCP/HTTP hacia ellos (síntoma: "VPN no aparece / no acceso").
TAILSCALE_MEMBER_GRANTS = [
    {
        "src": ["autogroup:member"],
        "dst": ["tag:k8s", "tag:k8s-operator", "tag:database", "tag:iot"],
        "ip": ["*"],
    },
]


def _tailscale_oauth_token(client_id, client_secret):
    status, resp = http_json(
        "https://api.tailscale.com/api/v2/oauth/token",
        {"Content-Type": "application/x-www-form-urlencoded"},
        data="grant_type=client_credentials", auth=(client_id, client_secret))
    if status != 200:
        return ""
    return (resp or {}).get("access_token", "") if isinstance(resp, dict) else ""


def ensure_tailscale_acl_tags(client_id, client_secret, log_fn=None):
    """Escribe en la ACL del tailnet los tagOwners que Kaanbal necesita.

    El usuario solo pega el OAuth client (con scope ACL + Auth Keys + Devices).
    No tiene que editar a mano login.tailscale.com/admin/acls: aquí se hace el
    merge preservando grants/acls/ssh existentes (misma idea que el terraform
    antiguo de software-factory).

    Devuelve (ok, detalle).
    """
    def say(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    token = _tailscale_oauth_token(client_id, client_secret)
    if not token:
        return False, "el cliente OAuth no devolvió token"

    # GET con Accept JSON; el ETag evita pisar cambios concurrentes.
    req = urllib.request.Request(
        "https://api.tailscale.com/api/v2/tailnet/-/acl",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            etag = resp.headers.get("ETag", "")
            acl = json.loads(resp.read().decode() or "{}")
    except Exception as exc:
        return False, f"no pude leer la ACL: {exc}"

    owners = dict(acl.get("tagOwners") or acl.get("tagowners") or {})
    missing = {k: v for k, v in TAILSCALE_PLATFORM_TAGS.items() if k not in owners}

    # Grants: members must reach tagged k8s devices (MagicDNS alone is not enough).
    grants = list(acl.get("grants") or [])
    grant_needed = []
    for wanted in TAILSCALE_MEMBER_GRANTS:
        if not _grant_covers(grants, wanted):
            grant_needed.append(wanted)

    # Legacy ACLs fallback if the tailnet still uses acls[] without grants[].
    acls = list(acl.get("acls") or [])
    acl_needed = []
    if not grants and not grant_needed:
        legacy = {
            "action": "accept",
            "src": ["autogroup:member"],
            "dst": ["tag:k8s:*", "tag:k8s-operator:*", "tag:database:*", "tag:iot:*"],
        }
        if not any(
            (e.get("action") == "accept"
             and "autogroup:member" in (e.get("src") or [])
             and any(str(d).startswith("tag:k8s") for d in (e.get("dst") or [])))
            for e in acls
        ):
            acl_needed.append(legacy)

    if not missing and not grant_needed and not acl_needed:
        say("ACL de Tailscale: tags + acceso de miembros ya presentes", "ok")
        return True, "already"

    new_acl = dict(acl)
    if missing:
        owners.update(missing)
        new_acl["tagOwners"] = owners
        new_acl.pop("tagowners", None)
    if grant_needed:
        new_acl["grants"] = grants + grant_needed
    if acl_needed:
        new_acl["acls"] = acls + acl_needed

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if etag:
        headers["If-Match"] = etag
    body = json.dumps(new_acl).encode()
    req = urllib.request.Request(
        "https://api.tailscale.com/api/v2/tailnet/-/acl",
        data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:240]
        return False, f"no pude escribir la ACL (HTTP {exc.code}): {detail}"
    except Exception as exc:
        return False, f"no pude escribir la ACL: {exc}"

    bits = []
    if missing:
        bits.append(f"tags {', '.join(sorted(missing))}")
    if grant_needed:
        bits.append(f"{len(grant_needed)} grant(s) member→k8s")
    if acl_needed:
        bits.append("acl member→k8s")
    say(f"ACL de Tailscale actualizada: {'; '.join(bits)}", "ok")
    return True, "updated"


def _grant_covers(existing, wanted):
    """True if an existing grant already allows wanted src→dst (superset OK)."""
    w_src = set(wanted.get("src") or [])
    w_dst = set(wanted.get("dst") or [])
    for g in existing:
        g_src = set(g.get("src") or [])
        g_dst = set(g.get("dst") or [])
        if (w_src <= g_src and w_dst <= g_dst
                and not g.get("srcPosture") and not g.get("via")
                and ("*" in (g.get("ip") or []) or set(wanted.get("ip") or []) <= set(g.get("ip") or []))):
            return True
    return False


def tailscale_can_tag(client_id, client_secret, tag=TAILSCALE_OPERATOR_TAG):
    """¿Puede este cliente OAuth emitir authkeys con la etiqueta del operador?

    Es lo primero que hace el operador de Tailscale al arrancar. Si la ACL del
    tailnet no declara la etiqueta, el operador se reinicia para siempre con un
    400 mientras el resto de la plataforma parece sana. Se comprueba emitiendo
    una llave efímera de cinco minutos y revocándola en el acto.

    Devuelve (puede?, motivo).
    """
    token = _tailscale_oauth_token(client_id, client_secret)
    if not token:
        return False, "el cliente OAuth no devolvió token"

    url = "https://api.tailscale.com/api/v2/tailnet/-/keys"
    payload = json.dumps({
        "capabilities": {"devices": {"create": {
            "reusable": False, "ephemeral": True, "preauthorized": True,
            "tags": [tag]}}},
        "expirySeconds": 300,
        # Tailscale rechaza descripciones con signos de puntuación.
        "description": "kaanbal preflight",
    })
    status, resp = http_json(
        url, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=payload, timeout=25)
    if status in (200, 201):
        key_id = resp.get("id", "") if isinstance(resp, dict) else ""
        if key_id:
            http_json(f"{url}/{urllib.parse.quote(key_id)}",
                      {"Authorization": f"Bearer {token}"}, method="DELETE", timeout=15)
        return True, ""

    message = resp.get("message", "") if isinstance(resp, dict) else str(resp)[:160]
    return False, message or f"HTTP {status}"


def validate_tailscale(client_id, client_secret, dns_suffix=""):
    suffix = (dns_suffix or "").strip().lower()
    if suffix and not suffix.endswith(".ts.net"):
        return {"valid": False, "message": "El DNS suffix debe terminar en .ts.net (ej. tailXXXX.ts.net)."}
    status, resp = http_json("https://api.tailscale.com/api/v2/oauth/token",
                             {"Content-Type": "application/x-www-form-urlencoded"},
                             data="grant_type=client_credentials", auth=(client_id, client_secret))
    if status == 200 and resp.get("access_token"):
        extra = f" DNS suffix '{suffix}' aceptado." if suffix else ""
        return {"valid": True, "message": f"OAuth de Tailscale válido. Autenticación comprobada; permisos, operador y conectividad se verifican durante el despliegue.{extra}"}
    if status == 401:
        return {"valid": False, "message": "Client ID/Secret inválidos. Regenera el OAuth client en Tailscale."}
    return {"valid": False, "message": f"Tailscale respondió HTTP {status}."}


def validate_docker(username, token):
    """Autentica contra Docker Hub v2 (usuario + Access Token)."""
    status, resp = http_json("https://hub.docker.com/v2/users/login/", {"Content-Type": "application/json"},
                             data=json.dumps({"username": username, "password": token}))
    if status == 200 and resp.get("token"):
        return {"valid": True, "message": f"Autenticado en Docker Hub como '{username}'."}
    if status == 401:
        return {"valid": False, "message": "Usuario o Access Token inválidos. Crea uno en hub.docker.com/settings/security."}
    return {"valid": False, "message": f"Docker Hub respondió HTTP {status}."}


# ------------------------------------------------------------ system checks ---
def system_info():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            mem_kb = int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1))
        info["ram_gb"] = round(mem_kb / 1024 / 1024, 1)
    except Exception:
        info["ram_gb"] = None
    info["cpus"] = os.cpu_count()
    try:
        disk = shutil.disk_usage("/")
        info["disk_free_gb"] = round(disk.free / 1024**3)
    except Exception:
        info["disk_free_gb"] = None
    rc, out = run("systemctl is-system-running 2>/dev/null || true", timeout=10)
    info["systemd"] = out.strip() in ("running", "degraded")
    info["wsl"] = "microsoft" in open("/proc/version").read().lower() if os.path.exists("/proc/version") else False
    info["k3s_installed"] = shutil.which("k3s") is not None
    rc, _ = run("k3s kubectl get node --no-headers 2>/dev/null | grep -q ' Ready'", timeout=20)
    info["node_ready"] = rc == 0
    rc, _ = run("k3s kubectl get ns argocd 2>/dev/null", timeout=20)
    info["argocd_present"] = rc == 0
    info["hostname"] = socket.gethostname().lower()
    # El bootstrap productivo ejecuta un servicio root temporal. El modo manual
    # conserva compatibilidad con sudo -n, pero nunca exige NOPASSWD:ALL.
    rc, _ = run("sudo -n true 2>/dev/null", timeout=5) if not PRIVILEGED else (0, "")
    info["privileged_installer"] = PRIVILEGED
    info["sudo_nopasswd"] = rc == 0
    with STATE_LOCK:
        STATE["sysinfo"] = info
    return info


# --------------------------------------------------------------- instalación ---
def detect_ingress_class(default="traefik"):
    """IngressClass que realmente sirve tráfico en este cluster.

    Prefiere la marcada como default; si no hay ninguna, la primera que no sea
    de Tailscale (esa solo enruta dentro de la VPN). Publicar un Ingress con
    una clase sin controlador es el fallo silencioso más caro de diagnosticar:
    kubectl lo acepta y la app nunca responde.
    """
    rc, out = kubectl(
        "get ingressclass -o jsonpath="
        "'{range .items[*]}{.metadata.name}|"
        "{.metadata.annotations.ingressclass\\.kubernetes\\.io/is-default-class}{\"\\n\"}{end}'",
        stream=False)
    if rc != 0:
        return default

    candidates = []
    for line in (out or "").strip().strip("'").splitlines():
        name, _, is_default = line.partition("|")
        name = name.strip()
        if not name:
            continue
        if is_default.strip().lower() == "true":
            return name
        if name != "tailscale":
            candidates.append(name)
    return candidates[0] if candidates else default


def apply_yaml(manifest, filename):
    """Aplica un manifiesto en el cluster. Devuelve el error o None.

    Los manifiestos van a un temporal con permisos 600 porque algunos llevan
    credenciales; se borra siempre, incluso si kubectl falla.
    """
    path = os.path.join("/tmp", f"kaanbal-{filename}")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(manifest)
        os.chmod(path, 0o600)
        rc, out = kubectl(f"apply -f {path}", timeout=60, stream=False)
        return None if rc == 0 else (out or "kubectl apply falló")[:300]
    except Exception as exc:
        return str(exc)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def ensure_runtime_secrets(cfg):
    """Crea los secrets que nunca deben vivir en Git.

    MongoDB y la clave de firma de los JWT se generan una sola vez y se
    conservan entre reinstalaciones: si rotaran en cada `--reset-local`, los
    datos existentes en el volumen de MongoDB quedarían inaccesibles.
    """
    import base64

    db_password = (cfg.get("db_password") or "").strip()
    api_secret = (cfg.get("api_secret_key") or "").strip()

    # Si ya existen en el cluster, reutilizarlos manda sobre generar nuevos.
    rc, existing = kubectl(
        "-n prod get secret kaanbal-api-runtime -o jsonpath='{.data.mongodb-uri}'",
        stream=False)
    if rc == 0 and existing.strip().strip("'"):
        try:
            current = base64.b64decode(existing.strip().strip("'")).decode()
            match = re.search(r"://admin:([^@]+)@", current)
            if match:
                db_password = urllib.parse.unquote(match.group(1))
        except Exception:
            pass

    if not db_password:
        db_password = secrets.token_urlsafe(24)
    if not api_secret:
        api_secret = secrets.token_urlsafe(48)

    safe_password = urllib.parse.quote(db_password, safe="")
    mongo_uri = (f"mongodb://admin:{safe_password}@datastore:27017/"
                 "forge?authSource=admin")

    def b64(value):
        return base64.b64encode(value.encode()).decode()

    err = apply_yaml(
        "apiVersion: v1\nkind: Secret\nmetadata:\n"
        "  name: datastore-credentials\n  namespace: prod\n"
        "type: Opaque\ndata:\n"
        f"  root-username: {b64('admin')}\n"
        f"  root-password: {b64(db_password)}\n",
        "datastore-credentials.yaml")
    if err:
        raise RuntimeError(f"No pude crear las credenciales de MongoDB: {err}")

    err = apply_yaml(
        "apiVersion: v1\nkind: Secret\nmetadata:\n"
        "  name: kaanbal-api-runtime\n  namespace: prod\n"
        "type: Opaque\ndata:\n"
        f"  mongodb-uri: {b64(mongo_uri)}\n"
        f"  secret-key: {b64(api_secret)}\n",
        "kaanbal-api-runtime.yaml")
    if err:
        raise RuntimeError(f"No pude crear el secret de runtime del API: {err}")

    cfg["db_password"] = db_password
    cfg["api_secret_key"] = api_secret
    return db_password, api_secret


def wait_until_exists(resource, namespace="prod", timeout=300, poll=5):
    """Espera a que un objeto aparezca en el cluster."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc, _ = kubectl(f"-n {namespace} get {resource}", timeout=30, stream=False)
        if rc == 0:
            return True
        time.sleep(poll)
    return False


def wait_for_rollout(deployment, namespace="prod", timeout=420, log_fn=None,
                     appear_timeout=300):
    """Espera a que un Deployment exista y quede disponible. Devuelve (ok, detalle).

    ArgoCD crea los objetos de forma asíncrona después de sincronizar, así que
    entre aplicar el app-of-apps y ver el Deployment pasan segundos. Preguntar
    por el rollout antes de tiempo devuelve NotFound al instante, que parece un
    despliegue roto cuando solo es impaciencia del instalador.
    """
    if not wait_until_exists(f"deployment/{deployment}", namespace, appear_timeout):
        detail = (f"ArgoCD no creó el Deployment en {appear_timeout}s; "
                  "revisa la Application en ArgoCD")
        if log_fn:
            log_fn(f"⚠ {deployment}: {detail}", "warn")
        return False, detail

    rc, out = kubectl(
        f"-n {namespace} rollout status deployment/{deployment} --timeout={timeout}s",
        timeout=timeout + 30, stream=False)
    if rc == 0:
        return True, ""

    # El detalle útil está en el estado del pod, no en el timeout de kubectl.
    _rc, reason = kubectl(
        f"-n {namespace} get pods -l app={deployment} "
        "-o jsonpath='{.items[*].status.containerStatuses[*].state.waiting.reason}'",
        stream=False)
    reason = (reason or "").strip().strip("'")
    detail = reason or (out or "").strip()[:200]
    if log_fn:
        log_fn(f"⚠ {deployment} no llegó a Ready: {detail}", "warn")
    return False, detail


class PortForward:
    """Port-forward efímero para hablar con un servicio del cluster."""

    def __init__(self, service, local_port, remote_port, namespace="prod"):
        self.service = service
        self.namespace = namespace
        self.local_port = local_port
        self.remote_port = remote_port
        self.cmd = (f"k3s kubectl -n {namespace} port-forward svc/{service} "
                    f"{local_port}:{remote_port}")
        self.proc = None
        self.ready = False

    def __enter__(self):
        self.proc = subprocess.Popen(
            self.cmd, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # El túnel tarda un instante en aceptar conexiones.
        for _ in range(40):
            time.sleep(0.5)
            if self.proc.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", self.local_port), timeout=1):
                    self.ready = True
                    return self
            except OSError:
                continue
        return self

    def __exit__(self, *_exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return False


def bootstrap_vault_lab(kubectl_fn=None, log_fn=None):
    token = vault_bootstrap.bootstrap()
    if log_fn:
        log_fn("Vault desbloqueado y KV v2 verificado. Respalda /etc/kaanbal/vault-recovery.json fuera del servidor; se necesita tras reinicios.", "ok")
    return token


def preflight_install(values):
    # One validation contract for browser and unattended entry points.
    import unattended
    cfg, errors = unattended.normalize(values)
    if not errors:
        provider_errors, _ = unattended.preflight(cfg)
        errors.extend(provider_errors)
    return cfg, errors


def confirm_admin_access(username, password):
    with PortForward("kaanbal-api", 18001, 8000) as pf:
        if not pf.ready:
            return False
        status, body = http_json(
            "http://127.0.0.1:18001/api/v1/auth/token",
            {"Content-Type": "application/x-www-form-urlencoded"},
            data=urllib.parse.urlencode({"username": username, "password": password}), timeout=20)
        return status == 200 and isinstance(body, dict) and bool(body.get("access_token"))


def _resolve_github_login(cfg):
    """Resolve the token owner, never substitute the destination organization."""
    login = (cfg.get("github_login") or "").strip()
    if login:
        return login
    token = (cfg.get("gitops_token") or "").strip()
    if not token:
        return ""
    status, user = _github_api("GET", "/user", token)
    if status == 200 and isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str):
            return login.strip()
    return ""


def seed_platform(cfg, argocd_password, log_fn=None, vault_token=""):
    """Siembra la configuración de la plataforma en Kaanbal API.

    Deja `system_config` en MongoDB con el dominio, la org de GitHub y las
    credenciales de Docker Hub/Cloudflare/Tailscale, que es lo que AppDeployer
    necesita para poder crear apps desde la consola sin volver a pedir nada.
    """
    def say(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    github_login = _resolve_github_login(cfg)
    if github_login:
        cfg["github_login"] = github_login
    else:
        raise RuntimeError("No se pudo resolver el usuario de GitHub; valida la conexión GitHub y reintenta")

    domain = (cfg.get("domain") or "").strip().lower()
    payload = {
        "mode": cfg.get("mode", "cloud"),
        "domain": domain,
        "git_provider": "github",
        "git_username": github_login,
        "git_token": (cfg.get("gitops_token") or "").strip(),
        "git_workspace": (cfg.get("github_org") or "").strip(),
        "github_is_org": bool(
            (cfg.get("github_org") or "").lower()
            and (cfg.get("github_org") or "").lower() != github_login.lower()),
        "dockerhub_username": (cfg.get("docker_user") or "").strip(),
        "dockerhub_token": (cfg.get("docker_token") or "").strip(),
        "tailscale_client_id": (cfg.get("tailscale_id") or "").strip(),
        "tailscale_client_secret": (cfg.get("tailscale_secret") or "").strip(),
        "tailscale_dns_suffix": (cfg.get("tailscale_dns") or "").strip(),
        "cloudflare_token": (cfg.get("cf_token") or "").strip(),
        "cloudflare_account_id": (cfg.get("cf_account") or "").strip(),
        "cloudflare_tunnel_id": (cfg.get("cf_tunnel_id") or "").strip(),
        "cloudflare_zone_id": (cfg.get("cf_zone_id") or "").strip(),
        "ingress_class": (cfg.get("ingress_class") or "traefik").strip(),
        "ingress_cluster_issuer": (
            (cfg.get("cluster_issuer") or "") if cfg.get("cluster_tls") else ""),
        "argocd_password": argocd_password or "",
        "argocd_server": "https://argocd-server.argocd.svc.cluster.local:443",
        "vault_addr": "http://vault.vault.svc.cluster.local:8200",
        "vault_token": (vault_token or "").strip(),
        "templates_repo": "kaanbal-templates",
        "admin_user": (cfg.get("admin_user") or "admin").strip(),
        "admin_password": (cfg.get("admin_pass") or "").strip(),
        # Procedencia del core (ADR-002): sin esto la célula no sabe qué
        # versión es y nunca podrá ofrecer una actualización.
        "core_release": cfg.get("core_release"),
    }

    headers = {"Content-Type": "application/json"}
    body_install = json.dumps(payload)
    body_ci = json.dumps({"repos": ["kaanbal-api", "kaanbal-console"]})

    def _post_seed(base_url: str):
        status, body = http_json(
            f"{base_url}/api/v1/setup/install", headers, data=body_install, timeout=60)
        if status not in (200, 201):
            return False, f"HTTP {status}: {str(body)[:200]}"
        say("Configuración de plataforma sembrada en Kaanbal API", "ok")

        # Auth as the just-seeded admin so we can refresh the template catalog.
        admin_user = payload["admin_user"]
        admin_pass = payload["admin_password"]
        token = ""
        if admin_user and admin_pass:
            try:
                form = urllib.parse.urlencode(
                    {"username": admin_user, "password": admin_pass}).encode()
                req = urllib.request.Request(
                    f"{base_url}/api/v1/auth/token",
                    data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    token = json.loads(resp.read().decode()).get("access_token", "")
            except Exception as exc:
                say(f"⚠ Auth post-seed falló: {str(exc)[:120]}", "warn")

        if not token:
            return False, "No se pudo autenticar al administrador después de configurar la plataforma"
        if token:
            auth_headers = {**headers, "Authorization": f"Bearer {token}"}
            st_t, body_t = http_json(
                f"{base_url}/api/v1/templates/refresh", auth_headers, timeout=90)
            if st_t in (200, 201):
                count = body_t.get("template_count") if isinstance(body_t, dict) else "?"
                say(f"Catálogo de templates refrescado ({count})", "ok")
            else:
                say(f"⚠ Refresh de templates HTTP {st_t}", "warn")

        status, body = http_json(
            f"{base_url}/api/v1/setup/bootstrap-core-ci",
            {**headers, **({"Authorization": f"Bearer {token}"} if token else {})},
            data=body_ci, timeout=90)
        if status in (200, 201):
            wired = ", ".join(body.get("configured", [])) if isinstance(body, dict) else ""
            if not isinstance(body, dict) or body.get("failed") or not {"kaanbal-api", "kaanbal-console"} <= set(body.get("configured", [])):
                return False, "Configuración de CI incompleta; revisa permisos de secrets de GitHub"
            say(f"Pipelines de GitHub Actions conectados: {wired}", "ok")
        elif status == 404:
            return False, "La API desplegada no soporta bootstrap de CI; usa una versión compatible"
        else:
            return False, f"No se pudo configurar CI (HTTP {status})"
        return True, ""

    # 1) Prefer in-cluster port-forward (works even before public DNS is live).
    with PortForward("kaanbal-api", 18000, 8000) as pf:
        if pf.ready:
            ok, detail = _post_seed("http://127.0.0.1:18000")
            if ok:
                return True, ""
            say(f"Seed vía port-forward falló: {detail}", "warn")
        else:
            say("Port-forward a kaanbal-api no listo — pruebo URL pública", "warn")

    # 2) Fallback: public API (Cloudflare / Traefik already routing).
    if domain:
        ok, detail = _post_seed(f"https://kaanbal-api.{domain}")
        if ok:
            return True, ""
        return False, detail
    return False, "Port-forward falló y no hay dominio para fallback público"


def probe_public_url(url, timeout=15):
    """(alcanzable?, código o motivo). Un 3xx/4xx ya prueba que hay ruta."""
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "kaanbal-installer"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status
    except urllib.error.HTTPError as exc:
        return True, exc.code
    except Exception as exc:
        return False, str(exc)[:120]


def do_install(cfg):
    global INSTALLING, PORT_FORWARD_PROC
    try:
        set_phase("installing")
        mode = cfg.get("mode", "local")
        log(f"Iniciando instalación — modo: {'dominio público (Cloudflare)' if mode == 'cloud' else 'local / VPN'}")

        # 1. Sistema
        set_step("sistema", "running")
        info = system_info()
        if not info["systemd"]:
            raise RuntimeError("systemd no está activo. En WSL2: agrega [boot] systemd=true a /etc/wsl.conf y ejecuta wsl --shutdown")
        if (info["ram_gb"] or 0) < 3.5:
            raise RuntimeError(f"RAM insuficiente: {info['ram_gb']}GB (mínimo 4GB)")
        if not info.get("sudo_nopasswd") and not info.get("k3s_installed"):
            raise RuntimeError(
                "El instalador no tiene privilegios. Inícialo con: sudo bash ./install.sh"
            )
        set_step("sistema", "done", f"{info['ram_gb']}GB RAM · {info['cpus']} CPUs · {info['disk_free_gb']}GB libres · systemd ✓")

        # 2. k3s
        set_step("k3s", "running")
        if info["k3s_installed"]:
            set_step("k3s", "done", "k3s ya instalado — detectado")
            log("k3s ya presente, se omite descarga", "ok")
        else:
            log("Descargando e instalando k3s (~60s)...")
            privilege = "" if PRIVILEGED else "sudo "
            rc, out = run(
                f"curl -sfL https://get.k3s.io | {privilege}INSTALL_K3S_EXEC='--write-kubeconfig-mode 600 --node-name {info['hostname']}' sh -",
                timeout=420, stream=True)
            if rc != 0:
                if "terminal is required" in (out or "") or "a password is required" in (out or "").lower():
                    raise RuntimeError(
                        "k3s falló: sudo sin password. Configura NOPASSWD (ver mensaje del paso Sistema) y reintenta."
                    )
                raise RuntimeError("La instalación de k3s falló — revisa el log")
            set_step("k3s", "done", "k3s instalado")

        # 3. Nodo Ready
        set_step("nodo", "running")
        for i in range(60):
            rc, _ = run("k3s kubectl get node --no-headers 2>/dev/null | grep -q ' Ready'", timeout=15)
            if rc == 0:
                break
            time.sleep(5)
        else:
            raise RuntimeError("El nodo no llegó a Ready en 5 minutos")
        rc, node = kubectl("get node --no-headers")
        set_step("nodo", "done", node.split()[0] if node else "Ready")
        log(f"Nodo Kubernetes Ready: {node}", "ok")

        # 4. ArgoCD (server-side apply: evita el error del CRD de 262KB)
        set_step("argocd", "running")
        rc, _ = kubectl("get ns argocd")
        if rc != 0:
            kubectl("create namespace argocd")
        log("Aplicando manifiestos de ArgoCD (server-side)...")
        rc, out = kubectl(
            "apply --server-side --force-conflicts -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml",
            timeout=180)
        if rc != 0:
            raise RuntimeError(f"ArgoCD apply falló: {out[-400:]}")
        log("Esperando a que ArgoCD esté listo (puede tardar en la primera descarga de imágenes)...")
        rc, _ = kubectl("-n argocd rollout status deployment/argocd-server --timeout=420s", timeout=440, stream=False)
        if rc != 0:
            raise RuntimeError("argocd-server no llegó a Ready")
        rc, _ = kubectl("get crd applicationsets.argoproj.io")
        crd_ok = "✓ ApplicationSets" if rc == 0 else "sin ApplicationSets"
        set_step("argocd", "done", f"ArgoCD Ready · {crd_ok}")
        log("ArgoCD desplegado y saludable", "ok")

        # 5. Agente IA — los proveedores validados se vuelven parte del SISTEMA
        set_step("ia", "running")
        providers = cfg.get("ai_providers") or STATE.get("ai_providers") or []
        if not providers:
            # el agente ahora se configura en el Acuaponsito Runtime — leer su config
            try:
                with open(os.path.expanduser("~/.acuaponsito/agent.config.json"), encoding="utf-8") as f:
                    providers = json.load(f).get("providers", [])
            except Exception:
                providers = []
        if providers:
            payload = json.dumps(providers)
            tmp_ai = "/tmp/kaanbal-ai-secret.json"
            with open(tmp_ai, "w") as f:
                f.write(payload)
            kubectl("get ns prod || k3s kubectl create namespace prod", timeout=30)
            rc, _ = run(
                "k3s kubectl -n prod create secret generic kaanbal-ai-providers "
                f"--from-file=providers.json={tmp_ai} --dry-run=client -o yaml | k3s kubectl apply -f -",
                timeout=30)
            os.remove(tmp_ai)
            if rc != 0:
                raise RuntimeError("No se pudo guardar el secret de proveedores IA")
            names = ", ".join(p["provider"] for p in providers)
            set_step("ia", "done", f"Proveedores en el cluster: {names} — los agentes del sistema ya pueden usarlos")
            log(f"Agente(s) IA integrados al sistema: {names}", "ok")
        else:
            set_step("ia", "skipped", "Sin proveedor IA — configúralo después en la consola")
            log("Paso IA omitido (sin proveedores validados)")

        # 5b. Credenciales base de la plataforma (Docker registry + Tailscale VPN)
        kubectl("get ns prod || k3s kubectl create namespace prod", timeout=30)
        admin_user = (cfg.get("admin_user") or "admin").strip()
        admin_pass = (cfg.get("admin_pass") or "").strip()
        if not admin_pass:
            raise RuntimeError("Falta la contraseña del administrador de Kaanbal")
        import base64 as _b64
        admin_secret = (
            "apiVersion: v1\nkind: Secret\nmetadata:\n"
            "  name: kaanbal-bootstrap-creds\n  namespace: prod\n"
            "type: Opaque\ndata:\n"
            f"  username: {_b64.b64encode(admin_user.encode()).decode()}\n"
            f"  password: {_b64.b64encode(admin_pass.encode()).decode()}\n"
        )
        tmp_admin = "/tmp/kaanbal-bootstrap-creds.yaml"
        with open(tmp_admin, "w", encoding="utf-8") as f:
            f.write(admin_secret)
        os.chmod(tmp_admin, 0o600)
        rc, _ = kubectl(f"apply -f {tmp_admin}", timeout=30)
        os.remove(tmp_admin)
        if rc != 0:
            raise RuntimeError("No se pudo crear el acceso administrativo de Kaanbal")
        log(f"Acceso administrativo preparado para '{admin_user}'", "ok")

        dk_user = (cfg.get("docker_user") or "").strip()
        dk_token = (cfg.get("docker_token") or "").strip()
        if dk_user and dk_token:
            auth = _b64.b64encode(f"{dk_user}:{dk_token}".encode()).decode()
            dockercfg = _b64.b64encode(json.dumps({"auths": {"https://index.docker.io/v1/":
                {"username": dk_user, "password": dk_token, "auth": auth}}}).encode()).decode()
            secret_yaml = ("apiVersion: v1\nkind: Secret\nmetadata:\n  name: regcred\n  namespace: prod\n"
                           "type: kubernetes.io/dockerconfigjson\ndata:\n"
                           f"  .dockerconfigjson: {dockercfg}\n")
            tmp = "/tmp/kaanbal-regcred.yaml"
            with open(tmp, "w") as f:
                f.write(secret_yaml)
            kubectl(f"apply -f {tmp}", timeout=30)
            os.remove(tmp)
            log(f"Docker Hub conectado: secret 'regcred' listo (pull/push como {dk_user})", "ok")

        ts_id = (cfg.get("tailscale_id") or "").strip()
        ts_secret = (cfg.get("tailscale_secret") or "").strip()
        cfg["tailscale_ready"] = False
        if ts_id and ts_secret:
            # Primero: escribir tagOwners en la ACL vía API (como hacía
            # terraform/tailscale.tf). El usuario no edita ACL a mano.
            acl_ok, acl_why = ensure_tailscale_acl_tags(ts_id, ts_secret, log_fn=log)
            if not acl_ok:
                raise RuntimeError(f"No se pudo preparar la política Tailscale: {acl_why}")
            can_tag, why = tailscale_can_tag(ts_id, ts_secret)
            if not can_tag:
                raise RuntimeError(f"Tailscale no permite emitir {TAILSCALE_OPERATOR_TAG}: {why}")
            kubectl("get ns tailscale || k3s kubectl create namespace tailscale", timeout=30)
            rc, _ = run(
                "k3s kubectl -n tailscale create secret generic operator-oauth "
                f"--from-literal=client_id='{ts_id}' --from-literal=client_secret='{ts_secret}' "
                "--dry-run=client -o yaml | k3s kubectl apply -f -", timeout=30)
            if rc:
                raise RuntimeError("No se pudo guardar la credencial del operador Tailscale")
            cfg["tailscale_ready"] = True
            log("Política y credencial Tailscale preparadas; pendiente verificar operador", "info")

        # 6. Cloudflare Tunnel (tier público) — AQUÍ el dominio cobra vida
        set_step("cloudflared", "running")
        domain = (cfg.get("domain") or "").strip().lower().lstrip("*.").rstrip("/")
        cf_token = (cfg.get("cf_token") or cfg.get("cloudflare_token") or "").strip()
        cf_account = (cfg.get("cf_account") or cfg.get("cloudflare_account_id") or "").strip()
        tunnel_token = (cfg.get("tunnel_token") or "").strip()
        if mode != "cloud":
            set_step("cloudflared", "skipped", "Modo local sin dominio — actívalo después desde la consola")
            log("Tier público omitido (modo local)")
        elif not domain:
            set_step("cloudflared", "failed", "Falta el dominio — la célula quedó lista, sin salida pública")
            log("⚠ Sin dominio: no puedo publicar a internet. Vuelve a Conectividad y pon tu dominio.", "warn")
        else:
            hostname = socket.gethostname().lower()
            with STATE_LOCK:
                STATE["domain"] = domain
            # 1) obtener el tunnel_token: creándolo vía API (ideal) o el que pegó el usuario
            if not tunnel_token and cf_token and cf_account:
                log(f"Creando túnel Cloudflare para {domain} (control plane vía API)...")
                res = create_cloudflare_tunnel(cf_token, cf_account, domain, hostname, log_fn=log)
                if res.get("error"):
                    set_step("cloudflared", "failed", f"Cloudflare: {res['error']} — célula lista igual")
                    log(f"⚠ No se pudo crear el túnel: {res['error']}. Revisa scopes del token.", "warn")
                    tunnel_token = None
                else:
                    tunnel_token = res.get("tunnel_token")
                    if res.get("zone_id"):
                        cfg["cf_zone_id"] = res["zone_id"]
                    with STATE_LOCK:
                        STATE["tunnel_dns"] = res.get("dns", [])
            if tunnel_token:
                # El id del túnel se guarda en la plataforma: sin él la API no puede
                # cablear dominios adicionales ni crear CNAMEs por app. Se deriva
                # del token para cubrir también el caso de un token pegado a mano.
                derived = tunnel_id_from_token(tunnel_token)
                if derived:
                    cfg["cf_tunnel_id"] = derived
                # 2) secret + 3) correr cloudflared (data plane: conexión saliente al edge)
                kubectl("get ns prod || k3s kubectl create namespace prod", timeout=30)
                rc, _ = run(
                    "k3s kubectl -n prod create secret generic cloudflared-secrets "
                    f"--from-literal=TUNNEL_TOKEN='{tunnel_token}' --dry-run=client -o yaml | k3s kubectl apply -f -",
                    timeout=30)
                if rc != 0:
                    raise RuntimeError("No se pudo crear el secret del túnel")
                err = apply_yaml(CLOUDFLARED_DEPLOYMENT, "cloudflared.yaml")
                if err:
                    raise RuntimeError(f"No pude desplegar el conector del túnel: {err}")
                # Sin este conector corriendo, Cloudflare acepta el dominio pero
                # no encuentra origen y responde 530 a todo. Dar el paso por
                # bueno sin comprobarlo convierte eso en un misterio.
                rc, out = kubectl(
                    "-n prod rollout status deployment/cloudflared --timeout=180s",
                    timeout=200, stream=False)
                if rc != 0:
                    raise RuntimeError(
                        "El conector del túnel no llegó a Ready: "
                        f"{(out or '').strip()[:200]}")
                set_step("cloudflared", "done", f"Túnel activo — {domain} servido desde esta máquina 🌐")
                log(f"🌐 Tier público EN VIVO: https://{domain} y *.{domain} salen por Cloudflare (sin IP pública)", "ok")
            elif not cf_token:
                set_step("cloudflared", "skipped", "Sin credenciales Cloudflare — pega tu token en Conectividad")
                log("Túnel omitido: faltó token de Cloudflare para crearlo.", "warn")

        # 6. Repos core en GitHub + baseline GitOps renderizado con TU dominio
        set_step("repos", "running")
        repo_token = (cfg.get("gitops_token") or "").strip()
        github_org = (cfg.get("github_org") or "").strip()
        github_login = (cfg.get("github_login") or "").strip()
        gitops_repo = (cfg.get("gitops_repo") or "infra-gitops").strip()
        gitops_ready = False
        build_core = True
        core_tags = {}
        core_shas = {}

        if not (github_org and repo_token):
            set_step("repos", "skipped", "Sin GitHub — conéctalo después desde la consola")
            log("Sin org o token de GitHub: la célula queda operativa pero sin GitOps.", "warn")
        else:
            repo_url = f"https://github.com/{github_org}/{gitops_repo}.git"

            # 6a. Los repos deben existir antes de poder publicar o construir.
            bs = bootstrap_github_core(repo_token, github_org, github_login,
                                       log_fn=log, create_only=True)
            if not bs.get("ok"):
                raise RuntimeError(
                    f"No pude preparar los repos en {github_org}: {bs.get('error', 'error desconocido')}")

            # 6b. El código del engine: solo se siembra si el repo está vacío.
            for component in corebuild.CORE_COMPONENTS:
                sha, err = gitops_publish.publish_source(
                    run, repo_token, github_org, component["repo"],
                    os.path.join(SF_ROOT, component["repo"]), log_fn=log)
                if err:
                    raise RuntimeError(err)
                # Mismo tag que produciría GitHub Actions para ese commit, para
                # que el pipeline y el instalador nunca se contradigan.
                core_tags[component["name"]] = f"prod-{sha[:7]}"
                # Procedencia (ADR-002): el SHA completo del repo standalone es
                # contra lo que después se detecta si el componente fue tuneado.
                core_shas[component["name"]] = sha

            # Catálogo de plantillas: la consola lista un fallback local, pero
            # AppDeployer necesita clonar este repo para scaffold + k8s.
            tpl_path = os.path.join(SF_ROOT, "kaanbal-templates")
            if not os.path.isdir(tpl_path):
                raise RuntimeError(
                    "Falta kaanbal-templates en el instalador — sin él no se "
                    "pueden lanzar apps desde la consola.")
            _, tpl_err = gitops_publish.publish_source(
                run, repo_token, github_org, "kaanbal-templates", tpl_path,
                log_fn=log)
            if tpl_err:
                raise RuntimeError(tpl_err)

            # 6b-bis. Una versión fijada gana sobre el código local: se despliega
            # tal cual, sin construir nada. Es la ruta de producción.
            core_version = (cfg.get("core_version") or "").strip()
            if core_version:
                pinned, missing = corebuild.resolve_pinned(
                    cfg.get("docker_user", ""), cfg.get("docker_token", ""),
                    core_version)
                if missing:
                    raise RuntimeError(
                        f"Pediste la versión {core_version} del engine pero no está "
                        f"publicada: falta {', '.join(missing)}. Publícala o deja "
                        "KAANBAL_CORE_VERSION vacío para construirla desde el código.")
                core_tags = pinned
                build_core = False
                log(f"Engine fijado a la versión {core_version}: no se construye nada", "ok")
            else:
                build_core = True

            # 6b-ter. Las imágenes ANTES del baseline. ArgoCD sincroniza en
            # cuanto el repo cambia, así que publicar manifiestos que apuntan a
            # una imagen todavía inexistente deja los pods en ImagePullBackOff
            # hasta que el build termina; el despliegue acaba saliendo, pero la
            # verificación final falla por una carrera que no aporta nada.
            if build_core:
                set_step("imagenes", "running")
                log("Construyendo el engine dentro del cluster (Kaniko, sin Docker en el nodo)…")
                corebuild.build_core_images(
                    kubectl, apply_yaml,
                    github_org=github_org, github_token=repo_token,
                    docker_user=cfg.get("docker_user", ""),
                    docker_token=cfg.get("docker_token", ""),
                    tags=core_tags, log_fn=log)
                built = ", ".join(c["name"] for c in corebuild.CORE_COMPONENTS)
                set_step("imagenes", "done", f"Publicados en Docker Hub: {built}")
            else:
                set_step("imagenes", "skipped",
                         f"Versión {core_version} ya publicada en Docker Hub")

            # 6c. El baseline: se renderiza con la config real y se refresca
            #     sin tocar los overlays de las apps creadas desde la consola.
            cfg["api_tag"] = core_tags.get("kaanbal-api", "bootstrap")
            cfg["console_tag"] = core_tags.get("kaanbal-console", "bootstrap")
            cfg["agent_tag"] = core_tags.get("kaanbal-agent", "bootstrap")
            # Procedencia del core (ADR-002). Se arma acá porque es el único
            # punto donde conviven el tag desplegado y el SHA que lo originó.
            _sha = upstream_sha()
            cfg["core_release"] = {
                "version": core_version or (f"install-{_sha[:7]}" if _sha else "install-local"),
                "upstream_sha": _sha or None,
                "upstream": upstream_slug() or None,
                # Sin versión fijada se construye desde el monorepo: es un build
                # de desarrollo, no una célula tuneada. `custom` queda para cuando
                # se detecta deriva.
                "channel": "stable" if core_version else "dev",
                "components": {
                    name: {
                        "image": f"{cfg.get('docker_user', '')}/{name}",
                        "tag": core_tags.get(name, "bootstrap"),
                        "repo_sha": core_shas.get(name),
                    }
                    for name in (c["name"] for c in corebuild.CORE_COMPONENTS)
                },
            }
            cfg["gitops_repo"] = gitops_repo
            cfg["ingress_class"] = detect_ingress_class()
            log(f"Controlador de ingress detectado: {cfg['ingress_class']}")
            context, flags = gitops_render.build_context(cfg)
            infra_src = os.path.join(SF_ROOT, "infra-gitops")
            # Qué se renderiza depende de las flags (sin Tailscale, su operador
            # no entra). Qué rutas *posee* el instalador en el repo publicado no:
            # deben seguir siendo suyas para poder borrar un componente que se
            # retiró, en vez de dejarlo huérfano sincronizándose para siempre.
            render_rules = gitops_render.load_baseline(infra_src, flags)
            owned_rules = gitops_render.load_baseline(infra_src)

            rendered = "/tmp/kaanbal-baseline-rendered"
            written = gitops_render.render_tree(
                infra_src, rendered, context, flags, render_rules)
            log(f"Baseline renderizado para {context['KAANBAL_DOMAIN']} "
                f"({len(written)} manifiestos)")

            failures = gitops_render.validate_rendered(rendered)
            if failures:
                detail = "; ".join(f"{t}: {e}" for t, e in failures[:3])
                raise RuntimeError(f"El baseline renderizado no compila: {detail}")
            log("Manifiestos validados con kustomize antes de publicar", "ok")

            _sha, err = gitops_publish.publish_baseline(
                run, repo_token, github_org, gitops_repo, rendered, owned_rules,
                log_fn=log)
            if err:
                raise RuntimeError(err)

            err = apply_yaml(
                "apiVersion: v1\nkind: Secret\nmetadata:\n"
                "  name: kaanbal-infra-gitops-repo\n  namespace: argocd\n"
                "  labels:\n    argocd.argoproj.io/secret-type: repository\n"
                "stringData:\n  type: git\n"
                f"  url: {repo_url}\n  username: kaanbal\n  password: {repo_token}\n",
                "repo-secret.yaml")
            if err:
                raise RuntimeError(f"ArgoCD no pudo registrar el repo: {err}")

            gitops_ready = True
            set_step("repos", "done",
                     f"{github_org}/{gitops_repo} al día · engine en {context['KAANBAL_DOMAIN']}")

        # Las imágenes se construyen dentro del paso de repos, antes de publicar
        # el baseline, para que ArgoCD nunca vea una referencia sin imagen.
        if not gitops_ready:
            set_step("imagenes", "skipped", "Requiere GitHub configurado")

        # 7. GitOps: ArgoCD toma el control del baseline
        if not gitops_ready:
            set_step("gitops", "skipped", "Requiere GitHub configurado")
        else:
            set_step("gitops", "running")
            ensure_runtime_secrets(cfg)
            log("Secrets de runtime creados fuera de Git (MongoDB y firma JWT)", "ok")

            rc, out = run(
                f"rm -rf /tmp/kaanbal-gitops && git clone --depth 1 "
                f"'{gitops_publish.auth_url(repo_token, github_org, gitops_repo)}' "
                "/tmp/kaanbal-gitops", timeout=180)
            if rc != 0:
                raise RuntimeError(f"No pude clonar el baseline publicado: {(out or '')[:200]}")

            boot = "/tmp/kaanbal-gitops/argocd/bootstrap/app-of-apps.yaml"
            rc, out = kubectl(f"apply -f {boot}", timeout=60, stream=False)
            if rc != 0:
                raise RuntimeError(f"No pude aplicar app-of-apps: {(out or '')[:200]}")
            log("app-of-apps aplicado — ArgoCD reconcilia la plataforma", "ok")

            for deployment in ("datastore", "kaanbal-api", "kaanbal-console"):
                ok, detail = wait_for_rollout(deployment, log_fn=log)
                if ok:
                    log(f"{deployment} Ready", "ok")
                elif deployment == "datastore":
                    log("MongoDB tarda más de lo normal; el API reintentará conectarse.", "warn")
                else:
                    raise RuntimeError(f"{deployment} no llegó a Ready ({detail})")
            set_step("gitops", "done", "Engine desplegado y sincronizado por ArgoCD")

        if cfg.get("tailscale_ready"):
            set_step("gitops", "running", "Verificando operador Tailscale (hasta 180 s)…")
            if not wait_until_exists("deployment/operator", namespace="tailscale", timeout=300):
                raise RuntimeError("El operador Tailscale no apareció")
            rc, _ = kubectl("-n tailscale rollout status deployment/operator --timeout=180s", timeout=200)
            if rc:
                raise RuntimeError("El operador Tailscale no llegó a Ready")
            set_step("gitops", "done", "Engine y operador Tailscale listos")

        # 9. Plataforma: sembrar configuración y conectar los pipelines
        if not gitops_ready:
            set_step("plataforma", "skipped", "Requiere GitHub configurado")
        else:
            set_step("plataforma", "running")
            rc, argo_pwd = kubectl(
                "-n argocd get secret argocd-initial-admin-secret "
                "-o jsonpath='{.data.password}'", stream=False)
            argo_plain = ""
            if rc == 0 and argo_pwd.strip():
                import base64 as _b64pw
                argo_plain = _b64pw.b64decode(argo_pwd.strip().strip("'")).decode()

            vault_token = bootstrap_vault_lab(kubectl, log_fn=log)

            ok, detail = seed_platform(cfg, argo_plain, log_fn=log,
                                       vault_token=vault_token)
            if ok:
                set_step("plataforma", "done",
                         "Kaanbal ya sabe tu dominio, tu org y tu Docker Hub")
            else:
                # La célula funciona; el operador puede completar esto en la
                # consola, así que no tiramos toda la instalación por aquí.
                raise RuntimeError(f"Configuración de plataforma incompleta: {detail}")

        # 10. Acceso operativo
        set_step("acceso", "running")
        rc, pwd = kubectl("-n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}'")
        password = ""
        if rc == 0 and pwd.strip():
            import base64
            password = base64.b64decode(pwd.strip()).decode()
        if PORT_FORWARD_PROC is None or PORT_FORWARD_PROC.poll() is not None:
            PORT_FORWARD_PROC = subprocess.Popen(
                "k3s kubectl -n argocd port-forward svc/argocd-server 8080:443 "
                f"--address {os.environ.get('KAANBAL_ARGO_FORWARD_ADDRESS', '127.0.0.1')}",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
        rc, node = kubectl("get node --no-headers")
        dom = STATE.get("domain", "")
        live = bool(dom) and STATE.get("steps", {}).get("cloudflared", {}).get("status") == "done"
        console_tailnet = str(cfg.get("console_exposure", "public")).lower() == "tailnet"

        # Mapa de URLs del engine: cada servicio del core en su propio nombre
        # bajo el prefijo "kaanbal-", más el atajo "kaanbal" hacia la consola.
        console_url = ""
        api_url = ""
        agent_url = ""
        if live and gitops_ready and not console_tailnet:
            console_url = f"https://{CORE_HOSTS['console']}.{dom}"
            api_url = f"https://{CORE_HOSTS['api']}.{dom}"
            agent_url = f"https://{CORE_HOSTS['agent']}.{dom}"
        elif console_tailnet:
            tailnet = (cfg.get("tailscale_dns") or "").strip()
            console_url = f"http://{CORE_HOSTS['console']}.{tailnet}" if tailnet else ""
            agent_url = f"http://{CORE_HOSTS['agent']}.{tailnet}" if tailnet else ""

        argocd_url = (f"https://{CORE_HOSTS['argocd']}.{dom}" if live
                      else "https://localhost:8080")

        # No invitamos a entrar hasta comprobar que la consola responde de
        # verdad por su URL pública: un enlace muerto es peor que ningún enlace.
        console_reachable = False
        if console_url.startswith("https://"):
            log(f"Comprobando que la consola responde en {console_url}…")
            for attempt in range(12):
                console_reachable, detail = probe_public_url(console_url)
                if console_reachable:
                    log(f"Consola respondiendo (HTTP {detail})", "ok")
                    break
                if attempt == 0:
                    log("Aún no responde — el DNS de Cloudflare tarda 1-2 min la primera vez.")
                time.sleep(10)
            if not console_reachable:
                raise RuntimeError("La consola no responde por su URL pública; revisa DNS y túnel, luego reintenta")

        with STATE_LOCK:
            STATE["handoff"] = {
                "domain": dom,
                "tunnel_live": live,
                "console_url": console_url,
                "console_reachable": console_reachable,
                "console_exposure": "tailnet" if console_tailnet else "public",
                "api_url": api_url,
                "agent_url": agent_url,
                "argocd_url": argocd_url,
                "argocd_user": "admin",
                "argocd_password": password or "(rotado — usa argocd admin initial-password)",
                "kubeconfig": "/etc/rancher/k3s/k3s.yaml",
                "node": node.split()[0] if node else "",
                "dns": STATE.get("tunnel_dns", []),
                "admin_user": admin_user,
                "engine_ready": gitops_ready,
            }

        if not gitops_ready or not console_url:
            raise RuntimeError("El core no tiene una vía de acceso configurada")
        if console_tailnet:
            STATE["handoff"]["vpn_verification_required"] = True
            log("Core listo; verifica el acceso VPN desde tu PC antes de confirmar el cierre", "warn")
        if console_url and gitops_ready:
            set_step("acceso", "done", f"Consola Kaanbal en {console_url}")
            log(f"🎉 Kaanbal operativo. Entra a {console_url} con el usuario "
                f"'{admin_user}' y empieza a desplegar apps.", "ok")
        elif live:
            set_step("acceso", "done", f"Túnel activo en {dom}, engine sin publicar")
            log("Túnel y cluster operativos, pero el engine no quedó publicado. "
                "Revisa los pasos Repos e Imágenes.", "warn")
        else:
            set_step("acceso", "done", "ArgoCD en https://localhost:8080 (túnel no activo — revisa Cloudflare)")
            log("Célula Kaanbal operativa 🎉 (acceso local; para dominio revisa el paso Túnel)", "ok")
        set_phase("done")
        emit("handoff", **STATE["handoff"])

    except Exception as e:
        log(f"ERROR: {e}", "error")
        failed_step = None
        with STATE_LOCK:
            for sid, s in STATE["steps"].items():
                if s["status"] == "running":
                    STATE["steps"][sid] = {"status": "error", "detail": str(e)}
                    failed_step = sid
                    break
        if failed_step:
            emit("step", step=failed_step, status="error", detail=str(e))
        set_phase("error")
    finally:
        INSTALLING = False


# ------------------------------------------------------------------ HTTP ---
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".mp4": "video/mp4", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".woff2": "font/woff2"}


class Handler(BaseHTTPRequestHandler):
    server_version = "KaanbalInstaller/1.0"

    def log_message(self, fmt, *args):
        pass  # silencio: la terminal es para el token y eventos importantes

    def _auth_ok(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        token = q.get("token", [None])[0] or self.headers.get("X-Kaanbal-Token")
        return not TOKEN_REVOKED and secrets.compare_digest(token or "", TOKEN)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        path = urllib.parse.unquote(path)
        root = STATIC_DIR
        if path.startswith("/anim/") and ANIM_DIR:  # clips servidos DESDE la carpeta animacion
            root = ANIM_DIR
            path = path[len("/anim/"):]
        fpath = os.path.normpath(os.path.join(root, path.lstrip("/")))
        if not fpath.startswith(os.path.normpath(root)) or not os.path.isfile(fpath):
            self.send_error(404)
            return
        ext = os.path.splitext(fpath)[1]
        ctype = MIME.get(ext, "application/octet-stream")
        size = os.path.getsize(fpath)
        range_header = self.headers.get("Range")
        with open(fpath, "rb") as f:
            if range_header:  # soporte Range para los clips de Acuaponsito
                m = re.match(r"bytes=(\d+)-(\d*)", range_header)
                start = int(m.group(1)) if m else 0
                end = int(m.group(2)) if m and m.group(2) else size - 1
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.end_headers()
                f.seek(start)
                self.wfile.write(f.read(length))
            else:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                shutil.copyfileobj(f, self.wfile)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self._serve_static(parsed.path)
        if not self._auth_ok():
            return self._json(401, {"error": "Token inválido. Usa la URL impresa en la terminal."})

        if parsed.path == "/api/state":
            with STATE_LOCK:
                snapshot = json.loads(json.dumps({k: v for k, v in STATE.items() if k != "ai_providers"}))
                snapshot["ai_providers"] = [{"provider": p["provider"], "model": p.get("model", "")}
                                            for p in STATE.get("ai_providers", [])]
            snapshot["installing"] = INSTALLING
            snapshot["hostname"] = socket.gethostname().lower()
            return self._json(200, snapshot)

        if parsed.path == "/api/credentials/status":
            return self._json(200, credentials_status())

        if parsed.path == "/api/observe":
            return self._json(200, observe())

        if parsed.path == "/api/memory":
            q = parse_qs(parsed.query)
            limit = int(q.get("limit", ["120"])[0])
            return self._json(200, {"file": MEMORY_FILE, "events": recall(limit)})

        if parsed.path == "/api/agent/config":
            return self._json(200, {"workflows": WORKFLOWS, "roles": ROLES})

        if parsed.path == "/api/system-check":
            return self._json(200, system_info())

        if parsed.path == "/api/catalog":
            return self._json(200, load_catalog())

        if parsed.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = parse_qs(parsed.query)
            since = int(q.get("since", ["0"])[0])
            try:
                with STATE_LOCK:
                    backlog = EVENTS[since:]
                for i, ev in enumerate(backlog, start=since):
                    self.wfile.write(f"id: {i + 1}\ndata: {json.dumps(ev)}\n\n".encode())
                self.wfile.flush()
                idx = since + len(backlog)
                while True:
                    try:
                        ev = EVENT_Q.get(timeout=15)
                        with STATE_LOCK:
                            idx = len(EVENTS)
                        self.wfile.write(f"id: {idx}\ndata: {json.dumps(ev)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        self.send_error(404)

    def do_POST(self):
        global INSTALLING, TOKEN_REVOKED
        from urllib.parse import urlparse
        parsed = urlparse(self.path)
        if not self._auth_ok():
            return self._json(401, {"error": "Token inválido"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode() or "{}")

        if parsed.path == "/api/validate":
            kind = body.get("kind")
            if kind == "cloudflare":
                return self._json(200, validate_cloudflare(body.get("token", ""), body.get("account_id", "")))
            if kind == "github":
                return self._json(200, validate_github(
                    body.get("token", ""),
                    org=body.get("org", ""),
                    repo=body.get("repo", "infra-gitops"),
                ))
            if kind == "tailscale":
                return self._json(200, validate_tailscale(body.get("client_id", ""), body.get("client_secret", ""),
                                                          body.get("dns_suffix", "")))
            if kind == "docker":
                return self._json(200, validate_docker(body.get("username", ""), body.get("token", "")))
            return self._json(400, {"error": f"kind desconocido: {kind}"})

        if parsed.path == "/api/ai/validate":
            return self._json(200, validate_ai(body.get("provider", ""), body.get("api_key", "")))

        if parsed.path == "/api/ai/greet":
            result = ai_greet(body.get("provider", ""), body.get("api_key", ""),
                              body.get("model", ""), socket.gethostname())
            return self._json(200 if "error" not in result else 502, result)

        if parsed.path == "/api/ai/chat":
            result = ai_chat(body)
            return self._json(200 if "error" not in result else 400, result)

        if parsed.path == "/api/memory":
            event = remember(body.get("source", "console"), body.get("kind", "accion"),
                             **{k: v for k, v in body.items() if k not in ("source", "kind")})
            return self._json(201, event)

        if parsed.path == "/api/env/import":
            env_text = body.get("env", "")
            if not isinstance(env_text, str) or len(env_text.encode()) > 65536:
                return self._json(400, {"error": "El .env debe ser texto y pesar menos de 64KB"})
            parsed_env = parse_env_text(env_text)
            if not parsed_env:
                return self._json(400, {"error": "No encontré variables Kaanbal reconocidas"})
            save_credentials(parsed_env)
            remember("installer", "credentials-imported", keys=sorted(parsed_env))
            return self._json(200, {"message": "Credenciales guardadas", **credentials_status()})

        if parsed.path == "/api/finalize":
            if STATE.get("phase") != "done":
                return self._json(409, {"error": "La instalación todavía no terminó"})
            creds = load_credentials()
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            if not (secrets.compare_digest(username.encode(), creds.get("admin_user", "").encode()) and
                    secrets.compare_digest(password.encode(), creds.get("admin_pass", "").encode())):
                return self._json(401, {"error": "Usuario o contraseña no coinciden con el acceso configurado"})
            if not STATE.get("handoff", {}).get("engine_ready") or any(
                    step.get("status") in ("failed", "error") for step in STATE.get("steps", {}).values()):
                return self._json(409, {"error": "Hay componentes pendientes; no se puede cerrar el instalador"})
            if STATE.get("handoff", {}).get("vpn_verification_required") and not body.get("vpn_access_confirmed"):
                return self._json(409, {"error": "Confirma primero el acceso real a la consola desde tu VPN"})
            if not confirm_admin_access(username, password):
                return self._json(401, {"error": "La API no confirmó el acceso administrativo; el instalador sigue disponible"})
            self._json(200, {"message": "Acceso confirmado. Token temporal revocado."})
            TOKEN_REVOKED = True
            remember("installer", "token-revoked", username=username)
            threading.Thread(target=_shutdown_privileged_installer, daemon=True).start()
            return

        if parsed.path == "/api/catalog/clip":
            # Registrar un clip nuevo en la tabla master (animacion/catalog.json)
            if not ANIM_DIR:
                return self._json(400, {"error": "Carpeta animacion no disponible"})
            required = ("id", "file", "state")
            if not all(body.get(k) for k in required):
                return self._json(400, {"error": f"Campos requeridos: {required}"})
            if not os.path.isfile(os.path.join(ANIM_DIR, body["file"])):
                return self._json(400, {"error": f"El archivo '{body['file']}' no existe en la carpeta animacion"})
            cat_path = os.path.join(ANIM_DIR, "catalog.json")
            with open(cat_path, encoding="utf-8") as f:
                cat = json.load(f)
            if any(c["id"] == body["id"] for c in cat["clips"]):
                return self._json(409, {"error": f"Ya existe un clip con id '{body['id']}'"})
            shutil.copyfile(cat_path, cat_path + ".bak")  # respaldo antes de tocar la tabla master
            clip = {
                "id": body["id"], "file": body["file"], "state": body["state"],
                "title": body.get("title", body["id"]),
                "description": body.get("description", ""),
                "energy": body.get("energy", "media"), "loop": body.get("loop", True),
                "tags": body.get("tags", []), "added": time.strftime("%Y-%m-%d"),
            }
            cat["clips"].append(clip)
            if body["state"] not in cat.get("states", {}):
                cat.setdefault("states", {})[body["state"]] = {
                    "desc": body.get("state_desc", body["state"]), "fallback": "idle"}
            with open(cat_path, "w", encoding="utf-8") as f:
                json.dump(cat, f, ensure_ascii=False, indent=2)
            remember("console", "clip-registrado", clip_id=clip["id"], state=clip["state"])
            return self._json(201, {"message": "Clip agregado a la tabla master", "clip": clip})

        if parsed.path == "/api/install":
            with INSTALL_REQUEST_LOCK:
                if INSTALLING:
                    return self._json(409, {"error": "Instalación ya en curso"})
                restored = load_credentials()
                merged = {**restored, **{k: v for k, v in body.items() if v not in (None, "")}}
                try:
                    merged, errors = preflight_install(merged)
                except Exception:
                    return self._json(400, {"error": "No se pudo validar la configuración; no se inició la instalación"})
                if errors:
                    return self._json(400, {"error": "No se inició la instalación", "errors": errors})
                save_credentials(merged)
                INSTALLING = True
                threading.Thread(target=do_install, args=(merged,), daemon=True).start()
                return self._json(202, {"message": "Instalación iniciada", "stream": "/api/stream"})

        self.send_error(404)


def _shutdown_privileged_installer():
    time.sleep(1.0)
    for path in ("/run/kaanbal-installer/token", "/etc/kaanbal/installer-runtime.env"):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    if PRIVILEGED:
        subprocess.Popen(
            ["systemctl", "disable", "--now", "kaanbal-installer.service"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def _acuaponsito_token_ok():
    """True si el runtime en :4600 acepta el TOKEN actual del instalador."""
    try:
        url = f"http://127.0.0.1:4600/api/boot?token={urllib.parse.quote(TOKEN, safe='')}"
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _launch_agent_runtime():
    """El agente (Acuaponsito Runtime) arranca JUNTO con el instalador,
    compartiendo token. Es un servicio aparte: el instalador solo lo embebe."""
    runtime = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "acuaponsito", "server.py"))
    if not os.path.isfile(runtime):
        return None
    running = False
    try:
        socket.create_connection(("127.0.0.1", 4600), timeout=1).close()
        running = True
    except OSError:
        pass
    if running:
        if _acuaponsito_token_ok():
            return "existente"
        # Runtime viejo con otro token (p. ej. tras reiniciar el instalador)
        raise RuntimeError("Puerto 4600 ocupado por otro runtime; no se cerró ningún proceso")
    env = {
        **os.environ,
        "ACUA_TOKEN": TOKEN,
        "ACUA_HOST": os.environ.get("ACUA_HOST", "127.0.0.1"),
    }
    if ANIM_DIR:
        env["KAANBAL_ANIM_DIR"] = ANIM_DIR
    subprocess.Popen([sys.executable, runtime], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "relanzado" if running else "lanzado"


def main():
    os.chdir(STATIC_DIR)
    agent = _launch_agent_runtime()
    server = ThreadingHTTPServer((os.environ.get("KAANBAL_INSTALLER_HOST", "127.0.0.1"), PORT), Handler)
    url = f"http://localhost:{PORT}/?token={TOKEN}"
    print("=" * 62)
    print("  🌱 Kaanbal Web Installer")
    print("=" * 62)
    print(f"  URL de acceso (incluye tu token de sesión):\n")
    print("    URL disponible en la terminal que lanzó install.sh\n" if PRIVILEGED else f"    {url}\n")
    print("  Acceso remoto mediante túnel SSH; consulta el manual de instalación.")
    if agent:
        print(f"  Agente  : Acuaponsito Runtime {agent} en :4600 (mismo token)")
    print("=" * 62, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
