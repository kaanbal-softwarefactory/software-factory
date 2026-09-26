"""
Template Spec Resolver
======================
Data-driven resolver that extracts ALL template-specific behavior from catalog.json.
The deployer uses this class instead of hardcoded string matching.

Adding a new template requires ONLY updating catalog.json — zero code changes.

Usage:
    spec = TemplateSpec(template_details)
    if spec.is_tcp:
        port = spec.tcp_port
    tags = spec.tailscale_tags_str
    secrets = spec.generate_secrets("prod", "my-app")
"""

import string
import secrets as secrets_module
import logging

logger = logging.getLogger(__name__)

# Categories that are inherently TCP (L4) services.
# Used as fallback when template doesn't declare service_type explicitly.
_TCP_CATEGORIES = frozenset({"database"})

# Default Tailscale tags per category (fallback when template has no tailscale_tags).
_CATEGORY_TAGS = {
    "database": ["tag:k8s", "tag:database"],
    "iot": ["tag:k8s", "tag:iot"],
}
_DEFAULT_TAGS = ["tag:k8s"]


class TemplateSpec:
    """
    Resolves template behavior from catalog data.
    
    This class is the SINGLE place that knows how to interpret
    template metadata. The deployer becomes 100% generic.
    """

    def __init__(self, template_details: dict):
        self._data = template_details or {}

    # ──────────────────────────────────────────────
    # Identity
    # ──────────────────────────────────────────────

    @property
    def template_id(self) -> str:
        return self._data.get("id", "")

    @property
    def category(self) -> str:
        return self._data.get("category", "")

    @property
    def name(self) -> str:
        return self._data.get("name", self.template_id)

    # ──────────────────────────────────────────────
    # Service Type (replaces _is_tcp_service)
    # ──────────────────────────────────────────────

    @property
    def is_tcp(self) -> bool:
        """
        Is this a raw TCP service (database/broker) that needs L4 exposure?
        
        Resolution order:
        1. Explicit 'service_type' field in catalog ("tcp" or "http")
        2. Fallback: category is in _TCP_CATEGORIES
        """
        service_type = self._data.get("service_type", "").lower()
        if service_type:
            return service_type == "tcp"
        return self.category in _TCP_CATEGORIES

    @property
    def is_http(self) -> bool:
        return not self.is_tcp

    # ──────────────────────────────────────────────
    # Ports (replaces _get_tcp_port)
    # ──────────────────────────────────────────────

    @property
    def port(self) -> int:
        """Primary port from catalog (e.g. 27017 for mongo, 80 for vue)."""
        return self._data.get("port", 80)

    @property
    def tcp_port(self) -> int:
        """TCP port for database/broker services. Same as port but semantically distinct."""
        return self.port

    @property
    def has_multi_ports(self) -> bool:
        """Does this template expose multiple ports? (e.g. EMQX, n8n)"""
        return bool(self._data.get("ports"))

    @property
    def ports(self) -> list[dict]:
        """Multi-port definitions from catalog."""
        return self._data.get("ports", [])

    @property
    def port_defaults(self) -> dict:
        """Per-port exposure defaults (e.g. {"mqtt": "public", "dashboard": "tailscale"})"""
        return self._data.get("port_defaults", {})

    @property
    def tailscale_tcp_ports(self) -> list[dict]:
        """Ports that need Tailscale L4 TCP Service (LoadBalancer) instead of L7 Ingress.
        
        For multi-port apps like EMQX where some ports are raw TCP (MQTT 1883)
        and others are HTTP (Dashboard 18083, WebSocket 8083).
        
        Returns list of full port definitions from the 'ports' array,
        filtered to only those named in 'tailscale_tcp_ports'.
        E.g. catalog: "tailscale_tcp_ports": ["mqtt"] → returns [{"name":"mqtt","port":1883,...}]
        """
        tcp_port_names = self._data.get("tailscale_tcp_ports", [])
        if not tcp_port_names:
            return []
        return [p for p in self.ports if p.get("name") in tcp_port_names]

    # ──────────────────────────────────────────────
    # Tailscale Tags (replaces _get_default_tags)
    # ──────────────────────────────────────────────

    @property
    def tailscale_tags(self) -> list[str]:
        """
        Default Tailscale ACL tags for this template.
        
        Resolution order:
        1. Explicit 'tailscale_tags' array in catalog
        2. Fallback: inferred from category via _CATEGORY_TAGS
        """
        tags = self._data.get("tailscale_tags")
        if tags:
            return list(tags)
        return list(_CATEGORY_TAGS.get(self.category, _DEFAULT_TAGS))

    @property
    def tailscale_tags_str(self) -> str:
        """Comma-separated tag string for K8s annotations."""
        return ",".join(self.tailscale_tags)

    # ──────────────────────────────────────────────
    # Secrets (replaces _generate_app_secrets)
    # ──────────────────────────────────────────────

    @property
    def secrets_schema(self) -> list[dict]:
        """
        Secret definitions from catalog.
        Each entry: {name, auto_generate, length?, pattern?, description?}
        """
        return self._data.get("secrets", [])

    def generate_secrets(self, env: str, app_name: str) -> dict:
        """
        Generate secret key-value pairs for a specific environment.
        
        Reads catalog 'secrets' schema and produces concrete values:
        - auto_generate=true  → random password of specified length
        - auto_generate=false → resolve pattern with variables
        - No secrets defined  → fallback generic APP_SECRET
        
        Pattern variables:
            {env_prefix}         → First 3 chars of env name
            {app_name}           → App name as-is
            {app_name_underscore}→ App name with - replaced by _
        """
        schema = self.secrets_schema
        if not schema:
            # Fallback: generic secret for templates without explicit schema
            return {"APP_SECRET": self._generate_password(24)}

        result = {}
        pattern_vars = {
            "env_prefix": env[:3],
            "app_name": app_name,
            "app_name_underscore": app_name.replace("-", "_"),
        }

        for secret_def in schema:
            name = secret_def.get("name", "")
            if not name:
                continue

            if secret_def.get("auto_generate", True):
                length = secret_def.get("length", 24)
                result[name] = self._generate_password(length)
            else:
                pattern = secret_def.get("pattern", "")
                if pattern:
                    try:
                        result[name] = pattern.format(**pattern_vars)
                    except (KeyError, ValueError):
                        result[name] = pattern
                else:
                    result[name] = ""

        return result

    @staticmethod
    def _generate_password(length: int = 24) -> str:
        """Generate a cryptographically secure random password."""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets_module.choice(alphabet) for _ in range(length))

    # ──────────────────────────────────────────────
    # Creation & Deployment metadata
    # ──────────────────────────────────────────────

    @property
    def needs_repo(self) -> bool:
        return self._data.get("needs_repo", True)

    @property
    def creation_modes(self) -> list[str]:
        return self._data.get("creation_modes", [])

    @property
    def is_config_only(self) -> bool:
        """Template's default mode is config-only (no repo/pipeline)."""
        modes = self.creation_modes
        return modes == ["config-only"]

    @property
    def docker_image(self) -> str | None:
        return self._data.get("docker_image")

    @property
    def health_endpoint(self) -> str | None:
        return self._data.get("health_endpoint")

    @property
    def k8s_base(self) -> str | None:
        return self._data.get("k8s_base")

    # ──────────────────────────────────────────────
    # Exposure
    # ──────────────────────────────────────────────

    @property
    def default_exposure(self) -> str:
        """Default exposure mode from catalog exposure.mode or category default."""
        exposure = self._data.get("exposure", {})
        if isinstance(exposure, dict):
            return exposure.get("mode", "internal")
        # Fallback to category-level defaults (loaded by caller)
        return "internal"

    @property
    def public_paths(self) -> list[str]:
        """URL paths that should be exposed publicly when exposure.mode == 'both'.
        
        Used mainly by n8n-style templates to expose /webhook/*, /form/* publicly
        while keeping the UI (/*) behind Tailscale VPN.
        Returns empty list if not defined (means full path: /).
        
        Checks both exposure.public_paths and exposure.mixed_config.public_paths
        for backward compatibility with different template.json structures.
        """
        exposure = self._data.get("exposure", {})
        if isinstance(exposure, dict):
            paths = exposure.get("public_paths", [])
            if not paths:
                mixed = exposure.get("mixed_config", {})
                if isinstance(mixed, dict):
                    paths = mixed.get("public_paths", [])
            return paths
        return []

    @property
    def private_env_vars(self) -> list[str]:
        """Env var names that should use Tailscale hostname when exposure == 'both'.
        
        For templates with mixed exposure (public_paths + Tailscale UI), these env vars
        control the UI/editor URL and should point to the Tailscale FQDN instead of
        the public domain. Example: ["N8N_EDITOR_BASE_URL"] for n8n templates.
        
        Returns empty list if not defined (no env var patching for 'both' mode).
        """
        exposure = self._data.get("exposure", {})
        if isinstance(exposure, dict):
            result = exposure.get("private_env_vars", [])
            if not result:
                mixed = exposure.get("mixed_config", {})
                if isinstance(mixed, dict):
                    result = mixed.get("private_env_vars", [])
            return result
        return []

    # ──────────────────────────────────────────────
    # Repr
    # ──────────────────────────────────────────────

    def __repr__(self):
        return f"TemplateSpec(id={self.template_id!r}, category={self.category!r}, is_tcp={self.is_tcp}, port={self.port})"
