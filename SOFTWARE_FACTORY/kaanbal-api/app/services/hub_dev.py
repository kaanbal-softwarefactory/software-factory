"""Prepare a whole Business Base Dev environment without copying Prod data or source scaffolds."""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from app.services import business_stack, business_deployer, hub_integration


def plan(apps, domain, target=""):
    candidates = [a for a in apps if a.get("template") == "business-base" and (not target or a["name"] == target)]
    if len(candidates) != 1:
        raise ValueError("Elige una única aplicación Business Base del proyecto para preparar su Dev.")
    web = candidates[0]
    selected = []
    for name, template in [(web["name"] + "-db", "business-postgres"),
                           (web["name"] + "-identity", "business-identity"), (web["name"], "business-base")]:
        row = next((a for a in apps if a["name"] == name and a.get("template") == template), None)
        if row is None:
            raise ValueError("El proyecto necesita sus tres servicios: base de datos, identidad y aplicación.")
        if row.get("domain_id") != web.get("domain_id"):
            raise ValueError("Los componentes del stack deben compartir el dominio del proyecto.")
        selected.append(row)
    repo = hub_integration.repo_from_url(web.get("repo_url") or "")
    if not repo or not domain:
        raise ValueError("El stack requiere repositorio GitHub y dominio configurados.")
    from app.services.domain_service import public_host
    components = [{"name": a["name"], "template": a["template"], "environment": "dev",
                   "exists": "dev" in (a.get("environments") or []),
                   "url": ("https://" + public_host(a["name"], "dev", domain)) if a["template"] != "business-postgres" else None}
                  for a in selected]
    fingerprint = hashlib.sha256(json.dumps({"repo": repo, "domain": domain,
        "components": [(str(a.get("_id")), a["name"], a["template"], a.get("domain_id")) for a in selected]}, sort_keys=True).encode()).hexdigest()
    return {"app": web["name"], "repo": repo, "domain": domain, "branch": "develop", "environment": "dev",
            "components": components, "fingerprint": fingerprint,
            "changes": ["Recursos, credenciales Vault, base e identidad propios en Dev.",
                        "develop se conserva si existe; si no, nace de la rama principal actual.",
                        "Se añade CI de ramas y despliegue Dev; el workflow de producción no se reemplaza.",
                        "Tras verificar Dev, las tareas revisadas se integran en develop con CI obligatorio."],
            "preserves": "No se copian datos, usuarios ni contraseñas de producción. Kaanbal se actualiza manualmente."}


def _git(directory, *args, allow_missing=False):
    result = subprocess.run(["git", *args], cwd=directory, capture_output=True, timeout=120, text=True)
    if result.returncode and not allow_missing:
        raise ValueError("No se pudo completar una operación Git del ambiente Dev. Revisa acceso y ramas protegidas.")
    return result.stdout.strip() if result.returncode == 0 else ""


async def prepare_source(deployer, destination, web, repo):
    """Keep all custom source. Only add a separate, generated Dev workflow."""
    public_repo = hub_integration.repo_from_url(deployer.provider.get_web_url(web["name"]))
    if public_repo != repo:
        raise ValueError("La credencial Git configurada no corresponde al repositorio del proyecto.")
    await asyncio.to_thread(_git, destination.parent, "clone", deployer.provider.get_auth_clone_url(web["name"]), str(destination))
    exists = await asyncio.to_thread(_git, destination, "ls-remote", "--heads", "origin", "develop")
    if exists:
        await asyncio.to_thread(_git, destination, "checkout", "-b", "develop", "origin/develop")
    else:
        # origin/HEAD is the actual default branch; never reset an existing develop.
        await asyncio.to_thread(_git, destination, "checkout", "-b", "develop", "origin/HEAD")
    launch = destination / "business.config.json"
    choices = json.loads(launch.read_text()) if launch.exists() else {}
    if not (destination / "scripts/provision-identity.mjs").is_file():
        raise ValueError("El repositorio no contiene el contrato Business Base esperado.")
    cfg = {"BUSINESS_PROFILE": "demo", "BUSINESS_APP": web["name"], "BUSINESS_DB_APP": web["name"] + "-db",
           "BUSINESS_IDENTITY_APP": web["name"] + "-identity", "BUSINESS_NAME": choices.get("title") or web["name"],
           "BUSINESS_PRESET": choices.get("preset") or "services", "BUSINESS_MODULES": choices.get("modules"),
           "node_version": "24.15.0"}
    business_stack.validate_config("business-base", cfg, ["dev"])
    from types import SimpleNamespace
    standard = destination / deployer.provider.get_ci_filename()
    previous = standard.read_bytes() if standard.exists() else None
    await deployer._generate_dynamic_pipeline(str(destination), SimpleNamespace(name=web["name"], template_config=cfg), ["dev"])
    generated = standard.read_bytes()
    if previous is not None:
        standard.write_bytes(previous)
    else:
        standard.unlink()
    dev_workflow = destination / ".github/workflows/kaanbal-dev.yml"
    if dev_workflow.exists() and b"Generated by Kaanbal Engine" not in dev_workflow.read_bytes():
        raise ValueError("Ya existe un workflow Dev personalizado; revísalo antes de continuar.")
    dev_workflow.parent.mkdir(parents=True, exist_ok=True)
    dev_workflow.write_bytes(generated)
    await asyncio.to_thread(_git, destination, "config", "user.name", "Kaanbal")
    await asyncio.to_thread(_git, destination, "config", "user.email", "kaanbal@example.com")
    await asyncio.to_thread(_git, destination, "add", ".github/workflows/kaanbal-dev.yml")
    changed = await asyncio.to_thread(_git, destination, "diff", "--cached", "--name-only")
    if changed:
        await asyncio.to_thread(_git, destination, "commit", "-m", "ci: validate task branches and deploy develop to isolated Dev")
    return cfg


