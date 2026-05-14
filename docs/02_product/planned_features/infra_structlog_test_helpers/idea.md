# Tiny test-helper kit for structlog log assertions

**Date:** 2026-05-14
**Status:** Idea — captured during the PR #112 (`chore_digest_worker_narrow_except`) CI session, refreshed by `/idea-preflight` after PR #112 + PR #113 finalization.
**Origin:** PR #112 surfaced two distinct structlog-test flakes in two CI runs:

1. **First CI run** (commit `aaa0fdd`, "tolerate structlog log_level vs level key naming") — the new unit tests in `backend/tests/unit/workers/test_digest_importance_audit.py` asserted `entry["log_level"] == "..."` but the CI environment's structlog emits the level under `"level"`. Inline fix tolerated either key.
2. **Second CI run** (commit `bc7dd60`, "replace structlog capture_logs with module-logger monkeypatch") — after #1 unblocked the assertion, `capture_logs()` returned an EMPTY list in CI. Root cause: `backend/app/core/logging.py:82` uses `structlog.configure(cache_logger_on_first_use=True)`. Once any earlier integration test warms the cache via FastAPI lifespan, the digest worker's `BoundLoggerLazyProxy` is frozen — `capture_logs()` cannot intercept emissions on the already-bound logger. Locally (cache cold) capture_logs works; in CI (cache warm) it doesn't. `structlog.reset_defaults()` doesn't help (already-frozen bindings are sticky); pytest `caplog` doesn't see structlog→stdlib emissions either. The robust fix that shipped: a tiny `_RecordingLogger` stub class duplicated into both `test_digest_importance_audit.py` and `test_digest_generate.py` plus `monkeypatch.setattr("backend.workers.digest.logger", rec)`.

This idea factors BOTH lessons into a shared test-helper module so the pattern doesn't get re-invented (or re-broken) the next time a worker or service needs structlog-event assertions.

## Problem

The repo currently has two distinct, half-overlapping patterns for asserting structlog events from tests:

**Pattern A — `structlog.testing.capture_logs()`.** Works when the logger under test isn't cached (i.e., no prior test in the session triggered `cache_logger_on_first_use`). Asserts against the captured EventDict list. Fragile in two ways:

- Level key naming: some structlog versions / processor configurations emit `log_level`, others emit `level`. Bare `entry["log_level"]` raises KeyError on mismatch; `entry.get("log_level")` returns None silently (which can cause filtered-list assertions to pass for the wrong reason — a slow-flake risk worse than the hard-flake).
- Cache warmth: if any sibling test in the same pytest session warmed the cache for the target logger, `capture_logs()` returns an empty list. The test then fails with `assert 0 == 1` and no signal that the capture mechanism itself was the culprit.

**Pattern B — `_RecordingLogger` stub + `monkeypatch.setattr(module_logger_path, stub)`.** The pattern shipped in PR #112 to escape Pattern A's cache trap. Records `.warning()` / `.error()` / `.info()` calls as `(level, event, kwargs)` tuples; offers a `.find(level=..., event_type=...)` helper. Bypasses structlog's processor chain entirely — invariant under cache state. Currently DUPLICATED verbatim across two test files; the next test that hits the same flake will copy it a third time.

**The shape of the factoring:**

| When to use | Helper |
|---|---|
| Logger NOT cached (most API/handler tests via `httpx.AsyncClient(app=...)` or pure-function unit tests where the logger is created fresh in the test process) | `capture_logs()` + `assert_log_level(entry, "warning")` for tolerant level reads + `find_log_events(captured, event_type)` for the common filter |
| Logger IS cached (worker tests running after any integration test that boots FastAPI lifespan; tests on modules whose logger was already bound elsewhere in the session) | `RecordingLogger()` stub + `monkeypatch.setattr("<module>.logger", rec)` |

Same library, two helpers, one decision point.

## Proposed capabilities

Add a single private test-helper module — `backend/tests/_log_helpers.py` — exporting three symbols:

