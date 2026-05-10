"""``studies`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"studies".

The status state machine (``queued → running → {completed | cancelled |
failed}``) is enforced by the ``studies_status_check`` CHECK constraint at
the DB level **and** by ``backend/services/study_state.py`` at the service
layer (Phase 2). Direct ORM ``UPDATE`` of ``status`` outside the service is
forbidden — Phase 2 wires a SQLAlchemy event listener that raises
``StudyStateProtectionError`` (per spec FR-7).

Notable columns:

- ``failed_reason`` — populated when ``status == 'failed'``.
- ``baseline_metric`` — single non-Optuna trial run before Optuna starts;
  populated by the orchestrator (Phase 2).
- ``optuna_study_name`` UNIQUE — convention is ``str(studies.id)`` so the
  Optuna RDB row is trivially traceable to the application row.
- ``parent_study_id`` self-FK — for forks (MVP2).
- ``best_metric`` / ``best_trial_id`` — denormalized for fast study-list
  rendering; populated by the orchestrator on completion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Study(Base):
    """One optimization run targeting a specific cluster + template + query set."""

    __tablename__ = "studies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'cancelled', 'failed')",
            name="studies_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(36), ForeignKey("clusters.id"), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    """Index or collection name on the cluster."""
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_templates.id"), nullable=False
    )
    query_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_sets.id"), nullable=False
    )
    judgment_list_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("judgment_lists.id"), nullable=False
    )
    search_space: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Per-parameter range/choice spec consumed by the Optuna sampler."""
    objective: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """``{metric, k, direction}`` — e.g. ``{metric: 'ndcg', k: 10, direction: 'maximize'}``."""
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """``{max_trials, time_budget_min, parallelism, sampler, pruner, seed, trial_timeout_s}``."""
    status: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``queued | running | completed | cancelled | failed`` (CHECK enforced)."""
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    optuna_study_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    """Convention: ``optuna_study_name = str(studies.id)``."""
    parent_study_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("studies.id"), nullable=True
    )
    """Self-FK for fork lineage (MVP2 surface)."""
    baseline_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Single non-Optuna trial run before Optuna starts; populated by the orchestrator."""
    best_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Denormalized winner metric value; set on study completion."""
    best_trial_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    """Denormalized FK to the winning trial; set on study completion. (Not a
    formal FK because the trial may not exist when the study is created and
    the relationship is one-to-many in the other direction; the
    orchestrator stamps it on completion.)"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
