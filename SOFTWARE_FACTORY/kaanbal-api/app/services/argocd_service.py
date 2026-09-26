"""
ArgoCD Service - Obtener estado real de apps desde ArgoCD
=========================================================
Consulta la API de ArgoCD para obtener health status, sync status y recursos.
Basado en pruebas reales con la API v3.2.6

Health Status Values:
- Healthy: All resources are healthy
- Progressing: Resources are being updated
- Degraded: One or more resources are unhealthy  
- Suspended: Application is suspended
- Missing: Resources are missing
- Unknown: Health status is unknown

Sync Status Values:
- Synced: Application state matches Git
- OutOfSync: Application state differs from Git
- Unknown: Sync status is unknown
"""

import time
import httpx
from typing import Optional, List
from app.db import get_db
from app.defaults import ARGOCD_SERVER, ARGOCD_USERNAME

TOKEN_MAX_AGE = 1200  # 20 minutes


class ArgoCDService:
    def __init__(self):
        self._config = None
        self._token = None
        self._token_time = 0

    async def _load_config(self):
        """Carga configuración de ArgoCD desde MongoDB"""
        if self._config:
            return self._config

        db = get_db()
        config = await db.system_config.find_one({"_id": "main"})

        if config:
            self._config = {
                "server": config.get("argocd_server", ARGOCD_SERVER),
                "username": config.get("argocd_username", ARGOCD_USERNAME),
                "password": config.get("argocd_password", "")
            }
        else:
            # Default for in-cluster
            self._config = {
                "server": ARGOCD_SERVER,
                "username": ARGOCD_USERNAME,
                "password": ""
            }

        return self._config

    async def _get_token(self, force_refresh: bool = False) -> Optional[str]:
        """Obtiene token de autenticación de ArgoCD"""
        if self._token and not force_refresh and (time.time() - self._token_time) < TOKEN_MAX_AGE:
            return self._token

        config = await self._load_config()

        if not config.get("password"):
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
                response = await client.post(
                    f"{config['server']}/api/v1/session",
                    json={
                        "username": config["username"],
                        "password": config["password"]
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    self._token = data.get("token")
                    self._token_time = time.time()
                    return self._token
                else:
                    print(f"ArgoCD auth failed: {response.status_code}")

        except Exception as e:
            print(f"ArgoCD auth error: {e}")

        return None

    async def _request(self, method: str, path: str, client: httpx.AsyncClient, **kwargs) -> httpx.Response:
        """Makes an authenticated ArgoCD request with automatic token refresh on 401/403."""
        config = await self._load_config()
        token = await self._get_token()
        if not token:
            return None

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        response = await client.request(method, f"{config['server']}{path}", headers=headers, **kwargs)

        if response.status_code in (401, 403):
            # Token expired or invalidated — refresh and retry once
            token = await self._get_token(force_refresh=True)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                response = await client.request(method, f"{config['server']}{path}", headers=headers, **kwargs)

        return response

    async def get_connection_status(self) -> dict:
        """Return ArgoCD connectivity diagnostics for UI and refresh endpoints."""
        config = await self._load_config()
        if not config.get("password"):
            return {
                "connected": False,
                "reason": "Missing argocd_password in system settings"
            }

        token = await self._get_token(force_refresh=True)
        if not token:
            return {
                "connected": False,
                "reason": "ArgoCD authentication failed"
            }

        return {"connected": True}
    
    async def list_applications(self) -> List[dict]:
        """
        Lista todas las aplicaciones en ArgoCD con resumen de estado
        """
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
                response = await self._request("GET", "/api/v1/applications", client)
                if not response or response.status_code != 200:
                    return []

                data = response.json()
                return [self._extract_app_summary(app) for app in data.get("items", [])]

        except Exception as e:
            print(f"ArgoCD list error: {e}")
            return []
    
    async def get_application_status(self, app_name: str) -> Optional[dict]:
        """
        Obtiene el estado detallado de una aplicación incluyendo:
        - Health y sync status
        - Estado de cada recurso (Deployment, Service, Ingress, Pods)
        - Imágenes desplegadas
        - URLs externas
        - Historial de deployments
        """
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
                # Intentar con diferentes patrones de nombre
                app_names_to_try = [
                    app_name,
                    f"{app_name}-prod",
                    f"{app_name}-dev",
                    f"{app_name}-staging",
                    f"{app_name}-prod-prod"  # En caso de apps duplicadas
                ]

                for name in app_names_to_try:
                    response = await self._request("GET", f"/api/v1/applications/{name}", client)
                    if response and response.status_code == 200:
                        app = response.json()
                        return self._extract_full_status(app)

                # No encontrada
                return {"exists": False, "name": app_name, "tried_names": app_names_to_try}

        except Exception as e:
            print(f"ArgoCD get app error: {e}")
            return {"error": str(e), "exists": False}
    
    async def get_resource_tree(self, app_name: str) -> Optional[dict]:
        """
        Obtiene el árbol de recursos con estado de cada pod, deployment, etc.
        Muy útil para debugging - muestra exactamente qué está fallando
        """
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
                # Intentar con nombre-prod primero
                for suffix in ["-prod", "-dev", "-staging", ""]:
                    name = f"{app_name}{suffix}" if suffix else app_name
                    response = await self._request("GET", f"/api/v1/applications/{name}/resource-tree", client)
                    if response and response.status_code == 200:
                        data = response.json()
                        return self._extract_resource_tree(data)

                return None

        except Exception as e:
            print(f"ArgoCD resource tree error: {e}")
            return None
    
    async def sync_application(self, app_name: str) -> dict:
        """Fuerza la sincronización de una aplicación"""
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                # Intentar con nombre-prod
                for suffix in ["-prod", "-dev", "-staging", ""]:
                    name = f"{app_name}{suffix}" if suffix else app_name
                    response = await self._request("POST", f"/api/v1/applications/{name}/sync", client, json={"prune": False})
                    if response and response.status_code == 200:
                        return {"success": True, "message": f"Sync initiated for {name}"}

                return {"error": "Application not found in ArgoCD"}

        except Exception as e:
            return {"error": str(e)}
    
    async def get_app_logs(self, app_name: str, pod_name: str = None, container: str = None) -> dict:
        """
        Obtiene logs de los pods de una aplicación
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                params = {}
                if pod_name:
                    params["podName"] = pod_name
                if container:
                    params["container"] = container

                for suffix in ["-prod", "-dev", ""]:
                    name = f"{app_name}{suffix}" if suffix else app_name
                    response = await self._request("GET", f"/api/v1/applications/{name}/logs", client, params=params)
                    if response and response.status_code == 200:
                        return {"logs": response.text, "app_name": name}

                return {"error": "Application not found or no logs available"}

        except Exception as e:
            return {"error": str(e)}
    
    def _extract_app_summary(self, app: dict) -> dict:
        """Extrae resumen de una app para listado"""
        metadata = app.get("metadata", {})
        spec = app.get("spec", {})
        status = app.get("status", {})
        health = status.get("health", {})
        sync = status.get("sync", {})
        
        return {
            "name": metadata.get("name"),
            "namespace": spec.get("destination", {}).get("namespace"),
            "health": health.get("status", "Unknown"),
            "healthMessage": health.get("message"),
            "sync": sync.get("status", "Unknown"),
            "revision": sync.get("revision", "")[:8] if sync.get("revision") else None,
            "reconciledAt": status.get("reconciledAt"),
            "labels": metadata.get("labels", {}),
            # Quick status indicator
            "isHealthy": health.get("status") == "Healthy",
            "isSynced": sync.get("status") == "Synced"
        }
    
    def _extract_full_status(self, app: dict) -> dict:
        """Extrae estado completo de una app"""
        metadata = app.get("metadata", {})
        spec = app.get("spec", {})
        status = app.get("status", {})
        health = status.get("health", {})
        sync = status.get("sync", {})
        summary = status.get("summary", {})
        operation = status.get("operationState", {})
        
        # Extraer estado de cada recurso
        resources = []
        for r in status.get("resources", []):
            resources.append({
                "kind": r.get("kind"),
                "name": r.get("name"),
                "namespace": r.get("namespace"),
                "syncStatus": r.get("status"),
                "health": r.get("health", {}).get("status"),
                "healthMessage": r.get("health", {}).get("message")
            })
        
        # Extraer historial de deployments
        history = []
        for h in status.get("history", [])[-5:]:  # Últimos 5
            history.append({
                "revision": h.get("revision", "")[:8],
                "deployedAt": h.get("deployedAt"),
                "initiatedBy": "automated" if h.get("initiatedBy", {}).get("automated") else "manual"
            })
        
        return {
            "exists": True,
            "name": metadata.get("name"),
            "namespace": spec.get("destination", {}).get("namespace"),
            "project": spec.get("project"),
            "createdAt": metadata.get("creationTimestamp"),
            
            # Source info
            "source": {
                "repoURL": spec.get("source", {}).get("repoURL"),
                "path": spec.get("source", {}).get("path"),
                "targetRevision": spec.get("source", {}).get("targetRevision")
            },
            
            # Health info
            "health": {
                "status": health.get("status", "Unknown"),
                "message": health.get("message"),
                "lastTransition": health.get("lastTransitionTime")
            },
            
            # Sync info
            "sync": {
                "status": sync.get("status", "Unknown"),
                "revision": sync.get("revision")
            },
            
            # Operation state (último sync)
            "operation": {
                "phase": operation.get("phase"),
                "message": operation.get("message"),
                "startedAt": operation.get("startedAt"),
                "finishedAt": operation.get("finishedAt")
            },
            
            # Summary
            "images": summary.get("images", []),
            "externalURLs": summary.get("externalURLs", []),
            
            # Resources detail
            "resources": resources,
            
            # History
            "history": history,
            
            # Conditions (warnings/errors)
            "conditions": status.get("conditions"),
            
            # Timestamps
            "reconciledAt": status.get("reconciledAt"),
            
            # Quick status helpers
            "isHealthy": health.get("status") == "Healthy",
            "isSynced": sync.get("status") == "Synced",
            "isDegraded": health.get("status") == "Degraded",
            "isProgressing": health.get("status") == "Progressing"
        }
    
    def _extract_resource_tree(self, data: dict) -> dict:
        """Extrae árbol de recursos con estado de cada uno"""
        pods = []
        deployments = []
        services = []
        ingresses = []
        other = []
        
        for node in data.get("nodes", []):
            resource = {
                "name": node.get("name"),
                "kind": node.get("kind"),
                "namespace": node.get("namespace"),
                "health": node.get("health", {}).get("status"),
                "healthMessage": node.get("health", {}).get("message"),
                "createdAt": node.get("createdAt"),
                "version": node.get("version")
            }
            
            kind = node.get("kind")
            if kind == "Pod":
                pods.append(resource)
            elif kind == "Deployment":
                deployments.append(resource)
            elif kind == "Service":
                services.append(resource)
            elif kind == "Ingress":
                ingresses.append(resource)
            else:
                other.append(resource)
        
        # Calcular resumen
        total = len(pods) + len(deployments) + len(services) + len(ingresses) + len(other)
        healthy = sum(1 for r in pods + deployments + services + ingresses 
                     if r.get("health") == "Healthy")
        degraded = sum(1 for r in pods + deployments + services + ingresses 
                      if r.get("health") == "Degraded")
        
        return {
            "pods": pods,
            "deployments": deployments,
            "services": services,
            "ingresses": ingresses,
            "other": other,
            "summary": {
                "total": total,
                "healthy": healthy,
                "degraded": degraded,
                "progressing": total - healthy - degraded
            }
        }
    
    async def refresh_application(self, app_name: str, hard: bool = True) -> dict:
        """
        Fuerza a ArgoCD a refrescar una aplicación (re-leer desde Git).
        hard=True invalida el cache completo del manifiesto.
        """
        refresh_type = "hard" if hard else "normal"

        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                response = await self._request("GET", f"/api/v1/applications/{app_name}", client, params={"refresh": refresh_type})
                if response and response.status_code == 200:
                    return {"success": True, "app": app_name, "refresh": refresh_type}
                return {"error": f"HTTP {response.status_code if response else 'no response'}", "app": app_name}

        except Exception as e:
            return {"error": str(e), "app": app_name}

    async def refresh_all_applications(self, hard: bool = True) -> dict:
        """
        Refresca todas las aplicaciones en ArgoCD.
        Retorna resumen de resultados.
        """
        apps = await self.list_applications()
        if not apps:
            conn = await self.get_connection_status()
            if not conn.get("connected"):
                return {
                    "refreshed": 0,
                    "failed": 0,
                    "errors": [{"app": "argocd", "error": conn.get("reason", "Not connected")}],
                    "message": "ArgoCD is not connected",
                    "connected": False,
                }
            return {
                "refreshed": 0,
                "failed": 0,
                "errors": [],
                "message": "No apps found",
                "connected": True,
            }

        results = {"refreshed": 0, "failed": 0, "errors": [], "apps": [], "connected": True}

        for app in apps:
            name = app.get("name")
            if not name:
                continue
            result = await self.refresh_application(name, hard=hard)
            if result.get("success"):
                results["refreshed"] += 1
                results["apps"].append(name)
            else:
                results["failed"] += 1
                results["errors"].append({"app": name, "error": result.get("error")})

        return results

    async def get_env_status(self, app_name: str, env: str) -> Optional[dict]:
        """
        Obtiene el estado de una aplicación para un environment específico.
        Busca directamente {app_name}-{env} en ArgoCD.
        """
        argo_name = f"{app_name}-{env}"

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
                response = await self._request("GET", f"/api/v1/applications/{argo_name}", client)
                if response and response.status_code == 200:
                    app = response.json()
                    return self._extract_full_status(app)

                return {"exists": False, "name": argo_name}

        except Exception as e:
            return {"error": str(e), "exists": False}

    async def get_multi_env_status(self, app_name: str, environments: list) -> dict:
        """
        Obtiene el estado de ArgoCD para cada environment de una aplicación.
        Retorna un dict { env: status_dict } con el estado de cada ambiente.
        """
        results = {}
        for env in environments:
            results[env] = await self.get_env_status(app_name, env)
        return results

    def clear_cache(self):
        """Limpia el cache de configuración y token"""
        self._config = None
        self._token = None


# Singleton instance
argocd_service = ArgoCDService()
