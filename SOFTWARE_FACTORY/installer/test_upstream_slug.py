"""De qué repositorio salió el checkout desde el que corre el instalador.

La procedencia de una célula es un SHA *y* el repo donde ese SHA existe. Sin lo
segundo, cuando el proyecto se mudó de repositorio nadie podía saber contra qué
historial comparar el commit instalado.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class SlugFromRemoteTests(unittest.TestCase):
    def setUp(self):
        import server

        self.slug = server.slug_from_remote

    def test_https(self):
        self.assertEqual(self.slug("https://github.com/acme/repo.git"), "acme/repo")
        self.assertEqual(self.slug("https://github.com/acme/repo"), "acme/repo")
        self.assertEqual(self.slug("https://github.com/acme/repo.git\n"), "acme/repo")

    def test_ssh(self):
        self.assertEqual(self.slug("git@github.com:acme/repo.git"), "acme/repo")

    def test_credentials_in_the_url_never_reach_the_provenance(self):
        got = self.slug("https://x-access-token:ghs_SECRET@github.com/acme/repo.git")
        self.assertEqual(got, "acme/repo")
        self.assertNotIn("SECRET", got)

    def test_anything_that_is_not_github_is_not_an_official_source(self):
        for value in ("", None, "/srv/checkout", "https://gitlab.com/acme/repo.git", "https://github.com/acme"):
            self.assertEqual(self.slug(value), "", value)


if __name__ == "__main__":
    unittest.main()
