"""Unit tests for ``DIGEST_RESPONSE_FORMAT`` (feat_digest_proposal cycle-1 F4).

Asserts the structured-output contract that ``backend/workers/digest.py``
passes to ``client.chat.completions.create(..., response_format=...)``:

* ``response_format["type"] == "json_schema"``.
* ``response_format["json_schema"]["strict"] is True``.
* ``response_format["json_schema"]["schema"]["properties"]
   ["suggested_followups"]["maxItems"] == 5``.
* The schema does NOT declare ``recommended_config`` — that field is
  worker-computed deterministically from best-trial params filtered to
  currently-declared template params (per spec FR-5 / cycle-1 F5 /
  cycle-2 F1).
"""

from __future__ import annotations

from backend.workers.digest import DIGEST_RESPONSE_FORMAT, DIGEST_RESPONSE_SCHEMA


def test_response_format_is_strict_json_schema() -> None:
    assert DIGEST_RESPONSE_FORMAT["type"] == "json_schema"
    js = DIGEST_RESPONSE_FORMAT["json_schema"]
    assert js["name"] == "digest_narrative"
    assert js["strict"] is True
    assert js["schema"] is DIGEST_RESPONSE_SCHEMA


def test_schema_caps_suggested_followups_at_five() -> None:
    """Cycle-1 F4: maxItems is wired into the schema, not just prose."""
    sf = DIGEST_RESPONSE_SCHEMA["properties"]["suggested_followups"]
    assert sf["type"] == "array"
    assert sf["items"] == {"type": "string"}
    assert sf["maxItems"] == 5


def test_schema_does_not_declare_recommended_config() -> None:
    """Cycle-1 F5 / cycle-2 F1: recommended_config is worker-deterministic, not LLM-generated."""
    properties = DIGEST_RESPONSE_SCHEMA["properties"]
    assert "recommended_config" not in properties
    assert "narrative" in properties
    assert "suggested_followups" in properties
    assert set(DIGEST_RESPONSE_SCHEMA["required"]) == {"narrative", "suggested_followups"}


def test_schema_disallows_additional_properties() -> None:
    """Strict mode means OpenAI will reject any extra fields the LLM tries to inject."""
    assert DIGEST_RESPONSE_SCHEMA["additionalProperties"] is False
