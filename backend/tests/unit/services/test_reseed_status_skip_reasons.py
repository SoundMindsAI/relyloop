# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the ``scenarios_skipped_reasons`` field on ``ReseedStatusResponse``.

feat_selective_engine_startup_and_demo Story 2.1 / FR-6.

Asserts the additive sibling-dict behavior:
- defaults to ``{}`` on fresh construction
- round-trips through JSON serialization
- accepts the two canonical reason values
- rejects unknown reason values at validation
- backward-compatible with older Redis-cached payloads that lack the
  field entirely (Pydantic defaults the field; the model stays valid)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.services.demo_seeding import ReseedStatusResponse


def test_scenarios_skipped_reasons_defaults_to_empty_dict() -> None:
    """Fresh construction without the field → ``scenarios_skipped_reasons == {}``."""
    response = ReseedStatusResponse(status="idle")
    assert response.scenarios_skipped_reasons == {}


def test_scenarios_skipped_reasons_accepts_user_excluded() -> None:
    response = ReseedStatusResponse(
        status="complete",
        scenarios_skipped=["foo"],
        scenarios_skipped_reasons={"foo": "user_excluded"},
    )
    assert response.scenarios_skipped_reasons == {"foo": "user_excluded"}


def test_scenarios_skipped_reasons_accepts_unreachable() -> None:
    response = ReseedStatusResponse(
        status="complete",
        scenarios_skipped=["bar"],
        scenarios_skipped_reasons={"bar": "unreachable"},
    )
    assert response.scenarios_skipped_reasons == {"bar": "unreachable"}


def test_scenarios_skipped_reasons_accepts_mixed() -> None:
    response = ReseedStatusResponse(
        status="complete",
        scenarios_skipped=["foo", "bar"],
        scenarios_skipped_reasons={
            "foo": "user_excluded",
            "bar": "unreachable",
        },
    )
    assert response.scenarios_skipped_reasons == {
        "foo": "user_excluded",
        "bar": "unreachable",
    }


def test_scenarios_skipped_reasons_rejects_unknown_reason() -> None:
    """An unknown reason string (e.g., from a typo) is rejected at validation."""
    with pytest.raises(ValidationError):
        ReseedStatusResponse(
            status="complete",
            scenarios_skipped=["foo"],
            scenarios_skipped_reasons={"foo": "wrong_reason"},
        )


def test_scenarios_skipped_reasons_json_round_trip() -> None:
    """Serializing then deserializing the model preserves the reasons map."""
    original = ReseedStatusResponse(
        status="complete",
        scenarios_skipped=["foo", "bar"],
        scenarios_skipped_reasons={
            "foo": "user_excluded",
            "bar": "unreachable",
        },
    )
    blob = original.model_dump_json()
    restored = ReseedStatusResponse.model_validate_json(blob)
    assert restored.scenarios_skipped_reasons == {
        "foo": "user_excluded",
        "bar": "unreachable",
    }


def test_scenarios_skipped_reasons_backward_compat_with_older_payload() -> None:
    """A Redis-cached payload from before this field landed must still deserialize.

    The worker writes the full ``ReseedStatusResponse.model_dump_json()``
    blob to Redis; cached values from before this PR will not include
    ``scenarios_skipped_reasons``. The field's ``default_factory=dict``
    populates the empty default — no migration needed.
    """
    older_blob = (
        '{"status":"complete","started_at":null,"finished_at":null,'
        '"scenarios_total":5,"scenarios_completed":4,"current_step":"done",'
        '"failed_reason":null,"summary":null,"steps":[],'
        '"scenarios_skipped":["news-search-staging"]}'
    )
    restored = ReseedStatusResponse.model_validate_json(older_blob)
    assert restored.scenarios_skipped == ["news-search-staging"]
    assert restored.scenarios_skipped_reasons == {}