```python
from collections.abc import MutableMapping
from typing import Any


def assert_log_level(entry: MutableMapping[str, Any], expected: str) -> None:
    """Assert a captured structlog entry's level matches ``expected``.

    Tolerant of the ``log_level`` vs ``level`` key naming inconsistency
    across structlog versions / processor configurations (PR #112 CI flake).
    Raise AssertionError with the full entry on mismatch — never silently
    return None.
    """
    actual = entry.get("log_level", entry.get("level"))
    assert actual == expected, (
        f"expected log level {expected!r}, got {actual!r} (entry: {entry!r})"
    )


def find_log_events(
    captured: list[MutableMapping[str, Any]],
    *,
    event_type: str | None = None,
    event: str | None = None,
) -> list[MutableMapping[str, Any]]:
    """Filter captured structlog entries by ``event_type`` and/or ``event``.

    Both kwargs optional; at least one must be provided. Pass the kwarg that
    matches what the production code emits — services use ``event_type`` for
    machine-routable events, FastAPI routers use ``event`` for the
    free-form action name.
    """
    if event_type is None and event is None:
        raise ValueError("at least one of event_type or event must be provided")
    return [
        e
        for e in captured
        if (event_type is None or e.get("event_type") == event_type)
        and (event is None or e.get("event") == event)
    ]


class RecordingLogger:
    """Records ``.warning()`` / ``.error()`` / ``.info()`` / ``.debug()`` calls.

    Designed to replace ``structlog.testing.capture_logs()`` for tests where
    the logger under test is already cached
    (``cache_logger_on_first_use=True`` in ``configure_logging``). Once any
    sibling test warms the cache via FastAPI lifespan, ``capture_logs()``
    cannot intercept emissions on the bound logger and returns an empty
    list. Monkeypatching the module-level ``logger`` attribute with this
    stub bypasses the cache entirely.

    Usage::

        rec = RecordingLogger()
        monkeypatch.setattr("backend.workers.digest.logger", rec)
        await generate_digest({}, study_id)
        warns = rec.find(level="warning", event_type="digest_importance_failed")
        assert len(warns) == 1
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("warning", event, dict(kwargs)))

    def error(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("error", event, dict(kwargs)))

    def info(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("info", event, dict(kwargs)))

    def debug(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("debug", event, dict(kwargs)))

    def find(
        self,
        *,
        level: str,
        event_type: str | None = None,
        event: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            kw
            for lvl, evt, kw in self.calls
            if lvl == level
            and (event_type is None or kw.get("event_type") == event_type)
            and (event is None or evt == event)
        ]
```

Then refactor the existing call sites:

1. **`backend/tests/unit/workers/test_digest_importance_audit.py`** — delete local `_RecordingLogger` class definition (lines 46-85); import `RecordingLogger` from `backend.tests._log_helpers`. Rename `rec.find(level=..., event_type=...)` calls to match the new signature (already compatible).
2. **`backend/tests/integration/test_digest_generate.py`** — same: delete local `_RecordingLogger` (lines 33-62); import the shared one.
3. **`backend/tests/integration/test_judgments_resume_sweep.py`** — lines 255, 300: replace `assert entry["log_level"] == "warning"` (brittle to key drift) with `assert_log_level(entry, "warning")`. Optionally migrate the inline `[e for e in captured if e["event"] == "..."]` filters to `find_log_events(captured, event=...)`.
4. **`backend/tests/unit/test_capability_check.py`** — lines 202, 282: replace `[e for e in captured if e.get("log_level") == "warning"]` (silent-pass risk when key is `level`) with `[e for e in captured if assert_log_level_or_skip(e, "warning")]` — or more cleanly, use `find_log_events(captured, event=...)` to filter by event name first, then `assert_log_level(e, "warning")` on each. The current `.get()` filter masks a real flake mode.

## Scope signals

