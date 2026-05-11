"""``digests`` ORM model (feat_digest_proposal Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"digests".

One row per study (UNIQUE on ``study_id``). Re-generating a digest requires
the runbook escape hatch (``DELETE FROM digests WHERE study_id = ...`` + Arq
re-enqueue) per spec §19 Decision log.

The ``suggested_followups`` column is ``Mapped[list[str]]`` (NOT
``Optional[list[str]]``) per cycle-1 F1 of the GPT-5.5 plan review — the
migration has ``server_default ARRAY[]::TEXT[]`` so the worker can write an
empty list (zero-trials AC-2 path; capability-fallback AC-11 path) without
the API layer carrying a NULL-vs-empty branch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Digest(Base):
    """One study-end summary narrative + parameter-importance + recommended config."""

    __tablename__ = "digests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("studies.id"),
        nullable=False,
        unique=True,
    )
    """UNIQUE — one digest per study (umbrella spec §9; CHECK at DB level)."""
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    """Markdown body — LLM-authored prose summarising the study's outcome."""
    parameter_importance: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    """``{param: importance_score}`` from ``optuna.importance.get_param_importances``."""
    recommended_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Deterministically computed from the best trial's params filtered to
    currently-declared template params (NOT LLM-generated; per FR-5 cycle-1
    F5 / cycle-2 F1)."""
    suggested_followups: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=func.text("ARRAY[]::TEXT[]"),
    )
    """List of LLM-suggested next-steps; max 5 entries (enforced in worker
    via the structured-output schema's ``maxItems: 5``). NOT NULL with empty
    default per cycle-1 F1."""
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    """Provider + model identifier (e.g. ``openai:gpt-4o-2024-08-06``) or
    ``local:zero_trials`` for the AC-2 placeholder path."""
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
