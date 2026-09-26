# Security Policy

Kaanbal installs and operates infrastructure: it holds credentials for GitHub, Docker Hub,
Cloudflare and Tailscale, deploys workloads, and administers a Vault. We take vulnerability
reports seriously.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| Earlier than 1.0.0 (`ProyectosUniUAEH/software-factory`) | No — follow the [migration guide](docs/guides/MIGRATION.md) |

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for a security problem.**

Report it privately through GitHub:

1. Go to the **Security** tab of this repository.
2. Choose **Report a vulnerability**.

That creates a private advisory that only you and the maintainers can see. If the option is
not available, open a public issue that says only that you need a private channel for a
security report — **without any technical detail** — and we will contact you.

Include, as far as you can:

- the affected component and version or commit;
- steps to reproduce, or a proof of concept;
- the impact you expect;
- whether you believe it is already being exploited.

## What to expect

This is a small team, so these are targets and not guarantees:

- **Acknowledgement** within 5 business days.
- **An initial assessment** within 10 business days.
- **A fix or a mitigation plan** communicated before public disclosure. We will agree a
  disclosure date with you, generally within 90 days of your report, and credit you in the
  advisory if you wish.

## Scope

In scope: the code, manifests and scripts in this repository — the API, the console, the
installer, the MCP server, the templates and the GitOps baseline.

Out of scope: vulnerabilities in third-party software that Kaanbal installs (K3s, Argo CD,
Vault, Tailscale and so on) unless Kaanbal configures it in an insecure way; social
engineering; denial of service through volume; and findings that require a compromised
administrator account or physical access to the server.

## If you find a leaked credential

Report it privately, exactly as above, even if it looks like a test value or is old. Do not use
it and do not try to find out whether it is valid. Maintainers will rotate it.

## Good faith

We will not pursue action against researchers who make a good-faith effort to follow this
policy: test only against installations you own, do not access data that is not yours, do not
degrade services, and give us reasonable time to respond before disclosing.

## Hardening your installation

- Keep the installer's temporary URL private. Its token controls the installer while it is active.
- Back up Vault's recovery material **off the server**. A copy in the same cluster is not a backup.
- Issue personal access tokens with the minimum scope, set an expiry, and revoke what you no longer use.
- Prefer the private (Tailscale) or LAN exposure for anything that does not need to be public.
- Pin a commit or tag when you install or upgrade, and read the changelog before upgrading.
