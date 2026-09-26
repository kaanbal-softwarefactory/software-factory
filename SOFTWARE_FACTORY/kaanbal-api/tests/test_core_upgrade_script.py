"""tools/core-upgrade.sh: dónde vive el proyecto y a dónde apunta el checkout de un nodo.

Cuando el proyecto se mudó de repositorio, el `origin` del checkout de cada nodo
seguía apuntando al anterior: la siguiente actualización habría bajado de allí, y
la célula quedaba atada a un repo que nadie mantiene. Estas pruebas ejecutan las
funciones reales del script (no una copia) contra un repositorio git temporal.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "core-upgrade.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")

LEGACY = "https://github.com/ProyectosUniUAEH/software-factory.git"
OFFICIAL = "https://github.com/kaanbal-softwarefactory/software-factory.git"


def script_functions() -> str:
    """Desde log() hasta antes del primer `command -v`: helpers y constantes, sin efectos."""
    text = SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index("log()  {")
    end = text.index("command -v kubectl")
    return text[start:end]


def bash(snippet: str, env=None):
    return subprocess.run(
        [BASH, "-c", script_functions() + snippet],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        env={**os.environ, **(env or {})},
    )


@unittest.skipUnless(BASH and GIT, "bash y git son necesarios")
class SlugOfTests(unittest.TestCase):
    def _slug(self, url):
        out = subprocess.run(
            [BASH, "-c", script_functions() + 'slug_of "$1"', "_", url],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_https_and_ssh_remotes(self):
        self.assertEqual(self._slug("https://github.com/acme/repo.git"), "acme/repo")
        self.assertEqual(self._slug("https://github.com/acme/repo"), "acme/repo")
        self.assertEqual(self._slug("git@github.com:acme/repo.git"), "acme/repo")

    def test_a_token_in_the_url_is_not_part_of_the_slug(self):
        got = self._slug("https://x-access-token:SECRETO@github.com/acme/repo.git")
        self.assertEqual(got, "acme/repo")

    def test_a_local_path_is_not_an_official_source(self):
        self.assertEqual(self._slug("/srv/checkout"), "")
        self.assertEqual(self._slug(""), "")


@unittest.skipUnless(BASH and GIT, "bash y git son necesarios")
class MigrateOriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kaanbal-origin-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = Path(self.tmp).as_posix()
        subprocess.run([GIT, "init", "--quiet", self.source], check=True, capture_output=True)

    def _set_origin(self, url):
        subprocess.run([GIT, "-C", self.source, "remote", "add", "origin", url], check=True, capture_output=True)

    def _origin(self):
        out = subprocess.run([GIT, "-C", self.source, "remote", "get-url", "origin"],
                             check=True, capture_output=True, text=True)
        return out.stdout.strip()

    def _migrate(self, slug, extra_env=None):
        return bash(
            f'SOURCE_DIR="{self.source}"; UPSTREAM_SLUG="{slug}"; migrate_origin',
            env=extra_env,
        )

    def test_an_origin_pointing_to_the_previous_repo_moves_to_the_official_one(self):
        self._set_origin(LEGACY)
        result = self._migrate("ProyectosUniUAEH/software-factory")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._origin(), OFFICIAL)
        self.assertIn("origin deja de apuntar a ProyectosUniUAEH/software-factory", result.stdout)

    def test_the_comparison_ignores_case(self):
        self._set_origin(LEGACY)
        self._migrate("proyectosuniuaeh/SOFTWARE-FACTORY")
        self.assertEqual(self._origin(), OFFICIAL)

    def test_a_fork_is_never_touched(self):
        """Quien instaló desde su propio fork no debe terminar apuntando al oficial."""
        self._set_origin("https://github.com/acme/fork.git")
        self._migrate("acme/fork")
        self.assertEqual(self._origin(), "https://github.com/acme/fork.git")

    def test_the_official_repo_stays_as_it_is(self):
        self._set_origin(OFFICIAL)
        self._migrate("kaanbal-softwarefactory/software-factory")
        self.assertEqual(self._origin(), OFFICIAL)

    def test_it_can_be_switched_off(self):
        self._set_origin(LEGACY)
        self._migrate("ProyectosUniUAEH/software-factory", extra_env={"KAANBAL_KEEP_ORIGIN": "1"})
        self.assertEqual(self._origin(), LEGACY)

    def test_the_official_repo_is_declared_once_and_matches_the_api(self):
        """core-upgrade.sh y core_release.py deben apuntar al mismo lugar."""
        import re
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import types

        sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))
        from app.services import core_release

        declared = re.search(r"^DEFAULT_UPSTREAM=(\S+)$", script_functions(), re.M).group(1)
        self.assertEqual(declared, core_release.DEFAULT_UPSTREAM)
        legacy = re.search(r"^LEGACY_UPSTREAM=(\S+)$", script_functions(), re.M).group(1)
        self.assertEqual(legacy, core_release.LEGACY_UPSTREAM)


if __name__ == "__main__":
    unittest.main()
