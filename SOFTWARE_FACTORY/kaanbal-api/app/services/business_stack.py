"""Business Base candidate: GitOps resources with separate process credentials.

This is an opt-in demo profile, not the local Compose/start-dev profile. Values
never enter Git: the provisioning path persists them in Vault and Kubernetes.
"""
import re
import json
from pathlib import Path

TEMPLATES = {"business-postgres", "business-identity", "business-base"}
SECRET_KEYS = {
    "business-postgres": ["POSTGRES_PASSWORD", "RUNTIME_PASSWORD", "MIGRATION_PASSWORD", "IDENTITY_PASSWORD"],
    "business-identity": ["KC_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD", "OIDC_CLIENT_SECRET", "OWNER_PASSWORD", "CUSTOMER_PASSWORD"],
    "business-base": ["PGPASSWORD", "MIGRATION_PGPASSWORD", "IDENTITY_ADMIN_PASSWORD", "OIDC_CLIENT_SECRET", "OWNER_PASSWORD", "CUSTOMER_PASSWORD"],
}


def normalize_modules(preset, selected=None):
    available = ["contact", "catalog", "appointments"]
    if selected is None:
        selected = ["contact"] if preset == "starter" else available
    if not isinstance(selected, list) or any(module not in available for module in selected):
        raise ValueError("Módulos Business Base desconocidos.")
    chosen = set(selected)
    if "appointments" in chosen:
        chosen.add("catalog")
    return [module for module in available if module in chosen]


def validate_config(template, config, environments):
    if template not in TEMPLATES:
        return
    if environments != ["prod"]:
        raise ValueError("Business Base candidato usa solo prod; crea otro nombre para una copia aislada.")
    if config.get("BUSINESS_PROFILE") != "demo":
        raise ValueError("Selecciona el stack Business Base demo: este candidato requiere su contrato completo.")
    for key in ("BUSINESS_DB_APP", "BUSINESS_IDENTITY_APP", "BUSINESS_APP"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,45}", str(config.get(key, ""))):
            raise ValueError(f"Falta un nombre válido en {key}.")
    if config.get("BUSINESS_PRESET", "services") not in ("starter", "services", "barber"):
        raise ValueError("Preset Business Base desconocido.")
    normalize_modules(config.get("BUSINESS_PRESET", "services"), config.get("BUSINESS_MODULES"))
    base = config["BUSINESS_APP"]
    if config["BUSINESS_DB_APP"] != f"{base}-db" or config["BUSINESS_IDENTITY_APP"] != f"{base}-identity":
        raise ValueError("Las dependencias de Business Base deben pertenecer al mismo sistema.")


def _resource(kind, name, spec=None, **fields):
    api = {"Deployment": "apps/v1", "Job": "batch/v1", "NetworkPolicy": "networking.k8s.io/v1", "Ingress": "networking.k8s.io/v1"}.get(kind, "v1")
    result = {"apiVersion": api, "kind": kind, "metadata": {"name": name}, **fields}
    if spec is not None:
        result["spec"] = spec
    return result


def _env(values, secret, keys):
    return ([{"name": k, "value": str(v)} for k, v in values.items()] +
            [{"name": k, "valueFrom": {"secretKeyRef": {"name": secret, "key": k}}} for k in keys])


def _container(name, image, env=None, command=None, port=None):
    result = {"name": name, "image": image, "env": env or [],
              "resources": {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"cpu": "1000m", "memory": "768Mi"}}}
    if command:
        result["command"] = command
    if port:
        result["ports"] = [{"containerPort": port}]
    return result


def _deployment(name, container, *, volumes=None, init=None, annotations=None, strategy=None):
    pod = {"automountServiceAccountToken": False, "containers": [container]}
    if init and volumes:
        pod["securityContext"] = {"fsGroup": 1000}
    if volumes:
        pod["volumes"] = volumes
    if init:
        pod["initContainers"] = init
    return _resource("Deployment", name, {
        "replicas": 1, "strategy": strategy or {"type": "RollingUpdate"},
        "selector": {"matchLabels": {"app": name}},
        "template": {"metadata": {"labels": {"app": name}, "annotations": annotations or {}}, "spec": pod},
    })


def _service(name, port):
    return _resource("Service", name, {"selector": {"app": name}, "ports": [{"name": "http" if port != 5432 else "postgres", "port": port, "targetPort": port}]})


def _probe(path, port):
    return {"httpGet": {"path": path, "port": port}, "periodSeconds": 5, "timeoutSeconds": 3, "failureThreshold": 60}


