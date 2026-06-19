# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""LLM-vs-UBI study comparison read-only models (feat_ubi_llm_study_comparison)."""

from __future__ import annotations

from pydantic import BaseModel

from backend.app.domain.study.comparison import CompareKind, CompareWarningCode

# ---------------------------------------------------------------------------
# Study comparison (feat_ubi_llm_study_comparison) — read-only.
# CompareKind / CompareWarningCode are defined in the domain layer
# (domain.study.comparison) so the service classifies/validates without
# importing API wire models; these response schemas re-use them.
# ---------------------------------------------------------------------------


class CompareWarning(BaseModel):
    """A non-fatal mismatch between the two compared studies."""

    code: CompareWarningCode
    message: str


class StudyComparePairing(BaseModel):
    """Validated LLM↔UBI study pair returned by ``GET /studies/compare``."""

    a_study_id: str
    b_study_id: str
    a_kind: CompareKind
    b_kind: CompareKind
    query_set_id: str
    warnings: list[CompareWarning]


class StudyPairResponse(BaseModel):
    """``GET /studies/{id}/pair`` — the counterpart, or nulls when none."""

    study_id: str | None
    kind: CompareKind | None


class JudgmentListStudyResponse(BaseModel):
    """``GET /judgment-lists/{id}/study`` — the single completed study, or null."""

    study_id: str | None
