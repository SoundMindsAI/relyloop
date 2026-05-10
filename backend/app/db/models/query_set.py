"""``query_sets`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"query_sets".
Cluster-scoped — judgments and trials are cluster-specific so a query set's
relevance ratings only make sense against the cluster it was authored for.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class QuerySet(Base):
    """A named collection of queries used for relevance evaluation."""

    __tablename__ = "query_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[str] = mapped_column(String(36), ForeignKey("clusters.id"), nullable=False)
    """Cluster the queries are authored against. Judgment ratings are
    cluster-specific — same query against a different cluster needs new
    judgments."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