def render(template, name, config, *, domain, image, ingress_class="traefik", cluster_issuer=""):
    """Return Kubernetes objects without any credential values."""
    validate_config(template, config, ["prod"])
    db, identity, web = (config[k] for k in ("BUSINESS_DB_APP", "BUSINESS_IDENTITY_APP", "BUSINESS_APP"))
    secret = f"{name}-secrets"
    app_origin = f"https://{domain}" if config.get("use_root_domain") else f"https://{web}.{domain}"
    issuer = f"https://{identity}.{domain}/realms/business"
    docs = []
    if template == "business-postgres":
        # psql's quoted variables handle passwords without string-built SQL.
        script = """#!/bin/sh
set -eu
psql -U postgres -d postgres --set ON_ERROR_STOP=1 <<'SQL'
\\set runtime_password `printf %s "$RUNTIME_PASSWORD"`
\\set migration_password `printf %s "$MIGRATION_PASSWORD"`
\\set identity_password `printf %s "$IDENTITY_PASSWORD"`
CREATE ROLE business_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'runtime_password';
CREATE ROLE business_migrator LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'migration_password';
CREATE ROLE business_identity LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'identity_password';
CREATE DATABASE business OWNER business_migrator;
CREATE DATABASE identity OWNER business_identity;
REVOKE ALL ON DATABASE business FROM PUBLIC;
GRANT CONNECT ON DATABASE business TO business_runtime;
REVOKE ALL ON DATABASE identity FROM PUBLIC;
SQL
"""
        docs += [_resource("ConfigMap", f"{name}-init", data={"01-business.sh": script}),
                 _resource("PersistentVolumeClaim", f"{name}-data", {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "5Gi"}}})]
        docs[-1]["metadata"]["annotations"] = {"argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}
        c = _container(name, "postgres:16.14-alpine", _env({"PGDATA": "/var/lib/postgresql/data/pgdata"}, secret, SECRET_KEYS[template]), port=5432)
        c["volumeMounts"] = [{"name": "data", "mountPath": "/var/lib/postgresql/data"}, {"name": "init", "mountPath": "/docker-entrypoint-initdb.d", "readOnly": True}]
        c["readinessProbe"] = {"exec": {"command": ["pg_isready", "-U", "postgres"]}, "periodSeconds": 5}
        docs += [_deployment(name, c, volumes=[{"name": "data", "persistentVolumeClaim": {"claimName": f"{name}-data"}}, {"name": "init", "configMap": {"name": f"{name}-init"}}], strategy={"type": "Recreate"}), _service(name, 5432)]
    elif template == "business-identity":
        c = _container(name, "quay.io/keycloak/keycloak:26.6.3", _env({
            "KC_DB": "postgres", "KC_DB_URL": f"jdbc:postgresql://{db}:5432/identity", "KC_DB_USERNAME": "business_identity",
            "KC_HOSTNAME": f"https://{identity}.{domain}", "KC_HTTP_ENABLED": "true", "KC_PROXY_HEADERS": "xforwarded",
            "KC_HEALTH_ENABLED": "true", "KC_BOOTSTRAP_ADMIN_USERNAME": "business-bootstrap",
        }, secret, ["KC_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD"]), command=["/opt/keycloak/bin/kc.sh", "start"], port=8080)
        c["resources"] = {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "1500m", "memory": "1536Mi"}}
        c["startupProbe"] = _probe("/health/ready", 9000)
        c["readinessProbe"] = _probe("/health/ready", 9000)
        docs += [_deployment(name, c), _service(name, 8080)]
    else:
        common = {"PGHOST": db, "PGPORT": "5432", "PGDATABASE": "business", "PGUSER": "business_runtime"}
        runtime = {**common, "APP_ORIGIN": app_origin, "OIDC_ISSUER": issuer, "OIDC_CLIENT_ID": "business-base",
                   "PUBLIC_ORGANIZATION": "demo", "PUBLIC_REGISTRATION": "true", "CONTACT_NOTIFICATION_EMAIL": "team@example.com"}
        migration = {**common, "BUSINESS_PROFILE": "demo", "MIGRATION_PGUSER": "business_migrator", "APP_ORIGIN": app_origin,
                     "OIDC_ISSUER": issuer, "BUSINESS_NAME": config.get("BUSINESS_NAME") or web,
                     "BUSINESS_PRESET": config.get("BUSINESS_PRESET", "services"),
                     "BUSINESS_MODULES": json.dumps(normalize_modules(config.get("BUSINESS_PRESET", "services"), config.get("BUSINESS_MODULES"))),
                     "IDENTITY_ADMIN_ORIGIN": f"http://{identity}:8080", "BUSINESS_INTERNAL_APP": web, "SMTP_HOST": f"{web}-mail"}
        initialize = _container("initialize", image, _env(migration, secret, ["MIGRATION_PGPASSWORD", "IDENTITY_ADMIN_PASSWORD", "OIDC_CLIENT_SECRET", "OWNER_PASSWORD", "CUSTOMER_PASSWORD"]),
                                command=["sh", "-c", "npm run migrate && node scripts/provision-identity.mjs && npx tsx scripts/seed.ts"])
        initialize["volumeMounts"] = [{"name": "bootstrap", "mountPath": "/bootstrap"}]
        web_c = _container(name, image, _env(runtime, secret, ["PGPASSWORD", "OIDC_CLIENT_SECRET"]), port=3000)
        web_c["startupProbe"] = _probe("/api/ready", 3000)
        web_c["readinessProbe"] = _probe("/api/ready", 3000)
        web_c["livenessProbe"] = _probe("/api/health", 3000)
        web_c["securityContext"] = {"runAsNonRoot": True, "runAsUser": 1000, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}
        docs += [_deployment(name, web_c, init=[initialize], volumes=[{"name": "bootstrap", "emptyDir": {}}]), _service(name, 3000)]
        # Wait for the migrated schema/identity initialization, not just a process port.
        wait = _container("wait", image, command=["node", "--input-type=module", "-e", f"const u='http://{web}:3000/api/ready'; for(let i=0;i<120;i++){{try{{if((await fetch(u)).ok)process.exit(0)}}catch{{}} await new Promise(r=>setTimeout(r,5000))}} process.exit(1)"])
        worker = _container("worker", image, _env({**common, "SMTP_HOST": f"{web}-mail", "SMTP_PORT": "1025", "SMTP_FROM": "notifications@example.com"}, secret, ["PGPASSWORD"]), command=["npm", "run", "worker"])
        docs += [_deployment(f"{web}-worker", worker, init=[wait]),
                 _deployment(f"{web}-mail", _container("mail", "axllent/mailpit:v1.27.8", port=1025)), _service(f"{web}-mail", 1025)]
        # SMTP deliberately captured internally for this demo. Never a public inbox.
    if template != "business-postgres":
        host = f"{identity}.{domain}" if template == "business-identity" else app_origin.removeprefix("https://")
        path = "/realms/" if template == "business-identity" else "/"
        ing = _resource("Ingress", name, {"ingressClassName": ingress_class, "rules": [{"host": host, "http": {"paths": [{"path": path, "pathType": "Prefix", "backend": {"service": {"name": name, "port": {"number": 8080 if template == "business-identity" else 3000}}}}]}}]})
        if cluster_issuer:
            ing["metadata"]["annotations"] = {"cert-manager.io/cluster-issuer": cluster_issuer}
            ing["spec"]["tls"] = [{"hosts": [host], "secretName": f"{name}-tls"}]
        if template == "business-identity":
            import copy
            assets = copy.deepcopy(ing["spec"]["rules"][0]["http"]["paths"][0])
            assets["path"] = "/resources/"
            ing["spec"]["rules"][0]["http"]["paths"].append(assets)
        docs.append(ing)
    # Default-deny incoming traffic to this system. HTTP only from ingress,
    # internal dependencies only from its sibling components in the namespace.
    siblings = [db, identity, web, f"{web}-worker", f"{web}-mail"]
    selected = [name, f"{web}-worker", f"{web}-mail"] if template == "business-base" else [name]
    rules = [{"from": [{"podSelector": {"matchExpressions": [{"key": "app", "operator": "In", "values": siblings}]}}]}]
    if template != "business-postgres":
        rules.append({"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}, {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}], "ports": [{"protocol": "TCP", "port": 8080 if template == "business-identity" else 3000}]})
    docs.append(_resource("NetworkPolicy", f"{name}-incoming", {"podSelector": {"matchExpressions": [{"key": "app", "operator": "In", "values": selected}]}, "policyTypes": ["Ingress"], "ingress": rules}))
    return docs


def write_overlay(root, template, name, config, *, domain, dockerhub_user, ingress_class="traefik", cluster_issuer=""):
    import yaml
    target = Path(root) / "apps" / name
    base = target / "base"
    overlay = target / "overlays" / "prod"
    base.mkdir(parents=True, exist_ok=True)
    overlay.mkdir(parents=True, exist_ok=True)
    image = "business-base-image:pending"
    documents = render(template, name, config, domain=domain, image=image, ingress_class=ingress_class, cluster_issuer=cluster_issuer)
    (base / "resources.yaml").write_text(yaml.safe_dump_all(documents, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (base / "kustomization.yaml").write_text("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - resources.yaml\n", encoding="utf-8")
    kust = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "namespace": "prod", "resources": ["../../base"]}
    if template == "business-base":
        kust["images"] = [{"name": image, "newName": f"{dockerhub_user}/{name}", "newTag": "pending-initial-build"}]
    (overlay / "kustomization.yaml").write_text(yaml.safe_dump(kust, sort_keys=False), encoding="utf-8")
