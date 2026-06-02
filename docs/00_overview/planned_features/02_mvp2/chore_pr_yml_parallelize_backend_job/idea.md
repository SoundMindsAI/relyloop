# chore_pr_yml_parallelize_backend_job — Split the 8m20s backend job into parallel lanes

**Date:** 2026-06-02
**Status:** Idea — captured during PR #426 CI watch
**Priority:** P2 — operator iteration cost, not a correctness gate
**Origin:** PR #426 CI watch. Operator noticed the `backend (lint + typecheck + tests + coverage)` job ran for **8m20s** while the rest of the suite finished in 2-3 min. Operator asked: "is it possible to run this quicker? Can we parallelize this?" The answer is yes — three orthogonal wins, all of which fit the existing `pr.yml` shape without architectural change.
**Depends on:** None.

## Problem

`.github/workflows/pr.yml` has a job named `backend (lint + typecheck + tests + coverage)` that runs four sequential things in one job: ruff/lint, mypy, the full pytest matrix (unit + integration + contract), and the coverage gate. It dominates the critical path of every PR check at ~8m20s. Meanwhile there's a separate `backend (unit tests — fast lane)` job that runs the unit subset in 38s — but it's a duplicate of part of the heavy lane's work, not a parallelization.

Three concrete operator costs:

1. **Round-trip latency on lint slips.** A one-line ruff or mypy error costs the full ~8 min before the failure surfaces. The fast-lane job catches unit-test failures faster but doesn't run lint/typecheck.
2. **Critical path blocks merge.** With the heavy job at 8m, the smoke job at 0s (skipped opt-in), and both docker buildxes at ~2.5 min, the wall-clock per PR is `max(2.5, 2.5, 8) ≈ 8 min`. Reducing the backend lane to ~3-4 min would let the docker buildxes dominate.
3. **Service-container boot waste.** The heavy job boots Postgres + Elasticsearch + OpenSearch service containers even for the lint/typecheck steps, which need none of them.

## Proposed capabilities

Three wins, ordered by effort/reward:

### Win 1 — Split lint + typecheck into their own job (~30-40s)

A new `backend-static-checks` job that runs `make lint && make typecheck` against a checkout-only container (no Postgres / ES / OpenSearch service containers, no `uv sync` for full pytest deps). The existing `backend (unit tests — fast lane)` already does ~38s with the dev-deps-only install; the lint+typecheck job can be even leaner.

Today there's a `static-checks-backend` job near the top of `pr.yml` (line ~10 in run logs) — verify what it covers and either extend it (preferred — fewer jobs to manage) or add a sibling. If it already covers lint + typecheck, the heavy `backend (lint + typecheck + ...)` job can drop those steps entirely.

**Effort:** ~30 min of YAML editing. **Expected wall-clock cut:** 3-4 min off the critical path (lint/typecheck failures surface in <1 min instead of ~5 min, and the heavy lane stops paying for the redundant work).

### Win 2 — Use `pytest -n auto` on unit + contract layers

Both `backend/tests/unit/` and `backend/tests/contract/` are hermetic (no DB, no Compose). On a 2-core GHA runner, `pytest -n auto` halves wall-clock for embarrassingly parallel suites. Local timing: `pytest backend/tests/unit/` at 2191 tests runs in ~8s already; on CI's slower runner it's currently 3-4 min serial. With `-n auto` it's likely <90s.

