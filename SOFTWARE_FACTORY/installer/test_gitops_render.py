"""Tests del renderizador del baseline de infra-gitops."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gitops_render as gr  # noqa: E402

SF_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFRA = os.path.join(SF_ROOT, "infra-gitops")

BASE_CFG = {
    "domain": "acmeplatform.site",
    "github_org": "acme-org",
    "docker_user": "acme-dockerhub",
    "tailscale_dns": "example.ts.net",
    "tailscale_id": "kOAuthId",
    "tailscale_secret": "tskey-secret",
    "api_tag": "bootstrap-abc1234",
    "console_tag": "bootstrap-abc1234",
}


class ConditionalTests(unittest.TestCase):
    def test_if_keeps_branch_when_flag_true(self):
        text = "a\n# @kaanbal:if F\nb\n# @kaanbal:endif\nc\n"
        self.assertEqual(gr.apply_conditionals(text, {"F": True}), "a\nb\nc\n")

    def test_if_drops_branch_when_flag_false(self):
        text = "a\n# @kaanbal:if F\nb\n# @kaanbal:endif\nc\n"
        self.assertEqual(gr.apply_conditionals(text, {"F": False}), "a\nc\n")

    def test_else_branch(self):
        text = "# @kaanbal:if F\nyes\n# @kaanbal:else\nno\n# @kaanbal:endif\n"
        self.assertEqual(gr.apply_conditionals(text, {"F": False}), "no\n")

    def test_unknown_flag_is_an_error(self):
        with self.assertRaises(gr.RenderError):
            gr.apply_conditionals("# @kaanbal:if NOPE\nx\n# @kaanbal:endif\n", {})

    def test_unbalanced_block_is_an_error(self):
        with self.assertRaises(gr.RenderError):
            gr.apply_conditionals("# @kaanbal:if F\nx\n", {"F": True})


class SubstitutionTests(unittest.TestCase):
    def test_replaces_known_vars(self):
        out = gr.substitute("host: a.${KAANBAL_DOMAIN}", {"KAANBAL_DOMAIN": "d.mx"})
        self.assertEqual(out, "host: a.d.mx")

    def test_missing_var_is_an_error(self):
        with self.assertRaises(gr.RenderError):
            gr.substitute("${KAANBAL_NOPE}", {})

    def test_leaves_shell_and_argocd_syntax_alone(self):
        text = "name: '{{path[1]}}-prod'\nrun: $HOME/bin\n"
        self.assertEqual(gr.substitute(text, {}), text)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.rules = gr.load_baseline(INFRA)

    def test_core_paths_are_included(self):
        for path in [
            "apps/kaanbal-api/base/deployment.yaml",
            "apps/kaanbal-console/overlays/prod/kustomization.yaml",
            "core/config/system-config.yaml",
            "argocd/bootstrap/app-of-apps.yaml",
            "argocd/applicationsets/apps-generator.yaml",
        ]:
            self.assertTrue(gr.path_included(path, self.rules), path)

    def test_legacy_apps_are_excluded(self):
        for path in [
            "apps/shop/base/ingress.yaml",
            "apps/homepage/overlays/prod/kustomization.yaml",
            "apps/agencia-de-autos/base/ingress.yaml",
            "apps/por1/base/ingress.yaml",
            "terraform/main.tf",
            "argocd/applications/vault.yaml",
            "apps/cloudflared/base/deployment.yaml",
        ]:
            self.assertFalse(gr.path_included(path, self.rules), path)

    def test_engine_dev_overlays_are_excluded(self):
        self.assertFalse(
            gr.path_included("apps/kaanbal-api/overlays/dev/kustomization.yaml", self.rules)
        )

    def test_tailscale_operator_follows_its_credentials(self):
        path = "apps/tailscale-operator/base/deployment.yaml"
        with_ts = gr.load_baseline(INFRA, {"TAILSCALE": True})
        without = gr.load_baseline(INFRA, {"TAILSCALE": False})
        self.assertTrue(gr.path_included(path, with_ts))
        self.assertFalse(gr.path_included(path, without))

    def test_the_placeholder_oauth_secret_is_never_published(self):
        for flags in ({"TAILSCALE": True}, {"TAILSCALE": False}):
            self.assertFalse(gr.path_included(
                "apps/tailscale-operator/base/secret.yaml",
                gr.load_baseline(INFRA, flags)))

    def test_unknown_condition_in_the_baseline_is_an_error(self):
        root = tempfile.mkdtemp(prefix="kaanbal-baseline-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        with open(os.path.join(root, gr.BASELINE_FILE), "w", encoding="utf-8") as fh:
            fh.write("?NOPE apps/**\n")
        with self.assertRaises(gr.RenderError):
            gr.load_baseline(root, {"TAILSCALE": True})


class RenderTreeTests(unittest.TestCase):
    def _render(self, **overrides):
        cfg = dict(BASE_CFG)
        cfg.update(overrides)
        context, flags = gr.build_context(cfg)
        tmp = tempfile.mkdtemp(prefix="kaanbal-render-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        written = gr.render_tree(INFRA, tmp, context, flags)
        return tmp, written

    def _read(self, root, relpath):
        with open(os.path.join(root, *relpath.split("/")), encoding="utf-8") as fh:
            return fh.read()

    def test_no_placeholder_survives_the_render(self):
        root, written = self._render()
        for relpath in written:
            if not relpath.endswith((".yaml", ".yml", ".json")):
                continue
            body = self._read(root, relpath)
            self.assertNotIn("${KAANBAL_", body, relpath)
            self.assertNotIn("@kaanbal:", body, relpath)

    def test_no_legacy_hardcode_survives_the_render(self):
        root, written = self._render()
        for relpath in written:
            body = self._read(root, relpath)
            for needle in ["legacy-org", "DOCKERHUB_USER", "kaanbal-console.local"]:
                self.assertNotIn(needle, body, f"{needle} en {relpath}")

    def test_public_mode_publishes_engine_hosts(self):
        root, _ = self._render()
        console = self._read(root, "apps/kaanbal-console/base/ingress.yaml")
        self.assertIn("kaanbal.acmeplatform.site", console)
        self.assertIn("kaanbal-console.acmeplatform.site", console)
        api = self._read(root, "apps/kaanbal-api/base/ingress.yaml")
        self.assertIn("kaanbal-api.acmeplatform.site", api)

    def test_tailnet_mode_drops_the_public_ingress(self):
        root, written = self._render(console_exposure="tailnet")
        self.assertNotIn("apps/kaanbal-console/base/ingress.yaml", written)
        kust = self._read(root, "apps/kaanbal-console/base/kustomization.yaml")
        self.assertNotIn("ingress.yaml", kust)
        svc = self._read(root, "apps/kaanbal-console/base/service.yaml")
        self.assertIn("tailscale.com/expose", svc)

    def test_every_core_service_has_its_own_kaanbal_name(self):
        # Una app de usuario puede llamarse "shop" o "api"; el core no debe
        # depender de nombres genéricos que cualquiera podría reclamar.
        root, _ = self._render()
        hosts = {
            "consola": ("apps/kaanbal-console/base/ingress.yaml",
                        "kaanbal-console.acmeplatform.site"),
            "atajo": ("apps/kaanbal-console/base/ingress.yaml",
                      "kaanbal.acmeplatform.site"),
            "api": ("apps/kaanbal-api/base/ingress.yaml",
                    "kaanbal-api.acmeplatform.site"),
            "agente": ("apps/kaanbal-agent/base/ingress.yaml",
                       "kaanbal-agent.acmeplatform.site"),
        }
        for service, (relpath, host) in hosts.items():
            with self.subTest(service=service):
                self.assertIn(f"host: {host}", self._read(root, relpath))

    def test_the_agent_is_a_service_of_its_own(self):
        root, written = self._render()
        self.assertIn("apps/kaanbal-agent/base/deployment.yaml", written)
        kust = self._read(root, "apps/kaanbal-agent/overlays/prod/kustomization.yaml")
        self.assertIn("newName: acme-dockerhub/kaanbal-agent", kust)

    def test_the_agent_follows_the_console_exposure_by_default(self):
        root, written = self._render(console_exposure="tailnet")
        self.assertNotIn("apps/kaanbal-agent/base/ingress.yaml", written)
        svc = self._read(root, "apps/kaanbal-agent/base/service.yaml")
        self.assertIn("tailscale.com/expose", svc)

    def test_the_agent_can_be_private_while_the_console_is_public(self):
        root, written = self._render(agent_exposure="tailnet")
        self.assertIn("apps/kaanbal-console/base/ingress.yaml", written)
        self.assertNotIn("apps/kaanbal-agent/base/ingress.yaml", written)
        self.assertIn("tailscale.com/expose",
                      self._read(root, "apps/kaanbal-agent/base/service.yaml"))

    def test_images_point_at_the_real_dockerhub_user(self):
        root, _ = self._render()
        kust = self._read(root, "apps/kaanbal-api/overlays/prod/kustomization.yaml")
        self.assertIn("newName: acme-dockerhub/kaanbal-api", kust)
        self.assertIn("newTag: bootstrap-abc1234", kust)

    def test_argocd_points_at_the_client_repo(self):
        root, _ = self._render()
        boot = self._read(root, "argocd/bootstrap/app-of-apps.yaml")
        self.assertIn(
            "repoURL: https://github.com/acme-org/infra-gitops.git", boot
        )

    def test_secrets_are_not_shipped_in_git(self):
        _, written = self._render()
        self.assertNotIn("apps/kaanbal-api/base/secret.yaml", written)
        self.assertNotIn("apps/datastore/base/secret.yaml", written)
        self.assertNotIn("apps/tailscale-operator/base/secret.yaml", written)

    def test_without_tailscale_its_operator_stays_out(self):
        _, written = self._render(tailscale_id="", tailscale_secret="")
        self.assertFalse([p for p in written if p.startswith("apps/tailscale-operator/")])
        # El resto del engine se publica igual: Tailscale es opcional.
        self.assertIn("apps/kaanbal-console/base/ingress.yaml", written)

    def test_tailscale_ready_overrides_the_mere_presence_of_keys(self):
        # Hay credenciales, pero el instalador comprobó que la ACL del tailnet
        # no concede la etiqueta del operador: no debe publicarse.
        root, written = self._render(tailscale_ready=False)
        self.assertFalse([p for p in written if p.startswith("apps/tailscale-operator/")])
        # Y su Application tampoco, o ArgoCD quedaría apuntando a una ruta
        # inexistente y reportaría la célula en error de forma permanente.
        boot = self._read(root, "argocd/bootstrap/app-of-apps.yaml")
        self.assertNotIn("name: tailscale-operator", boot)

    def test_with_tailscale_its_application_is_declared(self):
        root, _ = self._render()
        boot = self._read(root, "argocd/bootstrap/app-of-apps.yaml")
        self.assertIn("name: tailscale-operator", boot)

    def test_no_ingress_survives_without_a_controller_to_serve_it(self):
        # La IngressClass "tailscale" solo existe si su operador está desplegado.
        # Publicar un Ingress que la pide deja el objeto huérfano: aceptado por
        # la API y jamás servido, con la app eternamente en Progressing.
        root, written = self._render(tailscale_ready=False)
        self.assertNotIn("apps/vault/base/ingress-tailscale.yaml", written)
        kust = self._read(root, "apps/vault/base/kustomization.yaml")
        self.assertNotIn("ingress-tailscale.yaml", kust)

    def test_vpn_only_console_without_tailscale_is_refused(self):
        # Sin operador de Tailscale y sin Ingress público la consola quedaría
        # instalada y a la vez inalcanzable; mejor fallar antes de publicar.
        cfg = dict(BASE_CFG, console_exposure="tailnet",
                   tailscale_id="", tailscale_secret="")
        with self.assertRaises(gr.RenderError):
            gr.build_context(cfg)

    def test_build_context_requires_the_essentials(self):
        for missing in ["domain", "github_org", "docker_user"]:
            cfg = dict(BASE_CFG)
            cfg[missing] = ""
            with self.assertRaises(gr.RenderError):
                gr.build_context(cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
