# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``digests`` ORM model (feat_digest_proposal Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"digests".

One row per study (UNIQUE on ``study_id``). Re-generating a digest requires
the runbook escape hatch (``DELETE FROM digests WHERE study_id = ...`` + Arq
re-enqueue) per spec §19 Decision log.

The ``suggested_followups`` column is ``Mapped[list[dict[str, Any]]]`` —
JSONB carrying the discriminated-union ``FollowupItem`` shape
(``{kind, rationale, search_space}`` per
``backend.app.domain.study.followups``). Migration 0019 converted the
historical ``ARRAY(Text)`` rows into the structured shape via a PL/pgSQL
helper that wraps each text element as
``{"kind": "text", "rationale": <text>, "search_space": null}``.

The column is NOT NULL with ``server_default '[]'::jsonb`` so the worker
can write an empty list (zero-trials AC-2 path; capability-fallback
AC-11 path) without the API layer carrying a NULL-vs-empty branch.
Defensive read-path: every consumer wraps via
``parse_followup_list()`` so legacy or malformed payloads don't crash
the response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
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
    suggested_followups: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        # Match the migration 0019 default. ORM server_default is only
        # consumed by Base.metadata.create_all (we use Alembic), but keep
        # the two in sync for correctness.
        server_default=text("'[]'::jsonb"),
    )
    """List of LLM-suggested next-steps; max 5 entries (enforced in worker
    via the structured-output schema's ``maxItems: 5``). Each element is a
    ``FollowupItem`` dict (``{kind: 'narrow'|'widen'|'text', rationale: str,
    search_space: SearchSpace | null}``). NOT NULL with ``'[]'::jsonb``
    default."""
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    """Provider + model identifier (e.g. ``openai:gpt-4o-2024-08-06``) or
    ``local:zero_trials`` for the AC-2 placeholder path."""
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