async def wait_version(app, sha, *, timeout=1200):
    from app.services.argocd_service import argocd_service
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = await argocd_service.get_env_status(app, "dev")
        verdict, _ = hub_integration.deploy_verdict(state, sha)
        if verdict == "deployed":
            return
        if verdict == "unhealthy":
            raise ValueError("Dev no alcanzó una versión sana; se conservan recursos para diagnosticar.")
        await asyncio.sleep(10)
    raise ValueError("Se agotó la espera de la imagen de Dev. Revisa su pipeline y Argo.")


async def prepare(apps, requested_plan, emit):
    """Run only after the user applied a project-bound plan. No production mutations."""
    from app.services.app_deployer import AppDeployer
    deployer = AppDeployer()
    await deployer._load_credentials()
    web = next(a for a in apps if a["name"] == requested_plan["app"])
    await deployer.bind_domain(web)
    if deployer.domain != requested_plan["domain"]:
        raise ValueError("El dominio cambió; genera de nuevo el plan Dev.")
    with tempfile.TemporaryDirectory(prefix="hub-dev-", dir=deployer.workspace) as tmp:
        root = Path(tmp)
        infra, templates, source = root / "infra-gitops", root / "templates", root / "source"
        await emit("source", "Preparando la rama Dev sin reemplazar el código personalizado.")
        cfg = await prepare_source(deployer, source, web, requested_plan["repo"])
        await deployer._clone_repos(deployer._credentials.get("templates_repo", "kaanbal-templates"), str(infra), str(templates))
        for component in requested_plan["components"]:
            name, template = component["name"], component["template"]
            await emit("resources", f"Preparando {name} en Dev con sus credenciales propias.")
            values = await business_deployer.credentials(deployer, template, name, cfg, env="dev")
            await asyncio.to_thread(business_deployer.materialize_secret, name, values, env="dev")
            business_stack.write_overlay(infra, template, name, cfg, domain=deployer.domain,
                dockerhub_user=deployer._credentials["dockerhub_username"], ingress_class=deployer.ingress_class,
                cluster_issuer=deployer.ingress_cluster_issuer, env="dev")
            await deployer._push_infra(str(infra), name, ["dev"])
            if component["url"] and not await deployer._setup_cloudflare_dns(name, [component["url"].removeprefix("https://")]):
                raise ValueError("Falta publicar el DNS de Dev.")
        # Only now publish develop: its CI can find all three Dev overlays.
        await emit("pipeline", "Publicando develop y siguiendo su versión en Dev.")
        await asyncio.to_thread(_git, source, "push", "origin", "develop")
        sha = await asyncio.to_thread(_git, source, "rev-parse", "HEAD")
        await deployer._trigger_initial_ci(web["name"], ["dev"])
        for component in requested_plan["components"]:
            await business_deployer.wait_ready(component["name"], component["template"], env="dev")
        await wait_version(web["name"], sha)
        url = next(c["url"] for c in requested_plan["components"] if c["name"] == web["name"])
        proof = await hub_integration.verify_business_app(url)
        if not proof.get("ok"):
            raise ValueError("Dev está desplegado pero su comprobación funcional no pasó.")
        return {"state": "ready", "app": web["name"], "branch": "develop", "environment": "dev", "url": url,
                "verified_commit": sha, "verification": proof, "components": requested_plan["components"]}
