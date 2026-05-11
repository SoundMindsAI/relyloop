"""OpenAI judge client (feat_llm_judgments Story 1.4 — FR-2 hot-path helper).

One async function — :func:`rate_query_batch` — wraps the
:class:`openai.AsyncOpenAI` SDK with the contract the judgment worker needs:

* Structured-output ``response_format=json_schema`` with ``strict=True`` so the
  returned payload matches :data:`RATING_RESPONSE_SCHEMA` exactly.
* Exponential-backoff retry on transient failures (rate limits, 503s,
  malformed JSON), capped at ``max_retries`` attempts.
* Doc-id allowlist enforcement via ``expected_doc_ids`` (per GPT-5.5 cycle 1
  F9). Spurious ids are dropped with WARN; absent ids are logged at WARN but
  not raised — the worker is responsible for the partial-success policy.
* Token usage + cost extraction via :mod:`backend.app.llm.cost_model`.

The worker calls :func:`rate_query_batch` once per (query, top-K hits) — one
LLM call per query is the cost guardrail (spec §13).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import openai
from openai import AsyncOpenAI

from backend.app.core.logging import get_logger
from backend.app.llm.cost_model import compute_call_cost

logger = get_logger(__name__)


@dataclass(frozen=True)
class DocRating:
    """One LLM rating for a single ``(query, doc)`` pair."""

    doc_id: str
    rating: int
    rationale: str


@dataclass(frozen=True)
class JudgeCallResult:
    """Outcome of one :func:`rate_query_batch` invocation."""

    ratings: list[DocRating]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    model: str


# Module-level constant so contract tests can import it.
RATING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ratings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "rating": {"type": "integer", "minimum": 0, "maximum": 3},
                    "rationale": {"type": "string"},
                },
                "required": ["doc_id", "rating", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ratings"],
    "additionalProperties": False,
}


# How long to wait between retries. ``attempt`` is 1-indexed; sleep is
# ``2 ** (attempt - 1)`` so the first retry waits 1s, then 2s, then 4s.
def _backoff_seconds(attempt: int) -> float:
    return float(2 ** (attempt - 1))


async def rate_query_batch(
    *,
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    expected_doc_ids: set[str],
    max_retries: int = 3,
) -> JudgeCallResult:
    """Single batched OpenAI call returning ratings for every doc in user_prompt.

    Args:
        client: An :class:`openai.AsyncOpenAI` instance pre-configured with
            ``api_key`` + ``base_url`` from :class:`Settings`.
        model: The exact pinned model id (e.g., ``"gpt-4o-2024-08-06"``).
            CLAUDE.md Rule #8 — never hardcode model names; the caller pulls
            from :attr:`Settings.openai_model`.
        system_prompt: The bundle's ``system_prompt`` (FR-3c rubric is in the
            user prompt, not here — the system prompt only describes the role).
        user_prompt: The rendered Jinja user message produced by
            :func:`backend.app.llm.prompt_loader.render_user_prompt`.
        expected_doc_ids: Allowlist of doc ids the worker submitted to the
            template. Returned ratings whose ``doc_id`` is not in this set are
            dropped with a WARN log; absent ids are logged at WARN. Per
            GPT-5.5 cycle 1 F9 — without this, an OpenAI hallucination of a
            doc id would slip into the ``judgments`` rows.
        max_retries: Total attempt count INCLUDING the first. ``max_retries=3``
            → up to 3 attempts → up to 2 retries.

    Returns:
        :class:`JudgeCallResult` containing only validated ratings.

    Raises:
        openai.OpenAIError: All attempts exhausted with retryable errors.
        json.JSONDecodeError: Final attempt returned non-JSON content (rare
            given ``strict=True`` schema enforcement).
        UnknownModelPricingError: ``model`` has no pricing entry. This is a
            programmer error — the API preflight catches it long before this
            function runs.
    """
    started = time.monotonic()
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "judgment_ratings",
                        "schema": RATING_RESPONSE_SCHEMA,
                        "strict": True,
                    },
                },
            )
        except (openai.RateLimitError, openai.APITimeoutError) as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = _backoff_seconds(attempt)
            logger.warning(
                "OpenAI judge: retryable error, backing off",
                attempt=attempt,
                max_retries=max_retries,
                wait_seconds=wait,
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(wait)
            continue
        except openai.APIStatusError as exc:
            # 5xx is retryable; 4xx is not.
            if 500 <= exc.status_code < 600:
                last_exc = exc
                if attempt >= max_retries:
                    break
                wait = _backoff_seconds(attempt)
                logger.warning(
                    "OpenAI judge: upstream 5xx, backing off",
                    attempt=attempt,
                    max_retries=max_retries,
                    wait_seconds=wait,
                    status_code=exc.status_code,
                )
                await asyncio.sleep(wait)
                continue
            raise

        # Parse the structured-output JSON content. With ``strict=True`` the
        # API enforces schema conformance but the SDK still returns a string;
        # we json.loads it ourselves so a malformed payload surfaces as a
        # retryable failure rather than a downstream KeyError.
        content = response.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = _backoff_seconds(attempt)
            logger.warning(
                "OpenAI judge: malformed JSON from upstream, retrying",
                attempt=attempt,
                max_retries=max_retries,
                wait_seconds=wait,
            )
            await asyncio.sleep(wait)
            continue

        # Schema validation BEFORE iterating. OpenAI's strict=True enforces
        # the schema at the API level, but local OpenAI-compatible endpoints
        # (Ollama / LM Studio / vLLM / TGI) may not honor it. A payload like
        # ``{"ratings": {"doc_id":"d1"}}`` (object instead of array) would
        # crash the iteration with AttributeError otherwise (per GPT-5.5
        # cycle-3 C3-F2). Treat schema violations the same as malformed JSON
        # — retryable.
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ratings"), list):
            last_exc = ValueError("response does not match RATING_RESPONSE_SCHEMA")
            if attempt >= max_retries:
                break
            wait = _backoff_seconds(attempt)
            logger.warning(
                "OpenAI judge: response shape violates schema, retrying",
                attempt=attempt,
                max_retries=max_retries,
                wait_seconds=wait,
            )
            await asyncio.sleep(wait)
            continue

        # Validate + filter ratings against the doc-id allowlist.
        raw_ratings = parsed["ratings"]
        validated: list[DocRating] = []
        returned_ids: set[str] = set()
        for item in raw_ratings:
            if not isinstance(item, dict):
                logger.warning(
                    "OpenAI judge: dropping non-dict ratings item",
                    item_type=type(item).__name__,
                )
                continue
            doc_id = item.get("doc_id")
            rating = item.get("rating")
            rationale = item.get("rationale")
            if doc_id not in expected_doc_ids:
                logger.warning(
                    "OpenAI judge: dropping spurious doc_id not in expected set",
                    doc_id=doc_id,
                )
                continue
            # ``rationale`` is a required field per RATING_RESPONSE_SCHEMA.
            # Local OpenAI-compatible endpoints may ignore strict=True; reject
            # items missing rationale rather than silently substituting "" so
            # the worker's all-or-nothing set-equality check causes a retry
            # (per GPT-5.5 cycle-4 C4-F2).
            if not isinstance(rationale, str):
                logger.warning(
                    "OpenAI judge: dropping item missing required rationale",
                    doc_id=doc_id,
                )
                continue
            if not isinstance(rating, int) or not (0 <= rating <= 3):
                logger.warning(
                    "OpenAI judge: dropping out-of-range rating",
                    doc_id=doc_id,
                    rating=rating,
                )
                continue
            validated.append(DocRating(doc_id=doc_id, rating=rating, rationale=rationale))
            returned_ids.add(doc_id)

        missing = expected_doc_ids - returned_ids
        if missing:
            logger.warning(
                "OpenAI judge: response missing expected doc_ids",
                missing_count=len(missing),
                missing_sample=sorted(missing)[:5],
            )

        usage = response.usage
        input_tokens = int(usage.prompt_tokens) if usage else 0
        output_tokens = int(usage.completion_tokens) if usage else 0
        cost_usd = compute_call_cost(model, input_tokens, output_tokens)
        duration_ms = int((time.monotonic() - started) * 1000)

        return JudgeCallResult(
            ratings=validated,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            model=model,
        )

    # All attempts exhausted — the loop only `break`s after assigning ``last_exc``,
    # so the None case is unreachable, but be defensive for the type checker.
    if last_exc is None:  # pragma: no cover — unreachable
        raise RuntimeError("rate_query_batch exhausted retries with no captured error")
    raise last_exc
