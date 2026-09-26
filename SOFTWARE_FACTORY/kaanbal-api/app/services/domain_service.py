"""
Domain Service — multi-dominio (BLUEPRINT RFC-0001 §3.1)
=======================================================
Resuelve el dominio efectivo de una app y provisiona dominios adicionales en
Cloudflare.

El instalador deja un solo dominio cableado de punta a punta: un tunel con
reglas `*.dominio -> Traefik`, DNS wildcard + raiz apuntando a
`<tunnel>.cfargotunnel.com` y el zone_id guardado en `system_config`. Registrar
un segundo dominio exige repetir ese cableado, no solo insertar el documento:
por eso `provision()` **agrega** reglas al tunel existente en lugar de
sobrescribir su configuracion.
"""

import ipaddress
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.db import get_db

logger = logging.getLogger(__name__)

CF_API = "https://api.cloudflare.com/client/v4"
TRAEFIK_SERVICE = "http://traefik.kube-system.svc.cluster.local:80"


TUNNEL_SUFFIX = ".cfargotunnel.com"


class DomainError(Exception):
    """Fallo de validacion o provision de un dominio."""


async def _records(client: httpx.AsyncClient, token: str, zone_id: str, name: str) -> List[Dict[str, Any]]:
    resp = await client.get(
        f"{CF_API}/zones/{zone_id}/dns_records?name={name}", headers=_headers(token),
    )
    return resp.json().get("result", []) if resp.status_code == 200 else []


def _points_to_tunnel(record: Dict[str, Any]) -> bool:
    return record.get("type") == "CNAME" and str(record.get("content") or "").endswith(TUNNEL_SUFFIX)


# Rangos publicados por Cloudflare (https://www.cloudflare.com/ips-v4 y -v6,
# consultados 2026-09-22). Cambian muy rara vez.
_CLOUDFLARE_NETWORKS = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
)]


def _is_stale_import(record: Dict[str, Any]) -> bool:
    """A/AAAA que apunta a la propia red de Cloudflare: un resto de importación.

    Cuando un dominio que ya vivía en otra cuenta de Cloudflare se agrega a esta,
    el escaneo inicial importa lo que resolvía en público, que eran las IPs del
    proxy de la cuenta anterior. Esas IPs nunca son un origen válido (Cloudflare
    responde error 1000 si se usan como tal), así que reemplazarlas no puede
    tumbar ningún sitio real. Caso real: dev-morgan.space.
    """
    if record.get("type") not in ("A", "AAAA"):
        return False
    try:
        ip = ipaddress.ip_address(str(record.get("content") or ""))
    except ValueError:
        return False
    return any(ip in net for net in _CLOUDFLARE_NETWORKS)


def _describe(records: List[Dict[str, Any]]) -> str:
    return ", ".join(f"{r.get('type')} {r.get('content')}" for r in records)


async def dns_conflicts(client: httpx.AsyncClient, token: str, zone_id: str, fqdn: str) -> Dict[str, Any]:
    """Registros en la raiz y el wildcard que apuntan a algo que no es un tunel.

    Al agregar una zona, Cloudflare importa el DNS que tenia el registrador. Un
    A en la raiz hacia el hosting es lo normal, y Cloudflare rechaza un CNAME en
    un nombre que ya tiene A/AAAA/CNAME (codigo 81053).
    """
    def foreign(records):
        return [r for r in records if r.get("type") in ("A", "AAAA", "CNAME")
                and not _points_to_tunnel(r) and not _is_stale_import(r)]

    def stale(records):
        return [r for r in records if _is_stale_import(r)]

    wildcard = await _records(client, token, zone_id, f"*.{fqdn}")
    apex = await _records(client, token, zone_id, fqdn)
    return {
        # Conflictos reales: apuntan a un servidor que puede estar sirviendo algo.
        "wildcard": foreign(wildcard),
        "apex": foreign(apex),
        # Restos de importación: apuntan a la red de Cloudflare, se reemplazan.
        "stale": {"wildcard": stale(wildcard), "apex": stale(apex)},
    }


