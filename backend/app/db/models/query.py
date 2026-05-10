"""``queries`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"queries".
Cascade-deletes with the parent ``query_sets`` row.

**Naming note:** the Python attribute is ``query_metadata``, not ``metadata``,
because ``metadata`` is reserved on SQLAlchemy ``DeclarativeBase`` (it's the
table registry). The DB column name stays ``metadata`` via the explicit first
argument to ``mapped_column``. See implementation_plan.md Story 1.1 — this
was caught by the cycle-1 GPT-5.5 cross-model review (F5) before
implementation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Query(Base):
    """One query in a query set; the unit of relevance evaluation."""

    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_sets.id", ondelete="CASCADE"), nullable=False
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Optional gold answer for QA-style evaluation; not used by MVP1's
    rank-based metrics (nDCG / MAP / etc.)."""
    query_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    """DB column ``metadata``; Python attribute renamed because ``metadata``
    is reserved on SQLAlchemy ``DeclarativeBase``."""
