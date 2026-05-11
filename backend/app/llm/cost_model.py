"""Token → USD cost helper for judgment generation (feat_llm_judgments Story 1.4).

A small, hand-maintained dict of OpenAI model pricing. New models added here
become eligible as ``OPENAI_MODEL``; an unrecognized model fails closed via
:class:`UnknownModelPricingError` so the daily budget gate cannot be silently
defeated (per GPT-5.5 cycle 2 F4 adjudication — returning 0.0 + a WARN log was
not enough: the worker would happily run unmetered with no operator signal).

Both the API preflight (``POST /api/v1/judgments/generate``) and the worker
job (``backend/workers/judgments.py``) consult this module:

* :func:`compute_call_cost` — exact post-call USD given measured tokens.
* :func:`estimated_max_call_cost` — pre-call ceiling used by the budget peek
  to decide whether the next call is allowed.
"""

from __future__ import annotations

# Module-level dict — single source of truth for known MVP1 model pricing.
# Prices are USD per 1K tokens.
_MODEL_USD_PER_1K_INPUT: dict[str, float] = {
    "gpt-4o-2024-08-06": 0.0025,
    "gpt-4o-mini-2024-07-18": 0.00015,
}

_MODEL_USD_PER_1K_OUTPUT: dict[str, float] = {
    "gpt-4o-2024-08-06": 0.01,
    "gpt-4o-mini-2024-07-18": 0.0006,
}

# Conservative per-call token ceilings used by :func:`estimated_max_call_cost`.
# Sized to comfortably cover a 50-doc batch (~5K input + ~2K output observed
# during cassette recording; round up for headroom).
_INPUT_TOKEN_CEILING = 10_000
_OUTPUT_TOKEN_CEILING = 2_000


class UnknownModelPricingError(RuntimeError):
    """Configured model has no entry in :data:`_MODEL_USD_PER_1K_INPUT`.

    Raised by :func:`compute_call_cost` and :func:`estimated_max_call_cost`.
    Per GPT-5.5 cycle 2 F4 the budget gate cannot be defeated by an
    unrecognized model — operators MUST add the model to the table here
    before pointing ``Settings.openai_model`` at it. The API preflight
    translates this to HTTP 503 ``UNKNOWN_MODEL_PRICING`` so the failure
    is operator-visible BEFORE any LLM call.
    """


def known_models() -> frozenset[str]:
    """Set of models with both input and output pricing entries.

    Used by the API preflight to assert ``Settings.openai_model`` is priced
    before the row is inserted (per Story 3.1 preflight B.1).
    """
    return frozenset(_MODEL_USD_PER_1K_INPUT) & frozenset(_MODEL_USD_PER_1K_OUTPUT)


def compute_call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for one OpenAI chat-completions call.

    Args:
        model: Pinned model identifier (e.g., ``"gpt-4o-2024-08-06"``). Must be
            present in :data:`_MODEL_USD_PER_1K_INPUT` AND
            :data:`_MODEL_USD_PER_1K_OUTPUT`.
        input_tokens: ``response.usage.prompt_tokens`` from the OpenAI response.
        output_tokens: ``response.usage.completion_tokens``.

    Raises:
        UnknownModelPricingError: ``model`` has no entry in either pricing
            dict. The caller is expected to translate this to a user-visible
            error (HTTP 503 ``UNKNOWN_MODEL_PRICING`` at the API, terminal
            ``failed_reason='UNKNOWN_MODEL_PRICING'`` at the worker).
    """
    try:
        in_rate = _MODEL_USD_PER_1K_INPUT[model]
        out_rate = _MODEL_USD_PER_1K_OUTPUT[model]
    except KeyError as exc:
        raise UnknownModelPricingError(
            f"model {model!r} has no entry in cost_model._MODEL_USD_PER_1K_INPUT/OUTPUT; "
            "add it before pointing OPENAI_MODEL at this value"
        ) from exc
    return (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate


def estimated_max_call_cost(model: str) -> float:
    """Return a conservative per-call cost ceiling for the pre-call budget peek.

    Computed from :data:`_INPUT_TOKEN_CEILING` + :data:`_OUTPUT_TOKEN_CEILING`
    at the model's price points so a 50-doc batch is guaranteed to fit under
    this estimate. Used by the worker's pre-LLM budget check (per spec FR-2
    "MUST check the daily OpenAI budget before each LLM call"; GPT-5.5
    cycle 1 F8) and by the API preflight peek.
    """
    return compute_call_cost(model, _INPUT_TOKEN_CEILING, _OUTPUT_TOKEN_CEILING)
