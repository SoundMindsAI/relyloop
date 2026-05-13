# Idea — `chore_infra_foundation_github_token_file_retirement`

**Date:** 2026-05-12
**Status:** Idea (deferred from `feat_github_pr_worker` spec patch — captured because the cleanup spans `infra_foundation`'s shipped config and isn't in the PR-worker scope)

## Origin

`infra_foundation` (PR #4, merged 2026-05-09) introduced the `GITHUB_TOKEN_FILE` env var as a placeholder for the future PR worker — at the time, no per-repo config_repos.auth_ref column existed yet (those landed with `infra_adapter_elastic`). The worker also didn't exist yet, so the env var was never load-bearing.

The `feat_github_pr_worker` 2026-05-12 spec patch (decision-log entry 2026-05-12) committed to **per-repo `auth_ref` over global `GITHUB_TOKEN_FILE`** for enterprise-aligned secret rotation + least-privilege. That decision deprecates the env var. This idea file tracks the cleanup so the deprecated env var doesn't linger as dead config.

## Problem

After `feat_github_pr_worker` ships, `GITHUB_TOKEN_FILE` is:

1. **Documented** in `backend/app/core/settings.py` as `github_token_file: Path | None = Field(default=None, description="Path to file containing the GitHub PAT. Optional pre-feat_github_pr_worker.")` and resolved to a `github_token` cached_property.
2. **Probed** by the OpenAI capability-check / health surface in some way (TBC — the `infra_foundation` Story 3.3 capability check is OpenAI-specific; the GitHub probe may not exist yet, but the env var IS in `Settings`).
3. **Auto-generated** by `scripts/install.sh`'s secret-bootstrap (creates an empty `./secrets/github_token` file) per the `infra_foundation` install pattern.
4. **Documented** in `.env.example` as a configurable.
5. **Referenced** in `CLAUDE.md` Absolute Rule #2 examples and `docs/01_architecture/deployment.md` Secrets section.

None of these reference the actual production token-resolution path (which is now per-repo `./secrets/{config_repos.auth_ref}`). Leaving the env var in place creates operator confusion ("which token do I configure?") and a secret-leak risk if operators populate it expecting it to be used and it isn't.

## Why deferred

Cleanup spans multiple files in `infra_foundation`'s shipped config + the install script — orthogonal to `feat_github_pr_worker`'s scope (which is the PR worker itself, not the broader Settings/install/runbook surface). Filing as a separate chore so:

- The PR worker ships clean, focused on its own scope.
- The `GITHUB_TOKEN_FILE` deprecation gets its own spec/PR with focused review.
- Operators upgrading from a pre-deprecation install have a clear migration path documented in the cleanup PR's changelog.

## Proposed scope

### In scope

1. **Remove `github_token_file: Path | None` field** from `backend/app/core/settings.py`. Remove the `github_token` cached_property accessor.
2. **Remove `GITHUB_TOKEN_FILE` setup** from `scripts/install.sh` — the install script no longer creates an empty `./secrets/github_token` file.
3. **Remove `GITHUB_TOKEN_FILE` line** from `.env.example`.
4. **Update `CLAUDE.md` Absolute Rule #2** examples to reference per-repo `auth_ref` pattern (e.g., `./secrets/relyloop-bot-pat`) instead of `./secrets/github_token`.
5. **Update `docs/01_architecture/deployment.md`** Secrets section to document the per-repo pattern as the canonical path; document the deprecation + migration note.
6. **Add a startup warning** if `Settings` detects `GITHUB_TOKEN_FILE` is still set in env (operator carried it over from a pre-deprecation install) — log at WARN with a pointer to the deprecation note.
7. **Migration note** in the cleanup PR's description: "Operators on pre-2026-05-XX installs: `GITHUB_TOKEN_FILE` is no longer read. Migrate by registering each config_repo via `POST /api/v1/config-repos` with an explicit `auth_ref` and dropping the corresponding PAT at `./secrets/{auth_ref}`."

### Out of scope

- The PR worker itself (already shipped by `feat_github_pr_worker`).
- Changes to `config_repos.auth_ref` schema (already shipped by `infra_adapter_elastic`).
- Changes to the install script's overall idempotency model.

## Dependencies

- **`feat_github_pr_worker`** must ship first — this chore depends on the per-repo auth model being the established path.

## Scope signals

- **Backend:** ~15 lines removed from `settings.py`; tests updated.
- **Install script:** ~5 lines removed.
- **Docs:** updates to CLAUDE.md, deployment.md, .env.example.
- **Tests:** unit test for the deprecation warning at startup.
- **Migration:** zero-downtime — operators who haven't set `GITHUB_TOKEN_FILE` see no impact; operators who have set it see a startup WARN and a runbook link.
