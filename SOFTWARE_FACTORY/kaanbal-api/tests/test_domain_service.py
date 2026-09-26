"""
Tests de multi-dominio (domain_service + contexto de dominio del deployer).

Cubren las tres propiedades que hacen que un segundo dominio funcione y no
rompa el primero:
  1. La resolucion cae en cascada app -> default -> instalador.
  2. Provisionar un dominio AGREGA reglas al tunel; jamas pisa las existentes.
  3. El conteo de apps del dominio default incluye las apps sin domain_id.

Standalone: py tests/test_domain_service.py
"""
import asyncio
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# app.db arrastra motor (driver de Mongo), que no es dependencia de pruebas:
# el resto de la suite tambien corre sin el. get_db se mockea en cada test.
if "app.db" not in sys.modules:
    _db_stub = types.ModuleType("app.db")
    _db_stub.get_db = lambda: None
    sys.modules["app.db"] = _db_stub

# bson viaja con pymongo, que tampoco es dependencia de pruebas. El stub basta:
# lo unico que necesitan estos tests es que un id valido no haga match con los
# documentos falsos, que es justo el caso del dominio borrado.
if "bson" not in sys.modules:
    _bson_stub = types.ModuleType("bson")
    _bson_stub.ObjectId = lambda value: f"oid:{value}"
    _errors_stub = types.ModuleType("bson.errors")

    class _InvalidId(Exception):
        pass

    _bson_stub.errors = _errors_stub
    _errors_stub.InvalidId = _InvalidId
    sys.modules["bson"] = _bson_stub
    sys.modules["bson.errors"] = _errors_stub

from app.services import domain_service as ds  # noqa: E402


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.updates = []

    async def find_one(self, query, *a, **kw):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def update_one(self, query, update, *a, **kw):
        self.updates.append((query, update))

    async def count_documents(self, query):
        self.last_count_query = query
        return len(self.docs)


class FakeDB:
    def __init__(self, domains=None, system_config=None, apps=None):
        self.domains = FakeCollection(domains)
        self.system_config = FakeCollection(system_config)
        self.apps = FakeCollection(apps)


def run(coro):
    return asyncio.run(coro)


CONFIG = [{
    "_id": "main",
    "domain": "instalacion.com",
    "cloudflare_zone_id": "zone-default",
    "cloudflare_tunnel_id": "tunnel-1",
    "cloudflare_token": "tok",
    "cloudflare_account_id": "acct",
}]


class ResolveTests(unittest.TestCase):
    def test_falls_back_to_system_config_when_no_domains(self):
        """Instalacion anterior a multi-dominio: la coleccion `domains` esta vacia."""
        db = FakeDB(domains=[], system_config=CONFIG)
        with mock.patch.object(ds, "get_db", return_value=db):
            got = run(ds.resolve_for_app({"name": "app"}))
        self.assertEqual(got["fqdn"], "instalacion.com")
        self.assertEqual(got["source"], "system_config")

    def test_app_without_domain_id_uses_default_domain(self):
        db = FakeDB(
            domains=[{"_id": "d1", "fqdn": "default.com", "is_default": True}],
            system_config=CONFIG,
        )
        with mock.patch.object(ds, "get_db", return_value=db):
            got = run(ds.resolve_for_app({"name": "app"}))
        self.assertEqual(got["fqdn"], "default.com")
        self.assertEqual(got["source"], "default")

    def test_missing_domain_falls_back_instead_of_deploying_to_nothing(self):
        """Una app que apunta a un dominio borrado cae al default, no explota."""
        db = FakeDB(
            domains=[{"_id": "d1", "fqdn": "default.com", "is_default": True}],
            system_config=CONFIG,
        )
        with mock.patch.object(ds, "get_db", return_value=db):
            got = run(ds.resolve_for_app({"name": "app", "domain_id": "507f1f77bcf86cd799439011"}))
        self.assertEqual(got["fqdn"], "default.com")


