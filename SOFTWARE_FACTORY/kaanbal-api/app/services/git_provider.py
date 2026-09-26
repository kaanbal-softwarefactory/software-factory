"""
Git Provider Abstraction
========================
Multi-provider git/CI support: Bitbucket, GitHub (future: GitLab).

Each provider implements the same interface so the deployer,
pipeline service, and UI are provider-agnostic.

Usage:
    provider = get_git_provider("github", credentials)
    await provider.create_repo("my-app")
    await provider.set_ci_variables("my-app", {...})
    await provider.trigger_ci("my-app", "main")
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GitProvider(ABC):
    """Abstract base class for git hosting + CI/CD providers."""

    # ── Identity ──────────────────────────────────────────────
    name: str = "unknown"           # "bitbucket" | "github" | "gitlab"
    display_name: str = "Unknown"   # "Bitbucket" | "GitHub"

    def __init__(self, credentials: dict):
        self.credentials = credentials

    # ── Repositories ──────────────────────────────────────────
    @abstractmethod
    async def create_repo(self, app_name: str, private: bool = True) -> str:
        """Create a new repo. Returns clone HTTPS URL."""

    @abstractmethod
    async def delete_repo(self, app_name: str) -> bool:
        """Delete a repo. Returns True if deleted (or already gone)."""

    @abstractmethod
    def get_clone_url(self, repo_name: str) -> str:
        """Public HTTPS clone URL (no auth)."""

    @abstractmethod
    def get_auth_clone_url(self, repo_name: str) -> str:
        """Authenticated HTTPS clone URL for git operations."""

    @abstractmethod
    def get_web_url(self, repo_name: str) -> str:
        """Browser URL to view the repo."""

    # ── CI/CD ─────────────────────────────────────────────────
    @abstractmethod
    async def set_ci_variables(self, app_name: str, variables: list[dict]) -> None:
        """Set CI/CD variables/secrets.
        Each variable: {"key": str, "value": str, "secured": bool}
        """

    @abstractmethod
    async def enable_ci(self, app_name: str) -> None:
        """Enable CI/CD for the repo (no-op if auto-enabled)."""

    @abstractmethod
    async def trigger_ci(self, app_name: str, branch: str) -> Optional[dict]:
        """Trigger a CI run on the given branch. Returns run info or None."""

    @abstractmethod
    async def get_ci_status(self, app_name: str, limit: int = 1) -> list[dict]:
        """Get recent CI runs. Returns list of normalized run dicts."""

    @abstractmethod
    async def get_ci_logs(self, app_name: str, run_id: str = None) -> dict:
        """Get logs for a CI run (latest if run_id is None)."""

    # ── Repo Info ─────────────────────────────────────────────
    @abstractmethod
    async def get_repo_info(self, app_name: str) -> dict:
        """Get repo metadata: exists, branches, last commit, CI enabled."""

    # ── Pipeline YAML ─────────────────────────────────────────
    @abstractmethod
    def get_ci_filename(self) -> str:
        """Return the CI config filename: 'bitbucket-pipelines.yml' or '.github/workflows/deploy.yml'"""

    @abstractmethod
    def generate_ci_yaml(
        self,
        app_name: str,
        environments: list[str],
        image: str,
        build_steps: str,
        dockerhub_user: str,
        workspace_or_org: str,
        pipeline_email: str,
        infra_repo: str,
        pkg_manager: str = None,
    ) -> tuple[str, str]:
        """Generate CI/CD YAML content.
        Returns (relative_filepath, content).
        For Bitbucket: ('bitbucket-pipelines.yml', ...)
        For GitHub:    ('.github/workflows/deploy.yml', ...)
        """

    # ── Collaborators ─────────────────────────────────────────
    async def add_collaborator(self, repo_name: str, username: str, permission: str = "pull") -> bool:
        """Add a collaborator to a repo. Returns True on success."""
        return False

    async def remove_collaborator(self, repo_name: str, username: str) -> bool:
        """Remove a collaborator from a repo. Returns True on success."""
        return False

    # ── Validation ────────────────────────────────────────────
    @abstractmethod
    async def validate_credentials(self) -> dict:
        """Test credentials. Returns {"valid": bool, "user": str, "error": str|None}"""

    # ── Infra clone URL (for CI pipelines) ────────────────────
    def get_infra_clone_expr(self, infra_repo: str = "infra-gitops") -> str:
        """Shell expression used inside CI YAML to clone infra-gitops.
        Providers override to use their own auth var pattern.
        """
        return f"https://${{INFRA_REPO_AUTH}}@{self._host()}/{self._namespace()}/{infra_repo}.git"

    def _host(self) -> str:
        return "github.com"

    def _namespace(self) -> str:
        """Workspace (Bitbucket) or org/user (GitHub)."""
        return self.credentials.get("namespace", "")


# ══════════════════════════════════════════════════════════════
#  Bitbucket Provider
# ══════════════════════════════════════════════════════════════

class BitbucketProvider(GitProvider):
    name = "bitbucket"
    display_name = "Bitbucket"

    def _host(self):
        return "bitbucket.org"

    def _namespace(self):
        return self.credentials.get("bb_workspace", "")

    @property
    def _auth(self):
        """HTTP Basic auth tuple used by Bitbucket API."""
        return (
            self.credentials.get("bitbucket_email", self.credentials.get("git_user", "")),
            self.credentials.get("git_token", ""),
        )

    @property
    def _api(self):
        return "https://api.bitbucket.org/2.0"

    # ── Repos ─────────────────────────────────────────────────
    async def create_repo(self, app_name: str, private: bool = True) -> str:
        ws = self._namespace()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api}/repositories/{ws}/{app_name}",
                auth=self._auth,
                json={"scm": "git", "is_private": private},
            )
            if resp.status_code not in (200, 201, 409):
                raise Exception(f"Bitbucket create repo failed: {resp.status_code} {resp.text}")
        return self.get_clone_url(app_name)

    async def delete_repo(self, app_name: str) -> bool:
        ws = self._namespace()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._api}/repositories/{ws}/{app_name}",
                auth=self._auth,
            )
        return resp.status_code in (204, 404)

    def get_clone_url(self, repo_name: str) -> str:
        return f"https://bitbucket.org/{self._namespace()}/{repo_name}.git"

    def get_auth_clone_url(self, repo_name: str) -> str:
        user = self.credentials.get("git_user", "")
        token = self.credentials.get("git_token", "")
        return f"https://{user}:{token}@bitbucket.org/{self._namespace()}/{repo_name}.git"

    def get_web_url(self, repo_name: str) -> str:
        return f"https://bitbucket.org/{self._namespace()}/{repo_name}"

    # ── CI/CD ─────────────────────────────────────────────────
    async def set_ci_variables(self, app_name: str, variables: list[dict]) -> None:
        ws = self._namespace()
        async with httpx.AsyncClient() as client:
            for var in variables:
                if not var.get("value"):
                    continue
                resp = await client.post(
                    f"{self._api}/repositories/{ws}/{app_name}/pipelines_config/variables",
                    auth=self._auth,
                    json=var,
                )
                if resp.status_code not in (200, 201, 409):
                    raise Exception(
                        f"Bitbucket set var {var['key']} failed: {resp.status_code}"
                    )

    async def enable_ci(self, app_name: str) -> None:
        ws = self._namespace()
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self._api}/repositories/{ws}/{app_name}/pipelines_config",
                auth=self._auth,
                json={"enabled": True},
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Bitbucket enable pipelines {app_name}: {resp.status_code}")

    async def trigger_ci(self, app_name: str, branch: str) -> Optional[dict]:
        ws = self._namespace()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api}/repositories/{ws}/{app_name}/pipelines/",
                auth=self._auth,
                json={
                    "target": {
                        "ref_type": "branch",
                        "type": "pipeline_ref_target",
                        "ref_name": branch,
                    }
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "id": data.get("uuid"),
                    "number": data.get("build_number"),
                    "state": data.get("state", {}).get("name"),
                    "branch": branch,
                }
            logger.warning(f"Bitbucket trigger CI {app_name}/{branch}: {resp.status_code}")
            return None

    async def get_ci_status(self, app_name: str, limit: int = 1) -> list[dict]:
        ws = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._api}/repositories/{ws}/{app_name}/pipelines/",
                    auth=self._auth,
                    params={"sort": "-created_on", "pagelen": limit},
                )
                if resp.status_code != 200:
                    return []
                results = []
                for p in resp.json().get("values", []):
                    state = p.get("state", {})
                    results.append({
                        "id": p.get("uuid"),
                        "number": p.get("build_number"),
                        "state": state.get("name", "unknown"),
                        "result": state.get("result", {}).get("name") if state.get("result") else None,
                        "branch": p.get("target", {}).get("ref_name"),
                        "created_on": p.get("created_on"),
                        "completed_on": p.get("completed_on"),
                        "duration_seconds": p.get("duration_in_seconds"),
                        "trigger": p.get("trigger", {}).get("name"),
                    })
                return results
        except Exception as e:
            logger.error(f"Bitbucket get_ci_status {app_name}: {e}")
            return []

    async def get_ci_logs(self, app_name: str, run_id: str = None) -> dict:
        ws = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Resolve latest if no run_id
                if not run_id:
                    runs = await self.get_ci_status(app_name, limit=1)
                    if not runs:
                        return {"error": "No CI runs found"}
                    run_id = runs[0]["id"]

                # Get steps
                resp = await client.get(
                    f"{self._api}/repositories/{ws}/{app_name}/pipelines/{run_id}/steps/",
                    auth=self._auth,
                )
                if resp.status_code != 200:
                    return {"error": f"Failed to get steps: {resp.status_code}"}

                steps = []
                for s in resp.json().get("values", []):
                    step_info = {
                        "name": s.get("name"),
                        "uuid": s.get("uuid"),
                        "state": s.get("state", {}).get("name"),
                        "result": (
                            s.get("state", {}).get("result", {}).get("name")
                            if s.get("state", {}).get("result")
                            else None
                        ),
                        "duration_seconds": s.get("duration_in_seconds"),
                    }
                    # Get logs for failed or completed steps
                    if step_info["result"] in ("FAILED", "ERROR"):
                        log_resp = await client.get(
                            f"{self._api}/repositories/{ws}/{app_name}/pipelines/{run_id}/steps/{step_info['uuid']}/log",
                            auth=self._auth,
                        )
                        if log_resp.status_code == 200:
                            step_info["logs"] = log_resp.text[-6000:]
                    steps.append(step_info)
                return {"run_id": run_id, "steps": steps}
        except Exception as e:
            return {"error": str(e)}

    async def get_repo_info(self, app_name: str) -> dict:
        ws = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._api}/repositories/{ws}/{app_name}",
                    auth=self._auth,
                )
                if resp.status_code == 404:
                    return {"exists": False}
                if resp.status_code != 200:
                    return {"exists": False, "error": f"API error {resp.status_code}"}

                # Branches
                br_resp = await client.get(
                    f"{self._api}/repositories/{ws}/{app_name}/refs/branches",
                    auth=self._auth,
                    params={"pagelen": 10},
                )
                branches = []
                if br_resp.status_code == 200:
                    branches = [b["name"] for b in br_resp.json().get("values", [])]

                return {
                    "exists": True,
                    "web_url": self.get_web_url(app_name),
                    "clone_url": self.get_clone_url(app_name),
                    "branches": branches,
                }
        except Exception as e:
            return {"exists": False, "error": str(e)}

    # ── CI YAML Generation ────────────────────────────────────
    def get_ci_filename(self) -> str:
        return "bitbucket-pipelines.yml"

    def generate_ci_yaml(
        self,
        app_name: str,
        environments: list[str],
        image: str,
        build_steps: str,
        dockerhub_user: str,
        workspace_or_org: str,
        pipeline_email: str,
        infra_repo: str = "infra-gitops",
        pkg_manager: str = None,
    ) -> tuple[str, str]:
        env_to_branch = {"dev": "develop", "staging": "staging", "prod": "main"}
        branch_sections = []

        for env in environments:
            branch = env_to_branch.get(env)
            if not branch:
                continue
            env_upper = env.upper()
            deployment = {"dev": "test", "staging": "staging", "prod": "production"}.get(env, "test")

            section = f"""    # {'=' * 70}
    # RAMA {branch.upper()} -> Deploy a {env_upper}
    # {'=' * 70}
    {branch}:
{build_steps}

      - step:
          name: "🐳 Build & Push Docker ({env_upper})"
          services: [docker]
          script:
            - export COLON=":"
            - export APP_NAME="{app_name}"
            - export FULL_IMAGE="{dockerhub_user}/$APP_NAME"
            - export IMAGE_TAG="{env}-${{BITBUCKET_COMMIT:0:7}}"

            - echo "🏗️ Building for environment$COLON {env} (Tag$COLON $IMAGE_TAG)"
            - echo "$DOCKERHUB_PASSWORD" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
            - docker build -t $FULL_IMAGE:$IMAGE_TAG .
            - docker push $FULL_IMAGE:$IMAGE_TAG

            - echo $IMAGE_TAG > image_tag.txt
          artifacts:
            - image_tag.txt

      - step:
          name: "🚀 Update Infra ({env_upper})"
          image: alpine/git
          deployment: {deployment}
          script:
            - export COLON=":"
            - export APP_NAME="{app_name}"
            - export FULL_IMAGE="{dockerhub_user}/$APP_NAME"
            - export IMAGE_TAG=$(cat image_tag.txt)
            - apk add --no-cache sed

            - git clone --depth 1 https://${{INFRA_REPO_AUTH}}@bitbucket.org/{workspace_or_org}/{infra_repo}.git
            - cd {infra_repo}
            - git config user.email "{pipeline_email}"
            - git config user.name "Bitbucket Pipeline"

            - cd apps/$APP_NAME/overlays/{env}
            - sed -i "s|newName.*|newName$COLON $FULL_IMAGE|g" kustomization.yaml
            - sed -i "s/newTag.*/newTag$COLON $IMAGE_TAG/g" kustomization.yaml

            - git add kustomization.yaml
            - git commit -m "deploy({env})$COLON $APP_NAME to $IMAGE_TAG [skip ci]"
            - cd ../../../../
            - |
              # Retry push with rebase (handles race conditions from parallel pipelines)
              for i in 1 2 3 4 5; do
                git pull --rebase origin main && git push origin main && break
                echo "Push attempt $i failed, retrying in 5s..."
                sleep 5
              done
