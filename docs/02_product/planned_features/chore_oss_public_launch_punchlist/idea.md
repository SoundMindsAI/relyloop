# OSS Public-Launch Punchlist

**Date:** 2026-05-27
**Status:** Idea — captured during `chore_oss_launch_prep` (the PR that added SECURITY.md / GOVERNANCE.md / MAINTAINERS.md / CODEOWNERS / issue + PR templates and replaced the Code of Conduct)
**Priority:** P1 — gates flipping the repository from private to public.
**Origin:** Items the user named in the `chore_oss_launch_prep` request that are operator-decisions or bulk-mechanical sweeps too large to land in the same documentation-focused PR.
**Depends on:** None code-wise. Sequencing: do these before changing repo visibility.

## Problem

The `chore_oss_launch_prep` PR adds the foundational governance / security /
contributor files that prospective contributors and enterprise reviewers
look for first. Three remaining items are gates on flipping the repository
from private to public, but each is either an **operator action** (not
something a PR can land) or a **bulk-mechanical sweep** large enough to
deserve its own focused review pass. Bundling them into the docs PR would
hide the review surface; deferring them without a tracking file risks
forgetting them before the public flip.

## Proposed capabilities

### Capability 1 — SPDX-License-Identifier headers across source files

Adopt the [FSFE REUSE](https://reuse.software/) convention. Every source
file gets a two-line header:

```
# SPDX-FileCopyrightText: 2026 soundminds.ai
# SPDX-License-Identifier: Apache-2.0
```

(Comment marker swaps per language: `#` for Python / YAML / Dockerfile,
`//` for TS / JS / Go, `<!--` for HTML / Markdown where appropriate.)

- Bulk-add headers via `reuse annotate` for `backend/`, `ui/src/`,
  `migrations/`, `scripts/`, `prompts/`, `samples/`, `templates/`.
- Add a `.reuse/dep5` or `REUSE.toml` file declaring license metadata for
  files that should not carry inline headers (generated files, fixtures,
  vendored data).
- Add `reuse lint` as a pre-commit hook AND a CI job in `.github/workflows/pr.yml`
  — fast and noisy; catches missing headers on every new file in PR review.
- Update `CONTRIBUTING.md` with a one-paragraph "Every new source file
  gets an SPDX header — `reuse annotate` does it for you."

**Why this is its own PR, not part of `chore_oss_launch_prep`:** This is a
several-hundred-file diff. Reviewers cannot meaningfully read it as part of
a documentation PR; it deserves a focused review pass where the only
question is "do the headers look right?".

### Capability 2 — Git-history audit for secrets, customer names, internal URLs, design-partner data

Operator task — must run BEFORE flipping the repo public, because git
history is forever once pushed publicly. Use [`git-filter-repo`](https://github.com/newren/git-filter-repo)
(modern replacement for BFG) to rewrite history if anything is found.

- Run `gitleaks detect --source . --log-opts="--all"` against the full
  history. We have `gitleaks` in pre-commit (per `CONTRIBUTING.md` §"Pre-commit hooks");
  the historical sweep is the same tool with `--log-opts="--all"`.
- Manually scan for: design-partner names, internal URLs (`*.soundminds.internal`),
  customer index names, real OpenAI / GitHub keys, screenshot watermarks
  in `samples/` images.
- If anything is found, **stop**. Decide between (a) rewriting history with
  `git-filter-repo` (every collaborator must re-clone), (b) accepting the
  exposure and rotating the leaked credential, or (c) deferring the public
  flip.
- Document the audit outcome in a runbook under [`docs/03_runbooks/`](docs/03_runbooks/)
  so the next maintainer can re-run the same audit before a major release.

**Why this is its own work item:** This is an **operator decision** — the
sweep produces findings the maintainer team must adjudicate before any
push to public. The artifact is an audit log and (potentially) a history
rewrite, not a code change. Cannot be a PR.

### Capability 3 — Dependency license-compatibility audit

Apache 2.0 is incompatible with GPL / AGPL transitive dependencies under
most interpretations. Before publishing, produce an inventory of every
runtime + dev dependency and its license, flag any GPL / AGPL transitively
pulled in, and decide whether to replace or accept (with documentation).

- Python: `uv pip list --format=json | xargs -n1 ...` or `pip-licenses --format=markdown --with-license-file`.
- Frontend: `pnpm licenses list --long` (or `license-checker` if not
  enough detail).
- Container images: trivy / dive for layer-level licenses.
- Output: a single `docs/04_security/license-inventory.md` file with
  Apache-2.0-compatible / Apache-2.0-incompatible columns and the
  "decided action" per row.
- Add a CI job that regenerates the inventory and diffs against the
  committed copy — a new GPL dep breaks the build.

**Why this is its own work item:** The audit script itself is a few-hour
job, but the **decisions** about any AGPL findings are project-direction
calls (replace dep? defer? accept with documented exception?). Producing
the script + initial inventory + CI gate is cleaner as its own PR with the
license decisions discussed inline.

## Scope signals

- **Backend:** SPDX headers across `backend/` (~hundreds of files); license-audit script.
- **Frontend:** SPDX headers across `ui/src/`; pnpm license-list script.
- **Migration:** none.
- **Config:** new `.reuse/dep5` or `REUSE.toml`; new CI jobs (`reuse lint`, license-diff).
- **Audit events:** N/A (pre-MVP2; no state mutations).

## Why not now

Each of the three capabilities is bounded but distinct, with its own
review audience: SPDX is a bulk mechanical sweep, the history audit is an
operator decision the maintainer team adjudicates, and the dependency
license audit produces a report whose value is in the per-row decisions
rather than the code. Bundling any of them into the documentation-focused
`chore_oss_launch_prep` PR would hide the review surface that matters.

They are also all **soft-gated by the public-flip moment** — none of them
has user-facing impact while the repo is private. Once the flip is on the
calendar, this idea file converts to three sequential PRs in this order:
SPDX → license audit (so the audit can flag any new GPL deps the SPDX
sweep transitively pulls in) → history scrub (last, because it's
destructive if findings require rewriting).

## Relationship to other work

- Lives downstream of `chore_oss_launch_prep` (the PR that added the
  foundational files). That PR's reviewer guidance points at this idea
  file as the "what's still missing" pointer.
- Capability 3 (license audit) interacts with [NOTICE](../../../../NOTICE)
  — the existing dependency list there is hand-maintained and will become
  the seed for `docs/04_security/license-inventory.md`.
- Capability 2 (history scrub) interacts with the existing `gitleaks`
  pre-commit hook documented in [CONTRIBUTING.md](../../../../CONTRIBUTING.md)
  §"Verifying the gitleaks hook" — same tool, different invocation scope.