class CountAppsTests(unittest.TestCase):
    def test_default_domain_counts_apps_without_domain_id(self):
        """Borrar el default sin contar las apps legacy las dejaria huerfanas."""
        db = FakeDB(apps=[])
        with mock.patch.object(ds, "get_db", return_value=db):
            run(ds.count_apps_using("d1", is_default=True))
        clauses = db.apps.last_count_query["$or"]
        self.assertIn({"domain_id": None}, clauses)
        self.assertIn({"domain_id": {"$exists": False}}, clauses)

    def test_non_default_domain_counts_only_explicit_references(self):
        db = FakeDB(apps=[])
        with mock.patch.object(ds, "get_db", return_value=db):
            run(ds.count_apps_using("d2", is_default=False))
        self.assertEqual(db.apps.last_count_query, {"domain_id": "d2"})


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeClient:
    """Cliente httpx de mentira que registra los PUT al tunel."""

    def __init__(self, tunnel_ingress):
        self.tunnel_ingress = tunnel_ingress
        self.put_bodies = []
        self.posted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kw):
        if "configurations" in url:
            return FakeResponse({"result": {"config": {"ingress": self.tunnel_ingress}}})
        if "dns_records" in url:
            return FakeResponse({"result": []})
        return FakeResponse({"result": []})

    async def put(self, url, **kw):
        self.put_bodies.append(kw.get("json"))
        return FakeResponse({"result": {}})

    async def post(self, url, **kw):
        self.posted.append(kw.get("json"))
        return FakeResponse({"result": {}})

    async def delete(self, url, **kw):
        return FakeResponse({"result": {}})


class ProvisionTests(unittest.TestCase):
    def _provision(self, existing_ingress):
        db = FakeDB(system_config=CONFIG)
        client = FakeClient(existing_ingress)
        with mock.patch.object(ds, "get_db", return_value=db), \
             mock.patch.object(ds.httpx, "AsyncClient", return_value=client):
            run(ds.provision("nuevo.com", zone_id="zone-nuevo", tunnel_id="tunnel-1"))
        return client

    def test_preserves_existing_domain_rules(self):
        """El bug que este test cierra: un PUT ciego borraria el dominio que ya sirve."""
        existing = [
            {"hostname": "argocd.instalacion.com", "service": "https://argocd"},
            {"hostname": "*.instalacion.com", "service": ds.TRAEFIK_SERVICE},
            {"service": "http_status:404"},
        ]
        client = self._provision(existing)
        ingress = client.put_bodies[0]["config"]["ingress"]
        hostnames = [r.get("hostname") for r in ingress]
        self.assertIn("argocd.instalacion.com", hostnames)
        self.assertIn("*.instalacion.com", hostnames)
        self.assertIn("*.nuevo.com", hostnames)
        self.assertIn("nuevo.com", hostnames)

    def test_catch_all_stays_last(self):
        """Cloudflare rechaza la config si la regla sin hostname no va al final."""
        existing = [
            {"hostname": "*.instalacion.com", "service": ds.TRAEFIK_SERVICE},
            {"service": "http_status:404"},
        ]
        client = self._provision(existing)
        ingress = client.put_bodies[0]["config"]["ingress"]
        self.assertIsNone(ingress[-1].get("hostname"))
        self.assertEqual(ingress[-1]["service"], "http_status:404")
        for rule in ingress[:-1]:
            self.assertIsNotNone(rule.get("hostname"))

    def test_is_idempotent(self):
        """Re-provisionar un dominio ya cableado no reescribe las reglas del tunel."""
        existing = [
            {"hostname": "*.nuevo.com", "service": ds.TRAEFIK_SERVICE},
            {"hostname": "nuevo.com", "service": ds.TRAEFIK_SERVICE},
            {"service": "http_status:404"},
        ]
        client = self._provision(existing)
        tunnel_puts = [b for b in client.put_bodies if "config" in (b or {})]
        self.assertEqual(tunnel_puts, [])


