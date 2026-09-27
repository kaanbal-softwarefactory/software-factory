# Contributing to Kaanbal

Thank you for your interest in Kaanbal. This project welcomes bug reports, fixes,
documentation, translations, templates and features.

Issues and pull requests can be written in **English or Spanish**. Most existing
documentation is in Spanish; translations are especially welcome.

## Before you start

- **Security issues are not reported here.** Follow [SECURITY.md](SECURITY.md) instead.
- **Never put secrets in a commit, issue or pull request** — not even ones you think are
  expired. Use placeholders (`CHANGE_ME`) and, in tests and docs, reserved example values:
  `example.com`, `192.168.1.x` or `203.0.113.x`. Do not use real customer domains, names or
  server addresses.
- For anything larger than a small fix, open an issue first so we can agree on the approach
  before you invest time.

## Project layout

See the [README](README.md#repository-layout). The pieces you are most likely to touch:

| Area | Path | Stack |
|---|---|---|
| Control plane | `SOFTWARE_FACTORY/kaanbal-api` | Python, FastAPI, MongoDB |
| Console | `SOFTWARE_FACTORY/kaanbal-console` | Vue 3, Vite, Tailwind |
| Installer | `SOFTWARE_FACTORY/installer` | Python **standard library only**, vanilla JS |
| Templates | `SOFTWARE_FACTORY/kaanbal-templates` | see the [template spec](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) |
| MCP server | `SOFTWARE_FACTORY/kaanbal-api/app/mcp` (served at `/mcp`); stdio bridge in `SOFTWARE_FACTORY/kaanbal-mcp` | Python |
| GitOps baseline | `SOFTWARE_FACTORY/infra-gitops` | Kustomize, Argo CD |

## Set up and run the tests

```bash
# API (Python 3.11)
cd SOFTWARE_FACTORY/kaanbal-api
pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py'

# Installer — it must keep working with the standard library alone;
# PyYAML is only a test dependency
python -m pip install PyYAML==6.0.2
python -m unittest discover -s SOFTWARE_FACTORY/installer -p 'test_*.py'
bash -n install.sh && bash -n SOFTWARE_FACTORY/install.sh
node --check SOFTWARE_FACTORY/installer/static/app.js

# Console
cd SOFTWARE_FACTORY/kaanbal-console && npm ci && npm run build

# MCP server
cd SOFTWARE_FACTORY/kaanbal-mcp
pip install -r requirements.txt && python -m unittest discover -s tests
```

The pull request check runs the same commands, plus a secret scan of the tree.

## Making a change

1. Fork the repository and create a branch from `main`: `feat/<topic>`, `fix/<topic>`,
   `docs/<topic>`. Never push to `main` directly.
2. Keep each pull request to **one topic**. Small, reviewable changes are merged faster.
3. Write or update tests. A bug fix needs a test that fails without the fix.
4. Update the documentation and the [changelog](CHANGELOG.md) when behaviour changes.
5. Run the checks above before you push.
6. Open the pull request and fill in the template. Explain **why**, not only what.

### Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`,
with `feat`, `fix`, `docs`, `test`, `refactor`, `chore`. The body should say why the change
is needed and what it leaves unresolved.

### Rules that protect the platform

- **Every API endpoint needs an access rule.** Add it to
  `SOFTWARE_FACTORY/kaanbal-api/app/services/permissions.py`. The API denies any endpoint
  without a rule, and a test fails if you forget.
- **GitOps is the source of truth for deployments.** Do not patch a running cluster by hand;
  change the template or the installer and render again.
- **Migrations must be expand/contract.** A release may add a field but must not remove or
  rename the one the previous release reads.
- **The installer depends on the Python standard library only.** Do not add `pip` packages to it.
- **Secrets never live in Git.** They belong in Vault and reach the app as environment variables.

## Templates

A template is the community's unit of contribution. Read the
[template spec](SOFTWARE_FACTORY/docs/TEMPLATE_SPEC.md) and make sure it passes the platform's
validation cycle before proposing it.

## Working with AI coding assistants

The repository ships rules for assistants in [AGENTS.md](AGENTS.md) and `.cursor/`. Using an
assistant is fine; you remain responsible for what you submit. Review its output, run the
tests, and never paste credentials into a conversation.

## Licensing of contributions

Kaanbal is licensed under the [Apache License 2.0](LICENSE). By submitting a contribution you
agree that it is licensed under the same terms, as described in section 5 of the license.
You may also add a `Signed-off-by:` line (`git commit -s`) to certify the
[Developer Certificate of Origin](https://developercertificate.org/); it is welcome but not required.

## Conduct

Be respectful and constructive. Assume good faith, keep discussion focused on the work, and
help newcomers. Harassment and personal attacks are not tolerated, and maintainers may
remove content or restrict participation to protect the community.
