"""tools/core-upgrade.sh: dónde vive el proyecto y a dónde apunta el checkout de un nodo.

Cuando el proyecto se mudó de repositorio, el `origin` del checkout de cada nodo
seguía apuntando al anterior: la siguiente actualización habría bajado de allí, y
la célula quedaba atada a un repo que nadie mantiene. Estas pruebas ejecutan las
funciones reales del script (no una copia) contra un repositorio git temporal.
"""

import os
import shutil
import subprocess
import sys
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


@unittest.skipUnless(BASH and GIT, "bash y git son necesarios")
class CheckoutDriftTests(unittest.TestCase):
    """Un checkout a medias (archivos que git no pudo reescribir) no se despliega."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kaanbal-checkout-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = Path(self.tmp)
        api = self.source / "SOFTWARE_FACTORY" / "kaanbal-api"
        api.mkdir(parents=True)
        (api / "acl.py").write_text("nuevo\n", encoding="utf-8")
        run = lambda *args: subprocess.run([GIT, "-C", str(self.source), *args], check=True, capture_output=True)
        run("init", "--quiet")
        run("add", "-A")
        run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "base")

    def _drift(self):
        result = bash(f'SOURCE_DIR="{self.source.as_posix()}"; '
                      'SYNC_REPOS=(kaanbal-api kaanbal-console kaanbal-templates); checkout_drift')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_a_clean_checkout_has_no_drift(self):
        self.assertEqual(self._drift(), "")

    def test_a_file_git_could_not_rewrite_is_reported(self):
        """Lo que pasó: acl.py quedó en su versión vieja y el upgrade la publicó."""
        (self.source / "SOFTWARE_FACTORY" / "kaanbal-api" / "acl.py").write_text("viejo\n", encoding="utf-8")
        self.assertIn("SOFTWARE_FACTORY/kaanbal-api/acl.py", self._drift())

    def test_a_leftover_file_inside_what_gets_published_is_reported(self):
        (self.source / "SOFTWARE_FACTORY" / "kaanbal-api" / "tools.py").write_text("x\n", encoding="utf-8")
        self.assertIn("?? SOFTWARE_FACTORY/kaanbal-api/tools.py", self._drift())

    def test_a_loose_file_outside_what_gets_published_is_fine(self):
        (self.source / "notas-del-nodo.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(self._drift(), "")

    @unittest.skipUnless(sys.platform.startswith("linux"), "los dueños de archivos se prueban en Linux")
    def test_reclaiming_a_checkout_that_is_already_its_owners_changes_nothing(self):
        import getpass

        result = bash(f'SOURCE_DIR="{self.source.as_posix()}"; reclaim_checkout "{getpass.getuser()}"; echo fin')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "fin")


# kubectl falso: cada ConfigMap es una carpeta en $FAKE_KUBE con un archivo por clave.
FAKE_KUBECTL = r'''
cmd=$1; shift
case "$cmd" in
  create)
    name=$2; shift 2
    if [[ -n "${FAKE_KUBE_FORBIDDEN:-}" ]]; then
      echo "Error from server (Forbidden): configmaps is forbidden: cannot create resource" >&2; exit 1
    fi
    if [[ -d "$FAKE_KUBE/$name" ]]; then
      echo "Error from server (AlreadyExists): configmaps \"$name\" already exists" >&2; exit 1
    fi
    mkdir -p "$FAKE_KUBE/$name"
    for arg in "$@"; do
      case "$arg" in --from-literal=*) kv=${arg#--from-literal=}; printf '%s' "${kv#*=}" > "$FAKE_KUBE/$name/${kv%%=*}";; esac
    done ;;
  get)
    name=$2; shift 2
    [[ -d "$FAKE_KUBE/$name" ]] || { echo "Error from server (NotFound)" >&2; exit 1; }
    for arg in "$@"; do
      case "$arg" in jsonpath=*) key=${arg#jsonpath=\{.data.}; key=${key%\}}; cat "$FAKE_KUBE/$name/$key" 2>/dev/null;; esac
    done ;;
  delete)
    rm -rf "$FAKE_KUBE/$2" ;;
esac
'''


@unittest.skipUnless(BASH, "bash es necesario")
class UpgradeLockTests(unittest.TestCase):
    """Dos upgrades a la vez (botón de la consola y script del nodo) se pisaban los tags."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kaanbal-lock-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.kube = Path(self.tmp, "kube")
        self.kube.mkdir()
        self.fake = Path(self.tmp, "kubectl.sh")
        self.fake.write_text(FAKE_KUBECTL, encoding="utf-8", newline="\n")
        self.lock = self.kube / "kaanbal-upgrade-lock"

    def _run(self, snippet, **env):
        prelude = f'NS=prod; kubectl() {{ bash "{self.fake.as_posix()}" "$@"; }}; '
        return bash(prelude + snippet, env={"FAKE_KUBE": self.kube.as_posix(),
                                            "KAANBAL_UPGRADE_HOLDER": "este-upgrade", **env})

    def _hold(self, holder, since):
        self.lock.mkdir()
        (self.lock / "holder").write_text(holder, encoding="utf-8")
        (self.lock / "since").write_text(str(since), encoding="utf-8")

    def test_it_takes_the_lock_while_running_and_frees_it_on_exit(self):
        result = self._run('acquire_upgrade_lock; echo "durante=$(cat "$FAKE_KUBE/kaanbal-upgrade-lock/holder")"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("durante=este-upgrade", result.stdout)
        self.assertFalse(self.lock.exists(), "al salir, el candado se libera")

    def test_it_also_frees_it_when_the_upgrade_fails(self):
        result = self._run('acquire_upgrade_lock; die "falló el build"')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.lock.exists())

    def test_a_second_upgrade_stops_and_leaves_the_first_ones_lock(self):
        import time

        self._hold("kaanbal-upgrade-123-abc", int(time.time()) - 300)
        result = self._run('acquire_upgrade_lock; echo "no debería llegar aquí"')
        self.assertEqual(result.returncode, 1)
        self.assertIn("Ya hay un upgrade en curso (kaanbal-upgrade-123-abc", result.stderr)
        self.assertNotIn("no debería llegar", result.stdout)
        self.assertEqual((self.lock / "holder").read_text(encoding="utf-8"), "kaanbal-upgrade-123-abc")

    def test_an_abandoned_lock_is_released_and_taken(self):
        self._hold("pod-que-murio", 1)
        result = self._run('acquire_upgrade_lock; echo "ahora=$(cat "$FAKE_KUBE/kaanbal-upgrade-lock/holder")"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("abandonado", result.stderr)
        self.assertIn("ahora=este-upgrade", result.stdout)

    def test_without_permission_it_warns_and_goes_on(self):
        """La célula que todavía no tiene el permiso lo recibe justo con este upgrade."""
        result = self._run('acquire_upgrade_lock; echo SIGUE', FAKE_KUBE_FORBIDDEN="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SIGUE", result.stdout)
        self.assertIn("sin él", result.stderr)

    def test_only_the_passes_that_write_take_the_lock(self):
        cases = {
            ("all", ""): 1, ("all", "1"): 0, ("sync", ""): 1, ("sync", "1"): 0,
            ("build", ""): 0, ("promote", ""): 0, ("rollback", ""): 0,
            ("verify", ""): 1, ("snapshot", ""): 1,
        }
        for (phase, reexec), expected in cases.items():
            result = self._run(f'PHASE={phase}; needs_upgrade_lock', KAANBAL_UPGRADE_REEXEC=reexec)
            self.assertEqual(result.returncode, expected, f"PHASE={phase} REEXEC={reexec!r}")


if __name__ == "__main__":
    unittest.main()
