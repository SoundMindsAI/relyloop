"""``trials`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"trials".

Cascade-deletes with the parent ``studies`` row — when a study is removed,
trials cascade-delete with it. Trial history is regenerable from Optuna's
RDB if needed (Phase 2 / `infra_optuna_eval` co-tenants Optuna's storage).

CHECK constraint enforces ``status ∈ {complete, failed, pruned}``. Per
``infra_optuna_eval`` FR-4, the ``run_trial`` worker writes one row per
trial — even on failure (``status='failed'`` with ``error`` populated).

The ``trials_study_metric`` index on ``(study_id, primary_metric DESC NULLS
LAST)`` is created in the migration (Story 1.2) — not declared at the ORM
level — so the ``DESC NULLS LAST`` ordering survives ``--autogenerate``.

The ``per_query_metrics`` JSONB column (nullable; added by migration
``0015_trials_per_query_metrics`` for feat_pr_metric_confidence) carries the
per-query ir_measures scores from ``scoring.py::score()``'s ``per_query``
dict. Shape: ``{query_id: {metric_token: float}}`` where ``metric_token`` is
the user-facing token emitted by :func:`backend.app.eval.scoring.score` —
i.e. ``@<k>``-suffixed for cutoff-aware metrics (``ndcg@10``, ``map@10``,
``precision@10``, ``recall@10``) and bare names for cutoff-free metrics
(``mrr``, plain ``map``). The base name (everything before any ``@``) is
constrained to ``MetricCatalog`` (``ndcg``, ``map``, ``precision``,
``recall``, ``mrr``). The ``trials_per_query_metrics_object_check`` CHECK
constraint enforces NULL-or-object at the DB level (since the write path is
the Arq ``run_trial`` worker, not a Pydantic-validated HTTP request).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Trial(Base):
    """One trial in a study — one parameter combination evaluated against the engine."""

    __tablename__ = "trials"
    __table_args__ = (
        CheckConstraint(
            "status IN ('complete', 'failed', 'pruned')",
            name="trials_status_check",
        ),
        CheckConstraint(
            "per_query_metrics IS NULL OR jsonb_typeof(per_query_metrics) = 'object'",
            name="trials_per_query_metrics_object_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    optuna_trial_number: Mapped[int] = mapped_column(Integer, nullable=False)
    """Optuna's per-study trial number. Pre-assigned by ``feat_study_lifecycle``
    Phase 2's orchestrator via ``study.ask().number`` (which also calls
    ``trial.suggest_*`` to populate params) before enqueueing
    ``run_trial(study_id, optuna_trial_number)``. The ``infra_optuna_eval``
    worker does NOT call ``study.ask()`` — it loads the pre-assigned
    in-flight trial via ``study.trials[optuna_trial_number]``. Idempotency
    on ``(study_id, optuna_trial_number)`` is enforced by the worker
    (app-row check + Optuna-side reconciliation) per
    ``infra_optuna_eval/feature_spec.md`` §11."""
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """The parameter combination Optuna's sampler picked for this trial."""
    primary_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Denormalized from ``metrics[study.objective.metric]`` for fast index-
    backed sort. Index ``trials_study_metric`` (created in migration 0003)
    covers ``(study_id, primary_metric DESC NULLS LAST)``."""
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """``{ndcg@10: ..., map: ..., p@10: ...}`` — every metric the study's
    objective enumerated, scored by ``backend/eval/scoring.py`` (lands in
    ``infra_optuna_eval``)."""
    per_query_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """Per-query ir_measures scores from ``scoring.py::score()``'s
    ``per_query`` dict, persisted on every successful trial (NULL on
    failure/pruned and on trials predating migration 0015). Shape:
    ``{query_id: {metric_name: float}}`` using user-facing metric names
    (``ndcg``, ``map``, ``precision``, ``recall``, ``mrr``). Consumed by
    ``backend.app.domain.study.confidence`` to compute the
    ``ConfidenceShape`` surfaced on ``StudyDetail`` + PR body + digest
    narrative (feat_pr_metric_confidence)."""
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Wall-clock from ``study.ask()`` to ``study.tell()`` for this trial."""
    status: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``complete | failed | pruned`` (CHECK enforced)."""
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Populated when ``status == 'failed'`` — the exception message from
    whatever step raised (adapter, render, search, score)."""
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    """Marker for the off-band non-Optuna baseline trial
    (feat_study_baseline_trial FR-1). The baseline trial is one row per
    study with ``optuna_trial_number=-1`` (NOT-NULL sentinel filler) and
    ``is_baseline=TRUE``. Optuna's RDB never sees this row — the discriminator
    is the boolean flag, not the trial number. Every aggregate / list /
    confidence read path under :mod:`backend.app.db.repo.trial` MUST filter
    ``is_baseline=FALSE`` (FR-11). The trials-listing API helper is the
    one exception — it returns both Optuna and baseline rows so the UI
    can render them under the "Show baseline trial" toggle (FR-9)."""
