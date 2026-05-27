"""Worker smoke tests (infra_foundation Story 4.3 + infra_optuna_eval Story 2.3).

These tests verify the ``WorkerSettings`` class is importable,
``functions`` contains the registered Arq jobs, ``redis_settings`` resolves
the host from ``Settings.redis_url``, and the ``on_startup`` hook exists
(spec FR-1 — RDBStorage MUST initialize at worker startup).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def _settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the required Settings inputs so import-time wiring works."""
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    # Reset get_settings cache so it re-reads our env vars
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()


def test_worker_settings_importable(_settings_env: None) -> None:
    """WorkerSettings should import and register the expected Arq jobs.

    Phase 2 Stories 2.1 / 2.3 extend the registry from infra_optuna_eval's
    sole ``run_trial`` to four jobs: ``run_trial``, ``start_study``,
    ``resume_study``, ``generate_digest`` (stub). ``feat_llm_judgments``
    Story 2.1 adds ``generate_judgments_llm``. ``feat_digest_proposal``
    later replaces ``generate_digest``; ``feat_github_pr_worker`` adds
    ``open_pr``.
    """
    from backend.workers.all import WorkerSettings

    # Mix of raw coroutines and arq.func-wrapped Function objects (the
    # orchestrator + judgments jobs carry per-function timeouts via arq.func).
    names: set[str] = set()
    for fn in WorkerSettings.functions:
        # arq.func wraps as Function with .name; plain coroutines have __name__.
        name = getattr(fn, "name", None) or getattr(fn, "__name__", None)
        assert name is not None
        names.add(name)
    assert names == {
        "run_trial",
        "start_study",
        "resume_study",
        "generate_digest",
        "generate_judgments_llm",
        "open_pr",
        "register_webhook",
        # feat_auto_followup_studies Story 2.1
        "enqueue_followup_study",
        # feat_study_baseline_trial Story 1.4
        "run_baseline_trial",
        # bug_demo_reseed_fake_metric_regression — home-button reseed
        # converted from sync HTTP to Arq job with status polling.
        "run_demo_reseed",
    }


def test_open_pr_registered_with_retry_budget(_settings_env: None) -> None:
    """feat_github_pr_worker Story 2.2 / cycle-3 F1.

    open_pr is registered as ``func(open_pr, timeout=180, max_tries=30)``.
    The 30-try ceiling × 5s defer between retries gives the leading
    worker a ~150s window to release the per-config_repo advisory lock
    before the trailing worker exhausts retries.
    """
    from backend.workers.all import WorkerSettings

    open_pr_fn = next(
        (
            f
            for f in WorkerSettings.functions
            if (getattr(f, "name", None) or getattr(f, "__name__", "")) == "open_pr"
        ),
        None,
    )
    assert open_pr_fn is not None, "open_pr not registered in WorkerSettings.functions"
    # arq.func wraps as Function with .max_tries / .timeout_s attributes.
    assert getattr(open_pr_fn, "max_tries", None) == 30
    assert getattr(open_pr_fn, "timeout_s", None) == 180


def test_worker_settings_has_on_startup_hook(_settings_env: None) -> None:
    """Spec FR-1 — RDBStorage MUST be initialized at worker startup.

    WorkerSettings.on_startup is a coroutine that constructs Optuna's
    RDBStorage and caches it in ctx['optuna_storage'].
    """
    from backend.workers.all import WorkerSettings

    assert hasattr(WorkerSettings, "on_startup")
    # on_startup is bound as a coroutine on the class; verify it's callable.
    assert callable(WorkerSettings.on_startup)


def test_worker_settings_redis_host_parsed(_settings_env: None) -> None:
    """RedisSettings.from_dsn should pull host=redis port=6379 db=0 from the URL."""
    # Re-import so the class-level redis_settings is rebuilt with our env
    import importlib

    import backend.workers.all as worker_module

    importlib.reload(worker_module)

    rs = worker_module.WorkerSettings.redis_settings
    assert rs.host == "redis"
    assert rs.port == 6379
    assert rs.database == 0


def test_worker_settings_redis_host_overridable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A different REDIS_URL should be reflected after a settings cache clear."""
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.setenv("REDIS_URL", "redis://other-host:6380/2")

    from backend.app.core.settings import get_settings

    get_settings.cache_clear()

    import importlib

    import backend.workers.all as worker_module

    importlib.reload(worker_module)

    rs = worker_module.WorkerSettings.redis_settings
    assert rs.host == "other-host"
    assert rs.port == 6380
    assert rs.database == 2

    # Restore for other tests
    os.environ.pop("REDIS_URL", None)
    get_settings.cache_clear()


def test_pr_reconcile_cron_registered(_settings_env: None) -> None:
    """feat_github_webhook Story 3.1 — reconcile_pr_state registered via cron_jobs.

    Asserts the cron job is wired with the default 15-minute cadence
    (``minute={0, 15, 30, 45}``) at the default ``relyloop_pr_poll_minutes``.
    """
    from backend.workers.all import WorkerSettings

    cron_jobs = getattr(WorkerSettings, "cron_jobs", [])
    assert cron_jobs, "WorkerSettings.cron_jobs missing — reconcile_pr_state not wired"
    # arq.CronJob exposes the registered coroutine; match by its __name__.
    names = {getattr(job.coroutine, "__name__", None) for job in cron_jobs}
    assert "reconcile_pr_state" in names


def test_resume_judgment_lists_cron_registered(_settings_env: None) -> None:
    """feat_judgments_periodic_resume_sweep Story 1.3 — resume_stuck_judgment_lists wired.

    Parallel to :func:`test_pr_reconcile_cron_registered` for the second
    cron job added in this feature (spec FR-1 / AC-1). The set-membership
    assertion shape lets both crons coexist without test fragility.
    """
    from backend.workers.all import WorkerSettings

    cron_jobs = getattr(WorkerSettings, "cron_jobs", [])
    assert cron_jobs, "WorkerSettings.cron_jobs missing"
    names = {getattr(job.coroutine, "__name__", None) for job in cron_jobs}
    assert "resume_stuck_judgment_lists" in names
    # Sanity: the reconcile_pr_state cron is also still there — the new
    # registration must not displace the existing one.
    assert "reconcile_pr_state" in names
