# chore_pr_yml_parallelize_backend_job — Drop redundant lint/typecheck from the heavy backend job

**Date:** 2026-06-02 (preflighted + refreshed 2026-06-05; **descoped to lint-dedup 2026-06-05**)
**Status:** **Shipped (ad-hoc) 2026-06-05** — the only actionable residual (drop the redundant `ruff`/`format`/`mypy` steps from the heavy `backend` job) shipped as a ~zero-risk YAML edit. **The lane-split (Win 2′) + split-by-service (Win 3) were carved out to a deferred infra idea — see [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md).**
**Priority:** P2 — operator iteration cost, not a correctness gate
**Origin:** PR #426 CI watch. Operator noticed the `backend (lint + typecheck + tests + coverage)` job ran for **8m20s** while the rest of the suite finished in 2-3 min. Operator asked: "is it possible to run this quicker? Can we parallelize this?" The answer is yes — but as of the 2026-06-05 preflight the cheap wins were done/dead and the remaining safe win was the lint-dedup below; the lane-split's real ROI proved marginal (see descope note).
**Depends on:** None.

> **DESCOPE (2026-06-05).** During plan design the lane-split's expected win was re-quantified and found **marginal**: the ~8min critical path is dominated by the **integration** layer, which *cannot* run under `-n auto` (the FK-teardown collision documented at `pr.yml`, reverted on PR #291). Only the unit (~40s) + lint (~40s) portions can move off the critical path, and lint already runs in parallel via `static-checks-backend`. So the lane-split recovers only ~1–1.5 min, and only at the cost of a fiddly, blind-CI-validated `coverage combine` merge job. The operator chose to ship **only the lint-dedup** (the reliable, zero-risk part of the win — ~30-40s, ~5-line edit) here, and defer the lane-split + coverage-combine + split-by-service to [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md), to be picked up only if the integration layer ever becomes the binding constraint after other CI work lands.

> **PREFLIGHT REFRESH (2026-06-05).** A live-codebase audit found the idea materially overtaken by events:
> - **Win 1's main thrust shipped.** A dedicated `static-checks (backend — ruff + mypy + guards, always-run)` job already exists at [`.github/workflows/pr.yml:297-328`](../../../../.github/workflows/pr.yml) — runs `ruff check` + `ruff format --check` + `mypy --strict`, no Postgres/ES/OS service containers, always-run. The open question "confirm `static-checks-backend` exists and what it covers" is **resolved: yes, it covers all of ruff/format/mypy.**
> - **Win 2 (naive `-n auto`) was tried and reverted.** [`pr.yml:504-515`](../../../../.github/workflows/pr.yml) documents it: attempted on PR #291, reverted because the **integration** layer hit FK collisions (`query_sets_cluster_id_fkey` violation when parallel workers tear down a cluster another worker still references). `pytest-xdist>=3.6` is already a dev dep ([`pyproject.toml:78`](../../../../pyproject.toml)) for local opt-in. So naive whole-matrix `-n auto` is OFF THE TABLE; the real win is the **lane-split** (Win 2′ below).
> - **The heavy `backend` job still redundantly re-runs lint/typecheck** ([`pr.yml:479-486`](../../../../.github/workflows/pr.yml): `ruff check` + `Format check` + `mypy --strict`) before the pytest matrix — duplicating `static-checks-backend`. Dropping those 3 steps is the Win-1 residual.
> - **Timing today:** the heavy job ran ~9m20s on PR #476 (2026-06-05), still the critical-path bottleneck.
> - **Dangling reference:** the `chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md` cited in `pr.yml:514` + `pyproject.toml:77` does NOT exist under `planned_features/` (never filed, or shipped+moved). This chore subsumes its "split into parallel-safe unit+contract + serial integration lane" recommendation.

## Problem

`.github/workflows/pr.yml` has a job named `backend (lint + typecheck + tests + coverage)` that runs four sequential things in one job: ruff/lint, mypy, the full pytest matrix (unit + integration + contract), and the coverage gate. It dominates the critical path of every PR check at ~8m20s. Meanwhile there's a separate `backend (unit tests — fast lane)` job that runs the unit subset in 38s — but it's a duplicate of part of the heavy lane's work, not a parallelization.

Three concrete operator costs:

1. **Round-trip latency on lint slips.** A one-line ruff or mypy error costs the full ~8 min before the failure surfaces. The fast-lane job catches unit-test failures faster but doesn't run lint/typecheck.
2. **Critical path blocks merge.** With the heavy job at 8m, the smoke job at 0s (skipped opt-in), and both docker buildxes at ~2.5 min, the wall-clock per PR is `max(2.5, 2.5, 8) ≈ 8 min`. Reducing the backend lane to ~3-4 min would let the docker buildxes dominate.
3. **Service-container boot waste.** The heavy job boots Postgres + Elasticsearch + OpenSearch service containers even for the lint/typecheck steps, which need none of them.

## Proposed capabilities

Three wins, ordered by effort/reward:

### Win 1 — Split lint + typecheck into their own job (~30-40s) — ✅ SHIPPED (residual remains)

**STATUS (preflight 2026-06-05): the split SHIPPED.** `static-checks (backend — ruff + mypy + guards, always-run)` (`pr.yml:297-328`) already runs ruff + format-check + mypy with no service containers, always-run, giving sub-minute lint feedback in parallel with everything else.

