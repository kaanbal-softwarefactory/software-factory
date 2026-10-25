"""Provision a Business Base demo through existing repository/CI/GitOps services.

Unlike the legacy literal generator, this path never serializes secrets to Git.
All Kubernetes objects except credential material are committed to infra-gitops.
"""
import asyncio
import base64
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from app.services import business_stack


async def wait_ready(name, template, timeout=1200, env="prod"):
    """A generated repo is not readiness. Wait for all owned Deployments."""
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    api = client.AppsV1Api()
    names = [name, f"{name}-worker", f"{name}-mail"] if template == "business-base" else [name]
    deadline = time.monotonic() + timeout
    def healthy():
        try:
            for item in names:
                deployment = api.read_namespaced_deployment(item, env, _request_timeout=10)
                if (deployment.status.observed_generation or 0) < deployment.metadata.generation:
                    return False
                if (deployment.status.updated_replicas or 0) < 1 or (deployment.status.available_replicas or 0) < 1:
                    return False
            return True
        except Exception:
            return False
    while time.monotonic() < deadline:
        if await asyncio.to_thread(healthy):
            return
        await asyncio.sleep(5)
    raise ValueError("El componente no alcanzó readiness; revisa pipeline, pods e init containers. Se conservan datos y recursos.")


async def _vault_credentials(deployer, name, generate, env="prod"):
    """CAS create preserves passwords across retries and partial launches."""
    cfg = deployer._credentials or {}
    address, token = cfg.get("vault_addr"), cfg.get("vault_token")
    if not address or not token:
        raise ValueError("Business Base requiere Vault configurado y abierto; no hay fallback de secretos a Git.")
    url = f"{address.rstrip('/')}/v1/secret/data/{env}/{name}"
    async with httpx.AsyncClient(timeout=15) as client:
        headers = {"X-Vault-Token": token}
        response = await client.get(url, headers=headers)
        if response.status_code == 404:
            values = await generate()
            response = await client.post(url, headers=headers, json={"data": values, "options": {"cas": 0}})
            if response.status_code not in (200, 204, 400):
                raise ValueError("No se pudieron guardar las credenciales en Vault.")
            response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError("Vault no está disponible para Business Base. Revisa su estado y permisos.")
        return response.json()["data"]["data"]


async def credentials(deployer, template, name, config, env="prod"):
    async def generate():
        if template == "business-postgres":
            return {key: deployer._generate_password(48) for key in business_stack.SECRET_KEYS[template]}
        db_values = await deployer._read_vault_secrets(config["BUSINESS_DB_APP"], env)
        if not all(db_values.get(k) for k in business_stack.SECRET_KEYS["business-postgres"]):
            raise ValueError("Faltan las credenciales de la base del stack en Vault.")
        if template == "business-identity":
            return {**{key: deployer._generate_password(48) for key in business_stack.SECRET_KEYS[template]},
                    "KC_DB_PASSWORD": db_values["IDENTITY_PASSWORD"]}
        identity = await deployer._read_vault_secrets(config["BUSINESS_IDENTITY_APP"], env)
        if not all(identity.get(k) for k in business_stack.SECRET_KEYS["business-identity"]):
            raise ValueError("Faltan las credenciales de identidad del stack en Vault.")
        return {"PGPASSWORD": db_values["RUNTIME_PASSWORD"], "MIGRATION_PGPASSWORD": db_values["MIGRATION_PASSWORD"],
                "IDENTITY_ADMIN_PASSWORD": identity["KC_BOOTSTRAP_ADMIN_PASSWORD"],
                **{key: identity[key] for key in ["OIDC_CLIENT_SECRET", "OWNER_PASSWORD", "CUSTOMER_PASSWORD"]}}
    values = await _vault_credentials(deployer, name, generate, env=env)
    if not all(values.get(key) for key in business_stack.SECRET_KEYS[template]):
        raise ValueError("Contrato de secretos incompleto. No se sobrescriben credenciales existentes.")
    return values


def materialize_secret(name, values, env="prod"):
    """Normal platform provisioning of Vault-backed runtime material, never a manifest patch."""
    from kubernetes import client, config
    from kubernetes.client.exceptions import ApiException
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    core = client.CoreV1Api()
    target = f"{name}-secrets"
    data = {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}
    try:
        existing = core.read_namespaced_secret(target, env, _request_timeout=10)
    except ApiException as error:
        if error.status != 404:
            raise ValueError("La API necesita permiso de lectura/alta de secretos en prod.") from None
        try:
            core.create_namespaced_secret(env, client.V1Secret(
                metadata=client.V1ObjectMeta(name=target, labels={"app": name, "kaanbal.io/managed-secret": "business-base"}),
                type="Opaque", immutable=True, data=data), _request_timeout=10)
            return
        except ApiException as error:
            if error.status != 409:
                raise ValueError("No se pudo materializar el secreto de Business Base.") from None
            existing = core.read_namespaced_secret(target, env, _request_timeout=10)
    if existing.data != data:
        raise ValueError("El secreto runtime difiere de Vault; se detuvo para preservar credenciales existentes.")


