"""Renderiza el baseline de infra-gitops con la configuración de la célula.

El monorepo guarda `infra-gitops/` como plantilla: hosts, org de GitHub, usuario
de Docker Hub y tags de imagen viven como `${KAANBAL_*}`, y los bloques que
dependen del modo de exposición van entre marcas `@kaanbal:if`. Este módulo
produce el árbol concreto que se publica en el `infra-gitops` del cliente.

Regla de oro del proyecto: nada de parches manuales sobre el repo desplegado.
Si algo hay que cambiar, se cambia la plantilla o el contexto del instalador y
se vuelve a renderizar — el resultado es reproducible bit a bit.

Solo stdlib: corre en la máquina destino sin pip.
"""

import fnmatch
import os
import posixpath
import re
import shutil

BASELINE_FILE = ".kaanbal-baseline"

_VAR_RE = re.compile(r"\$\{(KAANBAL_[A-Z0-9_]+)\}")
_IF_RE = re.compile(r"^\s*#\s*@kaanbal:if\s+([A-Z0-9_]+)\s*$")
_ELSE_RE = re.compile(r"^\s*#\s*@kaanbal:else\s*$")
_ENDIF_RE = re.compile(r"^\s*#\s*@kaanbal:endif\s*$")

TEXT_SUFFIXES = {
    ".yaml", ".yml", ".json", ".md", ".txt", ".sh", ".tf", ".tfvars",
    ".py", ".ps1", ".gitignore", ".env", "",
}

# Directorios que nunca se copian aunque el baseline los incluya.
ALWAYS_SKIP_DIRS = {".git", "__pycache__", ".terraform", "node_modules"}


class RenderError(Exception):
    """Plantilla inválida o contexto incompleto."""


def load_baseline(root, flags=None):
    """Lee `.kaanbal-baseline` y devuelve [(patrón, incluir?)] en orden.

    Una regla puede condicionarse con `?FLAG ` delante del patrón: solo cuenta
    si esa flag está activa. Sirve para no publicar componentes que dependen de
    credenciales que el usuario no dio — un operador sin sus llaves no queda
    "pendiente", queda en CrashLoopBackOff y ensucia el veredicto de ArgoCD.

    Con `flags=None` las condiciones se ignoran y todas las reglas cuentan.
    """
    path = os.path.join(root, BASELINE_FILE)
    if not os.path.exists(path):
        raise RenderError(f"Falta {BASELINE_FILE} en {root}")

    rules = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            include = True
            if line.startswith("!"):
                include = False
                line = line[1:].strip()

            if line.startswith("?"):
                condition, _, rest = line[1:].partition(" ")
                line = rest.strip()
                if not line:
                    raise RenderError(
                        f"{BASELINE_FILE}:{lineno}: `?{condition}` sin patrón")
                if flags is not None:
                    if condition not in flags:
                        raise RenderError(
                            f"{BASELINE_FILE}:{lineno}: flag desconocida `{condition}`")
                    if not flags[condition]:
                        continue

            rules.append((line, include))
    if not rules:
        raise RenderError(f"{BASELINE_FILE} no declara ninguna ruta")
    return rules


def path_included(relpath, rules):
    """Gana la última regla que coincide; por defecto se excluye."""
    included = False
    for pattern, include in rules:
        if _match(relpath, pattern):
            included = include
    return included


def _match(relpath, pattern):
    if fnmatch.fnmatch(relpath, pattern):
        return True
    # "apps/kaanbal-api/**" debe cubrir también "apps/kaanbal-api" a secas.
    if pattern.endswith("/**") and relpath == pattern[:-3]:
        return True
    return False


def apply_conditionals(text, flags, origin=""):
    """Resuelve los bloques @kaanbal:if / :else / :endif."""
    out = []
    # Cada nivel guarda (flag_activo, ya_vimos_else). emitting = todos activos.
    stack = []
    for lineno, line in enumerate(text.splitlines(True), 1):
        m = _IF_RE.match(line)
        if m:
            flag = m.group(1)
            if flag not in flags:
                raise RenderError(f"{origin}:{lineno}: flag desconocida @kaanbal:if {flag}")
            stack.append([bool(flags[flag]), False])
            continue
        if _ELSE_RE.match(line):
            if not stack:
                raise RenderError(f"{origin}:{lineno}: @kaanbal:else sin @kaanbal:if")
            if stack[-1][1]:
                raise RenderError(f"{origin}:{lineno}: @kaanbal:else duplicado")
            stack[-1][0] = not stack[-1][0]
            stack[-1][1] = True
            continue
        if _ENDIF_RE.match(line):
            if not stack:
                raise RenderError(f"{origin}:{lineno}: @kaanbal:endif sin @kaanbal:if")
            stack.pop()
            continue
        if all(level[0] for level in stack):
            out.append(line)

    if stack:
        raise RenderError(f"{origin}: falta @kaanbal:endif")
    return "".join(out)


