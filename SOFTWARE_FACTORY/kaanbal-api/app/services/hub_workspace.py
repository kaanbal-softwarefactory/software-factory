"""Compact project context shared by people and agents; no provider credentials."""
from collections import Counter
from typing import Any, Mapping

PLATFORM_GROUP = "software-factory"
PLATFORM_NAME = "Software Factory · Mejorar Kaanbal"
PLATFORM_DESCRIPTION = "Fricciones, propuestas y trabajo del núcleo de Kaanbal. Su actualización se aplica manualmente."

DELIVERY_LABELS = {
    "reviewed": "Código revisado", "checking": "Comprobando CI", "merged": "Código integrado",
    "deploying": "Desplegando", "deployed": "Desplegado; falta prueba funcional",
    "verified": "Verificado en el ambiente", "blocked": "Integración bloqueada",
    "deploy_failed": "Despliegue fallido", "deploy_unknown": "Despliegue sin confirmar",
}


def delivery(task: Mapping[str, Any]) -> dict:
    record = task.get("integration") or {}
    state = record.get("state") or ("reviewed" if task.get("status") == "done" else task.get("status"))
    return {"task": task.get("key") or task.get("_id"), "title": task.get("title"),
            "state": state, "label": DELIVERY_LABELS.get(state, state),
            "environment": record.get("environment"), "branch": record.get("base") or task.get("branch"),
            "commit": record.get("sha"), "url": record.get("url"), "at": record.get("at"),
            "detail": record.get("detail"), "verification": record.get("verification")}


def snapshot(project, tasks, sessions, events, checkpoints, *, now):
    """Bounded, deterministic overview; done never implies visible or deployed."""
    from app.services import agent_hub as hub
    settings = hub.work_settings(project.get("settings"))
    objective = hub.objective_progress(tasks, settings)
    people = {}
    for session in sessions:
        item = hub.public_session(session, now)
        person = item.get("person") or "Sin persona"
        people.setdefault(person, {"person": person, "sessions": [], "active": 0})
        people[person]["sessions"].append(item)
        if item["presence"] in ("online", "idle"):
            people[person]["active"] += 1
    deliveries = [delivery(t) for t in tasks if t.get("status") == "done" or t.get("integration")]
    counts = Counter(d["state"] for d in deliveries)
    decisions = [hub.compact_event(e) for e in events if e.get("kind") in ("decision", "blocker", "handoff")][:5]
    return {"as_of": now, "objective": objective,
            "headline": (f"{objective['done']}/{objective['total']} tareas revisadas del objetivo"
                         if objective["total"] else "Define un objetivo o incorpora las fases del proyecto"),
            "delivery_counts": dict(counts), "deliveries": deliveries[-20:],
            "people": list(people.values()), "decisions": decisions,
            "checkpoints": [{k: c.get(k) for k in ("agent", "person", "summary", "decisions", "next_steps", "updated_at")}
                            for c in checkpoints[:8]],
            "next_steps": (["Promover a producción es un paso explícito; no mueve los datos de Dev."]
                           if counts.get("verified") else
                           ["El código revisado todavía necesita integrarse, desplegarse y comprobarse en Dev."]),
            "platform": {"group": PLATFORM_GROUP, "name": PLATFORM_NAME},
            "conversation_notice": "Se comparten resúmenes, decisiones y relevos. El Hub no recibe automáticamente el chat privado del agente."}


def service_cards(apps, default_domain=""):
    from app.services.domain_service import public_host
    rows = []
    for app in apps:
        domain = app.get("domain") or default_domain
        if not isinstance(domain, str):
            domain = default_domain
        envs = app.get("environments") or ["prod"]
        urls = {}
        for env in envs:
            exposure = app.get("exposure") or "public"
            if isinstance(exposure, dict):
                exposure = (exposure.get("per_env") or {}).get(env, exposure.get("type", "public"))
            exposure = (app.get("env_exposure") or {}).get(env, exposure)
            if domain and exposure != "internal" and app.get("category") != "database" and app.get("template") != "business-postgres":
                urls[env] = "https://" + public_host(app["name"], env, domain)
        rows.append({"name": app["name"], "display_name": app.get("display_name") or app["name"],
                     "template": app.get("template"), "category": app.get("category"),
                     "status": app.get("status"), "environments": envs, "urls": urls,
                     "repo_url": app.get("repo_url")})
    return rows
