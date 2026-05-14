# Split `make fmt` / `lint` / `typecheck` into backend-only sub-targets

**Date:** 2026-05-14
**Status:** Idea — captured during feat_judgments_periodic_resume_sweep impl-execute tangential sweep
**Origin:** `/impl-execute` Step 3 verification gate on Story 1.1 — `make fmt`, `make lint`, `make typecheck` all failed with `ERR_PNPM_UNSUPPORTED_ENGINE` because the bundled UI tooling requires Node ≥20.18 and the local environment had Node 18. The story was a backend-only change; the UI failure was scope-bleed friction.

## Problem

The current `Makefile` bundles backend (ruff, mypy) and frontend (prettier, eslint, tsc) tooling under each top-level target:

```makefile
fmt: ruff format + pnpm --dir ui prettier
lint: ruff check + pnpm --dir ui lint
typecheck: mypy + pnpm --dir ui typecheck
```

A backend-only contributor (e.g., agent or human working on `backend/workers/*.py`) hits the Node-engine guard on `pnpm --dir ui ...` and the whole make target fails. The workaround is to call `.venv/bin/ruff` and `.venv/bin/mypy` directly — but then the operator has lost the "one canonical command" promise that the Makefile makes.

CI works because GitHub Actions provisions Node 20+. Local dev breaks when an operator has Node 18 installed (still LTS until 2026-04, still widely deployed).

## Proposed capabilities

Add backend-only sub-targets that operators (and `/impl-execute`) can run on backend-only PRs:

```makefile
fmt-backend: ruff format backend/
lint-backend: ruff check backend/
typecheck-backend: mypy --strict --config-file=pyproject.toml backend/
```

Keep the existing top-level `fmt`/`lint`/`typecheck` as the combined entrypoints — they should keep their current behavior so CI doesn't drift.

Optionally add `fmt-frontend`/`lint-frontend`/`typecheck-frontend` parallels for symmetry. Not strictly needed since the existing targets already cover the frontend path.

## Scope signals

- **Backend:** none (Makefile only).
- **Frontend:** none.
- **Migration:** none.
- **Config:** Makefile additions (~10 lines).
- **Audit events:** N/A.

## Why deferred

The fix is ~10 lines of Makefile but it's out of scope for `feat_judgments_periodic_resume_sweep` (a worker-runtime feature, not a build-tooling feature). Bundling it into that PR would have muddied the diff. Capturing here for a future `/impl-execute --ad-hoc` infra-sweep PR.

## Relationship to other work

- Sibling chore: `infra_dashboard_regen_pre_commit_conflict` (also captured during this same impl-execute session).
- No interference with planned MVP2 work.
