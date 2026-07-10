# Digest-pin pre-commit hooks and Compose service images

**Date:** 2026-07-10
**Status:** Idea — surfaced during the 2026-07-10 full-codebase security audit (CI/CD + infra agent, findings #2 and #3)
**Priority:** P2
**Origin:** Security audit findings #2 (`.pre-commit-config.yaml:27,156,164`) and #3 (`docker-compose.yml:34,50,361,391,432,458`)
**Depends on:** None

## Problem

The repo's GitHub Actions and Dockerfile `FROM` lines are all SHA/digest-pinned
(strong posture, Scorecard-driven). Two surfaces are still pinned only by
**mutable tag**, inconsistent with that posture:

1. **Third-party pre-commit hooks** — `ruff-pre-commit` (`rev: v0.15.12`),
   `gitleaks` (`rev: v8.21.2`), `pre-commit-hooks` (`rev: v5.0.0`). Tags can be
   force-moved; a compromised upstream repo could re-point a tag and every
   contributor executes the hook code at `git commit` time (workstation
   compromise). Note the CI gitleaks *binary* download is now checksum-pinned
   (this audit's inline fix in `secrets-defense.yml`) — this item is the
   pre-commit half.
2. **Compose service images** — `postgres:17`, `redis:8` (floating major),
   `elasticsearch:9.4.1`, `opensearch:3.6.0`, `solr:10.0`, `ollama:0.30.10`.
   None carry `@sha256:` digests. A Docker Hub tag/account compromise (or a
   poisoned corporate `BASE_REGISTRY` mirror) serves a malicious image on the
   next operator `make up`; the postgres container holds all study data and the
   DB password.

## Proposed capabilities

### Pin pre-commit hook revisions to commit SHAs

- Replace each third-party `rev:` tag with the full 40-char commit SHA + a
  `# vX.Y.Z` comment, mirroring the workflow-action convention.

### Digest-pin Compose images

- Append `@sha256:<digest>` to each third-party `image:` line (keep the tag for
  readability), matching the Dockerfile `FROM` convention.
- Add/extend Dependabot's `docker` + `pre-commit` ecosystems so tag+digest
  rotate together automatically (avoids the pins going stale).

## Scope signals

- **Backend:** none.
- **Frontend:** none.
- **Migration:** none.
- **Config:** `.pre-commit-config.yaml`, `docker-compose.yml`,
  `.github/dependabot.yml`.
- **Audit events:** N/A.

## Why deferred

Doing this by hand means resolving exact commit SHAs for several third-party
repos and `@sha256:` digests for six runtime images — a wrong value silently
breaks every contributor's pre-commit or every operator's `make up`, and the
change is only LOW severity. It is genuinely Dependabot's job and wants a
coordinated Dependabot-config change so the pins don't rot. This fits the GA
"complete CI/CD with security gates / container scanning / image signing"
theme in the release matrix. The higher-severity supply-chain gap (unverified
gitleaks CI binary) was fixed inline in this audit's PR.

## Relationship to other work

Continues the `chore_scorecard_pin_deps_postcss` posture (SHA-pinned actions,
hash-pinned pip installs) to the two remaining tag-pinned surfaces.
