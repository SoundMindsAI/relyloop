# infra — subprocess-driven Arq worker test for FR-5 / AC-4

**Date:** 2026-05-10
**Preflighted:** 2026-05-14 — confirmed test functions still exist at cited paths; `_subprocess_helpers/` directory already in place from PR #20 precedent; arq still at `>=0.26` (`0.28.0` in `uv.lock`); two crons now registered in `WorkerSettings.cron_jobs` (added context note).
**Status:** Idea (deferred from `feat_study_lifecycle` Phase 2 / PR #25 final GPT-5.5 review). Still applicable as of 2026-05-14: the three in-process tests cited below still cover the resume contract correctly; a subprocess test would add a narrow Arq-version-regression guard.
**Origin:** GPT-5.5 final-review finding #8 on PR #25 — Story 2.3 task 4 called for a subprocess fixture that spawns `arq backend.workers.all.WorkerSettings`, runs N seconds, SIGTERMs, then restarts, and asserts trials continue. PR #25 shipped the in-process equivalent because spawning a real Arq worker requires Redis + DB connectivity from the test process and stable lifecycle hooks.

## Why deferred

* The three test cases shipped at the unit/integration boundary verify the resume contract surfaces — sweep correctness + idempotent resume + wrapper dispatch. They live in [`backend/tests/integration/test_study_resume.py`](../../../../backend/tests/integration/test_study_resume.py): `test_on_startup_resumes_every_running_study`, `test_resume_study_idempotent_on_already_running`, `test_resume_study_wrapper_delegates_to_start_study`.
* A subprocess test would additionally catch Arq-version-specific wiring regressions (Arq's `WorkerSettings` schema changes, function registration semantics, `on_startup` hook signature drift, **cron-jobs registry drift now that `WorkerSettings.cron_jobs` carries two crons** — `reconcile_pr_state` from `feat_github_webhook` and `resume_stuck_judgment_lists` from `feat_judgments_periodic_resume_sweep`).
* [`docs/03_runbooks/study-lifecycle-debugging.md`](../../../03_runbooks/study-lifecycle-debugging.md) documents the manual SIGTERM dance for operators — verified present, still authoritative.

## Proposed fix

The `_subprocess_helpers/` directory **already exists** ([`backend/tests/integration/_subprocess_helpers/`](../../../../backend/tests/integration/_subprocess_helpers/)) with one entrypoint: `run_trial_with_test_stubs.py` (shipped with `infra_optuna_eval` Story 3.1, used by [`test_run_trial_partial_failure.py`](../../../../backend/tests/integration/test_run_trial_partial_failure.py)). Add a **second** entrypoint there:

`backend/tests/integration/_subprocess_helpers/orchestrator_restart.py`:

```python
@asynccontextmanager
async def arq_worker_subprocess() -> AsyncIterator[Process]:
    """Spawn `arq backend.workers.all.WorkerSettings` as a child process.

    Yields the process handle; on exit, SIGTERM + wait. The caller
    can also SIGTERM mid-test to simulate worker crash."""
```

Then in `backend/tests/integration/test_study_resume_subprocess.py`:

1. Seed a running study with `max_trials=100, parallelism=4`.
2. `async with arq_worker_subprocess() as p:` — wait until 20 trials commit; SIGTERM p; restart `arq_worker_subprocess()`.
3. Within 30s, new trials accumulate from `optuna_trial_number 21+`; study eventually completes at trial 100.

### Why an `@asynccontextmanager` (different from the existing precedent)

The shipped `run_trial_with_test_stubs.py` is invoked via synchronous `subprocess.run(...)` in `test_run_trial_partial_failure.py:_run_subprocess_with_fault` — it blocks until the helper exits, returning the exit code. That shape works for "spawn helper, wait for it to fault on a specific seam, assert exit code."

This idea's test fundamentally needs **mid-test control over the subprocess** (kill while it's mid-loop, observe DB state, restart). A sync `subprocess.run()` can't do that — it's await-or-block. The `@asynccontextmanager + Process` shape lets the test:

* Spawn via `asyncio.create_subprocess_exec(...)`.
* Poll the DB on the test's event loop while the worker runs.
* `p.terminate()` (or `os.kill(p.pid, signal.SIGTERM)`) on a deterministic condition.
* `await p.wait()` for clean shutdown.

These are different test shapes solving different problems; they coexist cleanly.

### Stub-survival across the subprocess boundary

The existing precedent at `run_trial_with_test_stubs.py:33-71` shows how to thread test doubles into a fresh Python interpreter (env-var-passed JSON blobs reinstalled inside `_main`). The new helper will need a similar pattern for any stubs the resume test needs — but the resume test arguably needs **fewer** stubs than the partial-failure test, since the goal is to exercise the REAL `on_startup` sweep + REAL `run_trial` against a REAL Optuna RDBStorage. Open question: does the test stub the engine adapter (`build_adapter`) at all, or accept that trials will fail against a non-running Elasticsearch and verify resume of `status='failed'` rows instead of `complete` ones? Locked recommendation: stub the engine adapter the same way `run_trial_with_test_stubs.py` does so trials genuinely complete; the test isn't trying to exercise the engine path.

## Scope signals

* **Backend:** yes (test infrastructure only — 2 new files: the helper at `_subprocess_helpers/orchestrator_restart.py` and the test at `test_study_resume_subprocess.py`).
* **Frontend:** no.
* **Migration:** no.
* **Config:** no.
* **Audit events:** N/A (test-only).
* **CLAUDE.md absolute-rules walked:** none implicated. No schema, no API, no LLM call, no secret, no engine-adapter dispatch, no audit_log emission, no `<select>` option list.

## Why this isn't a blocker today

The resume contract is functionally tested. The subprocess test catches a narrow class of Arq-version-specific regressions; the next time we bump Arq's version we should consider adding it.

**Concrete trigger lock:** ship this when one of the following happens, whichever comes first:

1. The `arq>=0.26` pin in `pyproject.toml` is bumped to a new minor version (e.g., `>=0.29`). Arq's `WorkerSettings` schema changes have historically landed in minor releases; the subprocess test is the cheapest way to detect schema breakage.
2. A third cron job lands in `WorkerSettings.cron_jobs` (current count: 2). At three or more crons the registry shape becomes worth a smoke test that exercises the real `arq` CLI invocation, not just an in-process import.
3. MVP3 hardening explicitly opts in.

## Relationship to other work

* [`feat_study_lifecycle` Phase 2 (PR #25)](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/) — the origin. The three in-process tests at `test_study_resume.py` are the deferred-from work.
* [`infra_optuna_eval` Story 3.1 (PR #20)](../../../00_overview/implemented_features/2026_05_10_infra_optuna_eval/) — established the `_subprocess_helpers/` pattern with `run_trial_with_test_stubs.py`. This idea adds a sibling entrypoint to the same directory.
* [`feat_github_webhook`](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/) + [`feat_judgments_periodic_resume_sweep`](../../../00_overview/implemented_features/2026_05_14_feat_judgments_periodic_resume_sweep/) — both shipped after this idea was written; both register cron jobs in `WorkerSettings.cron_jobs`. The subprocess test would now incidentally smoke-test cron-jobs-registry correctness too (any cron-registration regression would surface as worker-boot failure in the spawned subprocess).
* Not blocking and not blocked by anything currently in the backlog.
