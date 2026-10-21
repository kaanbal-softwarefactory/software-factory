"""Read-only contract for the managed Business Base candidate.

Names here describe the deployed template, not values or a runtime inspection.
The legacy overlay inventory does not see this template's secretKeyRef bindings.
"""

TEMPLATES = {"business-base", "business-postgres", "business-identity"}
DATABASE = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
WEB = DATABASE + ["APP_ORIGIN", "OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET",
                  "PUBLIC_ORGANIZATION", "PUBLIC_REGISTRATION", "CONTACT_NOTIFICATION_EMAIL"]
WORKER = DATABASE + ["SMTP_HOST", "SMTP_PORT", "SMTP_FROM"]
BOOTSTRAP = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "MIGRATION_PGUSER", "MIGRATION_PGPASSWORD",
             "BUSINESS_PROFILE", "APP_ORIGIN", "OIDC_ISSUER", "BUSINESS_NAME", "BUSINESS_PRESET",
             "BUSINESS_INTERNAL_APP", "IDENTITY_ADMIN_ORIGIN", "IDENTITY_ADMIN_PASSWORD",
             "OIDC_CLIENT_SECRET", "OWNER_PASSWORD", "CUSTOMER_PASSWORD", "SMTP_HOST"]
IDENTITY = ["KC_DB", "KC_DB_URL", "KC_DB_USERNAME", "KC_DB_PASSWORD", "KC_HOSTNAME",
            "KC_HTTP_ENABLED", "KC_PROXY_HEADERS", "KC_HEALTH_ENABLED",
            "KC_BOOTSTRAP_ADMIN_USERNAME", "KC_BOOTSTRAP_ADMIN_PASSWORD"]
POSTGRES = ["PGDATA", "POSTGRES_PASSWORD", "RUNTIME_PASSWORD", "MIGRATION_PASSWORD", "IDENTITY_PASSWORD"]


def describe(template, name):
    if template not in TEMPLATES:
        return None
    base = name
    if template == "business-postgres" and name.endswith("-db"):
        base = name[:-3]
    elif template == "business-identity" and name.endswith("-identity"):
        base = name[:-9]
    processes = ({"web": WEB, "worker": WORKER, "bootstrap": BOOTSTRAP} if template == "business-base" else
                 {"identity": IDENTITY} if template == "business-identity" else {"postgres": POSTGRES})
    process = {"business-base": "web", "business-postgres": "postgres", "business-identity": "identity"}[template]
    return {
        "profile": "business-base-demo", "stage": "beta", "environment_names_source": "declared_contract",
        "runtime_inventory_verified": False,
        "environment_by_process": {p: sorted(names) for p, names in processes.items()},
        "primary_process": process,
        "components": {"app": base, "database": f"{base}-db", "identity": f"{base}-identity",
                       "worker": f"{base}-worker", "mail_capture": f"{base}-mail"},
        "connections": [
            {"from": "web", "to": "database", "database": "business", "role": "business_runtime"},
            {"from": "worker", "to": "database", "database": "business", "role": "business_runtime"},
            {"from": "bootstrap", "to": "database", "database": "business", "role": "business_migrator"},
            {"from": "identity", "to": "database", "database": "identity", "role": "business_identity"},
            {"from": "web", "to": "identity", "protocol": "OIDC Authorization Code + PKCE"},
        ],
        "email": {"mode": "capture", "external_delivery": False, "consumers": ["identity", "worker"],
                  "note": "SMTP real aún requiere un perfil gestionado para ambos procesos; no basta agregar una variable a la web."},
        "ownership": {"source": "authenticated_kaanbal_user", "existing_group_owner_preserved": True,
                      "scope": "Responsable del grupo; no concede roles de negocio ni acceso al repositorio GitHub."},
        "rules": [
            "Lanza este conjunto con launch_stack(stack='business-base-demo'); las conexiones y callbacks se generan juntos.",
            "El usuario autenticado del token MCP es el responsable inicial de un grupo nuevo; el cliente no elige otra identidad.",
            "Las cuentas ficticias owner/customer de la demo son distintas del responsable de Kaanbal.",
            "No uses link_apps, repair_db_bindings ni variables genéricas para reemplazar conexiones gestionadas de este stack.",
            "Web y worker usan business_runtime; credenciales de migración/administración solo en bootstrap.",
            "Mantén OIDC/PKCE, validación de membresías, evidencia MFA y RLS; no identifiques cuentas solo por correo.",
            "Los secretos viven en Vault y Secret references; nunca en Git, frontend, chat ni .env compartidos.",
            "Crea migraciones SQL nuevas expand/contract; el init container las aplica, las consultas HTTP no ejecutan DDL.",
            "Otra copia necesita nombre nuevo; conserva los datos al detenerla. No hay actualización automática de copias.",
            "Detener la web no detiene automáticamente worker, identidad o base; este candidato no tiene pausa conjunta.",
        ],
    }


def local_steps(template, name):
    if template != "business-base":
        return ["Trabaja desde el repositorio de la app Business Base del mismo grupo; su Compose local incluye identidad y base aisladas."]
    return [
        "Clona el campo repository de este contrato, con acceso propio de GitHub, y entra en la carpeta.",
        "Requisitos: Node.js 24 y Docker con Compose; ejecuta npm ci.",
        f"npm run local:up -- --name {name}-local  # por defecto app 3100, identidad 8180, correo 8125",
        "Para varios proyectos usa --port, --identity-port y --mail-port diferentes desde el primer arranque; no cambies los puertos de uno ya inicializado.",
        f"npm run local:access -- --name {name}-local  # solo en tu terminal; no envíes las credenciales al agente",
        "Edita app/ y components/ para pantallas, lib/ para reglas y migrations/ para cambios de datos.",
        "npm test && npm run build; repite local:up con los mismos argumentos para reconstruir lo modificado.",
        "Publica una rama y abre PR. Integrar main ejecuta CI y despliega esta copia; no modifica las otras.",
    ]