async def _delete_records(client: httpx.AsyncClient, token: str, zone_id: str, records: List[Dict[str, Any]]) -> List[str]:
    removed = []
    for record in records:
        resp = await client.delete(
            f"{CF_API}/zones/{zone_id}/dns_records/{record['id']}", headers=_headers(token),
        )
        if resp.status_code not in (200, 404):
            raise DomainError(f"No se pudo retirar {record.get('type')} {record.get('content')} ({record.get('name')})")
        removed.append(f"{record.get('type')} {record.get('content')}")
    return removed


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _check(check_id: str, label: str, status: str, detail: str = "") -> Dict[str, str]:
    """Un renglon del reporte de validacion que consume la UI."""
    return {"id": check_id, "label": label, "status": status, "detail": detail}


async def get_system_config() -> Dict[str, Any]:
    db = get_db()
    return await db.system_config.find_one({"_id": "main"}) or {}


async def resolve_for_app(app_doc: Optional[dict]) -> Dict[str, Any]:
    """Dominio efectivo de una app: su domain_id, si no el default, si no el del instalador.

    Devuelve siempre un dict con fqdn/zone_id/tunnel_id para que el deployer
    pueda operar aunque la coleccion `domains` todavia no exista (instalaciones
    anteriores a multi-dominio).
    """
    db = get_db()
    config = await get_system_config()
    fallback = {
        "fqdn": config.get("domain", ""),
        "cloudflare_zone_id": config.get("cloudflare_zone_id", ""),
        "tunnel_id": config.get("cloudflare_tunnel_id", ""),
        "is_default": True,
        "source": "system_config",
    }

    domain_id = (app_doc or {}).get("domain_id")
    if domain_id:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            doc = await db.domains.find_one({"_id": ObjectId(domain_id)})
        except InvalidId:
            doc = None
        if doc:
            doc["source"] = "app"
            return doc
        # La app apunta a un dominio borrado. Caer al default es preferible a
        # desplegar contra un FQDN inexistente, pero tiene que quedar en el log.
        logger.warning(
            "App %s references missing domain %s; falling back to default",
            (app_doc or {}).get("name"), domain_id,
        )

    default = await db.domains.find_one({"is_default": True})
    if default:
        default["source"] = "default"
        return default
    return fallback


async def installation_tunnel_id(client: httpx.AsyncClient, config: Dict[str, Any]) -> str:
    """Túnel de la instalación: el guardado, o el que enruta hoy su dominio.

    Instalaciones anteriores no guardaban el id del túnel. En vez de listar
    túneles y elegir uno —que puede atar apps a un túnel muerto— se lee el
    CNAME wildcard del dominio de la instalación, que es la ruta que Cloudflare
    está usando realmente. Se cachea en system_config al encontrarlo.
    """
    saved = (config.get("cloudflare_tunnel_id") or "").strip()
    if saved:
        return saved

    token = config.get("cloudflare_token", "")
    domain = (config.get("domain") or "").strip()
    if not token or not domain:
        return ""
    try:
        zone_id = config.get("cloudflare_zone_id") or ""
        if not zone_id:
            zr = await client.get(f"{CF_API}/zones?name={domain}", headers=_headers(token))
            zones = zr.json().get("result", []) if zr.status_code == 200 else []
            zone_id = zones[0]["id"] if zones else ""
        if not zone_id:
            return ""
        rr = await client.get(
            f"{CF_API}/zones/{zone_id}/dns_records?type=CNAME&name=*.{domain}",
            headers=_headers(token),
        )
        records = rr.json().get("result", []) if rr.status_code == 200 else []
    except Exception as exc:
        logger.warning("No se pudo descubrir el túnel de %s: %s", domain, exc)
        return ""

    suffix = ".cfargotunnel.com"
    for record in records:
        content = str(record.get("content") or "")
        if content.endswith(suffix):
            tunnel_id = content[: -len(suffix)]
            db = get_db()
            await db.system_config.update_one(
                {"_id": "main"},
                {"$set": {"cloudflare_tunnel_id": tunnel_id, "cloudflare_zone_id": zone_id}},
            )
            logger.info("Túnel de la instalación descubierto desde *.%s", domain)
            return tunnel_id
    return ""


