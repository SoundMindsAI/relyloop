# infra — subprocess-driven Arq worker test for FR-5 / AC-4

**Date:** 2026-05-10
**Status:** Idea (deferred from `feat_study_lifecycle` Phase 2 / PR #25 final GPT-5.5 review)
**Origin:** GPT-5.5 final-review finding #8 — Story 2.3 task 4 called
for a subprocess fixture that spawns
`arq backend.workers.all.WorkerSettings`, runs N seconds, SIGTERMs,
then restarts, and asserts trials continue. PR #25 shipped the in-
process equivalent (`test_study_resume.py::test_on_startup_resumes_*`)
because spawning a real Arq worker requires Redis + DB connectivity
from the test process and stable lifecycle hooks.

## Why deferred

* The three test cases shipped at the unit/integration boundary
  (`test_on_startup_resumes_every_running_study`,
  `test_resume_study_idempotent_on_already_running`,
  `test_resume_study_wrapper_delegates_to_start_study`) verify the
  resume contract surfaces — sweep correctness + idempotent resume +
  wrapper dispatch.
* A subprocess test would additionally catch Arq-version-specific
  wiring regressions (Arq's `WorkerSettings` schema changes, function
  registration semantics, on_startup hook signature drift).
* `docs/03_runbooks/study-lifecycle-debugging.md` documents the
  manual SIGTERM dance for operators.

## Proposed fix

Add `backend/tests/integration/_subprocess_helpers/orchestrator_restart.py`:

```python
@asynccontextmanager
async def arq_worker_subprocess() -> AsyncIterator[Process]:
    """Spawn `arq backend.workers.all.WorkerSettings` as a child process.

    Yields the process handle; on exit, SIGTERM + wait. The caller
    can also SIGTERM mid-test to simulate worker crash."""
```

Then in `backend/tests/integration/test_study_resume_subprocess.py`:

1. Seed a running study with `max_trials=100, parallelism=4`.
2. `async with arq_worker_subprocess() as p:` — wait until 20 trials
   commit; SIGTERM p; restart `arq_worker_subprocess()`.
3. Within 30s, new trials accumulate from `optuna_trial_number 21+`;
   study eventually completes at trial 100.

## Scope signals

* Backend: yes (test infrastructure).
* Frontend: no.
* Migration: no.
* Config: no.

## Why this isn't a blocker today

The resume contract is functionally tested. The subprocess test catches
a narrow class of Arq-version-specific regressions; the next time we
bump Arq's version we should consider adding it.