"""
            branch_sections.append(section)

        content = f"""# ==============================================================================
# BITBUCKET PIPELINES - {app_name}
# ==============================================================================
# Generated by Kaanbal Engine
# Environments: {', '.join(environments)}
# ==============================================================================

image: {image}

definitions:
  services:
    docker:
      memory: 2048

pipelines:
  branches:
{''.join(branch_sections)}
"""
        return ("bitbucket-pipelines.yml", content)

    # ── Validation ────────────────────────────────────────────
    async def validate_credentials(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.bitbucket.org/2.0/user",
                    auth=self._auth,
                )
                if resp.status_code == 200:
                    user = resp.json()
                    return {
                        "valid": True,
                        "provider": "bitbucket",
                        "user": user.get("display_name", user.get("username", "")),
                        "username": user.get("username", ""),
                    }
                return {"valid": False, "provider": "bitbucket", "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"valid": False, "provider": "bitbucket", "error": str(e)}


# ══════════════════════════════════════════════════════════════
#  GitHub Provider
# ══════════════════════════════════════════════════════════════

class GitHubProvider(GitProvider):
    name = "github"
    display_name = "GitHub"

    def _host(self):
        return "github.com"

    def _namespace(self):
        return self.credentials.get("github_org", self.credentials.get("git_user", ""))

    @property
    def _headers(self):
        token = self.credentials.get("github_token") or self.credentials.get("git_token", "")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def _api(self):
        return "https://api.github.com"

    @property
    def _token(self):
        return self.credentials.get("github_token") or self.credentials.get("git_token", "")

    def _is_org(self) -> bool:
        """Check if namespace is an org (vs personal account).
        Auto-detects: if github_org is set and differs from git_username, treat as org.
        """
        explicit = self.credentials.get("github_is_org")
        if explicit is not None:
            return bool(explicit)
        # Auto-detect: if github_org differs from the PAT user, it's an org
        org = self.credentials.get("github_org", "")
        user = self.credentials.get("git_username", "") or self.credentials.get("git_user", "")
        return bool(org and user and org.lower() != user.lower())

    # ── Repos ─────────────────────────────────────────────────
    async def create_repo(self, app_name: str, private: bool = True) -> str:
        ns = self._namespace()
        async with httpx.AsyncClient() as client:
            if self._is_org():
                url = f"{self._api}/orgs/{ns}/repos"
            else:
                url = f"{self._api}/user/repos"

            resp = await client.post(
                url,
                headers=self._headers,
                json={
                    "name": app_name,
                    "private": private,
                    "auto_init": False,
                },
            )
            if resp.status_code == 422:
                # Already exists — not an error
                logger.info(f"GitHub repo {ns}/{app_name} already exists")
                return self.get_clone_url(app_name)
            if resp.status_code not in (200, 201):
                raise Exception(f"GitHub create repo failed: {resp.status_code} {resp.text}")
        return self.get_clone_url(app_name)

    async def delete_repo(self, app_name: str) -> bool:
        ns = self._namespace()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._api}/repos/{ns}/{app_name}",
                headers=self._headers,
            )
        return resp.status_code in (204, 404)

    def get_clone_url(self, repo_name: str) -> str:
        return f"https://github.com/{self._namespace()}/{repo_name}.git"

    def get_auth_clone_url(self, repo_name: str) -> str:
        # GitHub supports token-only auth: https://x-access-token:{token}@github.com/...
        return f"https://x-access-token:{self._token}@github.com/{self._namespace()}/{repo_name}.git"

    def get_web_url(self, repo_name: str) -> str:
        return f"https://github.com/{self._namespace()}/{repo_name}"

    # ── CI/CD (GitHub Actions) ────────────────────────────────
    async def set_ci_variables(self, app_name: str, variables: list[dict]) -> None:
        """Set GitHub Actions secrets using the repository secrets API.
        Requires libsodium for encryption — falls back to environment secrets.
        """
        ns = self._namespace()
        async with httpx.AsyncClient() as client:
            # Get repo public key for secret encryption
            pk_resp = await client.get(
                f"{self._api}/repos/{ns}/{app_name}/actions/secrets/public-key",
                headers=self._headers,
            )
            if pk_resp.status_code != 200:
                raise Exception(f"GitHub get public key failed: {pk_resp.status_code}")

            pk_data = pk_resp.json()
            public_key = pk_data["key"]
            key_id = pk_data["key_id"]

            for var in variables:
                if not var.get("value"):
                    continue
                encrypted = self._encrypt_secret(public_key, var["value"])
                resp = await client.put(
                    f"{self._api}/repos/{ns}/{app_name}/actions/secrets/{var['key']}",
                    headers=self._headers,
                    json={"encrypted_value": encrypted, "key_id": key_id},
                )
                if resp.status_code not in (201, 204):
                    raise Exception(
                        f"GitHub set secret {var['key']} failed: {resp.status_code}"
                    )

    async def enable_ci(self, app_name: str) -> None:
        """GitHub Actions are enabled by default when workflow files exist."""
        pass

    async def trigger_ci(self, app_name: str, branch: str) -> Optional[dict]:
        ns = self._namespace()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api}/repos/{ns}/{app_name}/actions/workflows/deploy.yml/dispatches",
                headers=self._headers,
                json={"ref": branch},
            )
            if resp.status_code == 204:
                return {"state": "triggered", "branch": branch}
            # If workflow_dispatch is not configured, try pushing an empty commit
            # (GitHub Actions trigger on push by default)
            logger.warning(f"GitHub trigger CI {app_name}/{branch}: {resp.status_code}")
            return None

    async def get_ci_status(self, app_name: str, limit: int = 1) -> list[dict]:
        ns = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._api}/repos/{ns}/{app_name}/actions/runs",
                    headers=self._headers,
                    params={"per_page": limit},
                )
                if resp.status_code != 200:
                    return []

                results = []
                for run in resp.json().get("workflow_runs", []):
                    # Map GitHub statuses to our normalized format
                    status = run.get("status", "unknown")
                    conclusion = run.get("conclusion")
                    if status == "completed":
                        state = "COMPLETED"
                        result = {
                            "success": "SUCCESSFUL",
                            "failure": "FAILED",
                            "cancelled": "STOPPED",
                        }.get(conclusion, conclusion.upper() if conclusion else "UNKNOWN")
                    elif status == "in_progress":
                        state = "RUNNING"
                        result = None
                    elif status == "queued":
                        state = "PENDING"
                        result = None
                    else:
                        state = status.upper()
                        result = None

                    results.append({
                        "id": str(run.get("id")),
                        "number": run.get("run_number"),
                        "state": state,
                        "result": result,
                        "branch": run.get("head_branch"),
                        "created_on": run.get("created_at"),
                        "completed_on": run.get("updated_at") if status == "completed" else None,
                        "duration_seconds": None,  # GitHub doesn't expose this directly
                        "trigger": run.get("event"),
                    })
                return results
        except Exception as e:
            logger.error(f"GitHub get_ci_status {app_name}: {e}")
            return []

    async def get_ci_logs(self, app_name: str, run_id: str = None) -> dict:
        ns = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if not run_id:
                    runs = await self.get_ci_status(app_name, limit=1)
                    if not runs:
                        return {"error": "No CI runs found"}
                    run_id = runs[0]["id"]

                # Get jobs for the run
                resp = await client.get(
                    f"{self._api}/repos/{ns}/{app_name}/actions/runs/{run_id}/jobs",
                    headers=self._headers,
                )
                if resp.status_code != 200:
                    return {"error": f"Failed to get jobs: {resp.status_code}"}

                steps = []
                for job in resp.json().get("jobs", []):
                    step_info = {
                        "name": job.get("name"),
                        "uuid": str(job.get("id")),
                        "state": "COMPLETED" if job.get("status") == "completed" else job.get("status", "").upper(),
                        "result": (job.get("conclusion") or "").upper() or None,
                        "duration_seconds": None,
                    }
                    # Get logs for failed jobs
                    if step_info["result"] in ("FAILURE", "FAILED"):
                        log_resp = await client.get(
                            f"{self._api}/repos/{ns}/{app_name}/actions/jobs/{job['id']}/logs",
                            headers=self._headers,
                        )
                        if log_resp.status_code == 200:
                            step_info["logs"] = log_resp.text[-6000:]
                    steps.append(step_info)
                return {"run_id": run_id, "steps": steps}
        except Exception as e:
            return {"error": str(e)}

    async def get_repo_info(self, app_name: str) -> dict:
        ns = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._api}/repos/{ns}/{app_name}",
                    headers=self._headers,
                )
                if resp.status_code == 404:
                    return {"exists": False}
                if resp.status_code != 200:
                    return {"exists": False, "error": f"API error {resp.status_code}"}

                # Branches
                br_resp = await client.get(
                    f"{self._api}/repos/{ns}/{app_name}/branches",
                    headers=self._headers,
                    params={"per_page": 10},
                )
                branches = []
                if br_resp.status_code == 200:
                    branches = [b["name"] for b in br_resp.json()]

                return {
                    "exists": True,
                    "web_url": self.get_web_url(app_name),
                    "clone_url": self.get_clone_url(app_name),
                    "branches": branches,
                }
        except Exception as e:
            return {"exists": False, "error": str(e)}

    # ── CI YAML Generation ────────────────────────────────────
    def get_ci_filename(self) -> str:
        return ".github/workflows/deploy.yml"

    def generate_ci_yaml(
        self,
        app_name: str,
        environments: list[str],
        image: str,
        build_steps: str,
        dockerhub_user: str,
        workspace_or_org: str,
        pipeline_email: str,
        infra_repo: str = "infra-gitops",
        pkg_manager: str = None,
    ) -> tuple[str, str]:
        env_to_branch = {"dev": "develop", "staging": "staging", "prod": "main"}

        # Build branch list for 'on.push.branches'
        branches = [env_to_branch[e] for e in environments if e in env_to_branch]

        # Convert Bitbucket-style build_steps to GitHub Actions steps
        # Parse the build commands from the build_steps string
        build_commands = []
        for line in build_steps.split("\n"):
            line = line.strip()
            if line.startswith("- ") and not line.startswith("- step:") and not line.startswith("- dist/") and not line.startswith("- ./**"):
                cmd = line[2:].strip()
                if cmd and not cmd.startswith("name:") and not cmd.startswith("caches:") and not cmd.startswith("artifacts:"):
                    build_commands.append(cmd)

        # Filter only actual shell commands
        shell_cmds = [c for c in build_commands if c and not c.startswith('"') and c not in ("node", "pip")]

        build_run = "\n            ".join(shell_cmds) if shell_cmds else "echo 'No build step'"

        # Determine if Node or Python for setup action
        is_node = "node" in image
        is_python = "python" in image

        if is_node:
            node_version = image.split(":")[1].split("-")[0] if ":" in image else "20"
            # Use correct cache strategy based on package manager
            # setup-node cache requires a lockfile; detect via --frozen-lockfile in build_steps
            has_lockfile = "--frozen-lockfile" in build_steps or "npm ci" in build_steps
            cache_type = pkg_manager if pkg_manager in ("npm", "pnpm", "yarn") else "npm"
            enable_corepack = ""
            if cache_type == "pnpm":
                enable_corepack = """
      - name: Enable corepack
        run: corepack enable