class DnsAwareClient(FakeClient):
    """Cliente con registros DNS por nombre y fallos de creacion inyectables."""

    def __init__(self, tunnel_ingress, records_by_name=None, fail_create=False):
        super().__init__(tunnel_ingress)
        self.records_by_name = records_by_name or {}
        self.fail_create = fail_create
        self.deleted = []

    async def get(self, url, **kw):
        if "configurations" in url:
            return FakeResponse({"result": {"config": {"ingress": self.tunnel_ingress}}})
        if "dns_records?name=" in url:
            name = url.split("dns_records?name=", 1)[1]
            return FakeResponse({"result": self.records_by_name.get(name, [])})
        return FakeResponse({"result": []})

    async def post(self, url, **kw):
        self.posted.append(kw.get("json"))
        if self.fail_create:
            return FakeResponse({"errors": [{"code": 81053, "message": "record exists"}]}, 400)
        return FakeResponse({"result": {"id": f"rec-{len(self.posted)}"}})

    async def delete(self, url, **kw):
        self.deleted.append(url)
        return FakeResponse({"result": {}})


class ProvisionConflictTests(unittest.TestCase):
    BASE = [
        {"hostname": "*.instalacion.com", "service": ds.TRAEFIK_SERVICE},
        {"service": "http_status:404"},
    ]

    def _run(self, client):
        db = FakeDB(system_config=CONFIG)
        with mock.patch.object(ds, "get_db", return_value=db), \
             mock.patch.object(ds.httpx, "AsyncClient", return_value=client):
            return run(ds.provision("nuevo.com", zone_id="zone-nuevo", tunnel_id="tunnel-1"))

    def test_apex_pointing_to_registrar_hosting_is_respected(self):
        """El caso real de laboratorio: A de Hostinger en la raiz. Pisarlo tumbaria un sitio vivo."""
        client = DnsAwareClient(list(self.BASE), {
            "nuevo.com": [{"type": "A", "content": "203.0.113.7", "id": "hostinger"}],
        })
        result = self._run(client)
        self.assertFalse(result["apex"]["routed"])
        self.assertIn("203.0.113.7", result["apex"]["reason"])
        created_names = [p["name"] for p in client.posted]
        self.assertEqual(created_names, ["*.nuevo.com"])
        hostnames = [r.get("hostname") for r in client.put_bodies[0]["config"]["ingress"]]
        self.assertIn("*.nuevo.com", hostnames)
        self.assertNotIn("nuevo.com", hostnames)

    def test_foreign_wildcard_blocks_before_touching_the_tunnel(self):
        client = DnsAwareClient(list(self.BASE), {
            "*.nuevo.com": [{"type": "A", "content": "9.9.9.9", "id": "otro"}],
        })
        with self.assertRaises(ds.DomainError):
            self._run(client)
        self.assertEqual(client.put_bodies, [])
        self.assertEqual(client.posted, [])

    def test_dns_failure_rolls_back_tunnel_rules(self):
        """Nunca dejar el dominio a medio cablear."""
        client = DnsAwareClient(list(self.BASE), fail_create=True)
        with self.assertRaises(ds.DomainError):
            self._run(client)
        self.assertEqual(len(client.put_bodies), 2)  # agregar + revertir
        restored = client.put_bodies[-1]["config"]["ingress"]
        self.assertEqual(restored, self.BASE)

    def test_existing_tunnel_cname_is_updated_not_duplicated(self):
        """Reintentar tras un fallo parcial reutiliza el wildcard ya creado."""
        client = DnsAwareClient(list(self.BASE), {
            "*.nuevo.com": [{"type": "CNAME", "content": "tunnel-1.cfargotunnel.com", "id": "w1"}],
        })
        self._run(client)
        self.assertNotIn("*.nuevo.com", [p["name"] for p in client.posted])


INDEX = {
    "by_id": {
        "d-default": {"_id": "d-default", "fqdn": "northwindlearning.site", "is_default": True},
        "d-polar": {"_id": "d-polar", "fqdn": "polar-genomicsresearch.site", "is_default": False},
    },
    "default": {"_id": "d-default", "fqdn": "northwindlearning.site", "is_default": True},
}


