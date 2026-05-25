"""OpenAI capability-check result model (infra_foundation Story 3.2 / 3.3).

Shape matches the JSON cached in Redis under
``openai:capabilities:{sha256(base_url)}`` per
``docs/01_architecture/llm-orchestration.md`` §"Capability check at startup".

Story 3.2 references this type from ``probes.probe_openai_state``;
Story 3.3 adds the actual probe implementation and Redis caching.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CapabilityResult(BaseModel):
    """Cached result of the 4-step OpenAI-compatible endpoint capability check."""

    base_url: str = Field(description="The OPENAI_BASE_URL the check was run against")
    model: str = Field(description="The OPENAI_MODEL that was tested")
    models_endpoint: Literal["ok", "fail"] = Field(
        description="Whether GET {base_url}/models returned successfully"
    )
    chat_completion: Literal["ok", "fail", "untested"] = Field(
        description="Whether a 1-token chat completion succeeded"
    )
    function_calling: Literal["ok", "fail", "untested"] = Field(
        description="Whether tool_choice='required' produced a parseable tool_calls field"
    )
    structured_output: Literal["ok", "fail", "untested"] = Field(
        description="Whether response_format=json_schema produced parseable JSON"
    )
    models_endpoint_status_code: int | None = Field(
        default=None,
        description=(
            "HTTP status code captured when models_endpoint='fail' AND the failure "
            "was an HTTP response (>= 400). None for success / network-class failure "
            "/ pre-fix cached rows."
        ),
    )
    tested_at: datetime = Field(description="UTC timestamp when the check ran")