"""
            cache_line = f"\n          cache: '{cache_type}'" if has_lockfile else ""
            setup_step = f"""      - uses: actions/setup-node@v4
        with:
          node-version: '{node_version}'{cache_line}
{enable_corepack}"""
        elif is_python:
            py_version = image.split(":")[1].split("-")[0] if ":" in image else "3.11"
            setup_step = f"""      - uses: actions/setup-python@v5
        with:
          python-version: '{py_version}'"""
        else:
            setup_step = "      # No specific runtime setup needed"

        # Build env-to-branch mapping for the matrix
        env_branch_pairs = []
        for env in environments:
            branch = env_to_branch.get(env)
            if branch:
                env_branch_pairs.append((env, branch))

        # Build the branch conditions for deploy
        deploy_conditions = []
        for env, branch in env_branch_pairs:
            deploy_conditions.append(
                f"${{{{ github.ref == 'refs/heads/{branch}' }}}}"
            )

        # Environment mapping expression
        env_map_lines = []
        for env, branch in env_branch_pairs:
            env_map_lines.append(f"            echo \"DEPLOY_ENV={env}\" >> $GITHUB_ENV")
            if env != env_branch_pairs[-1][0]:
                # Not the last — need conditional
                pass

        # Simpler: use a direct branch→env mapping in the workflow
        env_mapping = " || ".join(
            f"(github.ref == 'refs/heads/{branch}' && '{env}')"
            for env, branch in env_branch_pairs
        )

        content = f"""# ==============================================================================