async def request_activation_check(client: httpx.AsyncClient, token: str, zone_id: str) -> str:
    """Pide a Cloudflare revisar ya los nameservers de una zona pendiente.

    Sin esto la activación depende del ciclo propio de Cloudflare, que puede
    tardar horas aunque el registrador ya esté apuntado. Best-effort: Cloudflare
    limita la frecuencia y un rechazo no invalida nada.
    """
    try:
        resp = await client.put(
            f"{CF_API}/zones/{zone_id}/activation_check", headers=_headers(token),
        )
        if resp.status_code == 200:
            return "Se pidió a Cloudflare revisar los nameservers ahora."
        if resp.status_code == 403:
            # El token de Kaanbal no suele tener el permiso de edición de zona que
            # pide este atajo. No es un problema del dominio: Cloudflare revisa
            # igual por su cuenta. Decir "Unauthorized" solo asustaba.
            return ("Cloudflare revisará los nameservers por su cuenta (acelerarlo requiere un "
                    "permiso de zona que el token no tiene; no es necesario). Vuelve a Validar en unos minutos.")
        errors = resp.json().get("errors") or []
        msg = errors[0].get("message") if errors else f"HTTP {resp.status_code}"
        return f"Cloudflare no aceptó revisar ahora ({msg}); lo hará en su propio ciclo."
    except Exception:
        return ""