class AppDomainDescriptionTests(unittest.TestCase):
    def test_public_url_uses_the_app_domain_not_the_installation(self):
        """El bug reportado: Open App mandaba tes al dominio de la instalación."""
        app = {"name": "tes", "domain_id": "d-polar", "environments": ["prod"],
               "exposure": {"per_env": {"prod": "public"}}}
        got = ds.describe_app_domain(app, INDEX)
        self.assertEqual(got["fqdn"], "polar-genomicsresearch.site")
        self.assertEqual(got["urls"]["prod"], "https://tes.polar-genomicsresearch.site")
        self.assertFalse(got["is_default"])

    def test_app_without_domain_id_lives_on_default(self):
        app = {"name": "web", "environments": ["prod"], "exposure": {"per_env": {"prod": "public"}}}
        self.assertEqual(ds.describe_app_domain(app, INDEX)["urls"]["prod"], "https://web.northwindlearning.site")

    def test_non_prod_envs_get_prefixed_hosts(self):
        app = {"name": "api", "domain_id": "d-polar", "environments": ["dev", "prod"],
               "exposure": {"per_env": {"dev": "public", "prod": "public"}}}
        hosts = ds.describe_app_domain(app, INDEX)["hosts"]
        self.assertEqual(hosts, {"dev": "dev-api.polar-genomicsresearch.site", "prod": "api.polar-genomicsresearch.site"})

    def test_private_app_has_no_public_urls(self):
        app = {"name": "db", "domain_id": "d-polar", "environments": ["prod"],
               "exposure": {"per_env": {"prod": "tailscale"}}}
        got = ds.describe_app_domain(app, INDEX)
        self.assertFalse(got["public"])
        self.assertEqual(got["urls"], {})

    def test_root_app_takes_the_bare_domain(self):
        """Escenario de clientes: cada dominio puede tener su propia app raíz."""
        app = {"name": "homepage-2", "domain_id": "d-polar", "is_root_domain": True,
               "environments": ["prod"], "exposure": {"per_env": {"prod": "public"}}}
        self.assertEqual(ds.describe_app_domain(app, INDEX)["hosts"]["prod"], "polar-genomicsresearch.site")

    def test_claims_are_scoped_to_the_domain(self):
        """Dos dominios no chocan aunque la app se llame igual en ambos hosts."""
        app = {"name": "web", "environments": ["prod"], "exposure": {"per_env": {"prod": "public"}}}
        self.assertNotEqual(ds.claims_for(app, "a.com"), ds.claims_for(app, "b.com"))
        self.assertEqual(ds.claims_for(app, "a.com"), ["web.a.com"])


