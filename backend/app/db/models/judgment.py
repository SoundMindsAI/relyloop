# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``judgments`` ORM model (feat_llm_judgments Story 1.2).

Child table of :class:`backend.app.db.models.judgment_list.JudgmentList`. One
row per ``(judgment_list_id, query_id, doc_id)`` triple — the UNIQUE
constraint enforces this and is the contract for human-override UPSERT
semantics (FR-4 / AC-2).

The CHECK constraints (``rating BETWEEN 0 AND 3`` +
``source IN ('llm','human','click')``) mirror the
``0004_judgments`` migration. ``click`` is reserved for v1.5+ click-derived
judgments and is rejected at the API filter layer (``JudgmentSourceFilterWire``)
per spec §8.4.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Judgment(Base):
    """One (query, doc) rating within a judgment list."""

    __tablename__ = "judgments"
    __table_args__ = (
        CheckConstraint(
            "rating BETWEEN 0 AND 3",
            name="judgments_rating_check",
        ),
        CheckConstraint(
            "source IN ('llm', 'human', 'click')",
            name="judgments_source_check",
        ),
        UniqueConstraint(
            "judgment_list_id",
            "query_id",
            "doc_id",
            name="judgments_unique_key",
        ),
        Index("judgments_list_query_idx", "judgment_list_id", "query_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    judgment_list_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("judgment_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    query_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("queries.id"),
        nullable=False,
    )
    doc_id: Mapped[str] = mapped_column(Text, nullable=False)
    """Engine-defined document identifier (e.g., Elasticsearch ``_id``)."""
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    """0..3 graded relevance (CHECK-enforced)."""
    source: Mapped[str] = mapped_column(Text, nullable=False)
    """``llm`` | ``human`` | ``click`` (CHECK-enforced; ``click`` reserved)."""
    rater_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Model identifier (e.g. ``openai:gpt-4o-2024-08-06``) or ``operator`` / ``import``."""
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Optional confidence score from the rater; populated for future model
    versions; ``None`` for the MVP1 OpenAI judge + manual overrides."""
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    """LLM rationale or human-supplied annotation."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