async def verify(fqdn: str, *, tunnel_id: str = "") -> Dict[str, Any]:
    """Valida que un dominio pueda servir apps publicas. No modifica nada.

    Reporta cada condicion por separado para que el alta en la consola diga
    exactamente que falta, en vez de un error opaco.
    """
    config = await get_system_config()
    token = config.get("cloudflare_token", "")
    account_id = config.get("cloudflare_account_id", "")
    checks: List[Dict[str, str]] = []

    if not token or not account_id:
        checks.append(_check(
            "credentials", "Credenciales de Cloudflare", "fail",
            "No hay token o account_id en la configuracion del sistema.",
        ))
        return {"fqdn": fqdn, "ok": False, "zone_id": None, "checks": checks}

    checks.append(_check(
        "credentials", "Credenciales de Cloudflare", "ok",
        "Cuenta " + account_id[:8] + "...",
    ))

    zone_id = None
    zone_status = None
    effective_tunnel = ""
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(f"{CF_API}/zones?name={fqdn}", headers=_headers(token))
            zones = resp.json().get("result", []) if resp.status_code == 200 else []
        except Exception as exc:  # red, DNS, timeout
            checks.append(_check(
                "zone", "Zona en Cloudflare", "fail",
                f"No se pudo consultar la API de Cloudflare: {exc}",
            ))
            return {"fqdn": fqdn, "ok": False, "zone_id": None, "checks": checks}

        if not zones:
            checks.append(_check(
                "zone", "Zona en Cloudflare", "fail",
                f"El token no ve ninguna zona llamada {fqdn}. Agrega el dominio a "
                "esta cuenta de Cloudflare, o revisa que el token tenga permiso "
                "Zone:Read sobre ella.",
            ))
            return {"fqdn": fqdn, "ok": False, "zone_id": None, "checks": checks}

        zone = zones[0]
        zone_id = zone["id"]
        zone_status = zone.get("status")
        zone_account = (zone.get("account") or {}).get("id")

        if zone_status == "active":
            checks.append(_check(
                "zone", "Zona en Cloudflare", "ok", f"Zone {zone_id[:8]}... activa",
            ))
        else:
            nameservers = ", ".join(zone.get("name_servers") or []) or "los que indica Cloudflare"
            nudge = await request_activation_check(client, token, zone_id)
            checks.append(_check(
                "zone", "Zona en Cloudflare", "fail",
                f"La zona existe pero esta en estado '{zone_status}'. Apunta los "
                f"nameservers del registrador a: {nameservers}. Si ya lo hiciste, "
                f"la propagacion puede tardar de minutos a horas. {nudge}".strip(),
            ))

        conflicts = await dns_conflicts(client, token, zone_id, fqdn)
        if conflicts["wildcard"]:
            checks.append(_check(
                "dns", "DNS existente", "fail",
                f"*.{fqdn} ya apunta a otro origen ({_describe(conflicts['wildcard'])}). "
                "Eliminalo en Cloudflare para que las apps en subdominios usen el tunel.",
            ))
        elif conflicts["apex"]:
            checks.append(_check(
                "dns", "DNS existente", "warn",
                f"La raiz {fqdn} apunta a otro origen ({_describe(conflicts['apex'])}). "
                "No se tocara: las apps en subdominios funcionaran y la raiz seguira "
                "sirviendo lo que tiene hoy. Si quieres usar la raiz, elimina ese "
                "registro en Cloudflare y usa Recablear.",
            ))
        else:
            checks.append(_check("dns", "DNS existente", "ok", "Sin registros en conflicto."))

        stale_found = conflicts["stale"]["wildcard"] + conflicts["stale"]["apex"]
        if stale_found:
            names = sorted({r.get("name") for r in stale_found})
            checks.append(_check(
                "dns_stale", "Registros importados de otra cuenta", "warn",
                f"{', '.join(names)} apuntan a IPs de la propia red de Cloudflare. Se importaron "
                "cuando el dominio vivía en otra cuenta de Cloudflare y no son un servidor real. "
                "Kaanbal los reemplazará por el túnel al registrar el dominio.",
            ))

        if zone_account and account_id and zone_account != account_id:
            checks.append(_check(
                "account", "Cuenta propietaria", "fail",
                "La zona pertenece a una cuenta de Cloudflare distinta a la del "
                "tunel; el tunel no podra servir este dominio.",
            ))
        else:
            checks.append(_check(
                "account", "Cuenta propietaria", "ok",
                "La zona vive en la misma cuenta que el tunel.",
            ))

        effective_tunnel = tunnel_id or await installation_tunnel_id(client, config)
        if not effective_tunnel:
            checks.append(_check(
                "tunnel", "Tunel de Cloudflare", "fail",
                "No hay tunel configurado en esta instalacion; sin el no existe "
                "ruta de entrada para trafico publico.",
            ))
        else:
            try:
                t_resp = await client.get(
                    f"{CF_API}/accounts/{account_id}/cfd_tunnel/{effective_tunnel}",
                    headers=_headers(token),
                )
                deleted = (t_resp.json().get("result") or {}).get("deleted_at") if t_resp.status_code == 200 else True
                if t_resp.status_code == 200 and not deleted:
                    checks.append(_check(
                        "tunnel", "Tunel de Cloudflare", "ok",
                        f"Tunel {effective_tunnel[:8]}... disponible",
                    ))
                else:
                    checks.append(_check(
                        "tunnel", "Tunel de Cloudflare", "fail",
                        "El tunel configurado no existe o fue borrado.",
                    ))
            except Exception as exc:
                checks.append(_check(
                    "tunnel", "Tunel de Cloudflare", "warn",
                    f"No se pudo verificar el tunel: {exc}",
                ))

    ok = all(c["status"] != "fail" for c in checks)
    return {
        "fqdn": fqdn,
        "ok": ok,
        "zone_id": zone_id,
        "zone_status": zone_status,
        # El túnel efectivo (guardado o descubierto) para que el alta provisione
        # contra el mismo que se validó.
        "tunnel_id": effective_tunnel or None,
        "checks": checks,
    }


