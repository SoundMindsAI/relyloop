"""Arq worker entry point (infra_foundation Story 4.3).

The Compose ``worker`` service starts via ``arq backend.workers.all.WorkerSettings``.
MVP1 ships with no jobs registered — the queue exists, listens, and stays idle.
Subsequent features add their own job functions to the ``functions`` list:

- ``feat_study_lifecycle`` → ``run_trial``
- ``feat_digest_proposal`` → ``generate_digest``
- ``feat_github_pr_worker`` → ``open_pr``

The ``redis_settings`` field is derived from ``Settings.redis_url`` so the
worker uses the same Redis instance as the API (Compose service ``redis``).
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from backend.app.core.settings import get_settings


def _build_redis_settings() -> RedisSettings:
    """Parse ``Settings.redis_url`` into Arq's RedisSettings dataclass."""
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """Arq worker configuration. ``arq`` reads ``functions`` and ``redis_settings``."""

    # Empty in MVP1; later features extend this list.
    functions: list[Any] = []
    # Computed at first attribute access — avoids reading Settings at module import.
    redis_settings = _build_redis_settings()
