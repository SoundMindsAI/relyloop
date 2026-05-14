# Idea — `chore_digest_worker_narrow_except`

**Date:** 2026-05-13
**Preflighted:** 2026-05-14 — line numbers verified (no churn on digest.py since 2026-05-13); cross-link to bug_fix.md updated for archive path; three open forks locked with defaults; CLAUDE.md absolute-rules walked.
**Status:** Idea (deferred from Gemini Code Assist Finding #2 on [PR #92](https://github.com/SoundMindsAI/relyloop/pull/92)) — ready for `/impl-execute --ad-hoc` after forks lock.

## Origin

Gemini Finding #2 on [PR #92 `bug_digest_param_importance_seam`](https://github.com/SoundMindsAI/relyloop/pull/92): the worker's broad `except Exception` at [`backend/workers/digest.py:538-546`](../../../../backend/workers/digest.py#L538-L546) silently swallowed the `ImportError` for ~2 days, which is what let `parameter_importance = {}` ship unnoticed. Adding `scikit-learn` closes the immediate gap; the maintainability concern about the broad-except remains as a separate hardening item.

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
- The misleading `assert digest.parameter_importance is not None` at [`test_digest_generate.py:65`](../../../../backend/tests/integration/test_digest_generate.py#L65) (kept intentionally — see [`bug_digest_param_importance_seam/bug_fix.md` decision #4](../../../00_overview/implemented_features/2026_05_13_bug_digest_param_importance_seam/bug_fix.md) — archive path; folder moved to `implemented_features/` 2026-05-13) passes because `{}` is not None.
- The only test that actually catches this is the dedicated AC-7 test, which was xfail-marked for 2 days because of the misdiagnosis.

## Why deferred (forks now locked — 2026-05-14 preflight)

The exception narrowing has design surface that's separate from the PR #92 dep fix:

1. **Which exceptions are "expected"?** Optuna documents `ValueError: No trials are completed yet` for small-study cases. The codebase doesn't yet have an audit of what other exceptions `optuna.importance.get_param_importances` legitimately raises (small studies, single-trial studies, all-pruned-trials studies, schema not initialized, etc.). Narrowing without an audit risks failing digests that should gracefully fall back to `{}`.

   **Locked decision (2026-05-14):** the allowlist of "expected" exceptions lives as a module-level `frozenset[type[BaseException]]` in `backend/workers/digest.py` next to the call site (e.g., `_PARAM_IMPORTANCE_EXPECTED: frozenset[type[BaseException]] = frozenset({ValueError, RuntimeError})` — final shape determined by the audit step). The audit is a Story 1 task (write parametrized unit tests against fixture studies that trigger each documented edge case; capture the actual exception types raised).

2. **What's the failure mode for unexpected exceptions?** Two options were on the table:
   - **(a) Hard fail** — re-raise unexpected exceptions; Arq retries; if persistent, the study's digest stays in `pending` and an operator gets paged.
   - **(b) Soft fail with louder signal** — keep the soft-fail behavior but emit `digest_importance_failed_unexpected` at ERROR level (not WARN) for non-allowlisted exceptions; the operator-facing `make logs` and (MVP2+) Langfuse alerting trigger off ERROR.

   **Locked decision (2026-05-14): option (b) — soft fail with ERROR-level signal.** MVP1 has no PagerDuty / SaaS install; "paging the operator" is functionally equivalent to "stands out in `make logs`". Hard-fail interrupts user-facing flow (digest stays pending; proposal can't show importance) for what was a non-fatal property of the digest. Soft-fail-with-ERROR keeps the digest shippable while making the regression loud. Allowlisted exceptions continue to log `digest_importance_failed` at WARN (existing event_type, no change); only the unexpected-exception path takes the new ERROR-level `digest_importance_failed_unexpected` event_type.

3. **What's the rollout?** The original concern was "currently-silently-failing digests would suddenly start failing loudly — operators would see a flood." **Re-evaluated 2026-05-14:** MVP1 is single-operator-laptop and has no SaaS install; "production digest state survey" doesn't apply. The only existing silently-failed case (sklearn ImportError) was fixed in PR #92, and at MVP1 scale all post-#92 digests should be re-runnable. **Locked: no pre-merge survey needed.** Revisit if/when MVP3 ships a SaaS install with persistent digest history.

## Proposed scope

1. **Audit** legitimate exceptions: write parametrized unit tests in `backend/tests/unit/workers/test_digest_importance_audit.py` that seed Optuna fixture studies into each documented edge case (zero-trial, single-trial, all-pruned, schema-uninitialized) and capture which exception type `optuna.importance.get_param_importances` actually raises. The audit OUTPUT is the allowlist: a `_PARAM_IMPORTANCE_EXPECTED: frozenset[type[BaseException]]` module-level constant in `digest.py` next to the call site.
2. **Narrow the except** to the audited allowlist. Allowlisted exception → log `digest_importance_failed` at WARN (existing event_type, unchanged) + return `{}`. Unexpected exception → log `digest_importance_failed_unexpected` at ERROR + return `{}` (soft-fail, per fork #2 lock above).
3. **Backfill an integration test** that monkeypatches `optuna.importance.get_param_importances` to raise `ImportError` (the canonical "this would have caught PR #92's regression on day one" case) and asserts the ERROR-level event_type fires + `parameter_importance == {}`.
4. **Update the existing AC-7 test** to assert the NEW path: an allowlisted exception (small-study `ValueError`) produces WARN-level event_type; the legacy `is not None` assertion at `test_digest_generate.py:65` stays as-is (it's a pre-existing canary, separately documented as decision #4 in the archived bug_fix.md).

## Scope signals

- **Backend only:** `backend/workers/digest.py` (3-5 LOC: add the frozenset, narrow the except, add the ERROR-level branch) + tests (2-3 unit cases + 1 integration case). No migration. No config.
- **Tests:** new unit test file `backend/tests/unit/workers/test_digest_importance_audit.py` (parametrized over edge cases) + 1 new integration case in `test_digest_generate.py`.
- **CLAUDE.md absolute-rules walked:** none implicated. Not a state mutation (digest already exists), no new endpoint, no new secret, no LLM call, no schema change. The ERROR-level event_type is structlog only (audit_log lands at MVP2; even then, this is a soft-fail observability signal, not a tenant-visible state change requiring an audit_log row).
- **Audit events:** N/A (MVP1).
- **Rollout:** no pre-merge survey needed (MVP1 has no SaaS install; per fork #3 lock).

## Dependencies

- PR #92 (`bug_digest_param_importance_seam`) — already merged 2026-05-13. Archived at [`implemented_features/2026_05_13_bug_digest_param_importance_seam/`](../../../00_overview/implemented_features/2026_05_13_bug_digest_param_importance_seam/).
- No other planned-features siblings touch `digest.py`. `digest.py` is unchanged since the PR #92 fix landed (verified 2026-05-14 via `git log --since="2026-05-13" -- backend/workers/digest.py`).

## Relationship to other work

- Cleanup follow-up from a Gemini-driven idea capture (Finding #2 on PR #92). The kind of "we noticed this but it's separate from the immediate fix" pattern that the day's preflight/adhoc loop is well-suited to drain.
- No interference with the remaining backlog. After this lands, the only backlog items are MVP2/MVP3-gated holds + the preflighted `infra_arq_subprocess_test` (waiting on a trigger condition).
- Sibling chore that's now archived: `infra_dashboard_regen_pre_commit_conflict` (shipped as PR #108) — similar "structlog event-type + observability hardening" shape; the new `digest_importance_failed_unexpected` event_type follows the same naming convention (`<domain>_<state>_<modifier>`).
