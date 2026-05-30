# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract test — POST /api/v1/studies parent body (Story 4.2).

Asserts:

- ``CreateStudyRequest.parent`` is optional in the OpenAPI schema.
- ``ParentFollowupRef`` has the spec's shape (proposal_id exact-36,
  followup_index >= 0).
- The three new error codes are emitted by the create_study handler
  (static-grep of the router source against the route handler — same
  pattern feat_digest_proposal uses for spec §8.5 audit).

DB-backed integration coverage of malformed-body envelopes lives at
``backend/tests/integration/test_studies_with_parent_followup.py``
(Story 4.2 integration test). The contract layer stays hermetic: no
DB, no http calls — just schema + source-grep assertions.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _studies_router_source() -> str:
    path = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "studies.py"
    return path.read_text(encoding="utf-8")


class TestOpenAPISurface:
    def test_create_study_request_parent_is_optional(self) -> None:
        from backend.app.api.v1.schemas import CreateStudyRequest

        schema = CreateStudyRequest.model_json_schema()
        # `parent` field is optional (allowed: object | null).
        assert "parent" in schema["properties"]
        # Required list does NOT include `parent`.
        assert "parent" not in schema.get("required", [])

    def test_parent_followup_ref_shape(self) -> None:
        from backend.app.api.v1.schemas import ParentFollowupRef

        schema = ParentFollowupRef.model_json_schema()
        # proposal_id: exact-length 36, followup_index: int >= 0.
        proposal_id_props = schema["properties"]["proposal_id"]
        assert proposal_id_props["minLength"] == 36
        assert proposal_id_props["maxLength"] == 36
        followup_index_props = schema["properties"]["followup_index"]
        assert followup_index_props["minimum"] == 0
        assert set(schema["required"]) == {"proposal_id", "followup_index"}

    def test_create_study_request_parent_study_id_is_optional_36_chars(self) -> None:
        """feat_study_clone_from_previous FR-7 — parent_study_id optional, exact-36 bound.

        The exact-length bound forces malformed strings (anything not a UUIDv7-shaped
        36-char string) to surface as 422 VALIDATION_ERROR at the Pydantic layer
        before the parent-study FK lookup runs.
        """
        from backend.app.api.v1.schemas import CreateStudyRequest

        schema = CreateStudyRequest.model_json_schema()
        assert "parent_study_id" in schema["properties"]
        # Required list does NOT include `parent_study_id`.
        assert "parent_study_id" not in schema.get("required", [])
        # Length bound matches the existing ParentFollowupRef.proposal_id discipline.
        # Optional field surfaces as anyOf: [{string + minLength + maxLength}, {null}].
        prop = schema["properties"]["parent_study_id"]
        # Pydantic v2 renders optional length-bounded strings as anyOf with the
        # string variant carrying the length bounds.
        if "anyOf" in prop:
            string_variant = next(v for v in prop["anyOf"] if v.get("type") == "string")
            assert string_variant["minLength"] == 36
            assert string_variant["maxLength"] == 36
        else:
            assert prop["minLength"] == 36
            assert prop["maxLength"] == 36


class TestNewErrorCodesSurfacedByRouter:
    """All five new error codes are emitted by the create_study handler.

    The first three (PROPOSAL_NOT_FOUND, DIGEST_NOT_FOUND,
    FOLLOWUP_INDEX_OUT_OF_RANGE) were introduced by Story 4.2 of
    feat_digest_executable_followups; the latter two
    (PARENT_STUDY_NOT_FOUND, PARENT_STUDY_WRONG_CLUSTER) are added by
    feat_study_clone_from_previous Story 1.2 / FR-8 / D-9 (early-placement
    parent-study FK validation).
    """

    @pytest.mark.parametrize(
        "code",
        [
            "PROPOSAL_NOT_FOUND",
            "DIGEST_NOT_FOUND",
            "FOLLOWUP_INDEX_OUT_OF_RANGE",
            "PARENT_STUDY_NOT_FOUND",
            "PARENT_STUDY_WRONG_CLUSTER",
        ],
    )
    def test_router_source_contains_code(self, code: str) -> None:
        assert code in _studies_router_source(), f"expected {code!r} to be raised in studies router"