**Residual (the only remaining Win-1 work):** the heavy `backend (lint + typecheck + tests + coverage)` job STILL re-runs `ruff check` (`pr.yml:479`), `Format check` (`:483`), and `mypy --strict` (`:486`) before its pytest matrix — redundant with `static-checks-backend`. **Drop those 3 steps from the heavy job.** Net: ~30-40s off the heavy lane; lint/typecheck fast-feedback is preserved by the parallel `static-checks-backend` job (a lint error still goes red in <1 min). Trade-off: on a lint-failing PR the heavy job no longer self-aborts early, wasting runner-minutes on a doomed run — acceptable, since the PR is already red from `static-checks-backend` and GHA doesn't auto-cancel.

**Effort:** ~5-line YAML edit. **Expected wall-clock cut:** ~30-40s off the critical path.

### Win 2′ (lane-split) + Win 3 (split-by-service) — DEFERRED to `infra_pr_yml_split_backend_test_lanes`

**Both deferred at the 2026-06-05 descope.** The lane-split (parallel `unit+contract` + serial `integration` + a `coverage combine` merge/gate job) and the split-integration-by-service-container work were moved to [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md). Rationale captured in the DESCOPE note above: the integration layer is the binding constraint and cannot parallelize (FK-teardown collision, reverted on PR #291), so the recoverable win is only ~1–1.5 min and requires a blind-CI-validated `coverage combine` path — not worth the risk until integration becomes the limiting factor. See the infra idea for the full design surface (coverage-combine option (a) vs feedback-only option (b), contract-layer `-n auto`-safety, per-service-container lanes).

## Decisions

- **D-1. Ship only the lint-dedup in this chore; defer the lane-split + split-by-service to `infra_pr_yml_split_backend_test_lanes`.** (Descoped 2026-06-05 — supersedes the original "Wins 1+2 here, Win 3 separate" decision.) Rationale in the DESCOPE note: the lint-dedup is a zero-risk ~5-line edit with a reliable ~30-40s win; the lane-split's incremental win is only ~1-1.5 min (integration can't parallelize) and carries blind-CI `coverage combine` risk — not worth bundling.
- **D-2. NO change to the coverage gate (this chore).** The heavy job still runs the full `pytest backend/tests/` matrix with `--cov`; dropping the lint/format/mypy steps doesn't touch coverage (those don't contribute to coverage). The `coverage combine` design lives in the deferred infra idea.
- **D-3. NO change to the fast-lane job.** The ~38s fast-lane (`pr.yml`, `backend (unit tests — fast lane)`) stays as-is — it's the canary for unit-test correctness.

## What shipped (ad-hoc, 2026-06-05)

Three redundant steps removed from the heavy `backend` job in `.github/workflows/pr.yml` (each already covered by the always-run `static-checks-backend` job):
- `ruff check .`
- `ruff format --check .`
- `mypy backend/`

Plus the now-unused `Restore mypy + ruff caches` step (it only served the removed ruff/mypy steps), and a job display-name update (`backend (lint + typecheck + tests + coverage)` → `backend (tests + coverage)`). Net: ~30-40s off the critical path; lint/type fast-feedback preserved by the parallel `static-checks-backend` job. The dangling `chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md` reference in the pytest-step comment was repointed at the new `infra_pr_yml_split_backend_test_lanes` idea.

## Scope signals

- **Backend:** none (no `backend/app/` source touched).
- **Frontend:** none.
- **Migration:** none.
- **Config:** `.github/workflows/pr.yml` only (remove 3 redundant steps + 1 unused cache step + rename display name). No `Makefile` / `pyproject.toml` change (those were lane-split concerns, now deferred).
- **Audit events:** N/A — CI workflow config.
- **Operator impact:** none on operator-path behavior. Affects CI feedback latency only. Operators flipping `SKIP_HEAVY_CI=true` see no change.

## Relationship to other work

- Sibling of `infra_smoke_reseed_runtime_budget` (shipped 2026-06-02 in PR #424) — that work made the `smoke` job feasible to opt-in via `SMOKE_TEST=true`. This chore reduces the *default* per-PR critical path (smoke is opt-in/off), so even when smoke runs it stops being the wall-clock bottleneck.
- Hands off the lane-split + split-by-service residual to [`infra_pr_yml_split_backend_test_lanes`](../infra_pr_yml_split_backend_test_lanes/idea.md) (deferred). The lint-dedup shipped here is a pure subtraction from the heavy job; the deferred work is a structural split.
- Captured during `bug_llm_capability_cache_no_refresh` (PR #426) CI watch — the slow backend job made the operator wait through two cycles (initial push + post-Gemini-fixes push); each waited the same 8 min on the same backend lane.

## Why filed instead of fixed inline during PR #426

Per CLAUDE.md "Tangential discoveries — fix inline by default": tested the inline-fix gate. This work is:
- **Cross-subsystem from the bug fix** (CI/workflow vs. LLM capability cache — different surfaces, no shared file).
- **>60 min of work** even for Wins 1 + 2 (need to audit existing `static-checks-backend`, verify `pytest-xdist` is in deps, test-isolation pass).
- **Would expand PR #426's review scope** from "Redis cache helper" to "Redis cache helper + CI parallelization" — confusing for the reviewer.

So the rubric rows for "cross-subsystem + >60 min" + "expands PR review scope" both say defer. Filed as a separate chore for parallel execution.
