"""
Pipeline Service - CI/CD status monitoring (provider-agnostic)
===============================================================
Supports Bitbucket Pipelines and GitHub Actions via GitProvider abstraction.
"""

import logging
from typing import Optional, List

from app.db import get_db
from app.services.git_provider import build_provider_from_config, GitProvider

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self):
        self._provider: GitProvider | None = None

    async def _get_provider(self, provider_name: str = None) -> GitProvider:
        """Get or build the git provider (cached per instance)."""
        if self._provider and not provider_name:
            return self._provider
        self._provider = await build_provider_from_config(provider_name)
        return self._provider

    async def _get_app_provider(self, app_name: str) -> GitProvider:
        """Get the provider for a specific app (checks app doc for provider override)."""
        db = get_db()
        app_doc = await db.apps.find_one(
            {"name": app_name},
            {"git_provider": 1}
        )
        override = app_doc.get("git_provider") if app_doc else None
        return await self._get_provider(override)

    async def get_pipeline_status(self, app_name: str) -> dict:
        """
        Get status of the latest CI run for an app.
        """
        try:
            provider = await self._get_app_provider(app_name)
            runs = await provider.get_ci_status(app_name, limit=1)

            if not runs:
                return {
                    "state": "never_run",
                    "result": None,
                    "message": "No CI runs executed yet"
                }

            latest = runs[0]
            return {
                "uuid": latest.get("id"),
                "build_number": latest.get("number"),
                "state": latest.get("state", "unknown"),
                "result": latest.get("result"),
                "created_on": latest.get("created_on"),
                "completed_on": latest.get("completed_on"),
                "duration_seconds": latest.get("duration_seconds"),
                "trigger": latest.get("trigger"),
                "target_branch": latest.get("branch"),
                "provider": provider.display_name,
            }

        except Exception as e:
            return {"state": "error", "error": str(e)}

    async def get_pipeline_logs(self, app_name: str, pipeline_uuid: str = None, include_all_logs: bool = False) -> dict:
        """
        Get detailed logs for a CI run (latest if no ID specified).
        """
        try:
            provider = await self._get_app_provider(app_name)
            result = await provider.get_ci_logs(app_name, run_id=pipeline_uuid)
            if result.get("error"):
                return result

            # Add provider info
            result["provider"] = provider.display_name
            return result

        except Exception as e:
            return {"error": str(e)}

    async def get_all_pipelines(self, app_name: str, limit: int = 5) -> List[dict]:
        """
        Get CI run history for an app.
        """
        try:
            provider = await self._get_app_provider(app_name)
            runs = await provider.get_ci_status(app_name, limit=limit)
            # Add provider info to each run
            for run in runs:
                run["provider"] = provider.display_name
            return runs

        except Exception:
            return []

    async def get_repo_status(self, app_name: str) -> dict:
        """
        Get the current status of a repository via the configured provider.
        """
        try:
            provider = await self._get_app_provider(app_name)
            info = await provider.get_repo_info(app_name)

            if not info.get("exists"):
                return {
                    "repo_exists": False,
                    "has_code": False,
                    "message": "Repository not found",
                    "provider": provider.display_name,
                }

            return {
                "repo_exists": True,
                "has_code": bool(info.get("branches")),
                "repo_url": info.get("web_url"),
                "clone_url": info.get("clone_url"),
                "branches": info.get("branches", []),
                "provider": provider.display_name,
            }

        except Exception as e:
            return {"error": str(e)}


# Singleton
pipeline_service = PipelineService()
