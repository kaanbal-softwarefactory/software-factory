"""Publica los repos core de Kaanbal en GitHub de forma idempotente.

Dos semánticas distintas, a propósito:

* **Repos de código** (`kaanbal-api`, `kaanbal-console`, `kaanbal-templates`):
  el instalador solo siembra el commit inicial. Si el repo ya tiene historia,
  no se toca — a partir del bootstrap manda el equipo, no el instalador.

* **`infra-gitops`**: el instalador es dueño *del baseline* y lo refresca en
  cada instalación, porque el dominio o el usuario de Docker Hub pueden haber
  cambiado. Pero `infra-gitops` también hospeda los overlays de las apps que
  Kaanbal Console crea después, así que el refresco es quirúrgico: solo se
  reescriben las rutas que el baseline declara suyas.

Solo stdlib.
"""

import os
import shutil
import tempfile
import urllib.parse

from gitops_render import path_included


class PublishError(Exception):
    pass


def auth_url(token, org, repo):
    return (f"https://x-access-token:{urllib.parse.quote(token, safe='')}"
            f"@github.com/{org}/{repo}.git")


def _git(run, workdir, args, timeout=300):
    return run(f"cd '{workdir}' && git {args}", timeout=timeout)


def _configure_identity(run, workdir):
    """Configura una identidad local; requiere que `workdir` ya sea un repo."""
    for args in (
        "config user.email 'installer@kaanbal.local'",
        "config user.name 'Kaanbal Installer'",
    ):
        rc, out = _git(run, workdir, args)
        if rc != 0:
            return f"falló `git {args.split()[0]} {args.split()[1]}` — {(out or '')[:300]}"
    return None


def remote_head_sha(run, token, org, repo, branch="main"):
    """SHA del branch remoto, o "" si el repo está vacío o no existe."""
    rc, out = run(f"git ls-remote '{auth_url(token, org, repo)}' refs/heads/{branch}",
                  timeout=60)
    if rc != 0:
        return ""
    line = (out or "").strip().splitlines()
    return line[0].split()[0] if line and line[0].split() else ""


def publish_source(run, token, org, repo, local_path, log_fn=None,
                   branch="main", message=None):
    """Siembra el commit inicial de un repo de código. Devuelve (sha, error).

    Si el repo ya tiene commits devuelve su SHA actual sin escribir nada: el
    código publicado manda sobre la copia local del instalador.
    """
    existing = remote_head_sha(run, token, org, repo, branch)
    if existing:
        if log_fn:
            log_fn(f"{org}/{repo} ya tiene código publicado ({existing[:7]}) — se respeta", "ok")
        return existing, None

    if not os.path.isdir(local_path):
        return "", f"No hay fuente local para {repo} en {local_path}"

    work = tempfile.mkdtemp(prefix=f"kaanbal-seed-{repo}-")
    src = os.path.join(work, "src")
    try:
        shutil.copytree(
            local_path, src,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "node_modules", ".venv", "*.pyc", "dist"),
        )
        # `git config user.*` sin --global solo funciona después de `git init`.
        # Configurarlo antes falla con "not in a git directory"; antes se
        # ignoraba ese error y el fallo aparecía recién al intentar el commit.
        rc, out = _git(run, src, f"init -b {branch}")
        if rc != 0:
            return "", f"{repo}: falló `git init` — {(out or '')[:300]}"
        identity_error = _configure_identity(run, src)
        if identity_error:
            return "", f"{repo}: {identity_error}"

        steps = [
            "add -A",
            f"commit -m '{message or f'bootstrap: {repo} publicado por el instalador Kaanbal'}'",
            f"remote add origin '{auth_url(token, org, repo)}'",
            f"push -u origin {branch}",
        ]
        for args in steps:
            rc, out = _git(run, src, args)
            if rc != 0 and args.startswith("commit") and "nothing to commit" in (out or ""):
                return "", f"{repo}: no hay nada que publicar"
            if rc != 0:
                detail = (out or "")[:300]
                # GitHub rechaza cualquier push que cree o toque
                # .github/workflows si el PAT no trae el scope `workflow`, y el
                # mensaje que devuelve no dice qué hacer.
                if "workflow" in detail and "scope" in detail:
                    return "", (
                        f"{repo}: tu token de GitHub no puede publicar los workflows de "
                        "GitHub Actions. Añade el scope `workflow` al Personal Access "
                        "Token (además de `repo`) y vuelve a intentarlo.")
                return "", f"{repo}: falló `git {args.split()[0]}` — {detail}"

        rc, sha = _git(run, src, "rev-parse HEAD")
        sha = (sha or "").strip()
        if log_fn:
            log_fn(f"Código inicial publicado en {org}/{repo} ({sha[:7]})", "ok")
        return sha, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _clear_owned_paths(root, rules):
    """Borra del working tree las rutas que el baseline declara suyas.

    Así un archivo que desaparece de la plantilla también desaparece del repo
    publicado, sin tocar nada que el baseline no reclame (las apps de usuario).
    """
    removed = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            if path_included(rel, rules):
                os.remove(abs_path)
                removed.append(rel)

    # Limpia los directorios que quedaron vacíos tras el borrado.
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if ".git" in dirpath.split(os.sep):
            continue
        if dirpath != root and not os.listdir(dirpath):
            os.rmdir(dirpath)
    return removed


