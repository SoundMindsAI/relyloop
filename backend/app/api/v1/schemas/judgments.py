# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Judgment-list, row, import, override, and calibration models (feat_llm_judgments)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.api.v1._wire_types import (
    JudgmentListStatusWire,
    JudgmentSourceWire,
    RatingWire,
)

# --------------------------------------------------------------------------
# feat_llm_judgments — Epic 3 schemas (Stories 3.1 – 3.5)
# --------------------------------------------------------------------------


class CreateJudgmentListGenerateRequest(BaseModel):
    """Body for ``POST /api/v1/judgments/generate`` (Story 3.1)."""

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    current_template_id: str = Field(min_length=1, max_length=36)
    rubric: str = Field(min_length=1)


class GenerateJudgmentsResponse(BaseModel):
    """Response of ``POST /api/v1/judgments/generate``.

    Per GPT-5.5 cycle 1 F5 — the endpoint registers a typed
    ``response_model`` so OpenAPI introspection + contract tests can verify
    the wire shape.
    """

    judgment_list_id: str
    status: Literal["generating"]


class _SourceBreakdown(BaseModel):
    """Source-breakdown sub-shape on :class:`JudgmentListDetail`.

    Evolved 2026-05-29 by ``feat_ubi_judgments`` FR-10 — now three terms
    (``llm + human + click == judgment_count``). The cycle-2 F6
    "click folds into human" contract is superseded the moment UBI ships
    click rows; the UI's source-breakdown card now renders all three
    buckets separately so operators see the mix at a glance.
    """

    llm: int
    human: int
    click: int


class JudgmentListSummary(BaseModel):
    """List-view row on ``GET /api/v1/judgment-lists``."""

    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    status: JudgmentListStatusWire
    created_at: datetime


class JudgmentListDetail(BaseModel):
    """``GET /api/v1/judgment-lists/{id}`` response.

    Note: ``generation_params`` is populated for UBI lists (feat_ubi_judgments
    Story 1.1's JSONB column) and NULL for LLM lists. The Story 4.3 UI
    (``<ValueDeltaCard>`` + ``<AmbiguousSkipRecoveryCard>``) reads the
    payload to discriminate UBI/hybrid lists and to reconstruct the
    original request for the ambiguous-skip "Re-run with most_recent"
    affordance.
    """

    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    current_template_id: str | None
    rubric: str
    status: JudgmentListStatusWire
    failed_reason: str | None
    judgment_count: int
    source_breakdown: _SourceBreakdown
    calibration: dict[str, Any] | None
    generation_params: dict[str, Any] | None
    created_at: datetime


class JudgmentListListResponse(BaseModel):
    """``GET /api/v1/judgment-lists`` response."""

    data: list[JudgmentListSummary]
    next_cursor: str | None
    has_more: bool


class JudgmentRow(BaseModel):
    """``GET /api/v1/judgment-lists/{id}/judgments`` row + PATCH response."""

    id: str
    judgment_list_id: str
    query_id: str
    doc_id: str
    rating: RatingWire
    source: JudgmentSourceWire
    rater_ref: str | None
    confidence: float | None
    notes: str | None
    created_at: datetime


class JudgmentListJudgmentsResponse(BaseModel):
    """``GET /api/v1/judgment-lists/{id}/judgments`` response."""

    data: list[JudgmentRow]
    next_cursor: str | None
    has_more: bool


class ImportJudgmentItem(BaseModel):
    """One row in :class:`ImportJudgmentListRequest`."""

    query_id: str = Field(min_length=1, max_length=36)
    doc_id: str = Field(min_length=1, max_length=512)
    rating: RatingWire
    notes: str | None = Field(default=None, max_length=2000)


class ImportJudgmentListRequest(BaseModel):
    """Body for ``POST /api/v1/judgment-lists/import`` (Story 3.2)."""

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    rubric: str = Field(min_length=1)
    judgments: list[ImportJudgmentItem] = Field(min_length=1, max_length=100_000)


class OverrideJudgmentRequest(BaseModel):
    """Body for ``PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}``.

    ``rating`` is INTENTIONALLY unbounded at the Pydantic layer — spec §8.5
    requires out-of-range failures to surface as 400 ``INVALID_RATING`` (not
    Pydantic's default 422 ``VALIDATION_ERROR``). The handler validates the
    value manually and raises the domain code (per GPT-5.5 cycle 1 F4).
    """

    rating: int
    notes: str | None = Field(default=None, max_length=2000)


class CalibrationSample(BaseModel):
    """One row in :class:`CalibrationSamplesRequest`."""

    query_id: str = Field(min_length=1, max_length=36)
    doc_id: str = Field(min_length=1, max_length=512)
    rating: RatingWire


class CalibrationSamplesRequest(BaseModel):
    """Body for ``POST /api/v1/judgment-lists/{id}/calibration`` (Story 3.5)."""

    human_samples: list[CalibrationSample] = Field(min_length=1)


class CalibrationResponse(BaseModel):
    """Calibration endpoint response.

    Mirrors :class:`backend.app.eval.calibration.CalibrationResult` —
    persisted as ``judgment_lists.calibration`` JSONB.
    """

    cohens_kappa: float | None
    weighted_kappa: float | None
    per_class: dict[str, float]
    n_samples: int
    warning: str | None
