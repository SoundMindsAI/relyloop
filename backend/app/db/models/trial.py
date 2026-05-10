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
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    optuna_trial_number: Mapped[int] = mapped_column(Integer, nullable=False)
    """Optuna's per-study trial number; idempotent across worker restarts
    (re-running a trial_number doesn't create a duplicate row because
    Optuna's ``study.ask()`` is idempotent on the trial number)."""
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
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Wall-clock from ``study.ask()`` to ``study.tell()`` for this trial."""
    status: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``complete | failed | pruned`` (CHECK enforced)."""
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Populated when ``status == 'failed'`` — the exception message from
    whatever step raised (adapter, render, search, score)."""
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