class SiteNamingTests(unittest.TestCase):
    """Un homepage por dominio: el nombre dice de qué dominio es."""

    def test_homepages_of_different_domains_never_collide(self):
        """El bloqueo real: todas se llamaban 'homepage' y la segunda chocaba."""
        names = {ds.root_app_name(d) for d in (
            "acmeplatform.site", "polar-genomicsresearch.site", "north-star-bay.store",
        )}
        self.assertEqual(names, {
            "acmeplatform-homepage", "polar-genomicsresearch-homepage", "north-star-bay-homepage",
        })

    def test_site_slug_uses_the_recognizable_part_of_the_domain(self):
        self.assertEqual(ds.site_slug("polar-genomicsresearch.site"), "polar-genomicsresearch")
        self.assertEqual(ds.site_slug("Dev_Morgan.Space"), "dev-morgan")

    def test_name_fits_kubernetes_limits_even_for_long_domains(self):
        """63 caracteres también con el dominio completo y un número de desempate."""
        fqdn = "un-dominio-extremadamente-largo-para-un-cliente-muy-especial.com"
        for name in (ds.root_app_name(fqdn), ds.root_app_name(fqdn, full=True, ordinal=12)):
            self.assertLessEqual(len(name), 63)
            self.assertTrue(name.endswith("-homepage"))
            self.assertRegex(name, r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

    def test_domains_sharing_first_label_get_readable_names(self):
        """northwind.site y northwind.store: el segundo dice de qué dominio es, no '-2'."""
        candidates = ds.root_app_candidates("northwind.store")
        self.assertEqual(
            [next(candidates) for _ in range(3)],
            ["northwind-homepage", "northwind-store-homepage", "northwind-store-2-homepage"],
        )

    def test_single_label_domain_does_not_repeat_candidates(self):
        candidates = ds.root_app_candidates("localhost")
        self.assertEqual([next(candidates) for _ in range(2)], ["localhost-homepage", "localhost-2-homepage"])

    def test_site_group_is_the_homepage_name_without_suffix(self):
        """Dos sitios nunca comparten grupo: el grupo sale del nombre único."""
        self.assertEqual(ds.site_group("northwind-homepage"), "northwind")
        self.assertEqual(ds.site_group("northwind-store-homepage"), "northwind-store")
        self.assertEqual(ds.site_group("landing"), "landing")


class StaleImportTests(unittest.TestCase):
    """dev-morgan.space: el dominio venía de otra cuenta de Cloudflare y el escaneo
    importó las IPs del proxy de esa cuenta como si fueran el origen."""

    IMPORTED = [
        {"type": "A", "content": "172.67.166.2", "id": "i1", "name": "*.nuevo.com"},
        {"type": "A", "content": "104.21.11.119", "id": "i2", "name": "*.nuevo.com"},
        {"type": "AAAA", "content": "2606:4700:3036::ac43:a602", "id": "i3", "name": "*.nuevo.com"},
    ]

    def test_cloudflare_edge_ips_are_stale_imports(self):
        for record in self.IMPORTED:
            self.assertTrue(ds._is_stale_import(record), record["content"])

    def test_real_origins_are_not_stale(self):
        """El A de Hostinger (polar) sí es un sitio real y se respeta."""
        self.assertFalse(ds._is_stale_import({"type": "A", "content": "203.0.113.7"}))
        self.assertFalse(ds._is_stale_import({"type": "CNAME", "content": "sitio.hostinger.com"}))

    def test_provision_replaces_imported_wildcard_instead_of_blocking(self):
        client = DnsAwareClient(
            [{"hostname": "*.instalacion.com", "service": ds.TRAEFIK_SERVICE}, {"service": "http_status:404"}],
            {"*.nuevo.com": self.IMPORTED, "nuevo.com": []},
        )
        db = FakeDB(system_config=CONFIG)
        with mock.patch.object(ds, "get_db", return_value=db), \
             mock.patch.object(ds.httpx, "AsyncClient", return_value=client):
            result = run(ds.provision("nuevo.com", zone_id="z", tunnel_id="tunnel-1"))
        self.assertEqual(len(result["removed_stale"]), 3)
        self.assertEqual(len(client.deleted), 3)
        self.assertIn("*.nuevo.com", [p["name"] for p in client.posted])


class ApexTakeoverTests(unittest.TestCase):
    """Homepage en la raíz: el caso de northwindlearning.site y acmeplatform.site."""

    BASE = [
        {"hostname": "*.instalacion.com", "service": ds.TRAEFIK_SERVICE},
        {"service": "http_status:404"},
    ]

    def _run(self, client):
        db = FakeDB(system_config=CONFIG)
        with mock.patch.object(ds, "get_db", return_value=db), \
             mock.patch.object(ds.httpx, "AsyncClient", return_value=client):
            return run(ds.ensure_apex_routed("instalacion.com", zone_id="z", tunnel_id="tunnel-1"))

    def test_replaces_registrar_parking_record_with_the_tunnel(self):
        client = DnsAwareClient(list(self.BASE), {
            "instalacion.com": [{"type": "A", "content": "203.0.113.7", "id": "hostinger"}],
        })
        result = self._run(client)
        self.assertEqual(result["replaced"], ["A 203.0.113.7"])
        self.assertTrue(any(url.endswith("/dns_records/hostinger") for url in client.deleted))
        self.assertEqual(client.posted[-1]["name"], "instalacion.com")
        self.assertEqual(client.posted[-1]["content"], "tunnel-1.cfargotunnel.com")
        self.assertTrue(client.posted[-1]["proxied"])

    def test_adds_tunnel_rule_for_the_apex_keeping_catch_all_last(self):
        """La wildcard *.dominio del túnel no cubre la raíz."""
        client = DnsAwareClient(list(self.BASE), {"instalacion.com": []})
        result = self._run(client)
        self.assertTrue(result["rule_added"])
        ingress = client.put_bodies[0]["config"]["ingress"]
        self.assertIn("instalacion.com", [r.get("hostname") for r in ingress])
        self.assertIsNone(ingress[-1].get("hostname"))

    def test_already_routed_apex_is_left_alone(self):
        client = DnsAwareClient(
            self.BASE[:1] + [{"hostname": "instalacion.com", "service": ds.TRAEFIK_SERVICE}] + self.BASE[1:],
            {"instalacion.com": [{"type": "CNAME", "content": "tunnel-1.cfargotunnel.com", "id": "ok"}]},
        )
        result = self._run(client)
        self.assertTrue(result["already_routed"])
        self.assertEqual(client.deleted, [])
        self.assertEqual(client.posted, [])
        self.assertEqual(client.put_bodies, [])


class VerifyTests(unittest.TestCase):
    def test_reports_missing_credentials_without_calling_cloudflare(self):
        db = FakeDB(system_config=[{"_id": "main", "domain": "x.com"}])
        with mock.patch.object(ds, "get_db", return_value=db):
            report = run(ds.verify("nuevo.com"))
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][0]["id"], "credentials")
        self.assertEqual(report["checks"][0]["status"], "fail")

    def test_pending_zone_is_blocking_and_names_the_nameservers(self):
        db = FakeDB(system_config=CONFIG)
        client = FakeClient([])

        async def fake_get(url, **kw):
            if "/zones?" in url:
                return FakeResponse({"result": [{
                    "id": "zone-nuevo",
                    "status": "pending",
                    "account": {"id": "acct"},
                    "name_servers": ["ns1.cloudflare.com", "ns2.cloudflare.com"],
                }]})
            return FakeResponse({"result": {}})

        client.get = fake_get
        with mock.patch.object(ds, "get_db", return_value=db), \
             mock.patch.object(ds.httpx, "AsyncClient", return_value=client):
            report = run(ds.verify("nuevo.com", tunnel_id="tunnel-1"))

        self.assertFalse(report["ok"])
        zone_check = next(c for c in report["checks"] if c["id"] == "zone")
        self.assertEqual(zone_check["status"], "fail")
        self.assertIn("ns1.cloudflare.com", zone_check["detail"])


