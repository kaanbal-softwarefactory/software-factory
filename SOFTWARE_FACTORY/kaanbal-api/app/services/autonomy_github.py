"""GitHub broker: only the API holds credentials; workspaces hold source files."""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

import httpx

from app.services.autonomy_policy import AutonomyError, safe_path, redact

MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_CHANGE_BYTES = 2 * 1024 * 1024


def contains_credential(text, secrets=()):
    return any(str(s) in text for s in secrets if s and len(str(s)) >= 4) or bool(re.search(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|kbl_[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)", text))


def repository(value: str) -> str:
    value = str(value or "").removeprefix("https://github.com/").removesuffix(".git").rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
        raise AutonomyError("Se requiere un repositorio GitHub owner/repo registrado.", 422)
    return value


def validate_changes(changes: list[dict], *, secrets=()) -> list[dict]:
    if not changes or len(changes) > 100:
        raise AutonomyError("Un PR debe contener entre 1 y 100 archivos.", 422)
    total, seen = 0, set()
    for change in changes:
        path = safe_path(change["path"])
        if path in seen or change.get("mode") not in ("100644", "100755"):
            raise AutonomyError("Archivo duplicado o modo de archivo no admitido.", 422)
        seen.add(path)
        content = change.get("content")
        if content is not None:
            if not isinstance(content, str) or "\x00" in content:
                raise AutonomyError("Esta versión publica únicamente archivos de texto.", 422)
            total += len(content.encode("utf-8"))
            if contains_credential(content, secrets):
                raise AutonomyError(f"Posible credencial en {path}; retírala antes de publicar.", 422)
    if total > MAX_CHANGE_BYTES:
        raise AutonomyError("Los cambios superan 2 MiB.", 422)
    return sorted(changes, key=lambda row: row["path"])


class GitHubBroker:
    def __init__(self, token: str):
        if not token:
            raise AutonomyError("Configura la credencial GitHub de Kaanbal antes de crear un workspace.")
        self.token = token

    async def request(self, method: str, path: str, *, body=None, params=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, "https://api.github.com" + path,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                json=body, params=params)
        if response.status_code >= 300:
            # Provider error bodies can contain credentials or submitted code.
            raise AutonomyError(f"GitHub respondió HTTP {response.status_code}; revisa permisos, protección de rama y disponibilidad.", 424)
        return response.json() if response.content else {}

    async def repo(self, repo: str):
        return await self.request("GET", f"/repos/{repository(repo)}")

    async def archive(self, repo: str, sha: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise AutonomyError("Commit de origen inválido.", 422)
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.get(f"https://api.github.com/repos/{repository(repo)}/zipball/{sha}", headers={"Authorization": f"Bearer {self.token}"})
            location = response.headers.get("location", "")
            parsed = urlparse(location)
            if response.status_code != 302 or parsed.scheme != "https" or parsed.hostname != "codeload.github.com" or parsed.username or parsed.password:
                raise AutonomyError("GitHub no entregó una descarga válida del repositorio.", 424)
            # Never forward the platform token to an archive redirect.
            data = bytearray()
            async with client.stream("GET", location) as download:
                if download.status_code != 200:
                    raise AutonomyError("No se pudo descargar el código fuente.", 424)
                async for chunk in download.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_ARCHIVE_BYTES:
                        raise AutonomyError("El repositorio comprimido supera 25 MiB.", 422)
            return bytes(data)

    async def base(self, repo: str) -> dict:
        info = await self.repo(repo)
        branch = info["default_branch"]
        commit = await self.request("GET", f"/repos/{repository(repo)}/commits/{quote(branch, safe='')}")
        return {"base_branch": branch, "base_sha": commit["sha"], "base_tree": commit["commit"]["tree"]["sha"]}

    async def contribution_target(self, source: str, configured_fork: str = "") -> str:
        info = await self.repo(source)
        if (info.get("permissions") or {}).get("push"):
            return source
        if not configured_fork:
            raise AutonomyError("La credencial no puede proponer ramas en upstream. Configura core_fork con un fork autorizado.")
        fork = await self.repo(configured_fork)
        ancestors = {(fork.get(key) or {}).get("full_name", "").lower() for key in ("source", "parent")}
        if not fork.get("fork") or source.lower() not in ancestors:
            raise AutonomyError("core_fork debe ser un fork del upstream configurado.", 422)
        if not (fork.get("permissions") or {}).get("push"):
            raise AutonomyError("La credencial no tiene escritura en el fork.", 403)
        return repository(configured_fork)

    async def commit(self, workspace: dict, changes: list[dict], message: str) -> str:
        repo = repository(workspace["push_repo"])
        entries = [{"path": c["path"], "mode": c["mode"], "type": "blob", **({"sha": None} if c.get("content") is None else {"content": c["content"]})} for c in changes]
        tree = await self.request("POST", f"/repos/{repo}/git/trees", body={"base_tree": workspace["base_tree"], "tree": entries})
        commit = await self.request("POST", f"/repos/{repo}/git/commits", body={"message": message, "tree": tree["sha"], "parents": [workspace["base_sha"]]})
        return commit["sha"]

    async def publish(self, workspace: dict, sha: str, title: str, body: str) -> dict:
        repo, source, branch = repository(workspace["push_repo"]), repository(workspace["repo"]), workspace["branch"]
        # Reconcile after a lost response: a retry reuses the same branch/PR.
        refs = await self.request("GET", f"/repos/{repo}/git/matching-refs/heads/{quote(branch, safe='/')}")
        exact = [r for r in refs if r["ref"] == f"refs/heads/{branch}"]
        if exact and exact[0]["object"]["sha"] != sha:
            raise AutonomyError("La rama cambió fuera del workspace; no se sobrescribe.")
        if not exact:
            await self.request("POST", f"/repos/{repo}/git/refs", body={"ref": f"refs/heads/{branch}", "sha": sha})
        head = f"{repo.split('/')[0]}:{branch}"
        existing = await self.request("GET", f"/repos/{source}/pulls", params={"head": head, "base": workspace["base_branch"], "state": "all"})
        if existing:
            return self.public_pr(existing[0])
        pr = await self.request("POST", f"/repos/{source}/pulls", body={"title": title, "body": body, "head": head, "base": workspace["base_branch"], "draft": workspace["target"] == "core", "maintainer_can_modify": True})
        return self.public_pr(pr)

    @staticmethod
    def public_pr(pr: dict) -> dict:
        return {k: pr.get(k) for k in ("number", "html_url", "state", "draft", "merged")}

    async def merge(self, workspace: dict, expected_sha: str) -> dict:
        if workspace["target"] == "core":
            raise AutonomyError("Las contribuciones a Kaanbal requieren revisión y merge del owner en GitHub.", 403)
        repo = repository(workspace["repo"])
        number = int(workspace["pull_request"]["number"])
        pr = await self.request("GET", f"/repos/{repo}/pulls/{number}")
        if expected_sha != workspace.get("published_sha") or pr["head"]["sha"] != expected_sha or pr["head"]["ref"] != workspace["branch"] or pr["base"]["ref"] != workspace["base_branch"]:
            raise AutonomyError("El PR cambió; vuelve a revisar el commit antes de integrar.")
        if pr.get("draft") or pr.get("state") != "open" or pr.get("mergeable_state") != "clean":
            raise AutonomyError("GitHub no considera el PR listo para merge; resuelve CI, revisiones o conflictos.")
        return await self.request("PUT", f"/repos/{repo}/pulls/{number}/merge", body={"sha": expected_sha, "merge_method": "squash"})
