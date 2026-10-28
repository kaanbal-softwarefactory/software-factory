"""Private provider capture for managed Business Base, without Git literals.

Credential material follows the existing Vault/immutable runtime Secret path.
The descriptor committed to Git contains only a Secret reference and does not
enable external delivery or change the database/identity Secret.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from app.services import app_variables, business_deployer


def credential_name(app_name, value):
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,45}", app_name):
        raise app_variables.VariableError("Nombre de aplicación gestionada inválido.")
    digest = hashlib.sha256((app_name + "\0" + value).encode()).hexdigest()[:12]
    return f"{app_name[:37]}-smtp-{digest}"


def descriptor(app_name, value):
    return {"provider": "sendgrid", "secret_name": f"{credential_name(app_name, value)}-secrets",
            "secret_key": "SENDGRID_API_KEY", "delivery_enabled": False}


def plan_descriptor(current, wanted, overwrite=False):
    if current == wanted:
        return app_variables.UNCHANGED
    if current and not overwrite:
        raise app_variables.VariableError("Ya existe una credencial SMTP. Para rotarla, confirma reemplazarla.")
    return app_variables.UPDATED if current else app_variables.CREATED


async def store_credential(deployer, app_name, variable, value, environments, *, overwrite=False):
    if variable != "SENDGRID_API_KEY":
        raise app_variables.VariableError(
            "Business Base usa conexiones gestionadas: las variables genéricas no pueden reemplazar sus secretos. "
            "La captura privada de proveedor admite SENDGRID_API_KEY.")
    if environments != ["prod"]:
        raise app_variables.VariableError("Business Base admite solo el ambiente prod.")
    if not value or len(value) > 4096 or any(c.isspace() for c in value):
        raise app_variables.VariableError("Credencial SMTP vacía o inválida.")
    wanted = descriptor(app_name, value)
    await deployer._load_credentials()
    try:
        with tempfile.TemporaryDirectory(prefix="provider-secret-", dir=deployer.workspace) as directory:
            infra = Path(directory) / "infra-gitops"
            await asyncio.to_thread(subprocess.run,
                ["git", "clone", deployer.provider.get_auth_clone_url("infra-gitops"), str(infra)],
                check=True, capture_output=True)
            overlay = infra / "apps" / app_name / "overlays" / "prod"
            if not (overlay / "kustomization.yaml").is_file():
                raise app_variables.VariableError("No existe el overlay gestionado de la aplicación.")
            target = overlay / "provider-credential.json"
            current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
            state = plan_descriptor(current, wanted, overwrite)

            async def generate():
                return {"SENDGRID_API_KEY": value}

            # Separate provider path: never read/overwrite database credentials.
            name = credential_name(app_name, value)
            values = await business_deployer._vault_credentials(
                deployer, f"{app_name}/providers/sendgrid/{name}", generate)
            if values != {"SENDGRID_API_KEY": value}:
                raise app_variables.VariableError("La referencia de proveedor no coincide. No se sobrescribieron secretos.")
            await asyncio.to_thread(business_deployer.materialize_secret, name, values)
            if state != app_variables.UNCHANGED:
                target.write_text(json.dumps(wanted, indent=2) + "\n", encoding="utf-8")
                await deployer._push_infra(str(infra), app_name, ["prod"],
                    message=f"fix({app_name}): referencia privada del proveedor de correo")
            return {"app": app_name, "variable": variable, "environments": {"prod": state},
                    "committed": state != app_variables.UNCHANGED,
                    "storage": "vault_runtime_secret", "credential_reference": wanted,
                    "message": "Credencial guardada en Vault y Secret runtime; el envío externo requiere conectar identidad y worker."}
    except app_variables.VariableError:
        raise
    except Exception:
        # Provider/Kubernetes exceptions may embed request bodies or clone credentials.
        raise app_variables.VariableError(
            "No se completó la captura privada. Revisa Vault, permisos de secretos y GitOps. "
            "No se publicaron valores ni se reemplazaron credenciales del sistema.") from None
