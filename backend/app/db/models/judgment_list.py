"""``judgment_lists`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"judgment_lists".

This feature creates the **full** MVP1 shape (not a stub) so
`feat_llm_judgments` can author rows immediately without further migration —
that feature owns the child ``judgments`` table and the LLM-runner that
populates ratings; this feature only owns the parent header.

CHECK constraint enforces ``status ∈ {generating, complete, failed}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class JudgmentList(Base):
    """The header row for a set of LLM- or human-generated judgments."""

    __tablename__ = "judgment_lists"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generating', 'complete', 'failed')",
            name="judgment_lists_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_sets.id"), nullable=False
    )
    # Generation context: persisted so the worker can reconstruct what
    # cluster / index / template the judgments were generated against.
    # Required for regeneration, calibration audits, and lineage.
    cluster_id: Mapped[str] = mapped_column(String(36), ForeignKey("clusters.id"), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    """Index or collection name on the cluster."""
    current_template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("query_templates.id"), nullable=True
    )
    """Template used at generation time; nullable for imported lists."""
    rubric: Mapped[str] = mapped_column(Text, nullable=False)
    """The rubric used (LLM prompt or human guidance text)."""
    status: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``generating | complete | failed`` (CHECK enforced)."""
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Populated when ``status == 'failed'``."""
    calibration: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """``{cohens_kappa, weighted_kappa, per_class, n_samples}`` —
    advisory, not gating."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