# GITHUB ACTIONS - {app_name}
# ==============================================================================
# Generated by Kaanbal Engine
# Environments: {', '.join(environments)}
# ==============================================================================

name: Deploy {app_name}

on:
  push:
    branches: [{', '.join(branches)}]
  workflow_dispatch:

# Portable entre células: nada de la célula va escrito aquí. La app es el repo,
# la cuenta de Docker Hub sale de los secrets que Kaanbal carga en el repo y el
# infra-gitops es el de la org dueña del repo. Copiar este archivo a otra app u
# otra célula no puede hacerla publicar en la cuenta u org equivocada.
env:
  APP_NAME: ${{{{ github.event.repository.name }}}}
  DOCKERHUB_USER: ${{{{ secrets.DOCKERHUB_USERNAME }}}}

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{{{ steps.meta.outputs.tag }}}}
      deploy_env: ${{{{ steps.meta.outputs.env }}}}
    steps:
      - uses: actions/checkout@v4

{setup_step}

      - name: Build
        run: |
            {build_run}

      - name: Determine environment
        id: meta
        run: |
          BRANCH="${{GITHUB_REF_NAME}}"
          case "$BRANCH" in
            main)    ENV="prod" ;;
            staging) ENV="staging" ;;
            develop) ENV="dev" ;;
            *)       ENV="dev" ;;
          esac
          TAG="${{ENV}}-$(echo $GITHUB_SHA | cut -c1-7)"
          echo "tag=$TAG" >> $GITHUB_OUTPUT
          echo "env=$ENV" >> $GITHUB_OUTPUT

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{{{ secrets.DOCKERHUB_USERNAME }}}}
          password: ${{{{ secrets.DOCKERHUB_PASSWORD }}}}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{{{ env.DOCKERHUB_USER }}}}/${{{{ env.APP_NAME }}}}:${{{{ steps.meta.outputs.tag }}}}

  update-infra:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Update infrastructure
        env:
          INFRA_REPO_AUTH: ${{{{ secrets.INFRA_REPO_AUTH }}}}
          IMAGE_TAG: ${{{{ needs.build.outputs.image_tag }}}}
          DEPLOY_ENV: ${{{{ needs.build.outputs.deploy_env }}}}
        run: |
          git clone --depth 1 https://${{INFRA_REPO_AUTH}}@github.com/${{GITHUB_REPOSITORY_OWNER}}/{infra_repo}.git
          cd {infra_repo}
          git config user.email "{pipeline_email}"
          git config user.name "GitHub Actions"

          cd apps/${{APP_NAME}}/overlays/$DEPLOY_ENV
          sed -i "s|newName.*|newName: ${{DOCKERHUB_USER}}/${{APP_NAME}}|g" kustomization.yaml
          sed -i "s/newTag.*/newTag: $IMAGE_TAG/g" kustomization.yaml

          git add kustomization.yaml
          git commit -m "deploy($DEPLOY_ENV): ${{APP_NAME}} to $IMAGE_TAG [skip ci]"
          cd ../../../../

          # Retry push with rebase
          for i in 1 2 3 4 5; do
            git pull --rebase origin main && git push origin main && break
            echo "Push attempt $i failed, retrying in 5s..."
            sleep 5
          done
