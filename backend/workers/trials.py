"""``run_trial`` Arq job (infra_optuna_eval Story 2.3 / FR-4 + FR-5).

Hot-path worker that executes one Optuna trial end-to-end:

1. Idempotency check against the app ``trials`` table (spec §11 clause 1a).
2. Optuna-side reconciliation if the in-flight trial is already terminal
   (spec §11 clause 1b) — reconstructs the app row from the cached Optuna
   state without re-executing search/score.
3. Happy path: render → ``_msearch`` → score → ``tell`` → INSERT app row.
4. Trial-level failure handling: any of adapter/render/search/score raises
   → ``status='failed'`` row + ``tell(state=FAIL)``; job returns normally.
5. Infra-level failures (DB unreachable, Redis lost) re-raise so Arq retries.

Orchestrator vs. worker contract (spec §11 lock-in):

* ``feat_study_lifecycle`` Phase 2's orchestrator pre-allocates
  ``optuna_trial_number`` via ``study.ask()`` AND populates
  ``FrozenTrial.params`` via ``trial.suggest_*`` against
  ``studies.search_space`` BEFORE enqueueing ``run_trial(...)``.
* This worker NEVER calls ``study.ask()`` or any ``suggest_*`` —
  doing so would create a duplicate Optuna trial that defeats the
  spec §11 idempotency contract.
* The worker loads the in-flight ``FrozenTrial`` via
  ``study.trials[optuna_trial_number]`` (sync RDB call wrapped in
  ``asyncio.to_thread``) and reads ``.params`` from it.

``study.tell()`` takes an integer trial number (NOT a ``FrozenTrial``)
per the Optuna API. All sync Optuna calls are wrapped in
``asyncio.to_thread`` to keep the event loop unblocked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import optuna
import structlog
import uuid_utils
from optuna.trial import TrialState
from sqlalchemy import select
from sqlalchemy.exc import OperationalError as SAOperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.adapters.protocol import NativeQuery, QueryTemplate
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Trial
from backend.app.db.session import get_session_factory
from backend.app.eval.qrels_loader import load_qrels
from backend.app.eval.scoring import Qrels, Run, objective_metric_key, score
from backend.app.services.cluster import build_adapter

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# TrialSnapshot — async-safe view of an Optuna FrozenTrial
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrialSnapshot:
    """Plain dataclass snapshot of an Optuna ``FrozenTrial``.

    Created by ``_snapshot_optuna_trial`` inside ``asyncio.to_thread`` so
    all RDB-backed lazy attribute access happens off the event loop.
    Subsequent reads of ``.params`` / ``.value`` / ``.state`` are local
    dict/scalar reads with no storage round-trip.
    """

    number: int
    state: TrialState
    params: dict[str, Any]
    value: float | None


def _snapshot_optuna_trial(study: optuna.Study, n: int) -> TrialSnapshot:
    """Synchronously load ``study.trials[n]`` and snapshot the fields we need.

    Always invoked from async code via
    ``await asyncio.to_thread(_snapshot_optuna_trial, study, n)``.
    """
    frozen = study.trials[n]
    return TrialSnapshot(
        number=frozen.number,
        state=frozen.state,
        params=dict(frozen.params),
        value=frozen.value,
    )


# ---------------------------------------------------------------------------
# Idempotency + reconciliation helpers
# ---------------------------------------------------------------------------


_TERMINAL_STATUSES = ("complete", "failed", "pruned")

# Default secondary metrics scored when ``studies.config.secondary_metrics``
# is absent. Per the implementation plan Story 2.3 step I — gives every
# trial row a comparable surface without requiring operators to enumerate
# the canonical inventory in every study config.
_DEFAULT_SECONDARY_METRICS: frozenset[str] = frozenset({"ndcg@10", "map@10", "mrr"})


async def _existing_terminal_app_row(db: AsyncSession, study_id: str, n: int) -> Trial | None:
    """Look up an existing terminal ``trials`` row for ``(study_id, n)``.

    Spec §11 clause 1a: if a row exists with a terminal status, the worker
    returns no-op (already-completed trial).
    """
    stmt = (
        select(Trial)
        .where(Trial.study_id == study_id)
        .where(Trial.optuna_trial_number == n)
        .where(Trial.status.in_(_TERMINAL_STATUSES))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


_OPTUNA_STATE_TO_APP_STATUS: dict[TrialState, str] = {
    TrialState.COMPLETE: "complete",
    TrialState.FAIL: "failed",
    TrialState.PRUNED: "pruned",
}


async def _reconstruct_from_optuna(
    db: AsyncSession,
    snapshot: TrialSnapshot,
    *,
    trial_id: str,
    study_id: str,
    optuna_trial_number: int,
    objective_key: str,
) -> Trial:
    """Spec §11 clause 1b: rebuild the app trials row from Optuna's terminal state.

    Fires when the worker died after ``study.tell()`` succeeded but before
    the app-row INSERT — Optuna has a terminal trial but the app does not.
    Returns the persisted ``Trial`` row.

    State-specific shapes (per cycle-3 review A3 — metrics dict stays in the
    user-facing-name namespace; reconciliation marker emitted via structured
    log events, NOT polluted into ``trials.metrics``):

    * ``COMPLETE`` → metrics = ``{objective_key: snapshot.value}``,
      primary_metric = snapshot.value, error = None.
    * ``FAIL``     → metrics = {}, primary_metric = None,
      error = "reconstructed from Optuna FAIL state; original exception unavailable".
    * ``PRUNED``   → metrics = {}, primary_metric = snapshot.value
      (may be None for pre-warmup prune), error = None.

    ``duration_ms`` is ``None`` for all reconstructed rows (wall-clock time
    is unknown — the original worker died before recording it).
    """
    status = _OPTUNA_STATE_TO_APP_STATUS.get(snapshot.state)
    if status is None:
        raise ValueError(
            f"unexpected non-terminal Optuna state {snapshot.state!r} "
            f"during reconciliation for ({study_id=}, {optuna_trial_number=})"
        )

    metrics: dict[str, Any]
    primary_metric: float | None
    error: str | None

    if status == "complete":
        metrics = {objective_key: snapshot.value}
        primary_metric = snapshot.value
        error = None
        logger.info(
            "trial reconstructed from optuna",
            event_type="optuna_reconciled",
            state="COMPLETE",
            trial_id=trial_id,
            study_id=study_id,
            optuna_trial_number=optuna_trial_number,
            primary_metric=primary_metric,
        )
    elif status == "failed":
        metrics = {}
        primary_metric = None
        error = "reconstructed from Optuna FAIL state; original exception unavailable"
        logger.warning(
            "trial reconstructed from optuna",
            event_type="optuna_reconciled",
            state="FAIL",
            trial_id=trial_id,
            study_id=study_id,
            optuna_trial_number=optuna_trial_number,
        )
    else:  # status == "pruned"
        metrics = {}
        primary_metric = snapshot.value
        error = None
        logger.info(
            "trial reconstructed from optuna",
            event_type="optuna_reconciled",
            state="PRUNED",
            trial_id=trial_id,
            study_id=study_id,
            optuna_trial_number=optuna_trial_number,
        )

    trial = await repo.create_trial(
        db,
        id=trial_id,
        study_id=study_id,
        optuna_trial_number=optuna_trial_number,
        params=snapshot.params,
        primary_metric=primary_metric,
        metrics=metrics,
        duration_ms=None,
        status=status,
        error=error,
        started_at=None,
        ended_at=None,
    )
    await db.commit()
    return trial


# ---------------------------------------------------------------------------
# run_trial — the Arq job
# ---------------------------------------------------------------------------


async def run_trial(ctx: dict[str, Any], study_id: str, optuna_trial_number: int) -> None:
    """Execute one Optuna trial end-to-end. See module docstring.

    ``ctx["optuna_storage"]`` is the boot-cached ``optuna.storages.RDBStorage``
    populated by ``WorkerSettings.on_startup``. Tests / replay CLI invocations
    that don't run through Arq's startup hook MUST seed ``ctx["optuna_storage"]``
    themselves before calling this function.

    Failure handling:

    * Trial-level (adapter / render / score raises) BEFORE ``tell``:
      writes ``status='failed'`` row + tells Optuna FAIL; returns normally
      (Arq treats success).
    * Trial-level AFTER ``tell`` (INSERT fails): re-raises so Arq retries;
      spec §11 clause 1b reconciliation handles the retry.
    * Infra-level (``OperationalError``): re-raises immediately for retry.
    """
    # Lazy import to keep optuna_runtime out of cold-import path.
    import asyncio

    from backend.app.eval.optuna_runtime import (
        build_pruner,
        build_sampler,
        get_or_create_study,
    )

    # A. Pre-generate trial_id; bind structlog contextvars; open session.
    trial_id = str(uuid_utils.uuid7())
    started_at: datetime | None = None
    adapter = None
    tell_succeeded = False

    structlog.contextvars.bind_contextvars(
        trial_id=trial_id,
        study_id=study_id,
        optuna_trial_number=optuna_trial_number,
    )

    # Pre-trial configuration check — fail loud and re-raise rather than
    # masking a startup/CLI defect as a failed trial row. Spec §13 "infra-level
    # failure" semantics: Arq treats this as a job-level error and retries.
    # MUST happen outside the trial-level try/except so it doesn't get caught
    # and converted into status='failed' on an unbound Optuna study.
    if "optuna_storage" not in ctx:
        raise RuntimeError(
            "ctx['optuna_storage'] missing — Arq on_startup hook did not run; "
            "tests/CLI invocations must seed ctx explicitly per the worker docstring"
        )

    session_factory = get_session_factory()
    async with session_factory() as db:
        try:
            # B. Load app Study row.
            study_row = await repo.get_study(db, study_id)
            if study_row is None:
                logger.warning("study deleted before run_trial executed")
                return

            # C. App-row idempotency check (spec §11 clause 1a).
            existing = await _existing_terminal_app_row(db, study_id, optuna_trial_number)
            if existing is not None:
                logger.info(
                    "trial already terminal in app table — no-op",
                    existing_status=existing.status,
                )
                return

            # D. Build / load the Optuna study.
            storage = ctx["optuna_storage"]
            objective = study_row.objective
            config = study_row.config
            sampler = build_sampler(config, seed=config.get("seed"))
            pruner = build_pruner(config)
            optuna_study = await asyncio.to_thread(
                get_or_create_study,
                storage=storage,
                optuna_study_name=study_row.optuna_study_name,
                direction=objective["direction"],
                sampler=sampler,
                pruner=pruner,
            )

            # E. Snapshot the in-flight trial; reconcile if terminal.
            objective_key = objective_metric_key(objective)
            snapshot = await asyncio.to_thread(
                _snapshot_optuna_trial, optuna_study, optuna_trial_number
            )

            if snapshot.state.is_finished():
                await _reconstruct_from_optuna(
                    db,
                    snapshot,
                    trial_id=trial_id,
                    study_id=study_id,
                    optuna_trial_number=optuna_trial_number,
                    objective_key=objective_key,
                )
                return

            # F. Fault seam #1 (test-only).
            if os.environ.get("INFRA_OPTUNA_EVAL_FAULT") == "after_trial_load_before_execute":
                os._exit(1)

            # G. Happy path — load adapter, template, queries, qrels.
            cluster = await repo.get_cluster(db, study_row.cluster_id)
            if cluster is None:
                raise RuntimeError(
                    f"cluster {study_row.cluster_id!r} not found for study {study_id}"
                )
            adapter = build_adapter(cluster)

            template_row = await repo.get_query_template(db, study_row.template_id)
            if template_row is None:
                raise RuntimeError(
                    f"template {study_row.template_id!r} not found for study {study_id}"
                )
            template = QueryTemplate(
                name=template_row.name,
                engine_type=cast(Any, template_row.engine_type),
                body=template_row.body,
                declared_params=cast(dict[str, str], template_row.declared_params),
            )
            queries = await repo.list_queries_for_set(db, study_row.query_set_id)
            qrels: Qrels = await load_qrels(db, study_row.judgment_list_id)

            # H. Retrieval depth — objective.k or sensible default
            # (objective.k is optional for `map` and ignored for `mrr` per spec §8.4).
            top_k_raw = objective.get("k")
            top_k = top_k_raw if isinstance(top_k_raw, int) else 100

            # I. Metric set — primary + secondary metrics.
            # When the operator hasn't declared `secondary_metrics` in
            # `studies.config`, fall back to the plan's default inventory so
            # every trial row carries a useful comparison surface (per FR-5
            # "every metric the study's objective enumerated"). Explicit
            # `secondary_metrics: []` is honored as "primary only" — operator
            # override of the default.
            metrics_set: set[str] = {objective_key}
            if "secondary_metrics" in config:
                secondaries = config["secondary_metrics"]
                if isinstance(secondaries, list):
                    metrics_set.update(str(m) for m in secondaries)
            else:
                metrics_set.update(_DEFAULT_SECONDARY_METRICS)

            # J. Execute search via the adapter.
            # Resolve per-trial timeout: study.config override OR the
            # operator-tunable Settings default. Bounds the adapter's
            # httpx call so a hung engine query can't monopolise a worker
            # slot indefinitely (infra_per_trial_timeout). Explicit
            # `is not None` (not `or`) so a falsy override like 0 is
            # respected — the Pydantic schema bounds 5..3600 today, but
            # the explicit form documents the intent.
            configured_timeout = study_row.config.get("trial_timeout_s")
            trial_timeout_s = float(
                configured_timeout
                if configured_timeout is not None
                else get_settings().studies_default_timeout_s
            )
            started_at = datetime.now(UTC)
            native_queries: list[NativeQuery] = [
                adapter.render(template, snapshot.params, q.query_text) for q in queries
            ]
            # The adapter mutates each NativeQuery.query_id to the per-query id we provide,
            # so we set them up front to match the qrels keys.
            native_queries = [
                NativeQuery(query_id=str(q.id), body=nq.body)
                for q, nq in zip(queries, native_queries, strict=True)
            ]
            hits = await adapter.search_batch(
                target=study_row.target,
                queries=native_queries,
                top_k=top_k,
                strict_errors=False,
                timeout=trial_timeout_s,
            )

            # K. Score and compute primary + duration.
            run_dict: Run = {
                qid: {hit.doc_id: float(hit.score) for hit in hit_list}
                for qid, hit_list in hits.items()
            }
            scored = score(qrels, run_dict, metrics_set)
            primary = scored["aggregate"][objective_key]
            duration_ms = int(round((datetime.now(UTC) - started_at).total_seconds() * 1000))

            # M. Tell Optuna (sync — wrap in to_thread).
            await asyncio.to_thread(optuna_study.tell, optuna_trial_number, primary)
            tell_succeeded = True

            # L.5. Fault seam #2 (test-only) — between tell and INSERT.
            if os.environ.get("INFRA_OPTUNA_EVAL_FAULT") == "after_tell_before_insert":
                os._exit(1)

            # N. INSERT the trials row.
            await repo.create_trial(
                db,
                id=trial_id,
                study_id=study_id,
                optuna_trial_number=optuna_trial_number,
                params=snapshot.params,
                primary_metric=primary,
                metrics=scored["aggregate"],
                duration_ms=duration_ms,
                status="complete",
                error=None,
                started_at=started_at,
                ended_at=datetime.now(UTC),
            )
            await db.commit()
            logger.info(
                "trial completed",
                status="complete",
                primary_metric=primary,
                duration_ms=duration_ms,
            )

        except SAOperationalError:
            # Infra-level: re-raise for Arq retry.
            await db.rollback()
            raise

        except Exception as exc:
            await db.rollback()

            if tell_succeeded:
                # Post-tell INSERT failure (spec §11 clause 1b path on retry).
                # DO NOT call study.tell again — Optuna trial is already
                # terminal-COMPLETE; second tell would either raise or no-op.
                # Re-raise so Arq retries; reconciliation handles the next run.
                logger.warning(
                    "post-tell INSERT failure; re-raising for spec §11 clause 1b reconciliation",
                    error=str(exc),
                )
                raise

            # Pre-tell failure: mark Optuna FAIL, persist failed row.
            try:
                await asyncio.to_thread(
                    optuna_study.tell, optuna_trial_number, state=TrialState.FAIL
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "study.tell(FAIL) raised during failure-path; continuing to persist row"
                )

            ended_at = datetime.now(UTC)
            failed_duration_ms: int | None
            if started_at is not None:
                failed_duration_ms = int(round((ended_at - started_at).total_seconds() * 1000))
            else:
                failed_duration_ms = None

            error_text = str(exc)[:500]
            failed_params = snapshot.params if "snapshot" in locals() else {}
            await repo.create_trial(
                db,
                id=trial_id,
                study_id=study_id,
                optuna_trial_number=optuna_trial_number,
                params=failed_params,
                primary_metric=None,
                metrics={},
                duration_ms=failed_duration_ms,
                status="failed",
                error=error_text,
                started_at=started_at,
                ended_at=ended_at,
            )
            await db.commit()
            logger.warning(
                "trial failed",
                status="failed",
                error=error_text,
                duration_ms=failed_duration_ms,
            )

        finally:
            if adapter is not None:
                await adapter.aclose()
            structlog.contextvars.unbind_contextvars("trial_id", "study_id", "optuna_trial_number")


# Re-export the domain exception names so the worker module is a complete
# imports-once surface for downstream test code.
__all__ = [
    "ClusterUnreachableError",
    "InvalidQueryDSLError",
    "QueryTimeoutError",
    "TrialSnapshot",
    "run_trial",
]
