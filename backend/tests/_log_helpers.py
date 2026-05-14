"""Test helpers for asserting structlog events.

Two helper families with one decision point:

1. ``capture_logs()`` callers (most API / handler tests, pure-function unit
   tests) → use :func:`assert_log_level` for tolerant level-key reads and
   :func:`find_log_events` for the common event filter. The level-key
   tolerance protects against the structlog version drift where some
   environments emit ``log_level`` and others emit ``level``
   (PR #112 first-CI-run flake).

2. Tests on a cached logger (worker tests that run inside a session where
   a sibling integration test has already warmed the cache via the
   FastAPI lifespan) → use :class:`RecordingLogger` + ``monkeypatch.setattr``.
   ``structlog.configure(cache_logger_on_first_use=True)`` in
   :func:`backend.app.core.logging.configure_logging` freezes the bound
   logger's processor chain on first use; ``structlog.testing.capture_logs()``
   cannot intercept emissions on the already-bound logger and returns an
   empty list. Monkeypatching the module-level ``logger`` attribute with
   this stub bypasses the cache entirely (PR #112 second-CI-run fix).

Origin: ``infra_structlog_test_helpers`` — see the implemented_features entry
for the design notes and the two-step debugging history.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def assert_log_level(entry: MutableMapping[str, Any], expected: str) -> None:
    """Assert a captured structlog entry's level matches ``expected``.

    Tolerant of the ``log_level`` vs ``level`` key-naming inconsistency
    across structlog versions / processor configurations. Raises
    ``AssertionError`` with the full entry on mismatch — never silently
    returns ``None`` (which would let a filtered-list assertion pass for
    the wrong reason).
    """
    actual = entry.get("log_level", entry.get("level"))
    assert actual == expected, f"expected log level {expected!r}, got {actual!r} (entry: {entry!r})"


def find_log_events(
    captured: list[MutableMapping[str, Any]],
    *,
    event_type: str | None = None,
    event: str | None = None,
) -> list[MutableMapping[str, Any]]:
    """Filter ``capture_logs()`` output by ``event_type`` and/or ``event``.

    Both kwargs optional, but at least one must be provided. Pass the kwarg
    that matches what the production code emits — service-layer code uses
    ``event_type`` for machine-routable events; FastAPI routers and ad-hoc
    log calls use ``event`` for the free-form action name.
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
    """Cache-safe structlog stub for tests on already-bound loggers.

    Records ``.warning()`` / ``.error()`` / ``.info()`` / ``.debug()`` calls
    as ``(level, event, kwargs)`` tuples. Designed to replace
    ``structlog.testing.capture_logs()`` for tests where the logger under
    test is already cached via ``cache_logger_on_first_use=True``. Bypasses
    structlog's processor chain entirely, so it works regardless of cache
    warmth.

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
        """Return kwargs dicts for calls matching ``level`` (+ optional event filter).

        ``event_type`` matches against the ``event_type`` kwarg (machine-routable
        events). ``event`` matches against the positional event name passed to
        ``.warning()`` / ``.error()`` / etc. Both kwargs optional; pass whichever
        the production code emits.
        """
        return [
            kw
            for lvl, evt, kw in self.calls
            if lvl == level
            and (event_type is None or kw.get("event_type") == event_type)
            and (event is None or evt == event)
        ]
