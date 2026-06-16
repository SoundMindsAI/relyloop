# infra_pr_yml_split_backend_test_lanes — Split the heavy backend job into parallel test lanes

**Date:** 2026-06-05
**Status:** **Win 2′ shipped 2026-06-16 (PR pending — opened ad-hoc as `infra_pr_yml_split_backend_test_lanes` after the operator hit the binding-constraint condition during a multi-PR session where the heavy backend job was 9–9.5 min on every run, dominating wall-clock).** Win 3 (split integration by service-container) remains deferred — pick up if the new integration-only `backend-heavy` lane becomes the next binding constraint.
**Priority:** Win 2′ → shipped. Win 3 → backlog (defer-until-binding-constraint, same posture as before).
**Origin:** Split out from `chore_pr_yml_parallelize_backend_job`. That chore shipped the reliable, zero-risk part (drop redundant lint/format/mypy from the heavy `backend` job — ~30-40s). This idea holds the remaining, riskier wins (Win 2′ lane-split + Win 3 split-by-service) that the operator chose to defer.
**Depends on:** None. (Builds on the post-lint-dedup `.github/workflows/pr.yml` shape.)

## Problem

The heavy `backend (tests + coverage)` job in `.github/workflows/pr.yml` runs the full `pytest backend/tests/` matrix (unit + integration + contract) serially in one job with `--cov` gating at `fail_under=80`. After the lint-dedup shipped, it's still the critical-path bottleneck (~8-9 min). The unit + contract layers *could* parallelize; the integration layer cannot.

## Why deferred (the descope rationale)

The naive whole-matrix `pytest -n auto` was tried on PR #291 and reverted: the **integration** layer hits FK-teardown collisions across parallel workers (`query_sets_cluster_id_fkey` violation when one worker tears down a cluster another worker still references) — documented in `.github/workflows/pr.yml` at the pytest step. `pytest-xdist>=3.6` remains a dev dep (`pyproject.toml`) for local opt-in.

Because integration must stay serial, the lane-split recovers only the **unit (~40s) + contract** portion off the critical path — roughly **~1–1.5 min** — and only at the cost of a `coverage combine` merge/gate job whose correctness can only be validated by watching CGA CI (blind). That ROI/risk ratio is why the operator descoped it out of the parent chore. Revisit when integration stops being the binding constraint (e.g., after a split-by-service-container reduces integration wall-clock) or when the ~1-1.5 min becomes worth the combine complexity.

## Proposed capabilities

### Win 2′ — Lane-split: parallel `unit+contract` lane + serial `integration` lane

Split the heavy job's single `pytest backend/tests/` into two jobs:

1. **`backend (unit + contract)` lane** — `pytest backend/tests/unit backend/tests/contract -n auto`. Parallel-safe because these layers don't share a mutable Postgres fixture across workers the way integration does. **Caveat:** a subset of contract tests boot the FastAPI app via `LifespanManager` (touches Redis/Postgres at startup); confirm `-n auto`-safe or mark the exceptions `@pytest.mark.xdist_group`/serial. The existing fast-lane (`backend (unit tests — fast lane)`, `pytest backend/tests/unit/ --no-cov`) proves the unit layer parallelizes cleanly.
2. **`backend (integration + coverage)` lane** — `pytest backend/tests/integration` **serial** (NO `-n auto` — this is the layer that broke), with Postgres + ES + OS service containers.

**Coverage wrinkle (load-bearing design decision):** the 80% `fail_under` gate needs coverage across ALL layers; neither split lane alone has full coverage. Two options:
- **(a) `coverage combine`** — each lane emits a partial `.coverage` data file as an artifact; a third tiny job runs `coverage combine` + `coverage report --fail-under=80`. Standard parallel-coverage pattern; needs `[tool.coverage.run] parallel = true` + `[tool.coverage.paths]` config + cross-job artifact passing. **The only option that actually recovers the ~1-1.5 min.**
- **(b) Feedback-only lane** — keep the single coverage-gated full-matrix run as-is, add the parallel `unit+contract` lane purely for fast feedback. No critical-path win (the coverage lane still runs everything serially). Cheaper to build, but doesn't recover any wall-clock.

Pick (a) if the win is worth the combine wiring; (b) is a fallback that only buys faster red-on-failure feedback.

### Win 3 — Split integration tests by service-container they need

All integration tests share one job that boots Postgres + Elasticsearch + OpenSearch. But most need only Postgres; subsets need ES / OS; a tiny subset needs Solr (mostly skip-gated). Split into `integration:postgres` / `integration:elastic` / `integration:opensearch` lanes (pytest markers + targeted `-m` selection) so each scales to what it needs and runs concurrently — the Postgres-only lane gets a faster boot (no ES/OS settle wait). **This is the higher-value win** if integration dominates, because it parallelizes the layer that can't use `-n auto` by sharding it across jobs rather than workers (no shared-DB FK collision — each lane has its own service containers + its own DB).

**Effort:** larger — pytest marker pass + per-lane service-container config + Makefile target split + verify test ordering holds under independent runs.

## Decisions

- **D-1. Integration lane stays serial under `-n auto` — non-negotiable.** The FK-teardown collision is why. Win 3 parallelizes integration by *sharding across jobs* (separate DBs), not by `-n auto` within a job.
- **D-2. Coverage strategy is the load-bearing spec decision.** Default to option (a) `coverage combine` if pursuing the lane-split for a real wall-clock win.

## Open questions for /spec-gen (when revisited)

- Is the ~1-1.5 min (Win 2′ alone) worth the `coverage combine` complexity, or should Win 3 (split-by-service) be tackled first since it attacks the binding constraint directly?
- Contract-layer `-n auto`-safety: which contract tests boot the app via `LifespanManager` and need quarantining into a serial lane / `xdist_group`?
- Win 3 service-container topology: how many parallel lanes, and does the demo-seed / repo-layer suite genuinely need only Postgres?

## Scope signals

- **Backend:** test markers only (`@pytest.mark.xdist_group` / per-service `-m` selection); no `backend/app/` source.
- **Frontend:** none.
- **Migration:** none.
- **Config:** `.github/workflows/pr.yml` (job split + service-container topology), `pyproject.toml` (`[tool.coverage.run] parallel` + `[tool.coverage.paths]` if option (a)), `Makefile` (test target split).
- **Audit events:** N/A.
- **Operator impact:** CI feedback latency only.

## Relationship to other work

- **Parent:** [`chore_pr_yml_parallelize_backend_job`](../../../implemented_features/2026_06_05_chore_pr_yml_parallelize_backend_job/idea.md) — shipped the lint-dedup; this idea holds its deferred lane-split + split-by-service residual.
- Sibling of `infra_smoke_reseed_runtime_budget` (shipped 2026-06-02, PR #424) — that made the `smoke` job feasible to opt-in; this reduces the default per-PR critical path.
