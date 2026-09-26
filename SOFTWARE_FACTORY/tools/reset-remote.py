#!/usr/bin/env python3
"""Borra los recursos remotos del sistema Kaanbal para reinstalar desde cero.

Pensado para el modo desarrollo, donde la instalación se repite muchas veces y
arrastrar un `infra-gitops` de una prueba anterior falsea el resultado.

Regla de seguridad: **allowlist estricta por nombre exacto**. Solo se toca lo
que el instalador creó (`infra-gitops`, `kaanbal-api`, `kaanbal-console`,
`kaanbal-templates` en GitHub; `kaanbal-api` y `kaanbal-console` en Docker Hub).
Cualquier otro repositorio o imagen de la organización se ignora, incluidas las
apps que hayas desplegado desde la consola. No hay modo "borra por prefijo".

Uso:
    sudo python3 tools/reset-remote.py --yes                 # GitHub + Docker Hub
    sudo python3 tools/reset-remote.py --dry-run             # solo enumera
    sudo python3 tools/reset-remote.py --yes --github-only

Solo stdlib.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENV_FILE = "/etc/kaanbal/installer.env"

# Nombres exactos. Añadir aquí es una decisión consciente: cualquier cosa que
# entre en esta lista se borra sin preguntar cuando corres --yes.
GITHUB_SYSTEM_REPOS = ("infra-gitops", "kaanbal-api", "kaanbal-console",
                       "kaanbal-agent", "kaanbal-templates")
DOCKERHUB_SYSTEM_REPOS = ("kaanbal-api", "kaanbal-console", "kaanbal-agent")

CYAN, RED, YELLOW, RESET = "\033[1;36m", "\033[1;31m", "\033[1;33m", "\033[0m"


def log(msg):
    print(f"{CYAN}[kaanbal-reset-remote]{RESET} {msg}")


def warn(msg):
    print(f"{YELLOW}[kaanbal-reset-remote]{RESET} {msg}")


def die(msg, code=1):
    print(f"{RED}[kaanbal-reset-remote] ERROR:{RESET} {msg}", file=sys.stderr)
    raise SystemExit(code)


# Un mismo dato viaja con varios nombres según quién escribió el .env.
ALIASES = {
    "GITHUB_ORG": ("GITHUB_ORG", "KB_GIT_ORG", "GITHUB_WORKSPACE_ORG"),
    "GITOPS_TOKEN": ("GITOPS_TOKEN", "KB_GIT_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"),
    "DOCKER_USER": ("DOCKER_USER", "KB_DOCKER_USER", "DOCKERHUB_USER",
                    "DOCKERHUB_USERNAME"),
    "DOCKER_TOKEN": ("DOCKER_TOKEN", "KB_DOCKER_TOKEN", "DOCKERHUB_TOKEN"),
}


def load_env(path):
    """Lee un archivo KEY=VALUE tolerando comillas, comentarios y minúsculas."""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.lower().startswith("export "):
                key = key[7:].strip()
            values[key.upper()] = value.strip().strip('"').strip("'")
    return values


def pick(env, canonical):
    """Primer valor no vacío entre los alias conocidos de una credencial."""
    for name in ALIASES.get(canonical, (canonical,)):
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def _request(method, url, headers=None, body=None, timeout=30):
    data = None
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except Exception:
            return exc.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


# ------------------------------------------------------------------ GitHub ---
def github_headers(token):
    prefixes = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_")
    auth = f"token {token}" if token.startswith(prefixes) else f"Bearer {token}"
    return {
        "Authorization": auth,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def reset_github(org, token, dry_run):
    headers = github_headers(token)
    deleted, skipped, failed = [], [], {}

    for repo in GITHUB_SYSTEM_REPOS:
        status, _ = _request("GET", f"https://api.github.com/repos/{org}/{repo}",
                             headers)
        if status == 404:
            skipped.append(f"{repo} (no existe)")
            continue
        if status != 200:
            failed[repo] = f"no pude consultarlo (HTTP {status})"
            continue

        if dry_run:
            deleted.append(f"{repo} (simulado)")
            continue

        status, body = _request(
            "DELETE", f"https://api.github.com/repos/{org}/{repo}", headers)
        if status == 204:
            deleted.append(repo)
        elif status == 403:
            failed[repo] = ("el token no tiene permiso delete_repo — añade ese "
                            "scope al PAT")
        else:
            failed[repo] = f"HTTP {status}: {body.get('message', '')[:120]}"

    return deleted, skipped, failed


# -------------------------------------------------------------- Docker Hub ---
def dockerhub_login(username, token):
    status, body = _request("POST", "https://hub.docker.com/v2/users/login/",
                            body={"username": username, "password": token})
    if status != 200 or not body.get("token"):
        return "", f"HTTP {status}: {str(body)[:150]}"
    return body["token"], None


def reset_dockerhub(username, token, dry_run):
    jwt, err = dockerhub_login(username, token)
    if err:
        return [], [], {"login": err}

    headers = {"Authorization": f"JWT {jwt}"}
    deleted, skipped, failed = [], [], {}

    for repo in DOCKERHUB_SYSTEM_REPOS:
        url = f"https://hub.docker.com/v2/repositories/{username}/{repo}/"
        status, _ = _request("GET", url, headers)
        if status == 404:
            skipped.append(f"{repo} (no existe)")
            continue
        if status != 200:
            failed[repo] = f"no pude consultarlo (HTTP {status})"
            continue

        if dry_run:
            deleted.append(f"{repo} (simulado)")
            continue

        status, body = _request("DELETE", url, headers)
        if status in (202, 204):
            deleted.append(repo)
        else:
            failed[repo] = f"HTTP {status}: {str(body)[:120]}"

    return deleted, skipped, failed


def _report(target, deleted, skipped, failed):
    for item in deleted:
        log(f"  {target}: borrado {item}")
    for item in skipped:
        log(f"  {target}: omitido {item}")
    for name, reason in failed.items():
        warn(f"  {target}: {name} -> {reason}")
    return not failed


def main(argv):
    parser = argparse.ArgumentParser(
        description="Borra los repos e imágenes del sistema Kaanbal (allowlist estricta).")
    parser.add_argument("--env", default=DEFAULT_ENV_FILE,
                        help=f"Archivo de credenciales (default: {DEFAULT_ENV_FILE})")
    parser.add_argument("--yes", action="store_true", help="No pedir confirmación")
    parser.add_argument("--dry-run", action="store_true",
                        help="Enumera lo que borraría sin tocar nada")
    parser.add_argument("--github-only", action="store_true")
    parser.add_argument("--dockerhub-only", action="store_true")
    args = parser.parse_args(argv)

    env = {**load_env(args.env), **{k.upper(): v for k, v in os.environ.items()}}
    org = pick(env, "GITHUB_ORG")
    git_token = pick(env, "GITOPS_TOKEN")
    docker_user = pick(env, "DOCKER_USER")
    docker_token = pick(env, "DOCKER_TOKEN")

    do_github = not args.dockerhub_only
    do_docker = not args.github_only

    print()
    log("Alcance del reset remoto (allowlist estricta):")
    if do_github:
        log(f"  GitHub {org or '(sin org)'}: {', '.join(GITHUB_SYSTEM_REPOS)}")
    if do_docker:
        log(f"  Docker Hub {docker_user or '(sin usuario)'}: "
            f"{', '.join(DOCKERHUB_SYSTEM_REPOS)}")
    log("  Nada más se toca: tus apps y sus repos quedan intactos.")
    print()

    if not args.yes and not args.dry_run:
        answer = input("Escribe RESET-REMOTO para continuar: ").strip()
        if answer != "RESET-REMOTO":
            die("Cancelado.")

    ok = True
    if do_github:
        if not (org and git_token):
            warn("GitHub omitido: faltan GITHUB_ORG o GITOPS_TOKEN en el entorno.")
        else:
            log(f"GitHub — organización {org}")
            ok &= _report("github", *reset_github(org, git_token, args.dry_run))

    if do_docker:
        if not (docker_user and docker_token):
            warn("Docker Hub omitido: faltan DOCKER_USER o DOCKER_TOKEN en el entorno.")
        else:
            log(f"Docker Hub — usuario {docker_user}")
            ok &= _report("dockerhub",
                          *reset_dockerhub(docker_user, docker_token, args.dry_run))

    print()
    if args.dry_run:
        log("Simulación terminada: no se borró nada.")
    elif ok:
        log("Reset remoto completado. La próxima instalación empieza de cero.")
    else:
        warn("Reset remoto terminó con avisos — revisa las líneas de arriba.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
