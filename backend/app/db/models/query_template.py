"""``query_templates`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"query_templates".
Templates are versioned via the composite ``UNIQUE (name, version)`` constraint;
forks use the ``parent_id`` self-FK (MVP2 surfaces the fork UI; MVP1 just
preserves the FK target).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class QueryTemplate(Base):
    """A Jinja2 query template with declared params + versioning."""

    __tablename__ = "query_templates"
    __table_args__ = (UniqueConstraint("name", "version", name="query_templates_name_version_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    engine_type: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``elasticsearch | opensearch`` (validated at the service layer
    against ``backend/app/adapters/elastic.py:SUPPORTED_ENGINE_TYPES``)."""
    body: Mapped[str] = mapped_column(Text, nullable=False)
    """Jinja2 template source. Rendered by ``ElasticAdapter.render``."""
    declared_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """``{param_name: type/range hint}`` — used to validate ``params`` at render time."""
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("query_templates.id"), nullable=True
    )
    """Self-FK for forks (MVP2 surface)."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