class TunnelDiscoveryTests(unittest.TestCase):
    """Instalaciones anteriores no guardaban el id del tunel en system_config."""

    def _client(self, cname_content):
        client = FakeClient([])

        async def fake_get(url, **kw):
            if "/zones?" in url:
                return FakeResponse({"result": [{"id": "zone-default"}]})
            if "dns_records" in url:
                return FakeResponse({"result": [{"content": cname_content}]})
            return FakeResponse({"result": {}})

        client.get = fake_get
        return client

    def test_uses_saved_tunnel_without_calling_cloudflare(self):
        db = FakeDB(system_config=CONFIG)
        with mock.patch.object(ds, "get_db", return_value=db):
            got = run(ds.installation_tunnel_id(FakeClient([]), CONFIG[0]))
        self.assertEqual(got, "tunnel-1")
        self.assertEqual(db.system_config.updates, [])

    def test_discovers_tunnel_from_live_wildcard_cname_and_caches_it(self):
        config = {k: v for k, v in CONFIG[0].items() if k != "cloudflare_tunnel_id"}
        db = FakeDB(system_config=[config])
        client = self._client("abc-123.cfargotunnel.com")
        with mock.patch.object(ds, "get_db", return_value=db):
            got = run(ds.installation_tunnel_id(client, config))
        self.assertEqual(got, "abc-123")
        cached = db.system_config.updates[0][1]["$set"]
        self.assertEqual(cached["cloudflare_tunnel_id"], "abc-123")

    def test_ignores_wildcard_that_does_not_point_to_a_tunnel(self):
        """Un CNAME a otro origen no es un tunel: inventarlo ataria apps a la nada."""
        config = {k: v for k, v in CONFIG[0].items() if k != "cloudflare_tunnel_id"}
        db = FakeDB(system_config=[config])
        client = self._client("otro-origen.example.com")
        with mock.patch.object(ds, "get_db", return_value=db):
            got = run(ds.installation_tunnel_id(client, config))
        self.assertEqual(got, "")
        self.assertEqual(db.system_config.updates, [])


if __name__ == "__main__":
    unittest.main()
