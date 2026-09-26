"""
Tests del generador de la matriz de vinculación (link_service).
Ejecutable standalone (python3 tests/test_link_service.py) o con pytest.
No requiere dependencias: link_service es puro.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import link_service as ls  # noqa: E402


def test_env_literals_contract():
    """Contrato {ALIAS}_HOST/PORT/URL — mismo patrón que database_bindings."""
    link = {
        "from_app": "mi-frontend", "from_env": "prod",
        "to_app": "shop-api", "to_env": "prod",
        "port_name": "http", "port_number": 8000, "alias": None,
    }
    lits = ls.build_env_literals(link)
    assert lits == [
        "SHOP_API_HOST=shop-api.prod.svc.cluster.local",
        "SHOP_API_PORT=8000",
        "SHOP_API_URL=http://shop-api.prod.svc.cluster.local:8000",
    ], lits


def test_env_literals_mqtt_scheme():
    """Puertos lógicos conocidos generan el esquema de URL correcto."""
    link = {
        "from_app": "backend", "from_env": "prod",
        "to_app": "broker", "to_env": "prod",
        "port_name": "mqtt", "port_number": 1883, "alias": "EMQX",
    }
    lits = ls.build_env_literals(link)
    assert "EMQX_URL=mqtt://broker.prod.svc.cluster.local:1883" in lits


def test_network_policy_generation():
    """Default-deny + allow por link + allow ingress-nginx si hay puerto público."""
    links = [{
        "from_app": "mi-frontend", "from_env": "prod",
        "to_app": "shop-api", "to_env": "prod",
        "port_name": "http", "port_number": 8000, "alias": "SHOP_API",
    }]
    manifests = ls.generate_policies_for_env(
        "prod", links, {"shop-api": {"public": True, "vpn": False}}
    )
    yaml_text = manifests["shop-api"]
    assert "name: shop-api-links" in yaml_text
    assert "kubernetes.io/metadata.name: ingress-nginx" in yaml_text
    assert "app: mi-frontend" in yaml_text
    assert "port: 8000" in yaml_text
    assert "software-factory.io/generated: service-links" in yaml_text

    try:
        import yaml
        parsed = yaml.safe_load(yaml_text)
        assert parsed["kind"] == "NetworkPolicy"
        assert len(parsed["spec"]["ingress"]) == 2
    except ImportError:
        pass  # PyYAML opcional: la aserción textual ya cubre la estructura


def test_cross_env_link_uses_namespace_selector():
    """Un link dev→prod debe permitir desde el namespace del consumidor."""
    links = [{
        "from_app": "experimento", "from_env": "dev",
        "to_app": "modelo-inferencia", "to_env": "prod",
        "port_name": "http", "port_number": 8080, "alias": "MODELO",
    }]
    manifests = ls.generate_policies_for_env("prod", links, {})
    yaml_text = manifests["modelo-inferencia"]
    assert "kubernetes.io/metadata.name: dev" in yaml_text


def test_no_links_no_manifests():
    """Apps sin links no se tocan: el default-deny es opt-in gradual."""
    assert ls.generate_policies_for_env("prod", [], {}) == {}


def test_diagram_build():
    """El diagrama es un SELECT: nodos, aristas y grupos desde las colecciones."""
    apps = [
        {"name": "shop-api", "template": "fastapi", "environments": ["prod"],
         "domain_id": None, "exposure": {"type": "public"}, "status": "healthy"},
        {"name": "mi-frontend", "template": "vue3-spa", "environments": ["prod"],
         "domain_id": None, "exposure": {"type": "public"}, "status": "healthy"},
    ]
    links = [{
        "from_app": "mi-frontend", "from_env": "prod",
        "to_app": "shop-api", "to_env": "prod",
        "port_name": "http", "port_number": 8000, "alias": "SHOP_API",
        "visibility": "app-scoped",
    }]
    domains = [{"_id": "d1", "fqdn": "example.com", "is_default": True}]
    sites = [{"name": "pc-alice", "type": "local", "status": "online"}]

    diagram = ls.build_diagram(apps, links, domains, sites)

    node_ids = {n["id"] for n in diagram["nodes"]}
    assert {"internet", "vpn", "shop-api", "mi-frontend"} <= node_ids

    kinds = [e["kind"] for e in diagram["edges"]]
    assert "service-link" in kinds
    assert "exposure-public" in kinds

    group_ids = {g["id"] for g in diagram["groups"]}
    assert "domain:example.com" in group_ids
    assert "site:pc-alice" in group_ids

    # Apps sin domain_id caen al dominio default
    shop_node = next(n for n in diagram["nodes"] if n["id"] == "shop-api")
    assert shop_node["group"] == "domain:example.com"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL {name}: {e}")
    if failures:
        sys.exit(f"{failures} test(s) failed")
    print("ALL LINK_SERVICE TESTS PASSED")
