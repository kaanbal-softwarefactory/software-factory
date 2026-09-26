"""Robustez del constructor de imágenes del core.

Un push rechazado por el rate limit de Docker Hub tumbaba la instalación entera
después de veinte minutos de trabajo válido, y el mensaje de error mostraba el
progreso del `git clone` en vez de la causa.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import corebuild  # noqa: E402

REGISTRY_REJECTION = """Compressing objects:  98% (49/50)
Compressing objects: 100% (50/50), done.
Total 55 (delta 0), reused 55 (delta 0), pack-reused 0 (from 0)
error checking push permissions -- make sure you entered the correct tag name, \
and that you are authenticated correctly, and try again: checking push permission \
for "index.docker.io/acme/kaanbal-api:prod-cae2dd1": UNAUTHORIZED: authentication required
"""


class TransientTests(unittest.TestCase):
    def test_registry_rejection_is_worth_retrying(self):
        self.assertTrue(corebuild.is_transient(REGISTRY_REJECTION))

    def test_rate_limit_is_worth_retrying(self):
        self.assertTrue(corebuild.is_transient("TOOMANYREQUESTS: too many requests"))

    def test_a_broken_dockerfile_is_not(self):
        self.assertFalse(corebuild.is_transient(
            "error building image: failed to execute command: /bin/sh -c npm run build"))

    def test_empty_output_is_not_transient(self):
        self.assertFalse(corebuild.is_transient(""))


class SummaryTests(unittest.TestCase):
    def test_the_cause_survives_the_clone_noise(self):
        summary = corebuild.summarize_failure(REGISTRY_REJECTION)
        self.assertIn("UNAUTHORIZED", summary)
        self.assertNotIn("Compressing objects", summary)

    def test_a_build_error_is_reported_verbatim(self):
        detail = ("Counting objects: 100% (50/50), done.\n"
                  "error building image: command failed: npm run build\n")
        self.assertEqual(
            corebuild.summarize_failure(detail),
            "error building image: command failed: npm run build")

    def test_without_logs_it_says_so(self):
        self.assertEqual(corebuild.summarize_failure(""), "(sin logs)")

    def test_only_noise_still_returns_something(self):
        self.assertTrue(corebuild.summarize_failure("Compressing objects: 10% (1/10)\n"))

    def test_the_summary_is_bounded(self):
        self.assertLessEqual(len(corebuild.summarize_failure("error: " + "x" * 900)), 300)


class ComponentTests(unittest.TestCase):
    def test_the_three_core_images_are_built(self):
        names = [c["name"] for c in corebuild.CORE_COMPONENTS]
        self.assertEqual(names, ["kaanbal-api", "kaanbal-console", "kaanbal-agent"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