async def provision(fqdn: str, *, zone_id: str, tunnel_id: str) -> Dict[str, Any]:
    """Cablea un dominio ya validado: reglas de tunel + DNS wildcard y raiz.

    Idempotente. Las reglas del tunel se leen, se **extienden** y se reescriben:
    un PUT ciego borraria el dominio que ya sirve la instalacion.
    """
    config = await get_system_config()
    token = config.get("cloudflare_token", "")
    account_id = config.get("cloudflare_account_id", "")
    if not token or not account_id:
        raise DomainError("Cloudflare no esta configurado en esta instalacion.")
    if not tunnel_id:
        raise DomainError("No hay tunel de Cloudflare al cual asociar el dominio.")

    created: List[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        # Conflictos ANTES de tocar el tunel: descubrirlos a mitad de camino deja
        # el dominio a medio cablear.
        conflicts = await dns_conflicts(client, token, zone_id, fqdn)
        if conflicts["wildcard"]:
            raise DomainError(
                f"*.{fqdn} ya apunta a otro origen ({_describe(conflicts['wildcard'])}). "
                "Eliminalo en Cloudflare para que las apps en subdominios usen el tunel."
            )
        # La raiz es opcional: las apps viven en subdominios. Si ya apunta a otro
        # origen (tipico: el hosting del registrador) se respeta en vez de pisar
        # un sitio que puede estar funcionando.
        apex_routed = not conflicts["apex"]

        cfg_url = f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
        cur_resp = await client.get(cfg_url, headers=_headers(token))
        if cur_resp.status_code != 200:
            raise DomainError(
                f"No se pudo leer la configuracion del tunel (HTTP {cur_resp.status_code})."
            )
        tunnel_cfg = (cur_resp.json().get("result") or {}).get("config") or {}
        original_ingress = list(tunnel_cfg.get("ingress") or [])

        existing_hosts = {r.get("hostname") for r in original_ingress if r.get("hostname")}
        wanted = [f"*.{fqdn}"] + ([fqdn] if apex_routed else [])
        additions = [
            {"hostname": host, "service": TRAEFIK_SERVICE}
            for host in wanted if host not in existing_hosts
        ]

        tunnel_changed = False
        created_record_ids: List[str] = []
        try:
            if additions:
                # El catch-all (regla sin hostname) tiene que quedar al final o
                # Cloudflare rechaza la configuracion completa.
                catch_all = [r for r in original_ingress if not r.get("hostname")]
                routed = [r for r in original_ingress if r.get("hostname")]
                tunnel_cfg["ingress"] = routed + additions + (catch_all or [{"service": "http_status:404"}])
                put_resp = await client.put(cfg_url, headers=_headers(token), json={"config": tunnel_cfg})
                if put_resp.status_code != 200:
                    raise DomainError(
                        f"No se pudieron agregar las reglas del tunel "
                        f"(HTTP {put_resp.status_code}): {put_resp.text[:200]}"
                    )
                tunnel_changed = True
                created.extend(r["hostname"] for r in additions)

            # Restos de importación (IPs de Cloudflare) en los nombres que se van a
            # cablear: bloquearían el CNAME (81053) y nunca fueron un origen
            # válido. No se restauran en el rollback, por la misma razón.
            stale = conflicts["stale"]["wildcard"] + (conflicts["stale"]["apex"] if apex_routed else [])
            removed_stale = await _delete_records(client, token, zone_id, stale)
            if removed_stale:
                logger.info("Registros importados retirados de %s: %s", fqdn, removed_stale)

            target = f"{tunnel_id}{TUNNEL_SUFFIX}"
            for name in wanted:
                record = {"type": "CNAME", "name": name, "content": target, "proxied": True}
                existing = [r for r in await _records(client, token, zone_id, name) if _points_to_tunnel(r)]
                if existing:
                    await client.put(
                        f"{CF_API}/zones/{zone_id}/dns_records/{existing[0]['id']}",
                        headers=_headers(token), json=record,
                    )
                else:
                    cr = await client.post(
                        f"{CF_API}/zones/{zone_id}/dns_records",
                        headers=_headers(token), json=record,
                    )
                    if cr.status_code != 200:
                        errors = cr.json().get("errors") or []
                        msg = errors[0].get("message") if errors else cr.text[:200]
                        raise DomainError(f"No se pudo crear el DNS {name}: {msg}")
                    created_record_ids.append((cr.json().get("result") or {}).get("id"))
                created.append(name)
        except Exception:
            # Revertir solo lo que esta llamada creo; lo que ya existia se queda.
            if tunnel_changed:
                tunnel_cfg["ingress"] = original_ingress
                await client.put(cfg_url, headers=_headers(token), json={"config": tunnel_cfg})
            for record_id in filter(None, created_record_ids):
                await client.delete(
                    f"{CF_API}/zones/{zone_id}/dns_records/{record_id}", headers=_headers(token),
                )
            logger.warning("Provision de %s revertida tras un fallo", fqdn)
            raise

    apex = {"routed": apex_routed}
    if not apex_routed:
        apex["reason"] = (
            f"La raiz {fqdn} apunta a otro origen ({_describe(conflicts['apex'])}) y se "
            "respeto. Las apps en subdominios funcionan; la raiz sigue sirviendo lo que "
            "tiene hoy."
        )
    logger.info("Domain %s provisioned on tunnel %s (apex routed=%s)", fqdn, tunnel_id, apex_routed)
    return {
        "fqdn": fqdn, "zone_id": zone_id, "tunnel_id": tunnel_id,
        "provisioned": created, "apex": apex, "removed_stale": removed_stale,
    }


async def ensure_apex_routed(fqdn: str, *, zone_id: str, tunnel_id: str) -> Dict[str, Any]:
    """Enruta la raíz del dominio al túnel. Solo para apps raíz (homepage).

    La raíz suele traer un A hacia el hosting del registrador (la página de
    "Parked Domain" de Hostinger). Cloudflare no admite un CNAME junto a ese A
    (81053) y un wildcard no cubre la raíz, así que la app raíz quedaba sana en
    el clúster pero el dominio seguía mostrando al registrador.

    A diferencia de provision(), aquí SÍ se reemplaza lo que había: desplegar
    una app en la raíz es una decisión explícita de ocuparla. Se reporta qué se
    reemplazó para que quede constancia.
    """
    config = await get_system_config()
    token = config.get("cloudflare_token", "")
    account_id = config.get("cloudflare_account_id", "")
    if not token or not account_id or not zone_id or not tunnel_id:
        raise DomainError("Faltan credenciales, zona o túnel de Cloudflare para enrutar la raíz.")

    target = f"{tunnel_id}{TUNNEL_SUFFIX}"
    replaced: List[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Regla del túnel para la raíz (la wildcard *.dominio no la cubre).
        cfg_url = f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
        cur = await client.get(cfg_url, headers=_headers(token))
        if cur.status_code != 200:
            raise DomainError(f"No se pudo leer la configuración del túnel (HTTP {cur.status_code}).")
        tunnel_cfg = (cur.json().get("result") or {}).get("config") or {}
        ingress = list(tunnel_cfg.get("ingress") or [])
        rule_added = False
        if not any(r.get("hostname") == fqdn for r in ingress):
            routed = [r for r in ingress if r.get("hostname")]
            catch_all = [r for r in ingress if not r.get("hostname")] or [{"service": "http_status:404"}]
            tunnel_cfg["ingress"] = routed + [{"hostname": fqdn, "service": TRAEFIK_SERVICE}] + catch_all
            put = await client.put(cfg_url, headers=_headers(token), json={"config": tunnel_cfg})
            if put.status_code != 200:
                raise DomainError(f"No se pudo agregar la regla del túnel para {fqdn}: {put.text[:200]}")
            rule_added = True

        # 2. DNS de la raíz: fuera lo que apunte a otro origen, CNAME al túnel.
        records = await _records(client, token, zone_id, fqdn)
        if any(_points_to_tunnel(r) for r in records):
            return {"fqdn": fqdn, "replaced": [], "rule_added": rule_added, "already_routed": True}
        for record in records:
            if record.get("type") in ("A", "AAAA", "CNAME"):
                resp = await client.delete(
                    f"{CF_API}/zones/{zone_id}/dns_records/{record['id']}", headers=_headers(token),
                )
                if resp.status_code not in (200, 404):
                    raise DomainError(f"No se pudo retirar {record.get('type')} {record.get('content')} de {fqdn}")
                replaced.append(f"{record.get('type')} {record.get('content')}")
        created = await client.post(
            f"{CF_API}/zones/{zone_id}/dns_records", headers=_headers(token),
            json={"type": "CNAME", "name": fqdn, "content": target, "proxied": True},
        )
        if created.status_code != 200:
            errors = created.json().get("errors") or []
            raise DomainError(
                f"No se pudo apuntar {fqdn} al túnel: {errors[0].get('message') if errors else created.text[:200]}"
            )

    logger.info("Raíz %s enrutada al túnel (reemplazado: %s)", fqdn, replaced or "nada")
    return {"fqdn": fqdn, "replaced": replaced, "rule_added": rule_added, "already_routed": False}


async def deprovision(fqdn: str, *, zone_id: str, tunnel_id: str) -> Dict[str, Any]:
    """Quita reglas de tunel y DNS wildcard/raiz de un dominio que se elimina."""
    config = await get_system_config()
    token = config.get("cloudflare_token", "")
    account_id = config.get("cloudflare_account_id", "")
    removed: List[str] = []
    if not token or not account_id or not tunnel_id:
        return {"fqdn": fqdn, "removed": removed, "skipped": "cloudflare-not-configured"}

    hosts = [f"*.{fqdn}", fqdn]
    async with httpx.AsyncClient(timeout=30) as client:
        cfg_url = f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
        cur_resp = await client.get(cfg_url, headers=_headers(token))
        if cur_resp.status_code == 200:
            tunnel_cfg = (cur_resp.json().get("result") or {}).get("config") or {}
            ingress = list(tunnel_cfg.get("ingress") or [])
            kept = [r for r in ingress if r.get("hostname") not in hosts]
            if len(kept) != len(ingress):
                tunnel_cfg["ingress"] = kept
                await client.put(cfg_url, headers=_headers(token), json={"config": tunnel_cfg})
                removed.append("tunnel-rules")

        if zone_id:
            for name in hosts:
                ex_resp = await client.get(
                    f"{CF_API}/zones/{zone_id}/dns_records?type=CNAME&name={name}",
                    headers=_headers(token),
                )
                records = ex_resp.json().get("result", []) if ex_resp.status_code == 200 else []
                for rec in records:
                    await client.delete(
                        f"{CF_API}/zones/{zone_id}/dns_records/{rec['id']}",
                        headers=_headers(token),
                    )
                    removed.append(name)

    return {"fqdn": fqdn, "removed": removed}


PUBLIC_MODES = ("public", "both")
ROOT_APP_SUFFIX = "-homepage"


def site_slug(fqdn: str, *, full: bool = False) -> str:
    """Identidad de un sitio a partir de su dominio: 'polar-genomicsresearch.site' → 'polar-genomicsresearch'.

    Se usa la primera etiqueta: es la parte reconocible del dominio y evita nombres
    como 'polar-genomicsresearch-site-homepage'. Con ``full`` entra el dominio
    completo ('northwind.store' → 'northwind-store'), para desempatar dominios que
    comparten la primera etiqueta. Mismo alfabeto que un nombre de app.
    """
    import re

    host = (fqdn or "").strip().lower()
    label = (host.replace(".", "-") if full else host.split(".")[0]).replace("_", "-")
    label = re.sub(r"[^a-z0-9-]", "", label)
    label = re.sub(r"-+", "-", label).strip("-")
    return label or "site"


def root_app_name(fqdn: str, *, full: bool = False, ordinal: int = 1) -> str:
    """Nombre de la app raíz de un dominio: '<sitio>-homepage', dentro de 63 caracteres.

    Antes toda app raíz se llamaba 'homepage' y el homepage del segundo dominio
    chocaba con el del primero: el nombre es la identidad de repo, despliegue y
    secretos. El número de desempate va antes del sufijo ('northwind-store-2-homepage')
    para que todo homepage termine igual y su grupo se derive del nombre.
    """
    tail = f"-{ordinal}" if ordinal > 1 else ""
    slug = site_slug(fqdn, full=full)[: 63 - len(ROOT_APP_SUFFIX) - len(tail)].rstrip("-")
    return f"{slug}{tail}{ROOT_APP_SUFFIX}"


def root_app_candidates(fqdn: str):
    """Nombres a probar, en orden: 'northwind-homepage', 'northwind-store-homepage', 'northwind-store-2-homepage'…

    'northwind.site' y 'northwind.store' comparten la primera etiqueta: el segundo homepage
    recibe el dominio completo en vez de un número que no dice de quién es.
    """
    yield root_app_name(fqdn)
    full = root_app_name(fqdn, full=True)
    if full != root_app_name(fqdn):
        yield full
    ordinal = 2
    while True:
        yield root_app_name(fqdn, full=True, ordinal=ordinal)
        ordinal += 1


def site_group(root_name: str) -> str:
    """Grupo lógico de un sitio: el nombre de su homepage sin el sufijo ('northwind-homepage' → 'northwind').

    Derivarlo del nombre (único) y no solo del dominio evita que dos sitios con la
    misma primera etiqueta compartan grupo y mezclen su API y su base.
    """
    name = (root_name or "").strip().lower()
    if name.endswith(ROOT_APP_SUFFIX) and len(name) > len(ROOT_APP_SUFFIX):
        return name[: -len(ROOT_APP_SUFFIX)]
    return name


def public_host(app_name: str, env: str, fqdn: str, *, is_root_domain: bool = False) -> str:
    """Host público de una app en un ambiente.

    Misma regla que AppDeployer._build_public_host: prod vive en <app>.<dominio>
    (o en el dominio desnudo si es la app raíz) y el resto en <env>-<app>.<dominio>.
    La consola no debe reconstruir esto por su cuenta: hacerlo con el dominio de
    la instalación fue lo que mandaba "Open App" al dominio equivocado.
    """
    if env == "prod":
        return fqdn if is_root_domain else f"{app_name}.{fqdn}"
    return f"{env}-{app_name}.{fqdn}"


def env_modes(app_doc: dict) -> Dict[str, str]:
    """Modo de exposición efectivo por ambiente activo."""
    exposure = app_doc.get("exposure") or {}
    per_env = exposure.get("per_env") or {}
    fallback = str(exposure.get("type") or "internal")
    return {
        env: str(per_env.get(env) or fallback)
        for env in (app_doc.get("environments") or ["prod"])
    }


async def domains_index() -> Dict[str, Any]:
    """Todos los dominios por id, más el default. Una sola consulta para listar apps."""
    db = get_db()
    docs = await db.domains.find().to_list(100)
    by_id = {str(d["_id"]): d for d in docs}
    default = next((d for d in docs if d.get("is_default")), None)
    if default is None:
        config = await get_system_config()
        if config.get("domain"):
            default = {"_id": None, "fqdn": config["domain"], "is_default": True}
    return {"by_id": by_id, "default": default}


def describe_app_domain(app_doc: dict, index: Dict[str, Any]) -> Dict[str, Any]:
    """Dominio de una app tal como debe verlo la consola.

    Incluye los hosts y URLs públicos ya resueltos por ambiente, así la consola no
    tiene que adivinarlos. Una app sin ambientes públicos no "vive" en ningún
    dominio: se reporta como privada aunque tenga domain_id.
    """
    domain = index["by_id"].get(str(app_doc.get("domain_id") or "")) or index.get("default") or {}
    fqdn = domain.get("fqdn") or ""
    modes = env_modes(app_doc)
    public_envs = [env for env, mode in modes.items() if mode in PUBLIC_MODES]
    is_root = bool(app_doc.get("is_root_domain"))
    hosts = {
        env: public_host(app_doc.get("name", ""), env, fqdn, is_root_domain=is_root)
        for env in public_envs
    } if fqdn else {}
    return {
        "id": str(domain["_id"]) if domain.get("_id") else None,
        "fqdn": fqdn or None,
        "is_default": bool(domain.get("is_default")),
        "public": bool(public_envs),
        "modes": modes,
        "hosts": hosts,
        "urls": {env: f"https://{host}" for env, host in hosts.items()},
    }


def claims_for(app_doc: dict, fqdn: str) -> List[str]:
    """Hosts públicos que una app reserva en un dominio (para detectar choques)."""
    is_root = bool(app_doc.get("is_root_domain"))
    return sorted({
        public_host(app_doc.get("name", ""), env, fqdn, is_root_domain=is_root).lower()
        for env, mode in env_modes(app_doc).items() if mode in PUBLIC_MODES
    })


async def count_apps_using(domain_id: str, *, is_default: bool) -> int:
    """Apps que quedarian huerfanas si el dominio desaparece.

    El dominio default tambien carga con las apps que nunca fijaron domain_id:
    borrarlo sin contarlas dejaria esas apps apuntando a la nada.
    """
    db = get_db()
    if is_default:
        query = {"$or": [
            {"domain_id": domain_id},
            {"domain_id": None},
            {"domain_id": {"$exists": False}},
        ]}
    else:
        query = {"domain_id": domain_id}
    return await db.apps.count_documents(query)
