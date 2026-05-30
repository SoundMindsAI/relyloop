# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``clusters`` ORM model (infra_adapter_elastic Story 1.2 / FR-5).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"clusters".
The migration in Story 1.3 (``0002_clusters_config_repos``) creates the
table to match this declarative model.

CHECK constraints enforce the three enumerated string columns
(``engine_type``, ``environment``, ``auth_kind``); see
``backend/app/adapters/protocol.py`` ``EngineType`` for the wire-value
source of truth on ``engine_type``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Cluster(Base):
    """One registered Elasticsearch / OpenSearch cluster."""

    __tablename__ = "clusters"
    __table_args__ = (
        CheckConstraint(
            "engine_type IN ('elasticsearch', 'opensearch')",
            name="clusters_engine_type_check",
        ),
        CheckConstraint(
            "environment IN ('prod', 'staging', 'dev')",
            name="clusters_environment_check",
        ),
        CheckConstraint(
            "auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4')",
            name="clusters_auth_kind_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    """UUIDv7 hex (lexicographically sortable, time-ordered)."""

    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    """Operator-supplied stable identifier, e.g. ``local-es``."""

    engine_type: Mapped[str] = mapped_column(String, nullable=False)
    """One of ``elasticsearch | opensearch`` (CHECK enforced)."""

    environment: Mapped[str] = mapped_column(String, nullable=False)
    """One of ``prod | staging | dev`` (CHECK enforced)."""

    base_url: Mapped[str] = mapped_column(String, nullable=False)
    """Cluster HTTP root, e.g. ``http://elasticsearch:9200``."""

    auth_kind: Mapped[str] = mapped_column(String, nullable=False)
    """One of ``es_apikey | es_basic | opensearch_basic | opensearch_sigv4``."""

    credentials_ref: Mapped[str] = mapped_column(String, nullable=False)
    """Key into the mounted ``cluster_credentials.yaml``."""

    config_repo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("config_repos.id"), nullable=True
    )
    """FK to ``config_repos.id``; nullable until a Git repo is wired in."""

    config_path: Mapped[str | None] = mapped_column(String, nullable=True)
    """Path inside the Git repo where this cluster's configs live."""

    engine_config: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    """Engine-specific config (e.g. ``{"api_version": "9"}``); free-form JSONB."""

    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    """Operator notes (free-form, max 2000 chars at the API layer)."""

    target_filter: Mapped[str | None] = mapped_column(String(256), nullable=True)
    """Operator-supplied glob pattern (``fnmatch.fnmatchcase`` syntax) scoping
    ``list_targets()`` to matching index names. ``NULL`` = no filter (default,
    backward-compatible). Trimmed at the API layer; stored verbatim otherwise."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Insert timestamp (UTC). server_default so DB clock is the source."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Soft-delete marker. ``NULL`` for active rows; UTC timestamp once deleted."""
