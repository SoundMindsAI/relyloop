# Idea — infra_nvmrc

**Date:** 2026-05-12
**Origin:** Noticed at start of `feat_studies_ui` implementation. `ui/package.json` engines field requires `node >=20.18` (set during `infra_frontend_stack_refresh` PR #49), but the repo has no `.nvmrc` so `nvm use` (no args) doesn't auto-select the correct Node. Contributors on default shells (e.g., my session: Node 18.20.8 active) get incompatible Node until they manually `nvm use 22` or set a global default. This produces subtle Vitest 4 / Next 16 / TypeScript 6 incompatibilities that aren't always obvious from error messages.

## Problem

- `ui/package.json` engines: `"node": ">=20.18"`, verified on Node 22.22.2 per `state.md`.
- No `.nvmrc` file at repo root or under `ui/`.
- Default shell may have an older nvm-active Node (Node 18 in my session).
- pnpm doesn't enforce engines by default (no `engine-strict=true` in `.npmrc` or `pnpm-workspace.yaml`).

## Proposed fix (low-effort)

1. Add `.nvmrc` at repo root with content `22.22.2` (the known-good version per state.md).
2. Optionally: add `ui/.npmrc` with `engine-strict=true` so `pnpm install` hard-fails on the wrong Node.
3. Update `docs/03_runbooks/local-dev.md` with a one-liner: "Run `nvm use` from the repo root before `pnpm install` / `pnpm dev`."

## Why deferred

Out of scope for `feat_studies_ui` (UI feature work, not env tooling). Trivial to fix in a future infra-sweep PR (~5 lines + 1 doc paragraph).

## References

- `ui/package.json` engines field
- `state.md` "Verified locally on Node 22.22.2" line
- `docs/03_runbooks/local-dev.md` (where the runbook note would land)
