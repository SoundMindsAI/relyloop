# Idea — `chore_digest_worker_narrow_except`

**Date:** 2026-05-13
**Status:** Idea (deferred from Gemini Code Assist Finding #2 on [PR #92](https://github.com/SoundMindsAI/relyloop/pull/92))

## Origin

Gemini Finding #2 on [PR #92 `bug_digest_param_importance_seam`](https://github.com/SoundMindsAI/relyloop/pull/92): the worker's broad `except Exception` at [`backend/workers/digest.py:538-546`](../../../../backend/workers/digest.py#L538-L546) silently swallowed the `ImportError` for ~2 days, which is what let `parameter_importance = {}` ship to production unnoticed. Adding sklearn closes the immediate gap; the maintainability concern about the broad-except remains as a separate hardening item.

## Problem

```python
try:
    parameter_importance = await _asyncio.to_thread(
        optuna.importance.get_param_importances, optuna_study
    )
except Exception as exc:  # noqa: BLE001 — small-study edge case
    logger.warning(
        "digest worker: get_param_importances raised; using empty map",
        event_type="digest_importance_failed",
        study_id=study_id,
        error_type=type(exc).__name__,
        error=str(exc),
    )
    parameter_importance = {}
```

`except Exception` catches *anything* — including future regressions like the sklearn-missing ImportError this PR resolved, a future scipy-missing ImportError, a misconfigured Optuna RDB connection, etc. The WARN log captures `error_type` but no operator pager / health-check signal exists for it. As a result:

- A dependency regression that breaks `get_param_importances` will silently return `{}` for every digest.
- The misleading `assert digest.parameter_importance is not None` at [`test_digest_generate.py:65`](../../../../backend/tests/integration/test_digest_generate.py#L65) (kept intentionally — see [`bug_digest_param_importance_seam/bug_fix.md`](../bug_digest_param_importance_seam/bug_fix.md) decision #4) passes because `{}` is not None.
- The only test that actually catches this is the dedicated AC-7 test, which was xfail-marked for 2 days because of the misdiagnosis.

## Why deferred

The exception narrowing has design surface that's separate from the PR #92 dep fix:

1. **Which exceptions are "expected"?** Optuna documents `ValueError: No trials are completed yet` for small-study cases. But the codebase doesn't have an audit of what other exceptions `optuna.importance.get_param_importances` legitimately raises (small studies, single-trial studies, all-pruned-trials studies, schema not initialized, etc.). Narrowing without an audit risks failing digests that should gracefully fall back to `{}`.
2. **What's the failure mode?** Two options:
   - **(a) Hard fail** — re-raise unexpected exceptions; the Arq worker retries; if it keeps failing, the study's digest stays in `pending` and an operator gets paged.
   - **(b) Soft fail with structured signal** — keep the broad except but emit `digest_importance_failed_unexpected` at ERROR level (not WARN) for non-allowlisted exceptions; add a `/healthz` subsystem check for "recent unexpected importance failures".
3. **What's the rollout?** If we narrow too aggressively, currently-silently-failing digests would suddenly start failing loudly — operators would see a flood of errors on existing studies that have been silently broken. Need a survey of how many production studies have `parameter_importance = {}` already (likely all of them pre-PR #92).

These three forks need their own design pass. Not a 1-PR change.

## Proposed scope

1. **Audit** legitimate exceptions: write a unit test that asserts the documented exception set (`ValueError: No trials are completed yet`, plus whatever Optuna's small-study path raises). Pin the expected set.
2. **Narrow the except** to that documented set.
3. **Re-raise** unexpected exceptions (or emit `digest_importance_failed_unexpected` ERROR-level + return `{}` — choose a fork).
4. **Backfill** an integration test that asserts a deliberately-broken Optuna call (e.g., monkeypatch `optuna.importance.get_param_importances` to raise `ImportError`) results in the chosen failure mode, not silent `{}`.

## Scope signals

- Backend only: `backend/workers/digest.py` + tests; no migration; no config.
- Tests: 2-3 unit cases + 1 integration case.
- Rollout: needs a pre-merge survey of production digest state to forecast operator impact.

## Dependencies

- PR #92 (`bug_digest_param_importance_seam`) — must merge first; this chore builds on the fix.
