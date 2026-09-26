"""Bootstrap Shamir local. Secret-bearing commands never enter installer logs.

Recovery material is persisted BEFORE unseal. Restart recovery is explicit:
sudo python3 installer/vault_bootstrap.py --recover
This is not auto-unseal and never reinitializes an initialized Vault.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

RECOVERY_FILE = Path(os.environ.get("KAANBAL_VAULT_RECOVERY_FILE", "/etc/kaanbal/vault-recovery.json"))


def execute(args, input_text=None):
    try:
        proc = subprocess.run(["k3s", "kubectl", *args], input=input_text,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Vault: no se pudo ejecutar kubectl (sin mostrar credenciales)") from None
    return proc.returncode, proc.stdout


def save_recovery(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".vault-recovery-", dir=path.parent)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def bootstrap(run=execute, recovery_path=None, allow_init=True, timeout=120):
    path = Path(recovery_path or RECOVERY_FILE)
    deadline = time.monotonic() + timeout
    status = None
    while True:
        _, raw = run(["-n", "vault", "exec", "deploy/vault", "--", "vault", "status", "-format=json"])
        try:
            status = json.loads(raw)
        except (ValueError, TypeError):
            status = None
        if isinstance(status, dict) and "initialized" in status:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Vault no responde; no se declara la instalación operativa")
        time.sleep(2)

    material = None
    if path.exists():
        material = json.loads(path.read_text(encoding="utf-8"))
    if not status["initialized"]:
        if material or not allow_init:
            raise RuntimeError("Vault sin inicializar pero hay recuperación previa o modo recuperar; restaura sus datos, no generes nuevas claves")
        rc, raw = run(["-n", "vault", "exec", "deploy/vault", "--", "vault", "operator", "init",
                       "-key-shares=1", "-key-threshold=1", "-format=json"])
        if rc:
            raise RuntimeError("Vault init falló; revisa el estado antes de reintentar")
        material = json.loads(raw)
        # Persist even an unexpected response: never discard generated recovery data.
        save_recovery(material, path)
    elif not material:
        # Import only the former installer's secret; do not initialize again.
        rc, raw = run(["-n", "vault", "get", "secret", "vault-init-keys", "-o", "json"])
        if rc:
            raise RuntimeError("Vault ya inicializado: restaura vault-recovery.json desde tu respaldo protegido")
        data = json.loads(raw).get("data", {})
        material = {"root_token": base64.b64decode(data.get("root-token", "")).decode(),
                    "unseal_keys_b64": [base64.b64decode(data.get("unseal-key", "")).decode()]}
        save_recovery(material, path)

    root = material.get("root_token", "")
    keys = material.get("unseal_keys_b64") or material.get("unseal_keys") or []
    if not root or not keys or not all(keys):
        raise RuntimeError("Recuperación de Vault incompleta; conserva el archivo y restaura las claves originales")
    if status.get("sealed") or not status["initialized"]:
        for key in keys:
            # The local process arguments and logs contain no unseal key.
            rc, _ = run(["-n", "vault", "exec", "-i", "deploy/vault", "--", "sh", "-c",
                         'read -r key; vault operator unseal "$key"'], key + "\n")
            if rc:
                raise RuntimeError("Vault no pudo desbloquearse; recuperación conservada, instalación detenida")
    rc, raw = run(["-n", "vault", "exec", "deploy/vault", "--", "vault", "status", "-format=json"])
    if rc or json.loads(raw).get("sealed", True):
        raise RuntimeError("Vault continúa sellado; no se declara éxito")

    # Token travels over stdin, never a logged command or local argv.
    prefix = ["-n", "vault", "exec", "-i", "deploy/vault", "--", "sh", "-c"]
    rc, raw = run(prefix + ['read -r VAULT_TOKEN; export VAULT_TOKEN; vault secrets list -format=json'], root + "\n")
    if rc:
        raise RuntimeError("Vault desbloqueado, pero el token de recuperación no autoriza la configuración")
    mounts = json.loads(raw)
    if "secret/" not in mounts:
        rc, _ = run(prefix + ['read -r VAULT_TOKEN; export VAULT_TOKEN; vault secrets enable -path=secret kv-v2'], root + "\n")
        if rc:
            raise RuntimeError("No se pudo habilitar KV v2 en Vault")
    elif mounts["secret/"].get("type") != "kv" or str(mounts["secret/"].get("options", {}).get("version")) != "2":
        raise RuntimeError("Vault secret/ no es KV v2; no se modifica un almacén existente")
    return root


def auto_unseal(run=execute, recovery_path=None):
    """Desbloqueo tras reinicio, pensado para un timer de systemd. Devuelve un mensaje o None.

    Vault se sella en cada reinicio del nodo. Si nadie lo desbloquea, los
    despliegues no pueden guardar secretos. Este modo es silencioso cuando no
    hay nada que hacer (Vault abierto o todavía arrancando) y nunca inicializa:
    un Vault sin inicializar requiere una decisión humana, no un timer.

    Sobre la seguridad: la llave ya vive en este mismo disco (RECOVERY_FILE, 600
    root). Desbloquear automáticamente no la expone más de lo que ya está; lo que
    sí evita es que cada reinicio deje la plataforma a medias.
    """
    _, raw = run(["-n", "vault", "exec", "deploy/vault", "--", "vault", "status", "-format=json"])
    try:
        status = json.loads(raw)
    except (ValueError, TypeError):
        return None  # Vault aún no arranca tras el reinicio; el timer reintenta
    if not status.get("initialized") or not status.get("sealed"):
        return None
    path = Path(recovery_path or RECOVERY_FILE)
    if not path.exists():
        raise RuntimeError("Vault está sellado y no hay archivo de recuperación en este nodo")
    bootstrap(run=run, recovery_path=path, allow_init=False, timeout=60)
    return "Vault estaba sellado tras un reinicio: desbloqueado. No se generaron claves nuevas."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Desbloquear Vault con la recuperación local protegida; no imprime claves")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--recover", action="store_true", help="Desbloqueo manual con verificación completa")
    mode.add_argument("--auto", action="store_true", help="Solo si está sellado; silencioso si no hay nada que hacer")
    args = parser.parse_args()
    try:
        if args.auto:
            message = auto_unseal()
            if message:
                print(message)
            raise SystemExit(0)
        bootstrap(allow_init=False)
        print("Vault desbloqueado y KV v2 comprobado. No se generaron claves nuevas.")
    except Exception as exc:
        # Avoid printing malformed JSON/secret-bearing exceptions.
        print(str(exc) if isinstance(exc, RuntimeError) else "Recuperación fallida; comprueba el archivo protegido y el estado de Vault")
        raise SystemExit(1)