def substitute(text, context, origin=""):
    """Reemplaza ${KAANBAL_*}; falla si la plantilla pide algo que no tenemos."""
    missing = set()

    def repl(match):
        key = match.group(1)
        if key not in context:
            missing.add(key)
            return match.group(0)
        return str(context[key])

    rendered = _VAR_RE.sub(repl, text)
    if missing:
        raise RenderError(
            f"{origin}: el contexto no define {', '.join(sorted(missing))}"
        )
    return rendered


def render_text(text, context, flags, origin=""):
    return substitute(apply_conditionals(text, flags, origin), context, origin)


def is_effectively_empty(text):
    """True si tras renderizar solo quedan comentarios y líneas en blanco.

    Un manifiesto así rompe `kustomize build`, así que no se escribe.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return False
    return True


def _is_text_file(relpath):
    suffix = os.path.splitext(relpath)[1].lower()
    if suffix in TEXT_SUFFIXES:
        return True
    return os.path.basename(relpath).startswith(".")


def render_tree(src_root, dst_root, context, flags, rules=None):
    """Renderiza `src_root` en `dst_root`. Devuelve las rutas escritas."""
    rules = rules if rules is not None else load_baseline(src_root, flags)

    if os.path.exists(dst_root):
        shutil.rmtree(dst_root)
    os.makedirs(dst_root, exist_ok=True)

    written = []
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d not in ALWAYS_SKIP_DIRS]
        for name in sorted(filenames):
            abs_src = os.path.join(dirpath, name)
            relpath = posixpath.join(
                *os.path.relpath(abs_src, src_root).split(os.sep)
            )
            if relpath == BASELINE_FILE:
                continue
            if not path_included(relpath, rules):
                continue

            abs_dst = os.path.join(dst_root, *relpath.split("/"))
            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)

            if not _is_text_file(relpath):
                shutil.copy2(abs_src, abs_dst)
                written.append(relpath)
                continue

            with open(abs_src, "r", encoding="utf-8") as fh:
                raw = fh.read()
            rendered = render_text(raw, context, flags, origin=relpath)

            if relpath.endswith((".yaml", ".yml")) and is_effectively_empty(rendered):
                continue

            with open(abs_dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(rendered)
            written.append(relpath)

    if not written:
        raise RenderError("El baseline no seleccionó ningún archivo")
    return sorted(written)


def kustomize_targets(root):
    """Directorios renderizados que ArgoCD va a construir."""
    targets = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ALWAYS_SKIP_DIRS]
        if "kustomization.yaml" not in filenames:
            continue
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        targets.append("." if rel == "." else rel)
    return sorted(targets)


def validate_rendered(root, kustomize_cmd=("k3s", "kubectl", "kustomize"), timeout=120):
    """Corre `kustomize build` en cada overlay. Devuelve [(target, error)].

    Una lista vacía significa que ArgoCD podrá sincronizar todo el baseline.
    Se ejecuta antes de publicar: es más barato fallar aquí que dejar apps en
    estado Degraded esperando a que alguien lea los logs de ArgoCD.
    """
    import subprocess

    failures = []
    for target in kustomize_targets(root):
        # Un base sin ingress se construye igual; lo que importa es que ningún
        # directorio referencie archivos que el render descartó.
        proc = subprocess.run(
            list(kustomize_cmd) + [target],
            cwd=root, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            failures.append((target, " ".join(detail[:3])[:400]))
    return failures


def build_context(cfg):
    """Traduce la config del wizard al contexto de la plantilla.

    `cfg` usa las claves del instalador (`domain`, `docker_user`, ...); aquí se
    normalizan y se derivan los valores que la plantilla espera.
    """
    domain = (cfg.get("domain") or "").strip().lower().lstrip("*.").rstrip("/")
    org = (cfg.get("github_org") or "").strip()
    repo = (cfg.get("gitops_repo") or "infra-gitops").strip()
    docker_user = (cfg.get("docker_user") or "").strip().lower()
    tailnet = (cfg.get("tailscale_dns") or "").strip().lower()

    if not domain:
        raise RenderError("Falta el dominio: el baseline no se puede renderizar")
    if not org:
        raise RenderError("Falta la organización de GitHub")
    if not docker_user:
        raise RenderError("Falta el usuario de Docker Hub")

    console_public = str(cfg.get("console_exposure", "public")).lower() != "tailnet"
    api_public = str(cfg.get("api_exposure", "public")).lower() != "tailnet"
    # Acuaponsito ve la plataforma entera, así que por defecto acompaña a la
    # consola: si ella es pública él también, y si ella está en la VPN él igual.
    agent_public = str(
        cfg.get("agent_exposure") or cfg.get("console_exposure", "public")
    ).lower() != "tailnet"

    # k3s trae Traefik como IngressClass por defecto. Declarar "nginx" sin
    # haber instalado el controlador deja los Ingress huérfanos: aceptados por
    # la API pero jamás servidos.
    ingress_class = (cfg.get("ingress_class") or "traefik").strip()

    # Con Cloudflare Tunnel el certificado lo emite el edge de Cloudflare y el
    # túnel entra por HTTP al cluster, así que cert-manager sobra. Solo se
    # activa TLS en el cluster si alguien lo pide explícitamente.
    cluster_tls = bool(cfg.get("cluster_tls"))
    cluster_issuer = (cfg.get("cluster_issuer") or "letsencrypt-prod").strip()

    context = {
        "KAANBAL_DOMAIN": domain,
        "KAANBAL_GITHUB_ORG": org,
        "KAANBAL_GITOPS_REPO": repo,
        "KAANBAL_GITOPS_REPO_URL": f"https://github.com/{org}/{repo}.git",
        "KAANBAL_DOCKER_USER": docker_user,
        "KAANBAL_TAILNET": tailnet,
        "KAANBAL_API_TAG": (cfg.get("api_tag") or "bootstrap").strip(),
        "KAANBAL_CONSOLE_TAG": (cfg.get("console_tag") or "bootstrap").strip(),
        "KAANBAL_AGENT_TAG": (cfg.get("agent_tag") or "bootstrap").strip(),
        "KAANBAL_CONSOLE_EXPOSURE": "public" if console_public else "tailscale",
        "KAANBAL_AGENT_EXPOSURE": "public" if agent_public else "tailscale",
        "KAANBAL_INGRESS_CLASS": ingress_class,
        "KAANBAL_CLUSTER_ISSUER": cluster_issuer,
        # Lo que ve la plataforma en runtime: vacío significa "no uses
        # cert-manager", que es lo correcto detrás del túnel.
        "KAANBAL_CLUSTER_ISSUER_CONFIG": cluster_issuer if cluster_tls else "",
    }
    flags = {
        "CONSOLE_PUBLIC": console_public,
        "CONSOLE_TAILNET": not console_public,
        "API_PUBLIC": api_public,
        "API_TAILNET": not api_public,
        "AGENT_PUBLIC": agent_public,
        "AGENT_TAILNET": not agent_public,
        "CLUSTER_TLS": cluster_tls,
        # El operador de Tailscale solo arranca con su OAuth y con la etiqueta
        # concedida en la ACL del tailnet. Sin eso se queda fuera del baseline
        # en vez de reiniciarse para siempre. El instalador confirma lo segundo
        # y lo informa en `tailscale_ready`; sin ese dato basta con las llaves.
        "TAILSCALE": bool(cfg["tailscale_ready"]) if "tailscale_ready" in cfg else bool(
            (cfg.get("tailscale_id") or "").strip()
            and (cfg.get("tailscale_secret") or "").strip()),
    }
    if not flags["TAILSCALE"]:
        for is_public, what in ((console_public, "la consola"),
                                (agent_public, "el agente")):
            if not is_public:
                raise RenderError(
                    f"Pediste {what} solo por VPN pero Tailscale no está "
                    "operativo: revisa las credenciales y que la ACL del tailnet "
                    "conceda tag:k8s-operator. Quedaría sin vía de acceso.")
    return context, flags


def _main(argv):
    """CLI de diagnóstico: renderiza el baseline sin tocar el cluster."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Renderiza el baseline de infra-gitops con una configuración dada."
    )
    parser.add_argument("--src", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "infra-gitops"))
    parser.add_argument("--out", required=True, help="Directorio destino (se recrea)")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--github-org", required=True)
    parser.add_argument("--docker-user", required=True)
    parser.add_argument("--tailnet", default="")
    parser.add_argument("--with-tailscale", action="store_true",
                        help="Hay credenciales de Tailscale: incluye su operador")
    parser.add_argument("--api-tag", default="bootstrap")
    parser.add_argument("--console-tag", default="bootstrap")
    parser.add_argument("--console-exposure", default="public", choices=["public", "tailnet"])
    parser.add_argument("--api-exposure", default="public", choices=["public", "tailnet"])
    parser.add_argument("--json", action="store_true", help="Salida legible por máquina")
    parser.add_argument("--validate", action="store_true",
                        help="Corre kustomize build sobre el resultado")
    parser.add_argument("--kustomize-cmd", default="k3s kubectl kustomize")
    args = parser.parse_args(argv)

    context, flags = build_context({
        "domain": args.domain,
        "github_org": args.github_org,
        "docker_user": args.docker_user,
        "tailscale_dns": args.tailnet,
        "tailscale_id": "cli" if args.with_tailscale else "",
        "tailscale_secret": "cli" if args.with_tailscale else "",
        "api_tag": args.api_tag,
        "console_tag": args.console_tag,
        "console_exposure": args.console_exposure,
        "api_exposure": args.api_exposure,
    })
    written = render_tree(args.src, args.out, context, flags)

    failures = []
    if args.validate:
        failures = validate_rendered(args.out, tuple(args.kustomize_cmd.split()))

    if args.json:
        print(json.dumps(
            {"out": args.out, "files": written,
             "failures": [{"target": t, "error": e} for t, e in failures]},
            indent=2))
    else:
        print(f"Renderizados {len(written)} archivos en {args.out}")
        for relpath in written:
            print(f"  {relpath}")
        if args.validate:
            for target in kustomize_targets(args.out):
                error = dict(failures).get(target)
                print(f"  {'FALLA' if error else 'ok   '}  {target}"
                      + (f"  -- {error}" if error else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
