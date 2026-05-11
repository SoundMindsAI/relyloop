"""Unit tests for the OpenAI judge client (feat_llm_judgments Story 1.4).

The judge client is mocked at the ``client.chat.completions.create`` boundary
— the test mocks the SDK call to return canned ``ChatCompletion``-shaped
objects (or to raise). This is simpler than going through ``httpx.MockTransport``
since the SDK's response parser does not have stable public surface for the
``ChatCompletion`` constructor across SDK versions.

Covers:

* Happy path: valid structured-output content → parsed ``DocRating`` list.
* Doc-id allowlist enforcement (GPT-5.5 cycle 1 F9): spurious ids dropped,
  missing ids logged but not raised.
* RateLimit retry → eventual success.
* Retry exhaustion → final error propagates.
* 5xx vs 4xx retry policy (5xx retries; 4xx raises immediately).
* Malformed JSON → retry → eventual success or exhaustion.
* Cost extraction from ``usage`` totals.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from backend.app.llm.openai_judge import (
    RATING_RESPONSE_SCHEMA,
    DocRating,
    rate_query_batch,
)

pytestmark = pytest.mark.asyncio


def _make_response(content: str, *, prompt_tokens: int = 100, completion_tokens: int = 200) -> Any:
    """Build a ``ChatCompletion``-shaped MagicMock the judge code path can read."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_client(side_effect: Any) -> Any:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=side_effect)
    return client


VALID_PAYLOAD = json.dumps(
    {
        "ratings": [
            {"doc_id": "d1", "rating": 3, "rationale": "exact match"},
            {"doc_id": "d2", "rating": 1, "rationale": "tangentially related"},
        ]
    }
)


@pytest.fixture
def expected_ids() -> set[str]:
    return {"d1", "d2"}


async def test_happy_path_returns_validated_ratings(expected_ids: set[str]) -> None:
    client = _make_client([_make_response(VALID_PAYLOAD)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )

    assert result.ratings == [
        DocRating(doc_id="d1", rating=3, rationale="exact match"),
        DocRating(doc_id="d2", rating=1, rationale="tangentially related"),
    ]
    assert result.input_tokens == 100
    assert result.output_tokens == 200
    # Cost = (100/1000)*0.0025 + (200/1000)*0.01 = 0.00025 + 0.002 = 0.00225
    assert result.cost_usd == pytest.approx(0.00225, rel=1e-9)
    assert result.model == "gpt-4o-2024-08-06"
    assert result.duration_ms >= 0
    client.chat.completions.create.assert_awaited_once()
    # Verify the structured-output schema was registered on the call.
    sent_kwargs = client.chat.completions.create.await_args.kwargs
    assert sent_kwargs["response_format"]["json_schema"]["schema"] == RATING_RESPONSE_SCHEMA
    assert sent_kwargs["response_format"]["json_schema"]["strict"] is True


async def test_drops_spurious_doc_ids(expected_ids: set[str]) -> None:
    """Returned doc ids outside expected_doc_ids are dropped with WARN."""
    payload = json.dumps(
        {
            "ratings": [
                {"doc_id": "d1", "rating": 3, "rationale": "ok"},
                {"doc_id": "fabricated", "rating": 2, "rationale": "hallucinated id"},
            ]
        }
    )
    client = _make_client([_make_response(payload)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert [r.doc_id for r in result.ratings] == ["d1"]


async def test_missing_doc_ids_logged_not_raised(expected_ids: set[str]) -> None:
    payload = json.dumps({"ratings": [{"doc_id": "d1", "rating": 3, "rationale": "only d1"}]})
    client = _make_client([_make_response(payload)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert {r.doc_id for r in result.ratings} == {"d1"}


async def test_drops_out_of_range_rating(expected_ids: set[str]) -> None:
    payload = json.dumps(
        {
            "ratings": [
                {"doc_id": "d1", "rating": 3, "rationale": "ok"},
                {"doc_id": "d2", "rating": 7, "rationale": "absurd"},
            ]
        }
    )
    client = _make_client([_make_response(payload)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert {r.doc_id for r in result.ratings} == {"d1"}


def _rate_limit_error() -> openai.RateLimitError:
    """Construct a RateLimitError without hitting the network. The SDK accepts
    (message, response, body) where response is an httpx.Response-like."""
    response = MagicMock()
    response.request = MagicMock()
    response.status_code = 429
    return openai.RateLimitError("rate limited", response=response, body=None)


def _api_status_error(status_code: int) -> openai.APIStatusError:
    response = MagicMock()
    response.request = MagicMock()
    response.status_code = status_code
    return openai.APIStatusError(f"upstream {status_code}", response=response, body=None)


async def test_rate_limit_retries_then_succeeds(
    expected_ids: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.app.llm.openai_judge.asyncio.sleep", AsyncMock())
    client = _make_client([_rate_limit_error(), _make_response(VALID_PAYLOAD)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert len(result.ratings) == 2
    assert client.chat.completions.create.await_count == 2


async def test_rate_limit_exhausted_raises(
    expected_ids: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.app.llm.openai_judge.asyncio.sleep", AsyncMock())
    client = _make_client([_rate_limit_error(), _rate_limit_error(), _rate_limit_error()])
    with pytest.raises(openai.RateLimitError):
        await rate_query_batch(
            client=client,
            model="gpt-4o-2024-08-06",
            system_prompt="sys",
            user_prompt="usr",
            expected_doc_ids=expected_ids,
            max_retries=3,
        )
    assert client.chat.completions.create.await_count == 3


async def test_5xx_retried_4xx_raised(
    expected_ids: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.app.llm.openai_judge.asyncio.sleep", AsyncMock())
    client = _make_client([_api_status_error(503), _make_response(VALID_PAYLOAD)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert len(result.ratings) == 2

    client_400 = _make_client([_api_status_error(400)])
    with pytest.raises(openai.APIStatusError):
        await rate_query_batch(
            client=client_400,
            model="gpt-4o-2024-08-06",
            system_prompt="sys",
            user_prompt="usr",
            expected_doc_ids=expected_ids,
        )
    assert client_400.chat.completions.create.await_count == 1


async def test_malformed_json_retried(
    expected_ids: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.app.llm.openai_judge.asyncio.sleep", AsyncMock())
    client = _make_client([_make_response("not a json string"), _make_response(VALID_PAYLOAD)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert len(result.ratings) == 2


async def test_cost_calculation_uses_model_pricing(expected_ids: set[str]) -> None:
    """gpt-4o-mini pricing differs; verify the helper reads the right model."""
    client = _make_client(
        [_make_response(VALID_PAYLOAD, prompt_tokens=1000, completion_tokens=500)]
    )
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-mini-2024-07-18",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    # (1000/1000)*0.00015 + (500/1000)*0.0006 = 0.00015 + 0.0003 = 0.00045
    assert result.cost_usd == pytest.approx(0.00045, rel=1e-9)


async def test_empty_ratings_array_returns_empty_result(expected_ids: set[str]) -> None:
    payload = json.dumps({"ratings": []})
    client = _make_client([_make_response(payload)])
    result = await rate_query_batch(
        client=client,
        model="gpt-4o-2024-08-06",
        system_prompt="sys",
        user_prompt="usr",
        expected_doc_ids=expected_ids,
    )
    assert result.ratings == []
