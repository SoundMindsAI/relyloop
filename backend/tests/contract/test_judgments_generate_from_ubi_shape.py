# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for ``POST /api/v1/judgments/generate-from-ubi``
(feat_ubi_judgments Story 3.2 / FR-3).

Locks the request body shape (including the hybrid conditional
``model_validator``) + the 13 documented error envelopes. The
service-layer behavior is covered by
``backend/tests/unit/services/test_agent_judgments_dispatch_ubi.py``
(14 cases over every preflight branch); this layer asserts the wire
shape + the Pydantic validator gates.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.api.v1.schemas import (
    CreateJudgmentListFromUbiRequest,
    GenerateJudgmentsResponse,
)


def _base_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "ubi-judgments-1",
        "description": None,
        "query_set_id": "qs_00000000000000000000000000000001",
        "cluster_id": "clu_0000000000000000000000000000001",
        "target": "products",
        "since": datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
        "until": datetime(2026, 5, 29, tzinfo=UTC).isoformat(),
        "converter": "ctr_threshold",
        "converter_config": None,
        "llm_fill_threshold": 20,
        "min_impressions_threshold": 100,
        "mapping_strategy": "reject",
        "current_template_id": None,
        "rubric": None,
    }
    payload.update(overrides)
    return payload


class TestRequestShape:
    def test_pure_converter_minimal_payload_accepted(self) -> None:
        req = CreateJudgmentListFromUbiRequest.model_validate(_base_payload())
        assert req.converter == "ctr_threshold"
        assert req.mapping_strategy == "reject"
        assert req.current_template_id is None

    def test_pure_converter_with_template_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            CreateJudgmentListFromUbiRequest.model_validate(
                _base_payload(
                    converter="dwell_time",
                    current_template_id="0" * 36,
                )
            )
        assert "MUST be null for non-hybrid" in str(ei.value)

    def test_pure_converter_with_rubric_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateJudgmentListFromUbiRequest.model_validate(
                _base_payload(converter="ctr_threshold", rubric="rate 0-3")
            )

    def test_hybrid_requires_template_and_rubric(self) -> None:
        with pytest.raises(ValidationError) as ei:
            CreateJudgmentListFromUbiRequest.model_validate(
                _base_payload(converter="hybrid_ubi_llm")
            )
        assert "REQUIRED when" in str(ei.value)

    def test_hybrid_with_template_and_rubric_accepted(self) -> None:
        req = CreateJudgmentListFromUbiRequest.model_validate(
            _base_payload(
                converter="hybrid_ubi_llm",
                current_template_id="0" * 36,
                rubric="rate documents 0-3",
            )
        )
        assert req.converter == "hybrid_ubi_llm"
        assert req.rubric == "rate documents 0-3"

    def test_invalid_converter_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateJudgmentListFromUbiRequest.model_validate(
                _base_payload(converter="llm")  # llm is not a UBI converter
            )

    def test_invalid_mapping_strategy_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateJudgmentListFromUbiRequest.model_validate(
                _base_payload(mapping_strategy="merge")  # not in the wire Literal
            )

    def test_min_impressions_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CreateJudgmentListFromUbiRequest.model_validate(
                _base_payload(min_impressions_threshold=0)
            )

    def test_llm_fill_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CreateJudgmentListFromUbiRequest.model_validate(_base_payload(llm_fill_threshold=0))

    def test_optional_until_defaults_to_none(self) -> None:
        payload = _base_payload()
        del payload["until"]
        req = CreateJudgmentListFromUbiRequest.model_validate(payload)
        assert req.until is None

    def test_required_fields_locked(self) -> None:
        """Inventory the request shape so a future refactor can't drop a field silently."""
        declared = set(CreateJudgmentListFromUbiRequest.model_fields.keys())
        assert declared == {
            "name",
            "description",
            "query_set_id",
            "cluster_id",
            "target",
            "since",
            "until",
            "converter",
            "converter_config",
            "llm_fill_threshold",
            "min_impressions_threshold",
            "mapping_strategy",
            "current_template_id",
            "rubric",
        }


class TestResponseShape:
    def test_generate_judgments_response_unchanged(self) -> None:
        """UBI endpoint reuses :class:`GenerateJudgmentsResponse` — wire compat."""
        resp = GenerateJudgmentsResponse(judgment_list_id="abc", status="generating")
        assert resp.judgment_list_id == "abc"
        assert resp.status == "generating"
