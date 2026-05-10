"""Arq worker entry point (infra_foundation Story 4.3 + infra_optuna_eval Story 2.3).

The Compose ``worker`` service starts via ``arq backend.workers.all.WorkerSettings``.

Registered jobs:

* ``run_trial`` — infra_optuna_eval Story 2.3; executes one Optuna trial
  (render → search → score → tell → persist trials row).

Subsequent features add their own job functions to the ``functions`` list:

- ``feat_digest_proposal`` → ``generate_digest``
- ``feat_github_pr_worker`` → ``open_pr``

The ``redis_settings`` field is derived from ``Settings.redis_url`` so the
worker uses the same Redis instance as the API (Compose service ``redis``).

The ``on_startup`` hook constructs Optuna's ``RDBStorage`` once per worker
boot and caches it in ``ctx["optuna_storage"]`` (spec FR-1: "RDBStorage
MUST be initialized at worker startup"). ``run_trial`` reads from ``ctx``
on each invocation instead of rebuilding the storage; this avoids the
sync DB-connection overhead per-job.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arq.connections import RedisSettings

from backend.app.core.settings import get_settings
from backend.app.eval.optuna_runtime import build_storage
from backend.workers.trials import run_trial


def _build_redis_settings() -> RedisSettings:
    """Parse ``Settings.redis_url`` into Arq's RedisSettings dataclass."""
    return RedisSettings.from_dsn(get_settings().redis_url)


async def on_startup(ctx: dict[str, Any]) -> None:
    """Initialize Optuna's RDBStorage once per worker boot.

    Wrapped in ``asyncio.to_thread`` because ``RDBStorage`` construction
    may open a sync DB connection (spec FR-1/AC-1b explicitly does not
    constrain Optuna's lazy-creation trigger — neither timing is guaranteed,
    so we play safe and offload it to a worker thread).
    """
    settings = get_settings()
    ctx["optuna_storage"] = await asyncio.to_thread(build_storage, settings.database_url)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Dispose Optuna's SQLAlchemy engine cleanly at worker shutdown.

    Optuna's ``RDBStorage`` exposes its internal SQLAlchemy engine via
    ``_url`` / ``_engine`` on current versions; if either attribute
    disappears in a future Optuna release the best-effort dispose is a
    no-op (try/except AttributeError).
    """
    storage = ctx.get("optuna_storage")
    if storage is None:
        return
    engine = getattr(storage, "_engine", None) or getattr(storage, "engine", None)
    if engine is None:
        return
    try:
        await asyncio.to_thread(engine.dispose)
    except AttributeError:  # pragma: no cover  - defensive against Optuna API drift
        pass


class WorkerSettings:
    """Arq worker configuration. ``arq`` reads ``functions`` and ``redis_settings``."""

    functions: list[Any] = [run_trial]
    redis_settings = _build_redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
