import os
import json
import subprocess
import tempfile
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime, timedelta
import logging

from app.db import get_db
from app.config import settings

logger = logging.getLogger(__name__)


class TemplateService:
    """
    Service for managing application templates from the catalog.
    Supports v4.0 architecture with categories, templates, and stacks.
    """
    
    def __init__(self):
        self.cache_dir = Path(tempfile.gettempdir()) / "kaanbal-templates"
        self.refresh_interval = 300  # 5 minutes
        self._last_sync = None
        self._credentials = None
        self._catalog_cache = None
    
    async def _get_credentials(self):
        """Get git credentials from MongoDB or settings"""
        if self._credentials:
            return self._credentials
            
        db = get_db()
        config = await db.system_config.find_one({"_id": "main"})
        
        if config:
            self._credentials = {
                "username": config.get("git_username", settings.git_username),
                "token": config.get("git_token", settings.git_token),
                "templates_repo": config.get("templates_repo", "kaanbal-templates"),
                "git_provider": config.get("git_provider", "bitbucket"),
                "github_org": config.get("github_org", ""),
                "github_token": config.get("github_token", ""),
            }
        else:
            self._credentials = {
                "username": settings.git_username,
                "token": settings.git_token,
                "templates_repo": "kaanbal-templates",
                "git_provider": "bitbucket",
                "github_org": "",
                "github_token": "",
            }
        
        return self._credentials
    
    def _get_auth_repo_url(self, creds):
        """Build authenticated repo URL based on git provider"""
        repo_name = creds.get("templates_repo", "kaanbal-templates")
        provider = creds.get("git_provider", "bitbucket")
        
        if provider == "github":
            namespace = creds.get("github_org") or creds.get("username", "")
            token = creds.get("github_token") or creds.get("token", "")
            return f"https://x-access-token:{token}@github.com/{namespace}/{repo_name}.git"
        else:
            workspace = settings.bitbucket_workspace
            return f"https://{creds['username']}:{creds['token']}@bitbucket.org/{workspace}/{repo_name}.git"
    
    async def _ensure_templates_cached(self, force=False):
        """Clone or pull the latest templates repository"""
        if not force and self._last_sync:
            if datetime.utcnow() - self._last_sync < timedelta(seconds=self.refresh_interval):
                return True
        
        creds = await self._get_credentials()
        repo_url = self._get_auth_repo_url(creds)
        
        try:
            if not self.cache_dir.exists():
                logger.info(f"Cloning templates repository")
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(self.cache_dir)],
                    check=True,
                    capture_output=True
                )
            else:
                logger.info("Pulling latest templates")
                subprocess.run(
                    ["git", "-C", str(self.cache_dir), "pull"],
                    check=True,
                    capture_output=True
                )
            
            self._last_sync = datetime.utcnow()
            self._catalog_cache = None  # Invalidate cache
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to sync templates: {e.stderr.decode() if e.stderr else str(e)}")
            return False
    
    async def _get_catalog(self) -> Dict:
        """Load the catalog.json file"""
        if self._catalog_cache:
            return self._catalog_cache
            
        await self._ensure_templates_cached()
        
        # Try catalog.json first (v4), then manifest.json (v3)
        catalog_path = self.cache_dir / "catalog.json"
        manifest_path = self.cache_dir / "manifest.json"
        
        try:
            if catalog_path.exists():
                with open(catalog_path) as f:
                    self._catalog_cache = json.load(f)
                    return self._catalog_cache
            elif manifest_path.exists():
                with open(manifest_path) as f:
                    data = json.load(f)
                    # Convert v3 manifest to v4 catalog format
                    self._catalog_cache = self._convert_v3_to_v4(data)
                    return self._catalog_cache
        except Exception as e:
            logger.error(f"Failed to read catalog: {e}")
        
        return self._get_fallback_catalog()
    
    def _convert_v3_to_v4(self, manifest: Dict) -> Dict:
        """Convert v3 manifest.json to v4 catalog format"""
        return {
            "version": manifest.get("version", "3.0.0"),
            "categories": {cat["id"]: cat for cat in manifest.get("categories", [])},
            "templates": manifest.get("templates", []),
            "stacks": [],
            "exposure_modes": manifest.get("creation_modes", {})
        }
    
    # ==================== TEMPLATES ====================
    
    async def get_templates(self, category: str = None, status: str = None) -> List[Dict]:
        """
        Get all templates, optionally filtered by category or status.
        """
        catalog = await self._get_catalog()
        templates = catalog.get("templates", [])
        
        # Add source marker
        for t in templates:
            t["source"] = "catalog"
            t["is_custom"] = False
        
        # Apply filters
        if category:
            templates = [t for t in templates if t.get("category") == category]
        if status:
            templates = [t for t in templates if t.get("status") == status]
        
        return templates
    
    async def get_template_details(self, template_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific template.
        Reads from template.json in the template directory if available.
        """
        catalog = await self._get_catalog()
        templates = catalog.get("templates", [])
        
        # Find template in catalog
        template = next((t for t in templates if t["id"] == template_id), None)
        if not template:
            return None
        
        # Try to read detailed template.json from templates/{category}/{id}/
        category = template.get("category", "")
        template_json_path = self.cache_dir / "templates" / category / template_id / "template.json"
        
        try:
            if template_json_path.exists():
                with open(template_json_path) as f:
                    details = json.load(f)
                # Merge: template.json provides rich detail, but catalog.json
                # is the single source of truth for deployment-critical fields.
                merged = {**template, **details, "has_detailed_config": True}
                # Catalog-owned fields: always prefer catalog.json when defined
                _CATALOG_OWNED_FIELDS = ("secrets", "service_type", "tailscale_tags")
                for field in _CATALOG_OWNED_FIELDS:
                    if field in template:
                        merged[field] = template[field]
                return merged
        except Exception as e:
            logger.warning(f"Failed to read template.json for {template_id}: {e}")
        
        return {**template, "has_detailed_config": False}
    
    async def get_template_files(self, template_id: str) -> Dict[str, str]:
        """Get template files (Dockerfile, pipeline, etc.)"""
        template = await self.get_template_details(template_id)
        if not template:
            return {}
        
        files = {}
        category = template.get("category", "")
        template_dir = self.cache_dir / "templates" / category / template_id
        
        # Read common files
        for filename in ["Dockerfile", "bitbucket-pipelines.yml", "template.json"]:
            file_path = template_dir / filename
            if file_path.exists():
                try:
                    with open(file_path) as f:
                        files[filename] = f.read()
                except Exception as e:
                    logger.warning(f"Failed to read {filename}: {e}")
        
        return files
    
    # ==================== CATEGORIES ====================
    
    async def get_categories(self) -> Dict[str, Dict]:
        """Get all categories with their configuration"""
        catalog = await self._get_catalog()
        return catalog.get("categories", {})
    
    async def get_category(self, category_id: str) -> Optional[Dict]:
        """Get a specific category by ID"""
        categories = await self.get_categories()
        return categories.get(category_id)
    
    async def get_categories_list(self) -> List[Dict]:
        """Get categories as a list for UI consumption"""
        categories = await self.get_categories()
        return [{"id": k, **v} for k, v in categories.items()]
    
    # ==================== STACKS ====================
    
    async def get_stacks(self, popular_only: bool = False) -> List[Dict]:
        """Get all stacks (predefined combinations of templates)"""
        catalog = await self._get_catalog()
        stacks = catalog.get("stacks", [])
        
        # Also load from stacks/ directory
        stacks_dir = self.cache_dir / "stacks"
        if stacks_dir.exists():
            for stack_file in stacks_dir.glob("*.json"):
                try:
                    with open(stack_file) as f:
                        stack = json.load(f)
                        # Avoid duplicates
                        if not any(s["id"] == stack["id"] for s in stacks):
                            stacks.append(stack)
                except Exception as e:
                    logger.warning(f"Failed to read stack {stack_file}: {e}")
        
        if popular_only:
            stacks = [s for s in stacks if s.get("popular")]
        
        return stacks
    
    async def get_stack_details(self, stack_id: str) -> Optional[Dict]:
        """Get detailed information about a specific stack"""
        stacks = await self.get_stacks()
        stack = next((s for s in stacks if s["id"] == stack_id), None)
        
        if not stack:
            return None
        
        # Enrich with template details for each component
        enriched_components = []
        for component in stack.get("components", []):
            template = await self.get_template_details(component["template"])
            enriched_components.append({
                **component,
                "template_details": template
            })
        
        return {
            **stack,
            "components": enriched_components
        }
    
    # ==================== EXPOSURE MODES ====================
    
    async def get_exposure_modes(self) -> Dict[str, Dict]:
        """Get all exposure modes (public, tailscale, both, internal)"""
        catalog = await self._get_catalog()
        return catalog.get("exposure_modes", {})
    
    # ==================== DOCKER HUB ====================
    
    async def get_dockerhub_registry(self) -> Dict:
        """Get Docker Hub registry configuration"""
        catalog = await self._get_catalog()
        return catalog.get("dockerhub_registry", {"enabled": False})
    
    # ==================== CACHE MANAGEMENT ====================
    
    async def refresh_cache(self) -> bool:
        """Force refresh the templates cache"""
        self._last_sync = None
        self._credentials = None
        self._catalog_cache = None
        return await self._ensure_templates_cached(force=True)
    
    def get_cache_status(self) -> Dict:
        """Get cache status information"""
        return {
            "cache_dir": str(self.cache_dir),
            "cache_exists": self.cache_dir.exists(),
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "catalog_cached": self._catalog_cache is not None
        }
    
    # ==================== FALLBACK ====================
    
    def _get_fallback_catalog(self) -> Dict:
        """Hardcoded catalog as fallback"""
        return {
            "version": "4.0.0-fallback",
            "categories": {
                "frontend": {"name": "Frontend", "icon": "🎨", "description": "Web applications"},
                "backend": {"name": "Backend", "icon": "⚙️", "description": "APIs and services"},
                "database": {"name": "Database", "icon": "💾", "description": "Data storage"},
                "workflow": {"name": "Workflow", "icon": "🔄", "description": "Automation"}
            },
            "templates": [
                {
                    "id": "vue3-spa",
                    "name": "Vue 3 SPA",
                    "description": "Modern Vue 3 app with Vite and Tailwind",
                    "icon": "vue",
                    "color": "#42b883",
                    "category": "frontend",
                    "stack": ["vue3", "vite", "tailwind"],
                    "popular": True,
                    "status": "ready",
                    "port": 80,
                    "creation_modes": ["scaffold", "empty", "upload"]
                },
                {
                    "id": "fastapi-api",
                    "name": "FastAPI",
                    "description": "High-performance Python API",
                    "icon": "python",
                    "color": "#009688",
                    "category": "backend",
                    "stack": ["python", "fastapi"],
                    "popular": True,
                    "status": "ready",
                    "port": 8000,
                    "creation_modes": ["scaffold", "empty", "upload"]
                },
                {
                    "id": "mongodb",
                    "name": "MongoDB",
                    "description": "NoSQL document database",
                    "icon": "mongodb",
                    "color": "#47a248",
                    "category": "database",
                    "stack": ["mongodb"],
                    "popular": True,
                    "status": "ready",
                    "port": 27017,
                    "creation_modes": ["config-only"]
                },
                {
                    "id": "n8n",
                    "name": "n8n",
                    "description": "Workflow automation",
                    "icon": "n8n",
                    "color": "#ff6d5a",
                    "category": "workflow",
                    "stack": ["n8n"],
                    "popular": True,
                    "status": "ready",
                    "port": 5678,
                    "creation_modes": ["config-only"]
                }
            ],
            "stacks": [],
            "exposure_modes": {
                "public": {"name": "Public", "icon": "🌐"},
                "tailscale": {"name": "Private VPN", "icon": "🔒"},
                "both": {"name": "Mixed", "icon": "🔀"},
                "internal": {"name": "Cluster Only", "icon": "🏠"}
            }
        }
