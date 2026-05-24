"""Contract test — DigestResponse.suggested_followups discriminated union (Story 4.1).

Asserts:

- ``DigestResponse.suggested_followups`` is a list of the
  ``FollowupItem`` discriminated union (kind ∈ {narrow, widen, text}).
- The worker's ``DIGEST_RESPONSE_SCHEMA`` matches the spec FR-1 shape
  (items are ``{kind, rationale, search_space}`` objects).
- Constructing ``DigestResponse(... suggested_followups=[NarrowFollowup(...)])``
  round-trips through ``model_dump_json()``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.app.api.v1.schemas import DigestResponse
from backend.app.domain.study.followups import (
    NarrowFollowup,
    TextFollowup,
    WidenFollowup,
)
from backend.app.domain.study.search_space import SearchSpace
from backend.workers.digest import DIGEST_RESPONSE_SCHEMA


def _valid_search_space() -> SearchSpace:
    return SearchSpace.model_validate(
        {
            "params": {
                "tie_breaker": {"type": "float", "low": 0.0, "high": 1.0},
            }
        }
    )


class TestDigestResponseShape:
    def test_round_trip_with_all_three_kinds(self) -> None:
        resp = DigestResponse(
            id="d1",
            study_id="s1",
            narrative="n",
            parameter_importance={},
            recommended_config={},
            suggested_followups=[
                NarrowFollowup(
                    kind="narrow", rationale="narrow", search_space=_valid_search_space()
                ),
                WidenFollowup(kind="widen", rationale="widen", search_space=_valid_search_space()),
                TextFollowup(kind="text", rationale="text", search_space=None),
            ],
            generated_by="openai:gpt-4o-2024-08-06",
            generated_at=datetime.now(UTC),
        )
        dumped = resp.model_dump_json()
        # Parse back from JSON via Pydantic to confirm the discriminator
        # works through the wire format.
        re_parsed = DigestResponse.model_validate_json(dumped)
        assert len(re_parsed.suggested_followups) == 3
        kinds = {f.kind for f in re_parsed.suggested_followups}
        assert kinds == {"narrow", "widen", "text"}

    def test_openapi_schema_uses_discriminated_union(self) -> None:
        schema = DigestResponse.model_json_schema()
        sf_schema = schema["properties"]["suggested_followups"]
        assert sf_schema["type"] == "array"
        # The items use the discriminator on ``kind``; in Pydantic's
        # JSON-schema rendering the discriminator surfaces as ``oneOf``
        # plus ``discriminator: {propertyName: 'kind', mapping: {...}}``.
        items = sf_schema["items"]
        assert "discriminator" in items or "$ref" in items or "oneOf" in items


class TestWorkerSchemaShape:
    """The worker's structured-output schema matches the FR-1 contract."""

    def test_items_are_objects_with_three_kind_enum(self) -> None:
        sf = DIGEST_RESPONSE_SCHEMA["properties"]["suggested_followups"]
        assert sf["type"] == "array"
        items = sf["items"]
        assert items["type"] == "object"
        assert items["properties"]["kind"]["enum"] == ["narrow", "widen", "text"]
        assert items["properties"]["rationale"]["type"] == "string"
        # search_space is nullable.
        assert items["properties"]["search_space"]["type"] == ["object", "null"]
        assert items["additionalProperties"] is False
        assert set(items["required"]) == {"kind", "rationale", "search_space"}

    def test_max_items_5(self) -> None:
        sf = DIGEST_RESPONSE_SCHEMA["properties"]["suggested_followups"]
        assert sf["maxItems"] == 5
