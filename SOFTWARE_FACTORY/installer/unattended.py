"""Instalación desatendida de Kaanbal a partir de un archivo .env.

Es la misma instalación que hace el asistente web: no duplica lógica, sino que
normaliza el archivo, valida cada credencial contra su proveedor y luego dispara
`/api/install` en el instalador local, que es el único que sabe desplegar.

El orden importa. Primero se comprueba todo lo que puede fallar sin efectos
secundarios (formato, permisos de los tokens, que el dominio sea tuyo), y solo
después se toca la máquina. Descubrir a los veinte minutos que al token de
GitHub le falta un permiso es el fallo más caro de esta instalación, y el más
fácil de evitar.

Solo stdlib.
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402  (reutiliza validadores y lector de .env)

CYAN, GREEN, RED, YELLOW, DIM, RESET = (
    "\033[1;36m", "\033[1;32m", "\033[1;31m", "\033[1;33m", "\033[2m", "\033[0m")

MIN_PASSWORD = 12
VALID_MODES = ("cloud", "local")
VALID_EXPOSURES = ("public", "tailnet")

_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


def say(msg):
    print(f"{CYAN}[kaanbal]{RESET} {msg}", flush=True)


def ok(msg):
    print(f"  {GREEN}OK{RESET}    {msg}", flush=True)


def warn(msg):
    print(f"  {YELLOW}AVISO{RESET} {msg}", flush=True)


def bad(msg):
    print(f"  {RED}FALLA{RESET} {msg}", flush=True)


# --------------------------------------------------------------- normalizar --

def normalize(values):
    """Convierte lo leído del .env en la configuración que espera el instalador.

    Devuelve (cfg, errores). Los errores son de forma, no de credencial: se
    detectan sin salir a la red y siempre describen qué variable arreglar.
    """
    cfg = dict(values)
    errors = []

    domain = (cfg.get("domain") or "").strip().lower().lstrip("*.").rstrip("/")
    cfg["domain"] = domain

    mode = (cfg.get("mode") or "").strip().lower()
    if not mode:
        # Con dominio y token de Cloudflare la intención es evidente; sin ellos
        # la célula solo puede vivir en la red local.
        mode = "cloud" if domain and cfg.get("cf_token") else "local"
    if mode not in VALID_MODES:
        errors.append(f"KAANBAL_MODE debe ser 'cloud' o 'local', no '{mode}'")
    cfg["mode"] = mode

    default_exposure = "public" if mode == "cloud" else "tailnet"
    for key, label in (("console_exposure", "KAANBAL_CONSOLE_EXPOSURE"),
                       ("api_exposure", "KAANBAL_API_EXPOSURE")):
        value = (cfg.get(key) or "").strip().lower() or default_exposure
        if value not in VALID_EXPOSURES:
            errors.append(f"{label} debe ser 'public' o 'tailnet', no '{value}'")
        cfg[key] = value

    # El agente ve toda la plataforma, así que sin instrucción explícita
    # acompaña a la consola en vez de quedar más expuesto que ella.
    agent = (cfg.get("agent_exposure") or "").strip().lower() or cfg["console_exposure"]
    if agent not in VALID_EXPOSURES:
        errors.append(f"KAANBAL_AGENT_EXPOSURE debe ser 'public' o 'tailnet', no '{agent}'")
    cfg["agent_exposure"] = agent

    cfg["admin_user"] = (cfg.get("admin_user") or "admin").strip()
    admin_pass = (cfg.get("admin_pass") or "").strip()
    cfg["admin_pass"] = admin_pass

    # --- lo que no puede faltar nunca ---
    if not cfg.get("github_org"):
        errors.append("Falta GITHUB_ORG: sin ella no hay dónde crear infra-gitops")
    if not cfg.get("gitops_token"):
        errors.append("Falta GITHUB_TOKEN: el instalador no podría publicar los repos")
    if not cfg.get("docker_user") or not cfg.get("docker_token"):
        errors.append("Faltan DOCKER_USER o DOCKER_TOKEN: sin registro no hay imágenes")
    if not admin_pass:
        errors.append("Falta KAANBAL_ADMIN_PASS: es la contraseña con la que entrarás a la consola")
    elif len(admin_pass) < MIN_PASSWORD:
        errors.append(
            f"KAANBAL_ADMIN_PASS tiene {len(admin_pass)} caracteres y el mínimo "
            f"son {MIN_PASSWORD}. Es la llave de toda la plataforma.")

    # --- lo que depende del modo ---
    if mode == "cloud":
        if not domain:
            errors.append("KAANBAL_MODE=cloud necesita un DOMAIN")
        elif not _DOMAIN_RE.match(domain):
            errors.append(f"DOMAIN no parece un dominio válido: '{domain}'")
        if not cfg.get("cf_token") or not cfg.get("cf_account"):
            errors.append("KAANBAL_MODE=cloud necesita CF_TOKEN y CF_ACCOUNT_ID")

    has_tailscale = bool(cfg.get("tailscale_id") and cfg.get("tailscale_secret"))
    if not has_tailscale:
        for key, label in (("console_exposure", "la consola"),
                           ("api_exposure", "la API")):
            if cfg.get(key) == "tailnet":
                errors.append(
                    f"Pediste {label} solo por VPN, pero faltan TAILSCALE_CLIENT_ID "
                    "y TAILSCALE_CLIENT_SECRET: quedaría sin ninguna vía de acceso.")

    cfg["ai_providers"] = cfg.get("ai_providers") or ai_providers_from(cfg)
    return cfg, errors


def ai_providers_from(cfg):
    """Proveedores de IA declarados en el archivo, en orden de preferencia."""
    providers = []
    for name, config_key in server.AI_KEY_CONFIG.items():
        api_key = (cfg.get(config_key) or "").strip()
        if api_key:
            providers.append({
                "provider": name,
                "api_key": api_key,
                "model": server.AI_PROVIDERS[name]["default_model"],
            })
    return providers


# ---------------------------------------------------------------- preflight --

def preflight(cfg, check_delete=False):
    """Valida cada credencial contra su proveedor. Devuelve (errores, avisos)."""
    errors, warnings = [], []

    say("Validando credenciales con cada proveedor")

    github = server.validate_github(cfg["gitops_token"], cfg["github_org"])
    if github.get("valid"):
        cfg["github_login"] = github.get("login", "")
        cfg["gitops_url"] = github.get("gitops_url", cfg.get("gitops_url", ""))
        ok(f"GitHub: {cfg['github_org']} accesible como {cfg['github_login'] or '?'}")
    else:
        errors.append(f"GitHub: {github.get('message', 'token rechazado')}")
        bad(f"GitHub: {github.get('message', 'token rechazado')}")

    missing_scopes = github_missing_scopes(cfg["gitops_token"], check_delete)
    for scope, why in missing_scopes:
        message = f"al token de GitHub le falta el permiso `{scope}` ({why})"
        if scope == "delete_repo":
            warnings.append(message)
            warn(message)
        else:
            errors.append(message)
            bad(message)

    docker = server.validate_docker(cfg["docker_user"], cfg["docker_token"])
    if docker.get("valid"):
        ok(f"Docker Hub: autenticado como {cfg['docker_user']}")
    else:
        errors.append(f"Docker Hub: {docker.get('message', 'token rechazado')}")
        bad(f"Docker Hub: {docker.get('message', 'token rechazado')}")

    if cfg["mode"] == "cloud":
        cloudflare = server.validate_cloudflare(cfg["cf_token"], cfg["cf_account"])
        if cloudflare.get("valid"):
            ok(f"Cloudflare: {cloudflare.get('message', 'token válido')}")
        else:
            errors.append(f"Cloudflare: {cloudflare.get('message', 'token rechazado')}")
            bad(f"Cloudflare: {cloudflare.get('message', 'token rechazado')}")

        zone = cloudflare_zone(cfg["cf_token"], cfg["domain"])
        if zone:
            ok(f"Cloudflare: la zona {cfg['domain']} está en tu cuenta")
        else:
            errors.append(
                f"Cloudflare: no encuentro la zona '{cfg['domain']}' con ese token. "
                "Revisa que el dominio esté en esta cuenta y que el token tenga "
                "permiso Zone·Read sobre él.")
            bad(f"Cloudflare: la zona {cfg['domain']} no aparece con este token")

    if cfg.get("tailscale_id") and cfg.get("tailscale_secret"):
        tailscale = server.validate_tailscale(
            cfg["tailscale_id"], cfg["tailscale_secret"], cfg.get("tailscale_dns", ""))
        if tailscale.get("valid"):
            ok(f"Tailscale: {tailscale.get('message', 'OAuth válido')}")
        else:
            errors.append(f"Tailscale: {tailscale.get('message', 'OAuth rechazado')}")
            bad(f"Tailscale: {tailscale.get('message', 'OAuth rechazado')}")
    else:
        warn("Sin Tailscale: el nivel 'solo VPN' no estará disponible")

    # El agente es un extra: que su clave falle no debe impedir instalar la
    # plataforma, solo dejarla sin agente hasta que se corrija.
    usable = []
    for provider in cfg.get("ai_providers", []):
        result = server.validate_ai(provider["provider"], provider["api_key"])
        if result.get("valid"):
            usable.append(provider)
            ok(f"Agente IA: {provider['provider']} responde")
        else:
            message = f"IA {provider['provider']}: {result.get('message', 'clave rechazada')}"
            warnings.append(message)
            warn(message)
    cfg["ai_providers"] = usable

    tpl_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kaanbal-templates")
    if not os.path.isdir(tpl_local):
        errors.append(
            "Falta el directorio kaanbal-templates en el instalador. "
            "Sin él la consola lista plantillas pero no puede desplegar apps.")
        bad("kaanbal-templates: no está en el paquete del instalador")
    else:
        ok("kaanbal-templates: fuente local presente")

    if cfg.get("gitops_token") and cfg.get("github_org"):
        st, _ = server._github_api(
            "GET", f"/repos/{cfg['github_org']}/kaanbal-templates",
            cfg["gitops_token"])
        if st == 200:
            ok("GitHub: repo kaanbal-templates accesible")
        elif st == 404:
            warnings.append(
                "GitHub: kaanbal-templates aún no existe — el instalador lo creará")
            warn("kaanbal-templates: se publicará durante la instalación")
        elif st == 401:
            warnings.append("GitHub: no pude verificar kaanbal-templates (token)")

    return errors, warnings


def github_missing_scopes(token, check_delete=False):
    """Permisos que le faltan al token para lo que el instalador va a hacer."""
    needed = [
        ("repo", "crear y escribir los repos del sistema"),
        ("workflow", "publicar los pipelines de GitHub Actions"),
    ]
    if check_delete:
        needed.append(("delete_repo", "necesario solo para --reset-remote"))

    request = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "kaanbal-installer"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            granted = response.headers.get("X-OAuth-Scopes") or ""
    except Exception:
        return []

    if not granted.strip():
        # Un token de grano fino no publica scopes clásicos; sus permisos se
        # verán al primer uso real y no tiene sentido adivinarlos aquí.
        return []

    have = {scope.strip() for scope in granted.split(",")}
    return [(scope, why) for scope, why in needed if scope not in have]


def cloudflare_zone(token, domain):
    """ID de la zona del dominio, o "" si el token no la ve."""
    url = ("https://api.cloudflare.com/client/v4/zones?"
           + urllib.parse.urlencode({"name": domain}))
    status, body = server.http_json(url, {"Authorization": f"Bearer {token}"})
    if status != 200 or not isinstance(body, dict):
        return ""
    results = body.get("result") or []
    return results[0].get("id", "") if results else ""


# ------------------------------------------------------------------- driver --

class Installer:
    """Cliente del instalador local que corre en esta misma máquina."""

    def __init__(self, token, port=3000, host="127.0.0.1"):
        self.base = f"http://{host}:{port}"
        self.token = token

    def _call(self, path, payload=None, timeout=60):
        request = urllib.request.Request(
            self.base + path,
            headers={"X-Kaanbal-Token": self.token,
                     "Content-Type": "application/json"},
            data=json.dumps(payload).encode() if payload is not None else None,
            method="POST" if payload is not None else "GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode() or "{}")

    def wait_until_up(self, timeout=90):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._call("/api/state", timeout=5)
                return True
            except Exception:
                time.sleep(1)
        return False

    def state(self):
        return self._call("/api/state")[1]

    def start(self, cfg):
        payload = {key: cfg[key] for key in (
            "domain", "mode", "console_exposure", "api_exposure", "agent_exposure",
            "admin_user", "admin_pass", "github_org", "gitops_token",
            "docker_user", "docker_token", "cf_token", "cf_account",
            "tunnel_token", "tailscale_id", "tailscale_secret", "tailscale_dns",
            "core_version",
        ) if cfg.get(key)}
        if cfg.get("ai_providers"):
            payload["ai_providers"] = cfg["ai_providers"]
        # Provider checks are shared with the UI and may require several requests.
        try:
            return self._call("/api/install", payload, timeout=600)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")


STEP_LABELS = {
    "sistema": "Sistema", "k3s": "k3s", "nodo": "Nodo", "argocd": "ArgoCD",
    "ia": "Agente IA", "cloudflared": "Túnel", "repos": "Repos",
    "imagenes": "Imágenes", "gitops": "GitOps", "plataforma": "Plataforma",
    "acceso": "Acceso",
}
STEP_MARKS = {"done": f"{GREEN}✓{RESET}", "error": f"{RED}✗{RESET}",
              "failed": f"{RED}✗{RESET}", "running": f"{CYAN}·{RESET}",
              "skipped": f"{DIM}–{RESET}", "pending": f"{DIM}·{RESET}"}


def follow(installer, timeout=3600, quiet=False):
    """Sigue la instalación hasta que termine. Devuelve el estado final."""
    seen_log = 0
    seen_steps = {}
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            state = installer.state()
        except Exception:
            time.sleep(3)
            continue

        for entry in (state.get("log") or [])[seen_log:]:
            level = entry.get("level", "info")
            message = entry.get("message", "")
            if quiet and level in ("cmd", "out"):
                continue
            prefix = {"ok": GREEN + "  ✓ " + RESET, "warn": YELLOW + "  ! " + RESET,
                      "error": RED + "  ✗ " + RESET}.get(level, DIM + "    " + RESET)
            print(prefix + message, flush=True)
        seen_log = len(state.get("log") or [])

        for step_id, step in (state.get("steps") or {}).items():
            status = step.get("status", "pending")
            if seen_steps.get(step_id) == status:
                continue
            seen_steps[step_id] = status
            if status in ("done", "error", "failed", "skipped"):
                label = STEP_LABELS.get(step_id, step_id)
                detail = step.get("detail", "")
                print(f"  {STEP_MARKS.get(status, '?')} {label}"
                      + (f" — {detail}" if detail else ""), flush=True)

        phase = state.get("phase")
        if phase in ("done", "error"):
            return state
        time.sleep(4)

    raise TimeoutError("La instalación excedió el tiempo máximo")


# -------------------------------------------------------------- verificación --

def resolves(hostname):
    try:
        socket.getaddrinfo(hostname, None)
        return True
    except OSError:
        return False


def verify(cfg, handoff):
    """Comprueba que lo prometido responde de verdad. Devuelve (ok?, hallazgos)."""
    findings = []
    healthy = True

    say("Verificando el resultado")

    domain = cfg.get("domain", "")
    console_public = cfg.get("console_exposure") == "public"
    api_public = cfg.get("api_exposure") == "public"

    targets = []
    if cfg["mode"] == "cloud" and domain:
        if console_public:
            targets.append(("Consola", f"https://{server.CORE_HOSTS['console']}.{domain}"))
            targets.append((f"Atajo {server.CONSOLE_SHORTCUT}",
                            f"https://{server.CONSOLE_SHORTCUT}.{domain}"))
            targets.append(("Agente Acuaponsito",
                            f"https://{server.CORE_HOSTS['agent']}.{domain}"))
        if api_public:
            targets.append(("API del engine",
                            f"https://{server.CORE_HOSTS['api']}.{domain}/health"))
        targets.append(("ArgoCD", f"https://{server.CORE_HOSTS['argocd']}.{domain}"))

    for label, url in targets:
        hostname = urllib.parse.urlparse(url).hostname
        if not resolves(hostname):
            healthy = False
            findings.append(f"{label}: {hostname} todavía no resuelve en DNS")
            bad(f"{label}: {hostname} no resuelve")
            continue
        reachable, detail = server.probe_public_url(url, timeout=20)
        if reachable:
            ok(f"{label}: {url} responde (HTTP {detail})")
        else:
            healthy = False
            findings.append(f"{label}: {url} no responde — {detail}")
            bad(f"{label}: {url} no responde ({detail})")

    if cfg.get("console_exposure") == "tailnet":
        suffix = cfg.get("tailscale_dns", "")
        hostname = f"kaanbal-console.{suffix}" if suffix else ""
        if hostname and resolves(hostname):
            reachable, detail = server.probe_public_url(f"http://{hostname}", timeout=20)
            if reachable:
                ok(f"Consola en la VPN: {hostname} responde")
            else:
                healthy = False
                findings.append(f"Consola VPN no responde: {detail}")
        else:
            healthy = False
            findings.append(
                "La consola es solo-VPN: verifica desde un equipo conectado a tu "
                "tailnet, este servidor puede no resolver MagicDNS todavía.")
            warn("Consola solo-VPN: no puedo comprobarla desde aquí")

    if not handoff.get("engine_ready"):
        healthy = False
        findings.append("El instalador no confirmó el core operativo")

    for key, label in (("console_url", "Consola"), ("api_url", "API"),
                       ("agent_url", "Agente"), ("argocd_url", "ArgoCD")):
        if handoff.get(key):
            print(f"  {DIM}{label}:{RESET} {handoff[key]}", flush=True)

    return healthy, findings


# ---------------------------------------------------------------------- CLI --

def load_config(env_file):
    with open(env_file, "r", encoding="utf-8") as handle:
        return server.parse_env_text(handle.read())


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Instala Kaanbal de forma desatendida a partir de un .env")
    parser.add_argument("--env", required=True, help="Archivo de configuración")
    parser.add_argument("--check-only", action="store_true",
                        help="Solo valida: no toca la máquina")
    parser.add_argument("--expect-reset", action="store_true",
                        help="Se va a usar --reset-remote: exige delete_repo")
    parser.add_argument("--token", default="",
                        help="Token del instalador (por defecto lo lee de /run)")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--quiet", action="store_true",
                        help="Oculta la salida cruda de los comandos")
    args = parser.parse_args(argv)

    if not os.path.exists(args.env):
        bad(f"No existe el archivo {args.env}")
        return 2

    cfg, errors = normalize(load_config(args.env))

    say(f"Configuración leída de {args.env}")
    print(f"  {DIM}dominio:{RESET} {cfg.get('domain') or '(sin dominio)'}"
          f"   {DIM}modo:{RESET} {cfg.get('mode')}"
          f"   {DIM}consola:{RESET} {cfg.get('console_exposure')}"
          f"   {DIM}api:{RESET} {cfg.get('api_exposure')}", flush=True)

    if errors:
        print()
        for message in errors:
            bad(message)
        print()
        say("Corrige el archivo y vuelve a ejecutar. No se tocó nada.")
        return 2

    online_errors, _warnings = preflight(cfg, check_delete=args.expect_reset)
    if online_errors:
        print()
        say("Hay credenciales que no sirven para lo que el instalador necesita:")
        for message in online_errors:
            bad(message)
        print()
        say("No se tocó nada. Corrige y vuelve a ejecutar.")
        return 2

    if args.check_only:
        print()
        say("Todo en orden. La instalación puede proceder.")
        return 0

    token = args.token or read_installer_token()
    if not token:
        bad("No encuentro el token del instalador: ¿está corriendo el servicio?")
        return 3

    installer = Installer(token, port=args.port)
    if not installer.wait_until_up():
        bad(f"El instalador no responde en el puerto {args.port}")
        return 3

    print()
    say("Instalando")
    status, body = installer.start(cfg)
    if status not in (200, 202):
        bad(f"El instalador rechazó la configuración: {body}")
        return 3

    try:
        state = follow(installer, timeout=args.timeout, quiet=args.quiet)
    except TimeoutError as exc:
        bad(str(exc))
        return 4

    handoff = state.get("handoff") or {}
    print()

    if state.get("phase") != "done":
        say("La instalación no terminó bien:")
        for step_id, step in (state.get("steps") or {}).items():
            if step.get("status") in ("error", "failed"):
                bad(f"{STEP_LABELS.get(step_id, step_id)}: {step.get('detail', '')}")
        return 5

    healthy, findings = verify(cfg, handoff)

    print()
    if healthy:
        say(f"{GREEN}Kaanbal está operativo.{RESET}")
        console = handoff.get("console_url") or ""
        if console:
            say(f"Entra en {console} con el usuario '{cfg['admin_user']}'.")
        return 0

    say(f"{YELLOW}La instalación terminó, pero falta que responda todo:{RESET}")
    for finding in findings:
        print(f"    {finding}", flush=True)
    say("Suele ser propagación de DNS de Cloudflare; reintenta la verificación "
        "en un par de minutos.")
    return 6


def read_installer_token(path="/run/kaanbal-installer/token"):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
