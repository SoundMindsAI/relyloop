# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Regression guard for ``bug_backend_suite_nondeterministic_caplog_isolation``.

The backend suite was order-dependently red: many unit tests that assert on
``structlog.testing.capture_logs()`` output failed with empty-capture shapes
(``assert []``) in the full suite yet passed in isolation. Root cause: every
``configure_logging()`` call handed structlog a brand-new ``processors`` list.

structlog binds each logger against the *same list instance* that
``structlog.get_config()["processors"]`` returns and (with
``cache_logger_on_first_use=True``) freezes that reference on the bound logger.
``capture_logs()`` works by mutating that list *in place*. So when a later
``configure_logging()`` (e.g. an integration test's FastAPI lifespan) swapped
the config's list for a fresh instance, any module-level logger already cached
against the previous instance went blind to ``capture_logs()`` — which mutates
the *current* instance. Whether a given logger was blind at assertion time
depended on test execution order, so the failing set varied run to run.

The fix makes ``configure_logging()`` mutate the existing processors list in
place (preserving instance identity), so bound loggers always observe the
current chain. These two tests fail on the pre-fix code and pass after it.
"""

from __future__ import annotations

import structlog

from backend.app.core.logging import configure_logging


def test_configure_logging_reuses_processors_list_instance() -> None:
    """A second ``configure_logging()`` must keep the same processors list object.

    This is the root-cause invariant: instance identity is what bound loggers
    (and ``capture_logs()``) rely on. Replacing the list is the bug.
    """
    configure_logging(json_output=True)
    first = structlog.get_config()["processors"]
    configure_logging(json_output=True)
    second = structlog.get_config()["processors"]

    assert first is second, (
        "configure_logging() replaced the processors list instance; a logger "
        "cached against the prior instance would go blind to capture_logs()."
    )


def test_capture_logs_survives_reconfigure_after_logger_cached() -> None:
    """Reproduce the exact poison: bind+cache a logger, reconfigure, then capture.

    Pre-fix, the second ``configure_logging()`` swapped the processors list, so
    the cached logger emitted through the stale instance and ``capture_logs()``
    (mutating the new instance) saw nothing.
    """
    configure_logging(json_output=True)
    # Bind + cache a logger against the current processors list instance.
    logger = structlog.get_logger("bug_caplog_isolation_regression")
    logger.info("warm_the_cache")

    # A later configure_logging() (integration lifespan, another unit test, ...).
    configure_logging(json_output=True)

    with structlog.testing.capture_logs() as logs:
        logger.info("under_capture", marker=True)

    events = [e for e in logs if e.get("event") == "under_capture"]
    assert len(events) == 1, (
        f"capture_logs() was blind to a logger cached before the 2nd "
        f"configure_logging() — the isolation regression is back. Captured: {logs}"
    )
    assert events[0].get("marker") is True