"""
        return (".github/workflows/deploy.yml", content)

    # ── Collaborators ─────────────────────────────────────────
    async def add_collaborator(self, repo_name: str, username: str, permission: str = "pull") -> bool:
        """Add a collaborator to a GitHub repo.
        permission: pull, push, maintain, admin
        """
        ns = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(
                    f"{self._api}/repos/{ns}/{repo_name}/collaborators/{username}",
                    headers=self._headers,
                    json={"permission": permission},
                )
                # 201 = invitation sent, 204 = already a collaborator
                return resp.status_code in (201, 204)
        except Exception as e:
            logger.error(f"GitHub add_collaborator {repo_name}/{username}: {e}")
            return False

    async def remove_collaborator(self, repo_name: str, username: str) -> bool:
        """Remove a collaborator from a GitHub repo."""
        ns = self._namespace()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(
                    f"{self._api}/repos/{ns}/{repo_name}/collaborators/{username}",
                    headers=self._headers,
                )
                return resp.status_code in (204, 404)
        except Exception as e:
            logger.error(f"GitHub remove_collaborator {repo_name}/{username}: {e}")
            return False

    # ── Validation ────────────────────────────────────────────
    async def validate_credentials(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._api}/user",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    user = resp.json()
                    return {
                        "valid": True,
                        "provider": "github",
                        "user": user.get("name", user.get("login", "")),
                        "username": user.get("login", ""),
                        "avatar": user.get("avatar_url", ""),
                    }
                return {"valid": False, "provider": "github", "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"valid": False, "provider": "github", "error": str(e)}

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
        """Encrypt a secret using the repo's public key (NaCl sealed box)."""
        try:
            from nacl import encoding, public as nacl_public

            public_key = nacl_public.PublicKey(
                public_key_b64.encode("utf-8"), encoding.Base64Encoder
            )
            sealed_box = nacl_public.SealedBox(public_key)
            encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
            import base64
            return base64.b64encode(encrypted).decode("utf-8")
        except ImportError:
            # Fallback: if PyNaCl is not installed, use a subprocess call
            # This shouldn't happen in production — add pynacl to requirements
            logger.warning("PyNaCl not installed — cannot encrypt GitHub secrets. Install with: pip install pynacl")
            raise Exception(
                "PyNaCl library required for GitHub secrets encryption. "
                "Run: pip install pynacl"
            )


