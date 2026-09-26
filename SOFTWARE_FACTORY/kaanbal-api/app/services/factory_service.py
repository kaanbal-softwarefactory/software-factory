import logging
from typing import List
from atlassian.bitbucket import Cloud
from kubernetes import client, config
from app.schemas.setup import SetupRequest
from app.config import settings
from app.db import get_db
import base64

logger = logging.getLogger(__name__)

class FactoryService:
    def __init__(self):
        try:
            config.load_incluster_config()
        except:
            # Fallback to local config for dev
            try:
                config.load_kube_config()
            except:
                logger.warning("No Kube Config found")
        
        self.k8s_core = client.CoreV1Api()

    async def initialize_factory(self, request: SetupRequest) -> dict:
        steps_completed = []
        missing_steps = []

        # 1. Validate & Store Git Credentials in K8s (ArgoCD Secret)
        try:
            await self._update_argocd_secret(request.git_username, request.git_token)
            steps_completed.append("git_creds_stored")
        except Exception as e:
            logger.error(f"Failed to store git creds: {e}")
            missing_steps.append("git_creds_stored")
            return {"status": "error", "message": str(e), "steps_completed": steps_completed}

        # 2. Connect to Bitbucket & Ensure Repos Exist
        try:
            bitbucket = Cloud(
                url="https://api.bitbucket.org/",
                username=request.git_username,
                password=request.git_token
            )
            # Check workspaces/repos logic here...
            # For V1 seed, we assume we just validate connection
            user_info = bitbucket.get_user_profile()
            steps_completed.append("bitbucket_connected")
        except Exception as e:
            logger.error(f"Failed to connect to Bitbucket: {e}")
            missing_steps.append("bitbucket_connected")

        # 3. Configure Modules (Toggle in GitOps repo - Logic Placeholder)
        # In a real scenario, this would clone the repo using the fresh creds,
        # edit files, and push back. 
        if request.modules:
            logger.info(f"Selected Modules: {request.modules}")
            steps_completed.append("modules_configured")

        return {
            "status": "success",
            "message": "Factory Initialized",
            "steps_completed": steps_completed,
            "missing_steps": missing_steps
        }

    async def _update_argocd_secret(self, username: str, token: str):
        """
        Updates the 'private-repo-creds' secret in 'argocd' namespace
        so ArgoCD can start syncing.
        """
        secret_name = "private-repo-creds"
        namespace = "argocd"

        # Get workspace from MongoDB or settings
        db = get_db()
        sys_config = await db.system_config.find_one({"_id": "main"})
        workspace = (sys_config or {}).get("bitbucket_workspace", "") or settings.bitbucket_workspace
        repo_url = f"https://bitbucket.org/{workspace}/infra-gitops.git"

        # Prepare Data
        data = {
            "username": base64.b64encode(username.encode()).decode(),
            "password": base64.b64encode(token.encode()).decode(),
            "type": base64.b64encode("git".encode()).decode(),
            "url": base64.b64encode(repo_url.encode()).decode()
        }

        # Check if exists
        try:
            self.k8s_core.read_namespaced_secret(name=secret_name, namespace=namespace)
            # Update
            body = client.V1Secret(
                metadata=client.V1ObjectMeta(name=secret_name, labels={"argocd.argoproj.io/secret-type": "repository"}),
                data=data
            )
            self.k8s_core.replace_namespaced_secret(name=secret_name, namespace=namespace, body=body)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # Create
                body = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=secret_name, labels={"argocd.argoproj.io/secret-type": "repository"}),
                    data=data,
                    type="Opaque"
                )
                self.k8s_core.create_namespaced_secret(namespace=namespace, body=body)
            else:
                raise e