def scaffold_source(destination, config):
    """Copy source byte-for-byte from the installed immutable monorepo revision.

    No Jinja or domain-wide replacements over TypeScript/example fixture emails.
    This avoids a second maintained copy of the business source in the catalog.
    """
    revision = config.get("BUSINESS_SOURCE_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Business Base requiere el SHA completo de la versión instalada.")
    repository = "https://github.com/kaanbal-softwarefactory/software-factory.git"
    with tempfile.TemporaryDirectory(prefix="business-source-") as directory:
        for args in (["git", "init", directory], ["git", "-C", directory, "fetch", "--depth", "1", repository, revision],
                     ["git", "-C", directory, "checkout", "--detach", "FETCH_HEAD"]):
            result = subprocess.run(args, capture_output=True, timeout=120)
            if result.returncode:
                raise ValueError("No se pudo descargar el código de Business Base en la revisión instalada.")
        source = Path(directory) / "SOFTWARE_FACTORY" / "business-base"
        if not (source / "scripts" / "provision-identity.mjs").exists():
            raise ValueError("Actualiza Kaanbal a la revisión que integra Business Base antes de lanzarlo.")
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "node_modules", ".next", ".env*", "coverage", "*.tsbuildinfo"))
        manifest = Path(destination) / "business.manifest.json"
        provenance = json.loads(manifest.read_text(encoding="utf-8"))
        provenance["source_sha"] = revision
        manifest.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        # Persist non-secret launch choices so cloning this app reproduces its preset locally.
        (Path(destination) / "business.config.json").write_text(json.dumps({
            "name": f"{config['BUSINESS_APP'][:39]}-local", "title": config.get("BUSINESS_NAME", config["BUSINESS_APP"]),
            "preset": config.get("BUSINESS_PRESET", "services"), "modules": config.get("BUSINESS_MODULES"), "port": 3100, "identityPort": 8180, "mailPort": 8125,
        }, indent=2) + "\n", encoding="utf-8")


async def deploy(deployer, app_data, emit):
    config = app_data.template_config or {}
    name, template = app_data.name, app_data.template
    business_stack.validate_config(template, config, app_data.environments)
    expected_name = {"business-base": config["BUSINESS_APP"], "business-postgres": config["BUSINESS_DB_APP"], "business-identity": config["BUSINESS_IDENTITY_APP"]}[template]
    if name != expected_name:
        raise ValueError("El nombre del componente no coincide con el sistema Business Base.")
    for env in app_data.environments:
        if deployer._get_env_exposure(app_data, env) != ("internal" if template == "business-postgres" else "public"):
            raise ValueError("El candidato requiere base interna y web/identidad HTTPS públicas por ambiente.")
    try:
        return await _deploy(deployer, app_data, emit, config, name, template)
    except Exception:
        # Providers and Kubernetes exceptions can embed request bodies. Keep the
        # persisted deploy event safe even if a dependency accidentally includes one.
        raise ValueError("Business Base no completó el despliegue. Revisa disponibilidad de Vault, permisos de secretos, GitOps y CI; se preservan los recursos creados.") from None


async def _deploy(deployer, app_data, emit, config, name, template):
    with tempfile.TemporaryDirectory(prefix=f"business-{name}-", dir=deployer.workspace) as work:
        root = Path(work)
        infra, templates, app = root / "infra-gitops", root / "templates", root / name
        await emit("clone", "Preparando repositorios GitOps y código de la revisión instalada")
        await deployer._clone_repos(deployer._credentials.get("templates_repo", "kaanbal-templates"), str(infra), str(templates))
        repo_url = ""
        if template == "business-base":
            await asyncio.to_thread(scaffold_source, app, config)
            repo_url = await deployer.provider.create_repo(name)
            await deployer._setup_pipeline_and_docker(str(app), {"pipeline_strategy": "dynamic"}, app_data, app_data.environments, str(templates))
            await deployer._push_new_repo(str(app), repo_url, name)
            await deployer._create_environment_branches(str(app), repo_url, app_data.environments)
        await emit("vault", "Provisionando credenciales independientes; Git solo recibirá referencias")
        for env in app_data.environments:
            values = await credentials(deployer, template, name, config, env=env)
            await asyncio.to_thread(materialize_secret, name, values, env=env)
            business_stack.write_overlay(infra, template, name, config, domain=deployer.domain,
                                         dockerhub_user=deployer._credentials["dockerhub_username"],
                                         ingress_class=deployer.ingress_class, cluster_issuer=deployer.ingress_cluster_issuer,
                                         env=env)
            await deployer._push_infra(str(infra), name, [env])
            if template != "business-postgres":
                host = deployer._build_public_host(name, env, app_data)
                if not await deployer._setup_cloudflare_dns(name, [host]):
                    raise ValueError("DNS pendiente: revisa la publicación del dominio antes de continuar.")
        if template == "business-base":
            await deployer._configure_ci_variables(name)
            await deployer.provider.enable_ci(name)
            await deployer._trigger_initial_ci(name, app_data.environments)
        await emit("ready", "Recursos publicados en GitOps; el stack verificará la disponibilidad real", "success")
        port = {"business-base": 3000, "business-identity": 8080, "business-postgres": 5432}[template]
        public = template != "business-postgres"
        default_env = "prod" if "prod" in app_data.environments else app_data.environments[0]
        host = deployer._build_public_host(name, default_env, app_data)
        return {"repo_url": repo_url, "subdomain": host, "url": f"https://{host}" if public else "",
                "environments": app_data.environments, "status": "success", "connection_info": {
                    "port": port, "secrets_name": f"{name}-secrets", "vault_path": f"secret/{default_env}/{name}",
                    "internal_dns_pattern": f"{name}.{{env}}.svc.cluster.local",
                    "business_profile": "demo", "source_sha": config.get("BUSINESS_SOURCE_SHA"),
                }}
