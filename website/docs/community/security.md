# Security

!!! abstract "Summary"
    Report vulnerabilities **privately** — never in a public issue, PR, or
    Discussion. The authoritative policy is
    [`SECURITY.md`](https://github.com/SoundMindsAI/relyloop/blob/main/SECURITY.md).

## Reporting a vulnerability

!!! danger "Do not open a public issue for an unpatched vulnerability"
    Use a private channel so a fix can ship before details are public.

- **Preferred** — GitHub's [private vulnerability
  reporting](https://github.com/SoundMindsAI/relyloop/security/advisories/new):
  on the repo, **Security → Report a vulnerability**. End-to-end private to
  the maintainers.
- **Backup** — email `security@soundminds.ai`. Ask in your first message if
  you need a PGP-encrypted reply.

Include a description and impact, a reproduction (a local `make up` stack is
easiest for us), the version/commit you tested, and whether you want credit.

## What to expect

- Acknowledgement within **3 business days**.
- An initial assessment (accept / decline with reasoning) within **10 business
  days**.
- A fix targeted within **90 days** of acknowledgement; complex issues get a
  written timeline.
- Coordinated disclosure — by default a GitHub Security Advisory with credit, a
  CVE request, and the patched release tagged.

The project is maintained by soundminds.ai employees during US Eastern
business hours; there is no 24/7 PSIRT.

## Supported versions

RelyLoop is pre-1.0 alpha. Only the latest minor release receives security
fixes — upgrade to pick up security work.

| Version | Supported |
|---|---|
| `v0.1.x` (MVP1) | yes |
| `< v0.1.0` | no |

## Scope

**In scope:** the `relyloop` codebase, the images it publishes (e.g.
`relyloop/api`), and operational docs that could materially mislead an operator
into an insecure configuration.

**Out of scope:** operator-deployed clusters (report upstream), third-party LLM
providers reachable via `OPENAI_BASE_URL` (report to the provider), the
operator's own Git provider / config repo / CI, and issues that require an
attacker to already hold a credential or shell on a trusted host. Full scope
in [`SECURITY.md`](https://github.com/SoundMindsAI/relyloop/blob/main/SECURITY.md).