# ══════════════════════════════════════════════════════════════
#  Factory
# ══════════════════════════════════════════════════════════════

PROVIDERS = {
    "bitbucket": BitbucketProvider,
    "github": GitHubProvider,
}


def get_git_provider(provider_name: str, credentials: dict) -> GitProvider:
    """Factory: instantiate the right provider."""
    cls = PROVIDERS.get(provider_name)
    if not cls:
        raise ValueError(
            f"Unknown git provider '{provider_name}'. "
            f"Available: {', '.join(PROVIDERS.keys())}"
        )
    return cls(credentials)


async def build_provider_from_config(provider_name: str = None) -> GitProvider:
    """
    Build a GitProvider using credentials from MongoDB system_config.
    If provider_name is None, reads git_provider from config (default: bitbucket).
    """
    from app.db import get_db

    db = get_db()
    config = await db.system_config.find_one({"_id": "main"}) or {}

    if not provider_name:
        provider_name = config.get("git_provider", "bitbucket")

    # Build credentials dict with all possible fields
    credentials = {
        "git_user": config.get("git_username", ""),
        "git_token": config.get("git_token", ""),
        # Bitbucket-specific
        "bb_workspace": config.get("bitbucket_workspace", ""),
        "bitbucket_email": config.get("bitbucket_email", ""),
        # GitHub-specific
        "github_org": config.get("github_org", ""),
        "github_token": config.get("github_token", ""),
        "github_is_org": config.get("github_is_org", False),
    }

    return get_git_provider(provider_name, credentials)
