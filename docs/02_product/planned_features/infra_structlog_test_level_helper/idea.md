# Tiny helper for structlog `capture_logs()` log-level assertions

**Date:** 2026-05-14
**Status:** Idea — captured during chore_digest_worker_narrow_except CI failure on PR #112
**Origin:** PR #112 CI run failed on `test_digest_importance_audit.py:163,203` and `test_digest_generate.py` because the assertions used `entry["log_level"]` but `structlog.testing.capture_logs()` emits the level under the key `"level"` in the CI environment. Same code passed locally. Same `["log_level"]` pattern is also present in `backend/tests/integration/test_judgments_resume_sweep.py` (already shipped via PR #104) — it happens to skip locally (Postgres internal-only) and was lucky enough to land in CI under a structlog version where `log_level` was the right key.

## Problem

`structlog.testing.capture_logs()` is supposed to give tests a stable EventDict per emission. In practice the level key varies:

- Some structlog versions / processor configurations emit `log_level`.
- Others emit `level`.
- The same test file passes locally and fails in CI, or vice versa, depending on which env's structlog the asserts hit.

The fix in PR #112 was inline:

```python
assert (entry.get("log_level") or entry.get("level")) == "warning"
```

That's correct but it's the kind of thing every future test that uses `capture_logs()` will re-invent. Three sites already use it (`test_digest_importance_audit.py`, `test_digest_generate.py`, `test_judgments_resume_sweep.py`); the next four will too unless we factor it.

## Proposed capabilities

Add a tiny helper in `backend/tests/conftest.py` (or `backend/tests/unit/_test_helpers.py` if you prefer to keep conftest minimal):

```python
def assert_log_level(entry: MutableMapping[str, Any], expected: str) -> None:
    """Assert the captured structlog entry's log level matches ``expected``.

    Tolerant of the ``log_level`` vs ``level`` key naming inconsistency across
    structlog versions / processor configurations (PR #112 CI flake).
    """
    actual = entry.get("log_level") or entry.get("level")
    assert actual == expected, (
        f"expected log level {expected!r}, got {actual!r} (entry: {entry!r})"
    )
```

And/or a complementary helper for the common "find events by event_type" pattern that all three sites duplicate:

```python
def find_log_events(
    captured: list[MutableMapping[str, Any]], event_type: str
) -> list[MutableMapping[str, Any]]:
    return [e for e in captured if e.get("event_type") == event_type]
```

Then refactor the three existing call sites to use the helpers + drop the inline `or` chains.

## Scope signals

- **Backend:** new helper(s) in `backend/tests/conftest.py` or `backend/tests/unit/_test_helpers.py` — 1 file, ~25 LOC.
- **Test refactors:** 3 existing call sites (PR #104's `test_judgments_resume_sweep.py`, PR #112's `test_digest_importance_audit.py` + `test_digest_generate.py`) — ~10 LOC of cleanup.
- **No production code touched.** Pure test-infra.
- **CLAUDE.md absolute-rules walked:** none implicated. Test-only.

## Why deferred

The PR #112 inline fix is correct and shippable. Extracting the helper would expand the PR scope from "narrow the digest worker except" to also "factor a project-wide test helper" — cross-subsystem scope creep. The refactor is best done as a separate `chore_` ad-hoc that touches just the three test files + the helper module.

## Relationship to other work

- Three existing test files would be the immediate beneficiaries:
  - `backend/tests/unit/workers/test_digest_importance_audit.py` (PR #112, this session)
  - `backend/tests/integration/test_digest_generate.py` (PR #112, this session)
  - `backend/tests/integration/test_judgments_resume_sweep.py` (PR #104)
- Not blocking anything. Pure DX cleanup.
- Ships best as `/impl-execute --ad-hoc` once any future test surfaces a 4th call site (at which point factoring becomes obviously worth it).