- **Backend:** one new private helper module — `backend/tests/_log_helpers.py` — ~70 LOC. No production code touched. Pure test-infra.
- **Test refactors:** 4 call sites (not 3 as the prior draft claimed):
  - `backend/tests/unit/workers/test_digest_importance_audit.py` (PR #112) — delete duplicate `_RecordingLogger`.
  - `backend/tests/integration/test_digest_generate.py` (PR #112) — delete duplicate `_RecordingLogger`.
  - `backend/tests/integration/test_judgments_resume_sweep.py` (PR #104) — `entry["log_level"]` at lines 255, 300 → `assert_log_level`.
  - `backend/tests/unit/test_capability_check.py` — `e.get("log_level")` filter at lines 202, 282 → grounded helper that doesn't silent-pass on key drift.
  Net change in those files: ~−40 LOC (most of the win is deleting two duplicate class bodies).
- **Untouched on purpose:** `backend/tests/integration/test_query_sets_router_queries.py` lines 526-585 — uses `capture_logs()` but filters by `event` (not level); not affected by the key-name drift. No refactor value.
- **CLAUDE.md absolute-rules walked:** none implicated. Test-only.

## Decisions locked

- **(locked)** Helper module path: `backend/tests/_log_helpers.py`. Sibling to `conftest.py`; importable from both `unit/` and `integration/`. Alternatives considered: bundling into `conftest.py` (rejected — conftest is for fixtures, not a kitchen sink); `backend/tests/unit/_test_helpers.py` (rejected — integration tests would need an awkward up-walk import).
- **(locked)** Factor BOTH helper families, not just the level-key tolerance. The `RecordingLogger` factoring is the load-bearing piece (deletes ~80 LOC of duplicated stub class); the `assert_log_level`/`find_log_events` helpers fix the latent silent-pass risk at the existing `capture_logs()` sites.
- **(locked)** Don't migrate `capture_logs()` callers to `RecordingLogger` wholesale. They're not on cached loggers — `capture_logs()` works fine there. Only swap to `RecordingLogger` when a new test hits the cache-warmth trap. Surface the decision rule in a docstring on each helper.
- **(locked)** Make the module private (`_log_helpers.py`, leading underscore) so it's clear this is test-only infra and not importable from production code.

## Open questions for /spec-gen

None blocking. The factoring is mechanical once the patterns are settled. If `/spec-gen` wants to surface anything, it's whether to add a one-line `tests/CLAUDE.md` (or docstring at the top of `_log_helpers.py`) pointing future test authors at the helper kit — recommended default: yes, a top-of-module docstring is enough; no new doc file.

## Why deferred

Still valid. The PR #112 inline fix shipped correctly via the `_RecordingLogger` route; the factoring isn't urgent. Two of the three reasons in the original draft still hold:

- The PR #112 + PR #113 squash-merge would have ballooned in scope to include a project-wide test helper.
- Factoring is best done as a focused `/impl-execute --ad-hoc` once the patterns are stable enough to crystallize (now true after PR #112's two-CI-run learning curve).

Refreshed trigger: the moment a 4th test file is about to use either pattern. Without that pressure the duplication is bounded at 2 files and is cheap to read.

## Relationship to other work

- **Beneficiaries** (call sites the factoring touches):
  - `backend/tests/unit/workers/test_digest_importance_audit.py` (PR #112)
  - `backend/tests/integration/test_digest_generate.py` (PR #112)
  - `backend/tests/integration/test_judgments_resume_sweep.py` (PR #104)
  - `backend/tests/unit/test_capability_check.py` (existed before MVP1 ship; the `.get()` form is a latent silent-pass risk surfaced by this audit)
- **Sibling planned features:** `infra_arq_subprocess_test` (separate surface — Arq worker subprocess CI hygiene; no overlap with structlog test helpers).
- **Not blocking anything.** Pure DX cleanup. Ships best as `/impl-execute --ad-hoc` once a 4th call site lands or as a standalone session when the operator wants to drain the backlog.
