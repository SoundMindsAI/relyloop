# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract test — _DigestEmbed.suggested_followups discriminated union (Story 4.1).

Asserts that the inline digest on the proposal-detail response carries
the same discriminated-union shape as ``DigestResponse``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.app.api.v1.schemas import _DigestEmbed
from backend.app.domain.study.followups import (
    NarrowFollowup,
    TextFollowup,
)
from backend.app.domain.study.search_space import SearchSpace


def _valid_search_space() -> SearchSpace:
    return SearchSpace.model_validate(
        {
            "params": {
                "title_boost": {"type": "float", "low": 0.5, "high": 5.0},
            }
        }
    )


class TestDigestEmbedShape:
    def test_round_trip_with_narrow_and_text(self) -> None:
        embed = _DigestEmbed(
            id="d1",
            narrative="n",
            parameter_importance={},
            recommended_config={},
            suggested_followups=[
                NarrowFollowup(
                    kind="narrow", rationale="narrow", search_space=_valid_search_space()
                ),
                TextFollowup(kind="text", rationale="text", search_space=None),
            ],
            generated_at=datetime.now(UTC),
        )
        dumped = embed.model_dump_json()
        re_parsed = _DigestEmbed.model_validate_json(dumped)
        assert len(re_parsed.suggested_followups) == 2
        kinds = [f.kind for f in re_parsed.suggested_followups]
        assert kinds == ["narrow", "text"]

    def test_openapi_schema_uses_discriminated_union(self) -> None:
        schema = _DigestEmbed.model_json_schema()
        items = schema["properties"]["suggested_followups"]["items"]
        assert "discriminator" in items or "$ref" in items or "oneOf" in items
