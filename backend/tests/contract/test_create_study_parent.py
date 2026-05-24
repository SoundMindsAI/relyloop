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


class TestNewErrorCodesSurfacedByRouter:
    """All three new error codes are emitted by the create_study handler."""

    @pytest.mark.parametrize(
        "code",
        ["PROPOSAL_NOT_FOUND", "DIGEST_NOT_FOUND", "FOLLOWUP_INDEX_OUT_OF_RANGE"],
    )
    def test_router_source_contains_code(self, code: str) -> None:
        assert code in _studies_router_source(), f"expected {code!r} to be raised in studies router"
