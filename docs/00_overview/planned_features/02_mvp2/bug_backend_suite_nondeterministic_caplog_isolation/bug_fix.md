# Bug fix — backend suite nondeterministic caplog isolation

**Source idea:** [idea.md](./idea.md)
**Branch:** `feature/mvp2-backlog-spec-plan-batch`
**Type:** bug fix — medium (test-infra root cause, product-code one-liner fix)
**Date:** 2026-06-01

## Problem

The full backend CI job (`pr.yml` → `backend`) is nondeterministically red. Many
unit tests that assert on `structlog.testing.capture_logs()` output fail with
empty-capture shapes (`assert []`) in the full suite yet pass in isolation, and
re-running the *identical* commit produces a *different* failing set. Whether
green is luck depends on test execution order, silently eroding the 80% coverage
gate and flaking every future PR.

## Reproduction

The idea attributed the randomization to `pytest-randomly` — but that plugin is
**not installed** (no entry in `pyproject.toml` / `uv.lock`), and CI runs plain
`uv run pytest backend/tests/` (no `-n auto`). The unit layer alone is stable
across `PYTHONHASHSEED` (8/8 seeds → 2068 passed). The real trigger is the
**combined** run where integration tests call `configure_logging()` (FastAPI
lifespan) in the same process as the caplog unit tests; run-to-run variation in
CI is a fresh `PYTHONHASHSEED` per GHA run changing bind/emit ordering.

Surgical reproducer (`/tmp/relyloop_repro/repro2.py`, real modules) — fails on
`main`, passes on this branch:

```python
from backend.app.core.logging import configure_logging
from backend.app.services import cluster_health_warmup as chw
import structlog

configure_logging(); chw.logger.info("warm")        # binds + caches chw.logger -> list L1
configure_logging()                                  # replaces config list -> L2
with structlog.testing.capture_logs() as logs:
    chw.logger.info("under_capture")
assert len(logs) == 1      # FAILS on main (0 captured); passes after the fix
```

Full in-container suite (CI parity, integration layer included): **33 failed,
14 errors** under one ordering; exit 0 under another — the nondeterminism, live.

## Root cause

- Owning layer: **product code** — `configure_logging()` (the idea guessed
  "conftest fixtures"; that guess is insufficient, see below).
- Origin: [backend/app/core/logging.py:79](../../../../backend/app/core/logging.py#L79) —
  `structlog.configure(processors=[*shared, wrap])` hands structlog a **brand-new
  list instance** on every call.
- Mechanism: structlog binds each logger against the *same list instance* that
  `get_config()["processors"]` returns, and `cache_logger_on_first_use=True`
  ([logging.py:86](../../../../backend/app/core/logging.py#L86)) freezes that
  reference. `structlog.testing.capture_logs()` (structlog 25.5.0) deliberately
  *mutates that list in place* — "keep the list instance intact to not break
  references held by bound loggers." So a second `configure_logging()` swaps the
  config's list for a fresh instance; a module-level logger cached against the
  old instance goes blind to `capture_logs()`, which mutates the new one.

Empirically confirmed that **no global reset un-blinds an already-cached proxy**:
`structlog.reset_defaults()` → captured 0; `configure(cache_logger_on_first_use=
False)` after caching → captured 0. That is why a conftest setup/teardown reset
fixture (the idea's proposed fix) cannot fully fix the cross-test poison.

### Second polluter (same mechanism, test side)

[backend/tests/unit/domain/ubi/test_position_bias_prior.py:36](../../../../backend/tests/unit/domain/ubi/test_position_bias_prior.py#L36)
hand-rolled its log-capture fixture with `structlog.configure(processors=[cap])`
+ `structlog.reset_defaults()` on teardown — both *replace* the list instance,
re-poisoning every logger bound before it ran, regardless of the
`configure_logging()` fix. This is why the in-container full suite still showed
the caplog cluster red after the product fix alone. Deterministic repro (host,
no DB): run `test_position_bias_prior.py` before the caplog cluster → 8 failed;
with both fixes → 75 passed.

## Fix design (locked decisions)

1. **Mutate the existing processors list in place** in `configure_logging()`
   instead of replacing it (`existing[:] = new; configure(processors=existing)`).
   Every bound logger — cached or not — then always observes the current chain,
   exactly like `capture_logs()` relies on. Cites: structlog 25.5.0
   `capture_logs()` source + its own in-place-mutation rationale; CLAUDE.md Bug
   Fix Protocol "fix at the right layer" (root cause is the list replacement, not
   the test).
2. **Keep `cache_logger_on_first_use=True`** — production keeps its perf win; the
   list-identity fix makes caching harmless. Cites: no behavior change for the
   single prod startup call.
2b. **Rewrite the `test_position_bias_prior` capture fixture** to mutate the
   processors list in place (mirroring `structlog.testing.capture_logs()`), so a
   test fixture can never be the polluter. Preserves the `cap.entries` API → zero
   test-body changes.
3. **Regression test is the guard** (idea capability #4), not a CI adversarial
   seed — a deterministic unit test that reproduces the poison is stronger and
   cheaper than a fixed-seed matrix entry. Cites: CLAUDE.md "every bug fix must
   include a regression test."

### Out of scope (separate, already-captured)

The 3 contract failures that reproduce **deterministically in isolation**
(`test_openapi_surface`, `test_enum_source_of_truth_helpers`,
`test_health_contract` — all missing `'solr'` / 5 MVP2 endpoints) are
hand-maintained allowlist drift tracked by
[`bug_contract_allowlists_outdated_after_mvp2_features`](../bug_contract_allowlists_outdated_after_mvp2_features/idea.md),
not this isolation bug. Left untouched here to keep scope clean.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/core/test_logging_configure_list_identity.py` | (1) two `configure_logging()` calls keep the same processors list object; (2) `capture_logs()` still sees a logger cached before a 2nd `configure_logging()`. Both fail on `main`, pass on branch. |
| unit (in-place validation) | existing `test_position_bias_prior.py` (15 tests) + the caplog cluster (`test_cluster_health_warmup`, `test_capability_check`, `test_stamp_baseline_trial`, `test_study_preflight`, `test_health`) | Run together poisoner-first: 8 failed pre-fix → 75 passed post-fix. The fixture rewrite is its own guard (it *is* the previously-poisoning fixture). |

## Rollout

None — code-only change. No migration, no API change, no operator action. The
single production caller (`main.py` lifespan) calls `configure_logging()` once;
the fix only affects the repeated-call (test) path's reference identity.

## Tangential observations

- Stray `/tmp/bisect.py` on the operator's machine shadows stdlib `bisect` when a
  script runs with `/tmp` on `sys.path[0]` — host-local debug leak, not in the
  repo, no idea file warranted.
- The `dev` group comment in `pyproject.toml` claims "the workflow passes
  `-n auto`" but `pr.yml` reverted it — stale comment, ≤5 LOC; noted, not filed.
