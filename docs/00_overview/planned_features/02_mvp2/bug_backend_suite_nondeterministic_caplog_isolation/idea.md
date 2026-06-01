# Idea — backend test suite is order-dependent: caplog/contract tests fail nondeterministically under `pytest-randomly`

**Date:** 2026-06-01
**Status:** Idea — bug surfaced by CI on PR #363
**Type:** `bug_`
**Priority:** P1 — the full backend CI job (`pr.yml` → `backend (lint + typecheck + tests + coverage)`) is **nondeterministically red**. Whether it passes depends on the `pytest-randomly` seed, so green is luck, not signal. This silently erodes the 80% coverage gate's value and will block / flake every future PR.

## Origin

PR #363 (`chore/regen-stale-guide-screenshots`) went red on the `backend` job with **21 failures**. Re-running the **identical commit** produced a **different** failing set (e.g. `test_enum_source_of_truth_helpers`, `test_openapi_surface`, `test_demo_seeding_ubi_full` appeared only on the second run). The PR's diff touched only test-only seeding code (`backend/app/api/v1/_test.py`, `backend/app/services/test_seeding.py`) — none of the failing tests or their SUTs — so the failures are not caused by that PR. `main`'s last full backend run (2026-05-28, run `26608512750`) passed only because its seed didn't trip the latent bug. (Backend CI has been mostly skipped since 2026-05-29 under `SKIP_HEAVY_CI`, which is why this stayed hidden until heavy CI was restored on 2026-05-31.)

## Problem

Many backend unit tests assert on captured log records (`caplog` / a structlog capture fixture) and fail with empty-capture shapes (`assert []`, `assert 'x' in []`) when run in the full randomized suite, yet **pass in isolation**. Confirmed locally on a clean tree:

- `backend/tests/unit/services/test_cluster_health_warmup.py` — 7/7 pass alone.
- `backend/tests/unit/test_capability_check.py` — pass alone.
- `backend/tests/unit/services/test_stamp_baseline_trial.py`, `test_study_preflight.py`, `test_health.py` — same pattern.

The shared signature (`assert []` for expected log records) points at **log-capture / structlog configuration state leaking across tests** — a test earlier in the random order reconfigures structlog (or detaches the capture handler) and later tests see no records. A separate cluster of failures (`test_openapi_surface`, `test_enum_source_of_truth_helpers`) suggests a second source of shared mutable state (FastAPI app / OpenAPI schema cache, or an enum registry).

Distinct from [`bug_baseline_phase_test_isolation`](../bug_baseline_phase_test_isolation/idea.md), which is the *narrow inverse* (one file fails in isolation, passes in the full run). This bug is broad and direction-opposite (pass in isolation, fail in full randomized run) and makes the whole job nondeterministic.

Two recurring failures are separate pre-existing MVP2 drift, not isolation-related:
- `test_judgment_generate.py::test_happy_path_ac1_ac6` — `{'click': 0}` now in the source breakdown (tracked by the contract-allowlist work, issues #356/#357 + `bug_contract_allowlists_outdated_after_mvp2_features`).
- `test_migration_0021_generation_params` downgrade — separate migration-roundtrip issue.

## Proposed capabilities

1. **Find the polluter(s).** Use `pytest-randomly`'s seed reproduction (`-p randomly --randomly-seed=<seed>` from a failing CI run) + `pytest --lf` / bisect to identify the test(s) that reconfigure structlog or leave the log-capture handler detached.
2. **Fix at the fixture layer.** Likely an autouse fixture that re-initializes structlog configuration + reattaches the capture handler per test (function-scoped), so log assertions are hermetic regardless of order.
3. **Audit the second cluster** (OpenAPI/enum) for a similarly shared cache that needs per-test reset.
4. **Add a guard** so this can't silently regress — e.g. a CI matrix entry that runs the unit suite under a fixed adversarial seed, or a marker that asserts structlog is in the expected config at the start of each caplog test.

## Why deferred (not fixed inline)

Out of scope for the guide-screenshot regen (PR #363), which is test-only seeding + assets and touches none of the affected files. Root-causing the polluter is a focused debugging task across the test-infra layer, not the feature surface. Captured per the tangential-discoveries rule rather than carried in working memory.

## Scope signals

- **Backend tests / test-infra:** the fix is in conftest fixtures, not product code.
- **No migration, no API change.**
- **CI:** may add a fixed-seed adversarial run to `pr.yml`.

## Relationship to other work

- Sibling: [`bug_baseline_phase_test_isolation`](../bug_baseline_phase_test_isolation/idea.md) (narrow inverse case — may share a root cause with the structlog cluster).
- Surfaced when `SKIP_HEAVY_CI` was deleted (2026-05-31), restoring the full backend job after a multi-day skip.
