"""Regresiones del publicador de repos core."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gitops_publish as gp  # noqa: E402


class PublishSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = tempfile.TemporaryDirectory()
        with open(os.path.join(self.source.name, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# Kaanbal\n")

    def tearDown(self):
        self.source.cleanup()

    def test_initializes_repo_before_configuring_local_identity(self):
        commands = []

        def run(command, timeout=300):
            commands.append(command)
            if "ls-remote" in command:
                return 0, ""
            if "rev-parse HEAD" in command:
                return 0, "abc1234\n"
            return 0, ""

        sha, error = gp.publish_source(
            run, "token", "org", "kaanbal-api", self.source.name)

        self.assertIsNone(error)
        self.assertEqual(sha, "abc1234")
        init = next(i for i, c in enumerate(commands) if "git init -b main" in c)
        email = next(i for i, c in enumerate(commands) if "git config user.email" in c)
        name = next(i for i, c in enumerate(commands) if "git config user.name" in c)
        commit = next(i for i, c in enumerate(commands) if "git commit -m" in c)
        self.assertLess(init, email)
        self.assertLess(email, name)
        self.assertLess(name, commit)

    def test_identity_configuration_failure_is_reported_before_commit(self):
        commands = []

        def run(command, timeout=300):
            commands.append(command)
            if "ls-remote" in command:
                return 0, ""
            if "git config user.email" in command:
                return 1, "fatal: not in a git directory"
            return 0, ""

        sha, error = gp.publish_source(
            run, "token", "org", "kaanbal-api", self.source.name)

        self.assertEqual(sha, "")
        self.assertIn("config user.email", error)
        self.assertFalse(any("git commit -m" in c for c in commands))


if __name__ == "__main__":
    unittest.main(verbosity=2)
