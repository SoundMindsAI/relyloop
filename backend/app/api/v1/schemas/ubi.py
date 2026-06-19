# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""UBI readiness + generate-from-ubi request shapes (feat_ubi_judgments)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.app.api.v1._wire_types import (
    UbiConverterKind,
    UbiMappingStrategyWire,
    UbiReadinessRungWire,
)

# ---------------------------------------------------------------------------
# UBI readiness + generate-from-ubi request shapes (feat_ubi_judgments
# Stories 3.1 + 3.2)
# ---------------------------------------------------------------------------


class UbiReadinessResponse(BaseModel):
    """``GET /api/v1/clusters/{cluster_id}/ubi-readiness`` response (FR-7).

    ``covered_pairs_pct`` and ``head_covered`` are nullable — MVP2's
    rung classifier uses event-count thresholds (the SearchAdapter
    Protocol doesn't expose an exact ``_count`` endpoint). The fields
    are reserved on the wire so a future ``infra_adapter_count_method``
    can fill them without breaking the contract. See
    :mod:`backend.app.services.ubi_readiness` for the rationale.
    """

    rung: UbiReadinessRungWire
    covered_pairs_pct: float | None
    head_covered: bool | None
    checked_at: datetime


class CreateJudgmentListFromUbiRequest(BaseModel):
    """Body for ``POST /api/v1/judgments/generate-from-ubi`` (Story 3.2 / FR-3).

    Mirrors :class:`backend.app.services.agent_judgments_dispatch.UbiJudgmentGenerationRequest`.
    The ``@model_validator(mode="after")`` enforces the conditional
    requiredness of ``current_template_id`` + ``rubric`` per the hybrid
    converter: REQUIRED when ``converter == 'hybrid_ubi_llm'`` (the LLM-
    fill path needs both); FORBIDDEN otherwise (pure UBI never calls
    the LLM so accepting them silently would mask operator error).
    """

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    since: datetime
    until: datetime | None = None
    converter: UbiConverterKind
    converter_config: dict[str, Any] | None = None
    llm_fill_threshold: int | None = Field(default=20, ge=1)
    min_impressions_threshold: int | None = Field(default=100, ge=1)
    mapping_strategy: UbiMappingStrategyWire = "reject"
    current_template_id: str | None = Field(default=None, min_length=36, max_length=36)
    rubric: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_hybrid_conditional(self) -> CreateJudgmentListFromUbiRequest:
        is_hybrid = self.converter == "hybrid_ubi_llm"
        has_template = self.current_template_id is not None
        has_rubric = self.rubric is not None
        if is_hybrid and not (has_template and has_rubric):
            raise ValueError(
                "current_template_id and rubric are REQUIRED when converter == 'hybrid_ubi_llm'"
            )
        if not is_hybrid and (has_template or has_rubric):
            raise ValueError(
                "current_template_id and rubric MUST be null for non-hybrid converters"
            )
        return self
