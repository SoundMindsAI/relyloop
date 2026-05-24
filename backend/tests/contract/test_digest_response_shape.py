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
    SwapTemplateFollowup,
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

    def test_round_trip_with_swap_template_kind(self) -> None:
        """AC-9: SwapTemplateFollowup survives round-trip through the wire.

        Owner: feat_digest_executable_followups_swap_template Story 4.1.
        """
        valid_template_id = "01931e8a-aaaa-7890-abcd-aaaaaaaaaaaa"
        resp = DigestResponse(
            id="d1",
            study_id="s1",
            narrative="n",
            parameter_importance={},
            recommended_config={},
            suggested_followups=[
                SwapTemplateFollowup(
                    kind="swap_template",
                    rationale="swap to template B",
                    template_id=valid_template_id,
                    search_space=_valid_search_space(),
                ),
            ],
            generated_by="openai:gpt-4o-2024-08-06",
            generated_at=datetime.now(UTC),
        )
        dumped = resp.model_dump_json()
        re_parsed = DigestResponse.model_validate_json(dumped)
        assert len(re_parsed.suggested_followups) == 1
        item = re_parsed.suggested_followups[0]
        assert item.kind == "swap_template"
        # Template id + search_space preserved verbatim.
        assert isinstance(item, SwapTemplateFollowup)
        assert item.template_id == valid_template_id
        assert item.search_space is not None

    def test_openapi_schema_includes_swap_template_branch(self) -> None:
        """The discriminator oneOf MUST surface the SwapTemplateFollowup
        branch with {kind: 'swap_template', template_id: str, search_space: object}.
        """
        schema = DigestResponse.model_json_schema()
        # Pydantic renders the union with $defs + items pointing at the
        # FollowupItem $ref. The branch shape lives in the model's $defs.
        defs = schema.get("$defs") or schema.get("definitions") or {}
        assert "SwapTemplateFollowup" in defs, (
            "expected SwapTemplateFollowup to appear in the OpenAPI $defs "
            "after the discriminated-union widening (Story 1.1)"
        )
        swap_def = defs["SwapTemplateFollowup"]
        # template_id is a required, 36-char string.
        assert "template_id" in swap_def["properties"]
        assert swap_def["properties"]["template_id"]["type"] == "string"
        assert "template_id" in swap_def["required"]
        assert "search_space" in swap_def["properties"]
        # FollowupItem discriminator def points at the SwapTemplateFollowup
        # branch via the mapping (Pydantic discriminated-union rendering).
        followup_item_def = defs.get("FollowupItem")
        if followup_item_def is not None:
            # Pydantic v2 uses oneOf + a discriminator object pointing into $defs.
            assert "oneOf" in followup_item_def or "discriminator" in followup_item_def
            if "discriminator" in followup_item_def:
                mapping = followup_item_def["discriminator"].get("mapping", {})
                assert "swap_template" in mapping

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

    def test_items_are_objects_with_four_kind_enum(self) -> None:
        # feat_digest_executable_followups Story 2.1: search_space is shipped
        # as a JSON-encoded string (search_space_json) to satisfy OpenAI
        # strict-mode JSON-schema constraints. The worker decodes the string
        # before passing to parse_followup_list.
        # feat_digest_executable_followups_swap_template Story 2.1 (Tier B)
        # widens the enum to 4 values + adds the uniform template_id field
        # to every item (worker drops empty-string sentinel before Pydantic
        # dispatch per spec D-29).
        sf = DIGEST_RESPONSE_SCHEMA["properties"]["suggested_followups"]
        assert sf["type"] == "array"
        items = sf["items"]
        assert items["type"] == "object"
        assert items["properties"]["kind"]["enum"] == [
            "narrow",
            "widen",
            "text",
            "swap_template",
        ]
        assert items["properties"]["rationale"]["type"] == "string"
        assert items["properties"]["search_space_json"]["type"] == "string"
        assert items["properties"]["template_id"]["type"] == "string"
        assert items["additionalProperties"] is False
        assert set(items["required"]) == {
            "kind",
            "rationale",
            "search_space_json",
            "template_id",
        }

    def test_max_items_5(self) -> None:
        sf = DIGEST_RESPONSE_SCHEMA["properties"]["suggested_followups"]
        assert sf["maxItems"] == 5