**Effort:** add `pytest-xdist` to the dev deps (it's already widely used in the ecosystem; check `uv.lock`), update `make test-unit` and `make test-contract` to pass `-n auto`, verify no test-ordering assumptions break (`@pytest.mark.order` or `pytest-ordering` if any test relies on specific ordering). Per CLAUDE.md "Common Pitfalls" the codebase already gates flaky tests behind `pytest-randomly` randomization — that's a sibling concern, not a blocker. **Expected wall-clock cut:** 2-3 min off the unit + contract portion of the heavy job.

### Win 3 — Split integration tests by service-container they need (~2-3 hours, deserves its own spec)

Today all integration tests share one job that boots Postgres + Elasticsearch + OpenSearch. But:
- Most tests need only Postgres (the demo-data + repo-layer suites).
- A subset needs Elasticsearch (the adapter integration tests).
- A subset needs OpenSearch (also adapter integration tests).
- A tiny subset needs Solr (when reachable; mostly skip-gated today).

Splitting into `integration:postgres` / `integration:elastic` / `integration:opensearch` (using pytest markers + targeted `-m` selection) lets each lane scale to what it actually needs and run concurrently. The Postgres-only lane gets a faster service-container boot since it doesn't wait for ES/OS to settle.

**Effort:** larger — needs pytest marker pass + per-lane service-container config + makefile target split + verification that test ordering still works under independent runs. **Recommend escalating Win 3 to a separate `infra_pr_yml_split_integration_by_service` spec via `/pipeline` if pursued.** Not in scope for this chore.

## Decisions (locked at idea time)

- **D-1. Wins 1 + 2 only in this chore; Win 3 deferred to a separate `infra_` spec.** Rationale: Wins 1 + 2 are ~1 hour of YAML/Makefile editing each, fit cleanly under the `chore_` prefix, and capture ~5-6 min of the 8m20s. Win 3 is multi-file with test-ordering implications across the full integration suite — that's `infra_`-shaped work warranting `/pipeline` ceremony (a spec + plan, not a `bug_fix.md`).
- **D-2. NO change to the coverage gate.** Coverage runs last as an aggregation step that needs the full pytest output. Splitting it naively (e.g., coverage per shard with merge) is its own rabbit hole. Keep the coverage step in whatever job ends up running the full pytest matrix; only the lint/typecheck split affects it (those don't contribute to coverage).
- **D-3. NO change to the fast-lane job.** The 38s fast-lane stays as-is — it's the canary for unit-test correctness. If Win 1 lands and lint/typecheck split out, the fast-lane becomes literally the unit-test subset; if Win 2 adds `-n auto` to it too, fast-lane drops to ~10s.

## Open questions for spec/impl-execute

- **Confirm `static-checks-backend` already exists and what it covers.** If it covers ruff/format and mypy already, then Win 1 reduces to dropping the redundant steps from the heavy job (a 5-line YAML edit). If it covers only one of those, the chore extends it. Worth a 5-minute audit of `pr.yml` before starting.
- **`pytest-xdist` test-isolation audit.** A small subset of tests may rely on shared fixture state (rare in this codebase but worth a one-pass grep for `@pytest.mark.serial`, module-level `_GLOBAL = ...` patterns, or `conftest.py` autouse fixtures with side effects). If any are found, the chore either marks them `@pytest.mark.serial` (xdist supports a single-worker serial group) or rewrites them — depends on count.

## Scope signals

- **Backend:** none (no `backend/app/` source touched).
- **Frontend:** none.
- **Migration:** none.
- **Config:** `.github/workflows/pr.yml` (job split), `Makefile` (test target update), `pyproject.toml` (add `pytest-xdist` to dev deps if not already there).
- **Audit events:** N/A — CI workflow config.
- **Operator impact:** none on operator-path behavior. Affects CI feedback latency only. Operators flipping `SKIP_HEAVY_CI=true` see no change.

## Relationship to other work

- Sibling of `infra_smoke_reseed_runtime_budget` (shipped 2026-06-02 in PR #424) — that work made the `smoke` job feasible to opt-in via `SMOKE_TEST=true`. This chore reduces the *default* per-PR critical path (smoke is opt-in/off), so even when smoke runs it stops being the wall-clock bottleneck.
- Coordinates with — but does NOT block — Win 3 (`infra_pr_yml_split_integration_by_service`). Wins 1 + 2 are pure subtractions from the heavy job; Win 3 is a structural split. Either can ship first.
- Captured during `bug_llm_capability_cache_no_refresh` (PR #426) CI watch — the slow backend job made the operator wait through two cycles (initial push + post-Gemini-fixes push); each waited the same 8 min on the same backend lane.

## Why filed instead of fixed inline during PR #426

Per CLAUDE.md "Tangential discoveries — fix inline by default": tested the inline-fix gate. This work is:
- **Cross-subsystem from the bug fix** (CI/workflow vs. LLM capability cache — different surfaces, no shared file).
- **>60 min of work** even for Wins 1 + 2 (need to audit existing `static-checks-backend`, verify `pytest-xdist` is in deps, test-isolation pass).
- **Would expand PR #426's review scope** from "Redis cache helper" to "Redis cache helper + CI parallelization" — confusing for the reviewer.

So the rubric rows for "cross-subsystem + >60 min" + "expands PR review scope" both say defer. Filed as a separate chore for parallel execution.