def publish_baseline(run, token, org, repo, rendered_dir, rules, log_fn=None,
                     branch="main"):
    """Refresca el baseline dentro de infra-gitops. Devuelve (sha, error)."""
    def say(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    work = tempfile.mkdtemp(prefix="kaanbal-gitops-publish-")
    repo_dir = os.path.join(work, "repo")
    url = auth_url(token, org, repo)
    try:
        rc, out = run(f"git clone --depth 1 '{url}' '{repo_dir}'", timeout=300)
        fresh = rc != 0
        if fresh:
            # Repo recién creado: clonar un repo vacío falla, se inicia local.
            os.makedirs(repo_dir, exist_ok=True)
            rc, out = run(f"cd '{repo_dir}' && git init -b {branch}", timeout=60)
            if rc != 0:
                return "", f"No pude inicializar {repo}: {(out or '')[:300]}"
            rc, out = run(f"cd '{repo_dir}' && git remote add origin '{url}'", timeout=60)
            if rc != 0:
                return "", f"No pude apuntar {repo} a GitHub: {(out or '')[:300]}"
        else:
            removed = _clear_owned_paths(repo_dir, rules)
            preserved = _count_tracked_files(repo_dir)
            say(f"Refrescando baseline en {org}/{repo}: {len(removed)} archivos "
                f"regenerados, {preserved} de tus apps intactos")

        _copy_tree(rendered_dir, repo_dir)
        identity_error = _configure_identity(run, repo_dir)
        if identity_error:
            return "", f"{repo}: {identity_error}"

        rc, _ = _git(run, repo_dir, "add -A")
        if rc != 0:
            return "", f"No pude preparar el commit en {repo}"

        rc, out = _git(
            run, repo_dir,
            "commit -m 'kaanbal: baseline de plataforma renderizado por el instalador'")
        nothing_to_commit = rc != 0 and "nothing to commit" in (out or "")
        if rc != 0 and not nothing_to_commit:
            return "", f"No pude commitear el baseline: {(out or '')[:300]}"
        if nothing_to_commit:
            say("El baseline publicado ya estaba al día", "ok")

        rc, out = _git(run, repo_dir, f"push -u origin {branch}", timeout=300)
        if rc != 0 and "Everything up-to-date" not in (out or ""):
            return "", f"No pude publicar el baseline: {(out or '')[:300]}"

        rc, sha = _git(run, repo_dir, "rev-parse HEAD")
        sha = (sha or "").strip()
        say(f"Baseline publicado en {org}/{repo} ({sha[:7]})", "ok")
        return sha, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _count_tracked_files(root):
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        total += len(filenames)
    return total


def _copy_tree(src, dst):
    for dirpath, _dirnames, filenames in os.walk(src):
        for name in filenames:
            abs_src = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_src, src)
            abs_dst = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
            shutil.copy2(abs_src, abs_dst)
