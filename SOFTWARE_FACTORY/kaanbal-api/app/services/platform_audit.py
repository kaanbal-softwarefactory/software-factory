"""
Auditoría de la plataforma: lo que conviene ordenar o atender
=============================================================

Recorre el inventario (apps, vínculos, salud y respaldos) y devuelve hallazgos
con severidad, las apps involucradas y la acción que lo resuelve. Es puro: no
lee nada por su cuenta, así el MCP le pasa lo que el token puede ver y el test
le pasa un inventario inventado.

No cambia nada. Cada hallazgo nombra la herramienta que lo arregla para que el
agente proponga el cambio y una persona lo apruebe.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

ALTA, MEDIA, BAJA = "alta", "media", "baja"
BACKUP_MAX_AGE_DAYS = 7
_ORDER = {ALTA: 0, MEDIA: 1, BAJA: 2}


def _finding(code: str, severity: str, title: str, detail: str, apps: Iterable[str], fix: str) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "title": title, "detail": detail,
            "apps": sorted(set(apps)), "fix": fix}


def _distance(a: str, b: str) -> int:
    """Levenshtein: detecta 'stremingdogia' frente a 'streamingdogia'."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


DATABASE_TEMPLATES = ("postgres", "mongodb", "mysql", "redis")


def _variable_prefix(name: str) -> str:
    """El prefijo con el que Kaanbal nombra las variables de una base: comms-lab-db → COMMS_LAB_DB."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).upper()


def _stem(name: str) -> str:
    for suffix in ("-api", "-bd", "-db", "-backend", "-frontend", "-web"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def audit(apps: List[Mapping[str, Any]], links: List[Mapping[str, Any]], *,
          health: Optional[Mapping[str, Optional[str]]] = None,
          backups: Optional[Mapping[str, Any]] = None,
          variable_names: Optional[Mapping[str, Iterable[str]]] = None,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """apps: como list_apps; links: {from_app, to_app}; health: {app: estado}; backups: {app: fecha|None};
    variable_names: {app: nombres de sus variables} (nunca valores), para ver qué bases usa cada una."""
    now = now or datetime.now(timezone.utc)
    by_name = {app["name"]: app for app in apps}
    findings: List[Dict[str, Any]] = []

    # Piezas conectadas en grupos distintos: en la consola aparecen separadas.
    split = []
    for link in links:
        source, target = by_name.get(link.get("from_app")), by_name.get(link.get("to_app"))
        if source and target and (source.get("group") or None) != (target.get("group") or None):
            split.append((source["name"], source.get("group"), target["name"], target.get("group")))
    for source, source_group, target, target_group in split:
        findings.append(_finding(
            "group_split", MEDIA, f"{source} y {target} están conectadas pero en grupos distintos",
            f"{source} está en '{source_group or 'sin grupo'}' y {target} en '{target_group or 'sin grupo'}'. "
            "En la consola se ven como sistemas separados.",
            [source, target], f"set_app_group en la que corresponda, para que compartan grupo."))

    # Apps de un mismo sistema (mismo prefijo) repartidas en varios grupos.
    families: Dict[str, List[Mapping[str, Any]]] = {}
    for app in apps:
        families.setdefault(_stem(app["name"]), []).append(app)
    for stem, members in families.items():
        groups = {member.get("group") for member in members}
        if len(members) > 1 and len(groups) > 1 and not any(f["code"] == "group_split" and set(f["apps"]) <= {m["name"] for m in members} for f in findings):
            findings.append(_finding(
                "family_split", BAJA, f"Las piezas de '{stem}' están en varios grupos",
                f"Grupos: {', '.join(sorted(str(g or 'sin grupo') for g in groups))}.",
                [m["name"] for m in members], "set_app_group para reunirlas."))

    # Nombre y grupo casi iguales: probable error de escritura.
    for app in apps:
        group, stem = str(app.get("group") or ""), _stem(app["name"])
        if group and group != stem and len(stem) >= 6 and 0 < _distance(group, stem) <= 2:
            findings.append(_finding(
                "name_typo", BAJA, f"'{app['name']}' y su grupo '{group}' difieren por {_distance(group, stem)} letra(s)",
                "Parece un error de escritura. El nombre interno no se cambia (es la identidad en repo, DNS y Vault), "
                "pero el nombre visible sí.", [app["name"]],
                "set_display_name para el nombre visible, o set_app_group si el que está mal es el grupo."))

    without_group = [app["name"] for app in apps if not app.get("group")]
    if without_group:
        findings.append(_finding("no_group", BAJA, f"{len(without_group)} app(s) sin grupo",
                                 "Sin grupo, la consola no las ordena junto a sus piezas.", without_group,
                                 "set_app_group."))

    # Bases que nadie usa. Un vínculo registrado la usa; también una app que recibe <BASE>_URI (así llegan
    # las credenciales cuando la base se conectó al lanzar un stack, que no deja un vínculo en la lista).
    used = {link.get("to_app") for link in links}
    databases = {_variable_prefix(app["name"]): app["name"] for app in apps
                 if str(app.get("template") or "") in DATABASE_TEMPLATES}
    for consumer, names in (variable_names or {}).items():
        for variable in names or []:
            owner = databases.get(variable[:-4]) if variable.endswith("_URI") else None
            if owner and owner != consumer:
                used.add(owner)
    unchecked = (" No se pudieron leer los nombres de variables de las apps: una que la use sin vínculo "
                 "registrado aparecería aquí aunque esté en uso." if variable_names is None else "")
    for app in apps:
        if str(app.get("template") or "") in DATABASE_TEMPLATES and app["name"] not in used:
            findings.append(_finding(
                "orphan_database", MEDIA, f"{app['name']} no tiene ninguna app conectada",
                "Ocupa disco y memoria. Si una app la usa con credenciales copiadas a mano, conviene vincularla." + unchecked,
                [app["name"]], "link_apps desde la API que la usa, o delete_app si ya no sirve (con respaldo)."))

    # Respaldos.
    if backups is not None:
        for app in apps:
            if str(app.get("template") or "") not in ("postgres", "mongodb"):
                continue
            last = _parse(backups.get(app["name"]))
            if last is None:
                findings.append(_finding("no_backup", ALTA, f"{app['name']} nunca se respaldó",
                                         "Si se pierde el disco o alguien borra datos, no hay a qué volver.",
                                         [app["name"]], "backup_database."))
            elif now - last > timedelta(days=BACKUP_MAX_AGE_DAYS):
                findings.append(_finding("stale_backup", MEDIA, f"El último respaldo de {app['name']} tiene {(now - last).days} días",
                                         "Lo que cambió desde entonces se perdería.", [app["name"]], "backup_database."))

    # Estado.
    for app in apps:
        if app.get("status") == "error":
            findings.append(_finding("app_error", ALTA, f"{app['name']} quedó en error",
                                     "El alta o el último cambio falló.", [app["name"]], "diagnose_app."))
    for name, state in (health or {}).items():
        if name in by_name and state and state not in ("Healthy", "Progressing"):
            findings.append(_finding("unhealthy", ALTA, f"{name} no está sana ({state})",
                                     "ArgoCD la reporta con problemas.", [name], "diagnose_app."))

    unnamed = [app["name"] for app in apps if not app.get("display_name")]
    if unnamed and len(unnamed) == len(apps):
        findings.append(_finding("no_display_names", BAJA, "Ninguna app tiene nombre visible",
                                 "La consola muestra el nombre interno (minúsculas y guiones).", unnamed,
                                 "set_display_name en las que se muestran a clientes."))

    findings.sort(key=lambda f: (_ORDER[f["severity"]], f["code"], f["apps"]))
    counts = {severity: sum(1 for f in findings if f["severity"] == severity) for severity in (ALTA, MEDIA, BAJA)}
    return {"apps": len(apps), "links": len(links), "counts": counts, "findings": findings,
            "summary": ("Sin hallazgos." if not findings else
                        f"{len(findings)} hallazgo(s): {counts[ALTA]} alta, {counts[MEDIA]} media, {counts[BAJA]} baja.")}
