# Split `make fmt` / `lint` / `typecheck` into backend-only sub-targets

**Date:** 2026-05-14
**Preflighted:** 2026-05-14 — verified the actual Makefile shape; scope **smaller than originally captured** (existing `ui-*` sub-targets already exist; just need to add symmetric `backend-*` siblings — ~12 lines of Makefile, not 10 lines of net new top-level targets).
**Status:** Idea — ready for `/impl-execute --ad-hoc`.
**Origin:** `/impl-execute` Step 3 verification gate on `feat_judgments_periodic_resume_sweep` Story 1.1 — `make fmt`, `make lint`, `make typecheck` all failed with `ERR_PNPM_UNSUPPORTED_ENGINE` because the bundled UI tooling requires Node ≥20.18 and the local environment had Node 18. The story was a backend-only change; the UI failure was pure scope-bleed friction. Same issue bit four more commits across the day's three-PR ad-hoc loop (#106, #108, #109).

## Problem

The current `Makefile` bundles backend (ruff, mypy) and frontend (prettier, eslint, tsc) tooling under each top-level target. Verified shape ([`Makefile:26-34`](../../../../Makefile#L26-L34)):

```makefile
fmt:  ## Format Python (ruff format) and frontend (prettier)
	uv run ruff format .
	pnpm --dir ui format

lint: ui-lint  ## Lint Python (ruff check) and frontend (eslint)
	uv run ruff check .

typecheck: ui-typecheck  ## Type-check Python (mypy --strict) and frontend (tsc --noEmit)
	uv run mypy backend/
```

A backend-only contributor (agent or human working on `backend/workers/*.py`) hits the Node-engine guard on `pnpm --dir ui ...` and the whole make target fails. The documented workaround is to call `.venv/bin/ruff` and `.venv/bin/mypy` directly — but then the operator has lost the "one canonical command" promise the Makefile makes.

CI works because GitHub Actions provisions Node 20+ via `actions/setup-node@v6`. Local dev breaks when an operator has Node 18 installed (still LTS until 2026-04, still widely deployed). The pattern bit four commits across 2026-05-14's three-PR ad-hoc loop alone.

## Proposed capabilities

**Symmetric `backend-*` sub-targets that mirror the existing `ui-*` targets** at [`Makefile:62-72`](../../../../Makefile#L62-L72) (`ui-lint`, `ui-typecheck`, `ui-test`, `ui-build`). The bundled top-level targets become composition layers:

```makefile
# ---------- Backend code quality (added per
# infra_make_targets_split_backend_only) ----------

backend-fmt:  ## Format Python (ruff format) — backend only
	uv run ruff format .

backend-lint:  ## Lint Python (ruff check) — backend only
	uv run ruff check .

backend-typecheck:  ## Type-check Python (mypy --strict) — backend only
	uv run mypy backend/

# ---------- Composed top-level targets ----------

fmt: backend-fmt  ## Format Python (ruff format) and frontend (prettier)
	pnpm --dir ui format

lint: backend-lint ui-lint  ## Lint Python (ruff check) and frontend (eslint)

typecheck: backend-typecheck ui-typecheck  ## Type-check Python (mypy --strict) and frontend (tsc --noEmit)
```

Total: ~12 lines added, 3 lines deleted from the existing bundled targets (the bodies move into the new sub-targets). `.PHONY` line at [`Makefile:6-10`](../../../../Makefile#L6-L10) gains 3 new entries.

### Why mirror the existing `ui-*` naming (not the originally-captured `fmt-backend`)

The original idea proposed `fmt-backend`/`lint-backend`/`typecheck-backend` (verb-first). The existing `ui-*` targets use scope-first naming (`ui-lint`, `ui-typecheck`). Mirroring that convention keeps the Makefile's `make help` output organized — all `backend-*` targets group together, all `ui-*` targets group together. **Locked: `backend-<verb>`** to match the existing convention; the original `fmt-backend` naming dropped.

## Scope signals

- **Backend:** none (Makefile only).
- **Frontend:** none.
- **Migration:** none.
- **Config:** Makefile additions (~12 lines net) + `.PHONY` line gains 3 entries (`backend-fmt`, `backend-lint`, `backend-typecheck`).
- **Audit events:** N/A.
- **CLAUDE.md absolute-rules walked:** none implicated. No schema, no API, no LLM, no secret, no engine call, no `<select>`, no `/healthz`.

## Acceptance test

After this lands, the following sequence should work without `ERR_PNPM_UNSUPPORTED_ENGINE` on a host with Node 18:

```bash
make backend-fmt && make backend-lint && make backend-typecheck
```

And the existing CI-visible behavior remains:

```bash
make fmt        # still runs ruff + prettier
make lint       # still runs ruff + eslint
make typecheck  # still runs mypy + tsc
```

CI (`.github/workflows/pr.yml`) continues to call `make lint`/`make typecheck` and sees no behavior change because both target compositions still run.

## Why deferred (originally)

The fix is ~12 lines of Makefile but it was out of scope for `feat_judgments_periodic_resume_sweep` (a worker-runtime feature, not build-tooling). Bundling it into that PR would have muddied the diff. Now ripe for `/impl-execute --ad-hoc` as a standalone infra commit — no spec/plan ceremony needed.

## Relationship to other work

- Sibling chore: [`infra_dashboard_regen_pre_commit_conflict`](../../../00_overview/implemented_features/2026_05_14_infra_dashboard_regen_pre_commit_conflict/idea.md) (shipped 2026-05-14 as PR #108 — `_maybe_write` idempotency + path-rewriter helpers). Both originated from the same `feat_judgments_periodic_resume_sweep` tangential sweep; same operational-friction class (build-tooling and pre-commit-hook drift).
- Builds on the existing `ui-*` sub-targets at [`Makefile:62-72`](../../../../Makefile#L62-L72) (precedent for the scope-first naming).
- Doesn't interfere with any active or backlogged feature.
