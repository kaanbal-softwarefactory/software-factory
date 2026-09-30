"""Kubernetes adapters for explicitly granted, disabled-by-default operations.

Host execution is root access. Only an elevated token plus an exact node grant
may reach it; no configuration is enabled by adding these adapters.
"""
from __future__ import annotations
import json
import time
from app.services.autonomy_policy import AutonomyError, resource_name, node_name

WORKSPACE_NAMESPACE = "kaanbal-workspaces"
HOST_NAMESPACE = "kaanbal-operations"
LABEL = "kaanbal-engine.io/workspace"
OUTPUT_LIMIT = 64 * 1024


def clients():
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.BatchV1Api()


def execute(namespace, pod, command, *, container, seconds=30, stdin="", limit=OUTPUT_LIMIT):
    from kubernetes.stream import stream
    core, _ = clients()
    ws = stream(core.connect_post_namespaced_pod_exec, pod, namespace,
                container=container, command=command, stderr=True, stdout=True,
                stdin=bool(stdin), tty=False, _preload_content=False)
    output, size, truncated = [], 0, False
    deadline = time.monotonic() + seconds + 10
    try:
        if stdin:
            for offset in range(0, len(stdin), 32768):
                if time.monotonic() >= deadline:
                    raise AutonomyError("Tiempo agotado enviando datos al contenedor.", 504)
                ws.write_stdin(stdin[offset:offset + 32768])
        while ws.is_open() and time.monotonic() < deadline:
            ws.update(timeout=1)
            for read in (ws.read_stdout, ws.read_stderr):
                chunk = read()
                if chunk:
                    remaining = max(0, limit - size)
                    output.append(chunk[:remaining])
                    size += len(chunk)
                    truncated = truncated or size > limit
        timed_out = ws.is_open()
        code = None if timed_out else ws.returncode
    finally:
        ws.close()
    return {"output": "".join(output), "exit_code": code, "timed_out": timed_out, "truncated": truncated}


def shell_command(command, seconds):
    return ["/bin/sh", "-c", 'command -v timeout >/dev/null || { echo "La imagen requiere timeout"; exit 125; }; exec timeout -k 5 "$1" /bin/sh -c "$2"', "kaanbal", str(seconds), command]


def app_execute(app, env, command, seconds):
    core, _ = clients()
    pods = core.list_namespaced_pod(resource_name(env), label_selector=f"app={resource_name(app)}").items
    candidates = [p for p in pods if p.status.phase == "Running" and not p.metadata.deletion_timestamp]
    if not candidates:
        raise AutonomyError("La app no tiene un pod en ejecución.")
    pod = sorted(candidates, key=lambda p: p.metadata.name)[0]
    containers = [c for c in pod.spec.containers if c.name == app]
    if not containers and len(pod.spec.containers) == 1:
        containers = pod.spec.containers
    if len(containers) != 1:
        raise AutonomyError("No se puede identificar inequívocamente el contenedor de la app.")
    result = execute(env, pod.metadata.name, shell_command(command, seconds), container=containers[0].name, seconds=seconds)
    return {"pod": pod.metadata.name, "container": containers[0].name, **result}


def workspace_manifest(name, image, lifetime):
    return {"apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "namespace": WORKSPACE_NAMESPACE, "labels": {LABEL: name}},
        "spec": {"automountServiceAccountToken": False, "restartPolicy": "Never", "activeDeadlineSeconds": lifetime,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001, "fsGroup": 10001, "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [{"name": "workbench", "image": image, "workingDir": "/workspace",
                "command": ["python", "-I", "-c", f"import time; time.sleep({lifetime})"],
                "env": [{"name": "HOME", "value": "/tmp"}, {"name": "GIT_TERMINAL_PROMPT", "value": "0"}],
                "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "2", "memory": "1Gi", "ephemeral-storage": "2Gi"}},
                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}, {"name": "tmp", "mountPath": "/tmp"}]}],
            "volumes": [{"name": "workspace", "emptyDir": {"sizeLimit": "1Gi"}}, {"name": "tmp", "emptyDir": {"sizeLimit": "512Mi"}}]}}


def create_workspace(name, image, lifetime):
    core, _ = clients()
    core.create_namespaced_pod(WORKSPACE_NAMESPACE, workspace_manifest(name, image, lifetime))


def workspace_phase(name):
    core, _ = clients()
    return core.read_namespaced_pod(name, WORKSPACE_NAMESPACE).status.phase


def remove_workspace(name):
    from kubernetes.client.exceptions import ApiException
    core, _ = clients()
    try:
        core.delete_namespaced_pod(name, WORKSPACE_NAMESPACE, grace_period_seconds=5)
    except ApiException as exc:
        if exc.status != 404:
            raise


def host_manifest(name, image, node, command, seconds):
    return {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": HOST_NAMESPACE},
        "spec": {"backoffLimit": 0, "activeDeadlineSeconds": seconds + 30, "ttlSecondsAfterFinished": 3600,
            "template": {"spec": {"nodeName": node_name(node), "hostPID": True,
                "automountServiceAccountToken": False, "restartPolicy": "Never",
                "containers": [{"name": "repair", "image": image,
                    "securityContext": {"privileged": True, "runAsUser": 0},
                    "command": ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "timeout", "-k", "5", str(seconds), "/bin/sh", "-c", command],
                    "resources": {"requests": {"cpu": "100m", "memory": "64Mi"}, "limits": {"cpu": "1", "memory": "256Mi"}}}]}}}}


def start_host(name, image, node, command, seconds):
    _, batch = clients()
    batch.create_namespaced_job(HOST_NAMESPACE, host_manifest(name, image, node, command, seconds))


def host_status(name):
    core, batch = clients()
    job = batch.read_namespaced_job(name, HOST_NAMESPACE)
    state = "succeeded" if job.status.succeeded else "failed" if job.status.failed else "running"
    pods = core.list_namespaced_pod(HOST_NAMESPACE, label_selector=f"job-name={name}").items
    output = ""
    if pods and pods[0].status.phase != "Pending":
        output = core.read_namespaced_pod_log(pods[0].metadata.name, HOST_NAMESPACE, limit_bytes=OUTPUT_LIMIT)
    return {"state": state, "output": output}


def workspace_python(name, script, payload, *, limit=4 * 1024 * 1024, seconds=60):
    result = execute(WORKSPACE_NAMESPACE, name, ["python", "-I", "-c", script], container="workbench",
                     stdin=json.dumps(payload) + "\n", seconds=seconds, limit=limit)
    if result["exit_code"] != 0 or result["truncated"]:
        raise AutonomyError("Falló la operación de archivos (límite, ruta, formato o proceso).", 422)
    try:
        return json.loads(result["output"])
    except ValueError:
        raise AutonomyError("Respuesta inválida del workbench.", 502)
