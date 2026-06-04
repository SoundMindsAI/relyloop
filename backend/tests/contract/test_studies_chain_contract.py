# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for ``GET /api/v1/studies/{id}/chain`` (feat_overnight_autopilot Story 1.3).

Pure-contract layer (no DB / Redis / engine): asserts the response-model
shapes (top-level keys + per-link 12-field set), the ``stop_reason`` enum
matches the ``CHAIN_STOP_REASONS`` frozenset, the ``direction`` enum, the
endpoint's presence in the OpenAPI document, and the canonical 404
``STUDY_NOT_FOUND`` envelope shape.
"""

from __future__ import annotations

import typing
from typing import cast

from backend.app.api.v1.schemas import StudyChainLink, StudyChainResponse
from backend.app.domain.study.chain_summary import CHAIN_STOP_REASONS, ChainStopReason


def test_chain_response_top_level_keys() -> None:
    assert set(StudyChainResponse.model_fields) == {
        "anchor_study_id",
        "best_link_id",
        "best_metric",
        "cumulative_lift",
        "direction",
        "stop_reason",
        "proposal_id_for_best_link",
        "links",
    }


def test_chain_link_fourteen_fields() -> None:
    """feat_overnight_final_solution Story 3.1 — two additive fields:
    ``template_id`` (P1-B5; needed by the chain panel's swap_template
    badge to resolve the target template's display name) and
    ``selected_followup_kind`` (FR-6; soft-contract additive Literal).
    Both are additive — older clients still parse the response.
    Field count rises 12 → 14."""
    assert set(StudyChainLink.model_fields) == {
        "id",
        "name",
        "status",
        "best_metric",
        "baseline_metric",
        "direction",
        "delta_from_prev",
        "proposal_id",
        "auto_followup_depth_remaining",
        "failed_reason",
        "created_at",
        "completed_at",
        "template_id",
        "selected_followup_kind",
    }
    assert len(StudyChainLink.model_fields) == 14


def test_chain_link_selected_followup_kind_is_literal_with_four_values() -> None:
    """feat_overnight_final_solution Story 3.1 / FR-6 — the Literal
    on the response model must mirror SELECTED_FOLLOWUP_KIND_VALUES
    character-for-character so the frontend mirror in enums.ts and
    this contract cannot silently drift."""
    from backend.app.domain.study.auto_followup_strategy import (
        SELECTED_FOLLOWUP_KIND_VALUES,
    )

    annotation = StudyChainLink.model_fields["selected_followup_kind"].annotation
    args = typing.get_args(annotation)
    # Optional[Literal[...]] renders as Union[Literal[...], None]; the
    # Literal is the non-None entry.
    literal_arg = next(a for a in args if a is not type(None))
    assert set(typing.get_args(literal_arg)) == set(SELECTED_FOLLOWUP_KIND_VALUES)


def test_chain_link_template_id_is_required_string() -> None:
    """feat_overnight_final_solution Story 3.1 / P1-B5 — every study
    has a template_id, so this field is non-optional. The chain panel's
    swap_template badge depends on it for the per-link template-name
    fetch (Story 3.2)."""
    info = StudyChainLink.model_fields["template_id"]
    assert info.annotation is str
    assert info.is_required()


def test_stop_reason_literal_matches_frozenset() -> None:
    literal_values = set(typing.get_args(ChainStopReason))
    assert literal_values == set(CHAIN_STOP_REASONS)
    assert literal_values == {
        "depth_exhausted",
        "no_lift",
        "budget",
        "parent_failed",
        "cancelled",
        "in_flight",
    }


def test_response_model_stop_reason_uses_chain_literal() -> None:
    annotation = StudyChainResponse.model_fields["stop_reason"].annotation
    assert set(typing.get_args(annotation)) == set(CHAIN_STOP_REASONS)


def test_direction_literal_values() -> None:
    annotation = StudyChainResponse.model_fields["direction"].annotation
    assert set(typing.get_args(annotation)) == {"maximize", "minimize"}
    link_annotation = StudyChainLink.model_fields["direction"].annotation
    assert set(typing.get_args(link_annotation)) == {"maximize", "minimize"}


def test_endpoint_present_in_openapi() -> None:
    from backend.app.main import app

    schema = app.openapi()
    path = "/api/v1/studies/{study_id}/chain"
    assert path in schema["paths"]
    assert "get" in schema["paths"][path]
    responses = schema["paths"][path]["get"]["responses"]
    assert "200" in responses


def test_study_not_found_envelope_shape() -> None:
    # The router raises HTTPException(404, detail={error_code, message,
    # retryable}); assert the envelope contract the global handler emits.
    from backend.app.api.v1.studies import _err

    exc = _err(404, "STUDY_NOT_FOUND", "study x not found", False)
    assert exc.status_code == 404
    detail = cast("dict[str, object]", exc.detail)
    assert detail == {
        "error_code": "STUDY_NOT_FOUND",
        "message": "study x not found",
        "retryable": False,
    }
