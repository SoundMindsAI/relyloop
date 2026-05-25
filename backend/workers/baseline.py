"""``run_baseline_trial`` Arq job (feat_study_baseline_trial Story 1.4 / FR-10).

One-shot non-Optuna trial executed before the Optuna polling loop starts.
Mirrors :mod:`backend.workers.trials.run_trial` for the render → search →
score → persist pipeline, but does NOT touch Optuna's RDB:

* No ``study.ask()`` / ``study.tell()`` — the baseline isn't an Optuna
  trial. The orchestrator pre-generates a UUIDv7 ``trial_id`` and
  passes it as a job argument; the worker writes a ``trials`` row with
  ``is_baseline=TRUE`` and ``optuna_trial_number=-1`` (NOT-NULL sentinel
  filler — the canonical discriminator is ``is_baseline``).

* Idempotency by ``trial_id`` (NOT ``(study_id, optuna_trial_number)``):
  if a terminal row with ``id = trial_id`` already exists, no-op and
  return. This handles Arq retries cleanly because the orchestrator
  passes the same UUID on every retry.

* On ``status='complete'``: self-stamps ``studies.baseline_trial_id`` +
  ``baseline_metric`` via :func:`backend.app.services.study_state.
  stamp_baseline_trial` (FR-12 chokepoint), then commits. This is the
  durable stamping path; the orchestrator's fast-path stamp in
  ``start_study`` is just an accelerator (per D-13).

* On failure (adapter raises, scorer raises, render raises): persist
  the failed ``Trial`` row with ``is_baseline=TRUE, status='failed',
  error=<message>``; commit; return normally (Arq treats as success).
  Failed baselines do NOT fail the study — the orchestrator falls back
  to runner-up comparison and first-decile-extremum auto-followup gate.

* Test-only fault seam (plan F9): when
  ``FEAT_STUDY_BASELINE_TRIAL_FAULT=delay_before_score`` is set, the
  worker sleeps for ``FEAT_STUDY_BASELINE_TRIAL_FAULT_DELAY_S`` seconds
  before scoring. Used by ``test_baseline_late_completion_stamp.py`` to
  force the orchestrator's wait phase to time out so the worker's
  self-stamp is the only path that lands the FK (covers AC-16).

Spec: ``feat_study_baseline_trial/feature_spec.md`` FR-10. AC-1 / AC-3 /
AC-16 depend on this contract.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError as SAOperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.protocol import NativeQuery, QueryTemplate
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Trial
from backend.app.db.session import get_session_factory
from backend.app.eval.qrels_loader import load_qrels
from backend.app.eval.scoring import Qrels, Run, objective_metric_key, score
from backend.app.services import study_state
from backend.app.services.cluster import build_adapter

logger = structlog.get_logger(__name__)

# Mirrors ``backend.workers.trials._DEFAULT_SECONDARY_METRICS`` — the same
# inventory ensures baseline + Optuna trials have comparable metric surfaces.
_DEFAULT_SECONDARY_METRICS: frozenset[str] = frozenset({"ndcg@10", "map@10", "mrr"})

_BASELINE_OPTUNA_TRIAL_NUMBER: int = -1
"""Sentinel filler for the NOT-NULL ``trials.optuna_trial_number`` column.
The canonical baseline discriminator is ``is_baseline=TRUE`` — Optuna
never queries this row (it uses its own RDB)."""


async def _existing_terminal_row(db: AsyncSession, trial_id: str) -> Trial | None:
    """Look up an existing terminal ``trials`` row by ``trial_id``.

    FR-10 idempotency: if a row with the orchestrator-generated ``trial_id``
    already exists at terminal status, return it so the worker can no-op
    on retry without duplicating the INSERT.
    """
    stmt = (
        select(Trial)
        .where(Trial.id == trial_id)
        .where(Trial.status.in_(("complete", "failed", "pruned")))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def run_baseline_trial(
    ctx: dict[str, Any],
    study_id: str,
    trial_id: str,
    params: dict[str, Any],
) -> None:
    """Execute one non-Optuna baseline trial end-to-end. See module docstring."""
    structlog.contextvars.bind_contextvars(
        study_id=study_id,
        trial_id=trial_id,
        is_baseline=True,
    )
    started_at: datetime | None = None
    adapter = None

    session_factory = get_session_factory()
    async with session_factory() as db:
        try:
            # A. Idempotency check (FR-10): if this trial_id already terminal,
            # no-op. Arq retries land here on repeat.
            existing = await _existing_terminal_row(db, trial_id)
            if existing is not None:
                logger.info(
                    "baseline trial already terminal — no-op",
                    event_type="baseline_already_terminal",
                    existing_status=existing.status,
                )
                # If complete but unstamped, attempt the FR-12 stamp (idempotent).
                if existing.status == "complete" and existing.primary_metric is not None:
                    try:
                        await study_state.stamp_baseline_trial(
                            db, study_id, trial_id, float(existing.primary_metric)
                        )
                        await db.commit()
                    except (
                        study_state.BaselineTrialNotFound,
                        study_state.InvalidBaselineTrialState,
                    ):
                        await db.rollback()
                return

            # B. Load study, cluster, template, queries, qrels.
            study_row = await repo.get_study(db, study_id)
            if study_row is None:
                logger.warning(
                    "study deleted before baseline trial executed",
                    event_type="baseline_study_missing",
                )
                return

            cluster = await repo.get_cluster(db, study_row.cluster_id)
            if cluster is None:
                raise RuntimeError(
                    f"cluster {study_row.cluster_id!r} not found "
                    f"for baseline trial in study {study_id}"
                )
            adapter = build_adapter(cluster)

            template_row = await repo.get_query_template(db, study_row.template_id)
            if template_row is None:
                raise RuntimeError(
                    f"template {study_row.template_id!r} not found "
                    f"for baseline trial in study {study_id}"
                )
            template = QueryTemplate(
                name=template_row.name,
                engine_type=cast(Any, template_row.engine_type),
                body=template_row.body,
                declared_params=cast(dict[str, str], template_row.declared_params),
            )
            queries = await repo.list_queries_for_set(db, study_row.query_set_id)
            qrels: Qrels = await load_qrels(db, study_row.judgment_list_id)

            # C. Resolve retrieval depth + metric set (mirror run_trial).
            objective = study_row.objective
            objective_key = objective_metric_key(objective)
            top_k_raw = objective.get("k")
            top_k = top_k_raw if isinstance(top_k_raw, int) else 100

            metrics_set: set[str] = {objective_key}
            if "secondary_metrics" in study_row.config:
                secondaries = study_row.config["secondary_metrics"]
                if isinstance(secondaries, list):
                    metrics_set.update(str(m) for m in secondaries)
            else:
                metrics_set.update(_DEFAULT_SECONDARY_METRICS)

            # D. Resolve per-trial timeout (same precedence as run_trial).
            configured_timeout = study_row.config.get("trial_timeout_s")
            trial_timeout_s = float(
                configured_timeout
                if configured_timeout is not None
                else get_settings().studies_default_timeout_s
            )

            # E. Render queries.
            started_at = datetime.now(UTC)
            native_queries: list[NativeQuery] = [
                adapter.render(template, params, q.query_text) for q in queries
            ]
            native_queries = [
                NativeQuery(query_id=str(q.id), body=nq.body)
                for q, nq in zip(queries, native_queries, strict=True)
            ]

            # F. Test-only fault seam (plan F9): force a delay before score
            # so test_baseline_late_completion_stamp.py can exercise the
            # orchestrator's wait-timeout + worker self-stamp path.
            fault = os.environ.get("FEAT_STUDY_BASELINE_TRIAL_FAULT")
            if fault == "delay_before_score":
                delay_s = float(os.environ.get("FEAT_STUDY_BASELINE_TRIAL_FAULT_DELAY_S", "5"))
                logger.info(
                    "baseline fault seam active — delaying before score",
                    event_type="baseline_fault_delay",
                    delay_s=delay_s,
                )
                await asyncio.sleep(delay_s)

            # G. Execute search via the adapter.
            hits = await adapter.search_batch(
                target=study_row.target,
                queries=native_queries,
                top_k=top_k,
                strict_errors=False,
                timeout=trial_timeout_s,
            )

            # H. Score.
            run_dict: Run = {
                qid: {hit.doc_id: float(hit.score) for hit in hit_list}
                for qid, hit_list in hits.items()
            }
            scored = score(qrels, run_dict, metrics_set)
            primary_metric = float(scored["aggregate"][objective_key])
            duration_ms = int(round((datetime.now(UTC) - started_at).total_seconds() * 1000))

            # I. INSERT the Trial row. Catch IntegrityError from the
            # partial unique index in case a sibling worker (e.g., Arq
            # dedupe bypass under exotic race) inserted first.
            try:
                await repo.create_trial(
                    db,
                    id=trial_id,
                    study_id=study_id,
                    optuna_trial_number=_BASELINE_OPTUNA_TRIAL_NUMBER,
                    params=params,
                    primary_metric=primary_metric,
                    metrics=scored["aggregate"],
                    per_query_metrics=scored["per_query"],
                    duration_ms=duration_ms,
                    status="complete",
                    error=None,
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    is_baseline=True,
                )
                await db.commit()
            except IntegrityError as exc:
                # Partial unique index uq_trials_study_baseline_complete
                # rejected this INSERT — a sibling worker already wrote a
                # complete baseline for this study. The FR-12 stamp will
                # have already landed via that sibling; this worker exits
                # cleanly. (Defense-in-depth — Arq _job_id dedupe in FR-2
                # should normally prevent this entirely.)
                await db.rollback()
                logger.warning(
                    "baseline INSERT lost partial-unique race",
                    event_type="baseline_insert_race",
                    error=str(exc)[:200],
                )
                return

            # J. Self-stamp the studies row (FR-10 step 7).
            try:
                await study_state.stamp_baseline_trial(db, study_id, trial_id, primary_metric)
                await db.commit()
            except (
                study_state.BaselineTrialNotFound,
                study_state.InvalidBaselineTrialState,
            ) as exc:
                # The trial row exists (we just inserted it), so missing /
                # invalid-state would be a real bug. Log + rollback.
                await db.rollback()
                logger.exception(
                    "baseline self-stamp failed — caller bug",
                    event_type="baseline_self_stamp_error",
                    error=str(exc)[:200],
                )

            logger.info(
                "baseline trial completed",
                event_type="baseline_trial_completed",
                status="complete",
                primary_metric=primary_metric,
                duration_ms=duration_ms,
            )

        except SAOperationalError:
            # Infra-level failure (DB unreachable) — re-raise for Arq retry.
            await db.rollback()
            raise

        except Exception as exc:
            await db.rollback()
            ended_at = datetime.now(UTC)
            failed_duration_ms: int | None
            if started_at is not None:
                failed_duration_ms = int(round((ended_at - started_at).total_seconds() * 1000))
            else:
                failed_duration_ms = None
            error_text = str(exc)[:500]

            try:
                await repo.create_trial(
                    db,
                    id=trial_id,
                    study_id=study_id,
                    optuna_trial_number=_BASELINE_OPTUNA_TRIAL_NUMBER,
                    params=params,
                    primary_metric=None,
                    metrics={},
                    duration_ms=failed_duration_ms,
                    status="failed",
                    error=error_text,
                    started_at=started_at,
                    ended_at=ended_at,
                    is_baseline=True,
                )
                await db.commit()
            except IntegrityError:
                await db.rollback()
                # The trial_id is unique by orchestrator-generation; this
                # branch shouldn't fire. Log + return.
                logger.exception(
                    "baseline failed-row INSERT also raised IntegrityError",
                    event_type="baseline_failed_insert_race",
                )
                return

            logger.warning(
                "baseline trial failed",
                event_type="baseline_trial_failed",
                status="failed",
                error=error_text,
                duration_ms=failed_duration_ms,
            )

        finally:
            if adapter is not None:
                await adapter.aclose()
            structlog.contextvars.unbind_contextvars("study_id", "trial_id", "is_baseline")


__all__ = ["run_baseline_trial"]
