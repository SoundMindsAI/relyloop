# Security Policy

We take security seriously. If you believe you have found a vulnerability in
RelyLoop, please report it privately so we can investigate and ship a fix
before details become public.

## Supported versions

RelyLoop is pre-1.0 alpha software. Only the latest minor release receives
security fixes. Older versions are not patched — upgrade to the latest
release to pick up security work.

| Version | Supported |
|---|---|
| `v0.1.x` (MVP1) | yes |
| `< v0.1.0` | no |

## Reporting a vulnerability

**Preferred:** use GitHub's [private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
on this repository — click **Security** → **Report a vulnerability**. The
channel is end-to-end private to the project maintainers.

**Backup:** email `security@soundminds.ai`. If you need an encrypted reply,
say so in your first message and we will arrange a PGP-encrypted thread.

Please include:

- A description of the vulnerability and its impact.
- A reproduction (minimal failing input, sequence of API calls, or steps in
  the UI). Reproductions against a local `make up` stack are easiest for us
  to act on.
- The version (`git rev-parse HEAD` or the release tag) you tested.
- Whether you would like credit in the public advisory.

Please **do not** open a public GitHub issue, draft PR, or Discussion thread
for an unpatched vulnerability.

## What to expect

- We will acknowledge your report within **3 business days**.
- We will share an initial assessment (accept / decline with reasoning) within
  **10 business days**.
- We aim to ship a fix within **90 days** of acknowledgement. Complex issues
  may need longer; if so, we will share a written timeline with you.
- We will coordinate the public-disclosure date with you. By default we
  publish a [GitHub Security Advisory](https://docs.github.com/code-security/security-advisories/working-with-repository-security-advisories/about-repository-security-advisories)
  with credit to the reporter, request a CVE, and tag the patched release.

The project is currently maintained by soundminds.ai employees. There is no
24/7 PSIRT. Reports are triaged during the maintainers' working hours
(US Eastern Time business days).

## Scope

**In scope:**

- The `relyloop` codebase in this repository.
- Container images published under `relyloop/api` and any other images this
  repository ships.
- The published [`docs/03_runbooks/`](docs/03_runbooks/) operational guidance,
  if it materially misleads operators into an insecure configuration.

**Out of scope:**

- Operator-deployed clusters (Elasticsearch, OpenSearch, Postgres, Redis) —
  report those to the upstream projects.
- Third-party LLM providers reachable via the `OPENAI_BASE_URL` setting —
  report those to the provider.
- The operator's own Git provider account, config repo, or CI — these are
  the operator's surface, not RelyLoop's.
- Vulnerabilities that require an attacker to already have a credential or
  shell on the host (e.g., "if I can `docker exec` into the api container, I
  can read the database password"). The threat model assumes the host is
  trusted.
- Denial-of-service via expensive search-space or trial-count parameters —
  these are operator-tunable limits, not security boundaries in MVP1.

If you are not sure whether something is in scope, report it anyway and we
will route it appropriately.

## Hardening guidance for operators

See [`docs/04_security/`](docs/04_security/) for the operator-facing security
documentation, including secrets handling, GitHub token rotation, and the
LLM data-flow summary.
