"""``SignalsConverter`` Protocol + three concrete converters (feat_ubi_judgments Story 1.2 / FR-2).

Async Protocol (cycle-3 fix D-10e) so the worker can call
``await converter.convert(...)`` uniformly across all three concrete
implementations. The two pure-UBI converters
(:class:`CtrThresholdConverter`, :class:`DwellTimeThresholdConverter`)
trivially conform — they ``return`` without awaiting anything. The
hybrid converter awaits the injected ``llm_rate`` callback for
below-threshold pairs.

**Anti-pattern guard:** None of these classes instantiates
``openai.AsyncClient`` or otherwise constructs an LLM client. The
hybrid converter receives ``llm_rate`` as a constructor argument and
calls it; the caller (worker, Story 3.3) builds the callback by
wrapping ``rate_query_batch`` from
:mod:`backend.app.llm.openai_judge` so the daily-budget gate +
capability cache fire unchanged. This preserves CLAUDE.md Absolute
Rules #3 / #8 / #10 — every LLM call goes through the shared client +
``Settings.openai_model``, never a freshly-constructed one inside
domain code. An ast-based test at
``backend/tests/unit/domain/ubi/test_converter_no_openai_import.py``
fails the suite if ``openai`` ever lands in this module's import set.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from backend.app.domain.ubi.features import FeatureVec

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_CTR_DEFAULTS: dict[int, float] = {1: 0.05, 2: 0.15, 3: 0.30}
"""Position-bias-corrected CTR thresholds that map to ratings 1, 2, 3.

A pair below the rung-1 threshold (default 0.05) is rated 0.

Rationale: ~5% corrected CTR is the "barely clicked-on-occasionally"
signal floor; 30% is the "users find this consistently" signal ceiling
for e-commerce-shaped UBI corpora. These match the spec FR-2 defaults
and are operator-overridable via ``ConverterConfig.extra['thresholds']``."""

_DWELL_DEFAULTS: dict[int, float] = {1: 10.0, 2: 30.0, 3: 90.0}
"""Mean post-click dwell-time thresholds (seconds) that map to ratings 1, 2, 3.

A pair below the rung-1 threshold (default 10s) is rated 0. Best for
content-discovery surfaces where dwell-after-click separates
scan-and-bounce from genuine engagement."""

_HYBRID_LLM_FILL_THRESHOLD_DEFAULT = 20
"""Per-pair impression-count threshold for the hybrid converter's UBI/LLM split.

Pairs with ``impression_count >= 20`` get a UBI rating from the inner
converter (CTR or dwell); pairs below get an LLM-fill call. Matches
spec FR-2 + the idea recommendation."""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


LlmRateCallback = Callable[
    [list[tuple[str, str, str]]],
    Awaitable[dict[tuple[str, str], int]],
]
"""Type of the callback the hybrid converter awaits for below-threshold pairs.

Input: ``[(query_id, doc_id, query_text), ...]`` — the worker pulls
``query_text`` from ``query_set.queries`` so the LLM call sees the
operator-facing text, not the engine-internal ``query_id``.

Output: ``{(query_id, doc_id): rating_int}`` — same key shape as the
inner converter so the hybrid result merges cleanly. Ratings ∈
``{0, 1, 2, 3}`` (enforced by the caller; the converter does not
re-validate).

The worker constructs the callback by binding ``rate_query_batch`` +
the daily-budget gate; the converter knows nothing about OpenAI. See
the CLAUDE.md Absolute Rules anti-pattern guard above the module
docstring."""


class ConverterConfig(BaseModel):
    """JSON-serializable converter config carried through the API.

    The new ``POST /api/v1/judgments/generate-from-ubi`` endpoint accepts
    an optional ``converter_config: dict[str, Any] | None`` field; that
    dict round-trips through Pydantic as ``ConverterConfig(extra=...)``
    so the worker can persist + reconstruct it without loss.

    Shape inside ``extra``:

    * ``thresholds`` (optional, CTR / dwell converters): ``{1: float,
      2: float, 3: float}`` overriding the per-converter defaults.
    * ``inner`` (optional, hybrid converter): ``'ctr_threshold' |
      'dwell_time'`` selecting which pure converter the hybrid wraps
      for above-threshold pairs (default ``'ctr_threshold'``).

    The schema is intentionally permissive — future converter additions
    in v1.5+ add new keys without a Pydantic-validator migration. The
    converters themselves read what they need and ignore the rest.
    """

    extra: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SignalsConverter(Protocol):
    """Async Protocol — maps :class:`FeatureVec` map → rating map.

    See module docstring for the async-rationale (cycle-3 fix D-10e).
    Implementations MUST return ratings strictly in ``{0, 1, 2, 3}``;
    the worker relies on the
    ``judgments_rating_check`` CHECK constraint catching any escape, but
    converters that emit out-of-range values would surface as
    ``IntegrityError`` mid-bulk-insert rather than clean errors. Keep
    the conversion correct at the source.
    """

    async def convert(
        self,
        features: dict[tuple[str, str], FeatureVec],
        config: ConverterConfig,
    ) -> dict[tuple[str, str], int]:
        """Map a :class:`FeatureVec` map to a per-pair rating in ``{0, 1, 2, 3}``."""
        ...


# ---------------------------------------------------------------------------
# Pure-UBI converters
# ---------------------------------------------------------------------------


def _resolve_thresholds(
    config: ConverterConfig,
    defaults: dict[int, float],
) -> dict[int, float]:
    """Read ``config.extra['thresholds']`` if present, else return defaults.

    Validates that the override dict has exactly the three required keys
    1, 2, 3 and that values are monotonically increasing. Falls back to
    defaults (with a structured ValueError) on malformed input — the
    worker catches the error and marks the list ``failed_reason=
    'INVALID_CONVERTER_CONFIG'`` rather than producing weird ratings.
    """
    raw = config.extra.get("thresholds")
    if raw is None:
        return defaults
    if not isinstance(raw, dict):
        raise ValueError(f"converter_config.thresholds must be a dict, got {type(raw).__name__}")
    parsed: dict[int, float] = {}
    for key, value in raw.items():
        try:
            rating = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"converter_config.thresholds key {key!r} is not an int") from exc
        if rating not in (1, 2, 3):
            raise ValueError(
                f"converter_config.thresholds key {rating!r} must be 1, 2, or 3 "
                "(rating 0 is implicit — below the rating-1 threshold)"
            )
        try:
            parsed[rating] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"converter_config.thresholds value for rating {rating} is not a number: {value!r}"
            ) from exc
    missing = {1, 2, 3} - set(parsed.keys())
    if missing:
        raise ValueError(
            f"converter_config.thresholds missing required keys {sorted(missing)}; "
            "all three of {1, 2, 3} must be present when overriding"
        )
    if not (parsed[1] < parsed[2] < parsed[3]):
        raise ValueError(
            "converter_config.thresholds must be strictly increasing "
            f"(got 1={parsed[1]}, 2={parsed[2]}, 3={parsed[3]})"
        )
    return parsed


def _threshold_rating(value: float, thresholds: dict[int, float]) -> int:
    """Map a scalar to the highest rating whose threshold the value crosses.

    ``thresholds[1]`` is the rung-1 cutoff; anything below earns rating 0.
    """
    if value < thresholds[1]:
        return 0
    if value < thresholds[2]:
        return 1
    if value < thresholds[3]:
        return 2
    return 3


class CtrThresholdConverter:
    """Pure UBI — position-bias-corrected CTR → 0/1/2/3.

    Async conformance only (no awaits); satisfies the
    :class:`SignalsConverter` Protocol so the worker can treat all three
    converters uniformly. Default thresholds: ``{1: 0.05, 2: 0.15,
    3: 0.30}``.

    Pairs with ``impression_count == 0`` are dropped (no signal) — the
    worker treats absent pairs as "no judgment for this pair", same as
    LLM-only lists drop pairs the LLM declined to rate.
    """

    async def convert(
        self,
        features: dict[tuple[str, str], FeatureVec],
        config: ConverterConfig,
    ) -> dict[tuple[str, str], int]:
        """Map position-bias-corrected CTR → rating per the configured thresholds."""
        thresholds = _resolve_thresholds(config, _CTR_DEFAULTS)
        out: dict[tuple[str, str], int] = {}
        for pair, fvec in features.items():
            if fvec.impression_count == 0:
                continue
            out[pair] = _threshold_rating(fvec.corrected_ctr, thresholds)
        return out


class DwellTimeThresholdConverter:
    """Pure UBI — post-click dwell-time (seconds) → 0/1/2/3.

    Default thresholds: ``{1: 10.0, 2: 30.0, 3: 90.0}``. Pairs with
    ``dwell_mean_seconds is None`` (no dwell events emitted) are
    dropped — operators who don't emit dwell can't use this converter
    meaningfully; the worker surfaces the empty result.
    """

    async def convert(
        self,
        features: dict[tuple[str, str], FeatureVec],
        config: ConverterConfig,
    ) -> dict[tuple[str, str], int]:
        """Map mean post-click dwell-time → rating per the configured thresholds."""
        thresholds = _resolve_thresholds(config, _DWELL_DEFAULTS)
        out: dict[tuple[str, str], int] = {}
        for pair, fvec in features.items():
            if fvec.dwell_mean_seconds is None:
                continue
            out[pair] = _threshold_rating(fvec.dwell_mean_seconds, thresholds)
        return out


# ---------------------------------------------------------------------------
# Hybrid converter (UBI head + LLM tail)
# ---------------------------------------------------------------------------


_INNER_REGISTRY: dict[str, type[SignalsConverter]] = {
    "ctr_threshold": CtrThresholdConverter,
    "dwell_time": DwellTimeThresholdConverter,
}


class HybridUbiLlmConverter:
    """UBI head + LLM tail (feat_ubi_judgments FR-2).

    Splits the feature map at ``impression_count >= llm_fill_threshold``
    (default 20). Above-threshold pairs go to the inner pure-UBI
    converter (CTR by default; dwell when ``config.extra['inner'] ==
    'dwell_time'``). Below-threshold pairs are deferred to the
    injected async ``llm_rate`` callback — the worker constructs the
    callback by wrapping ``rate_query_batch`` from
    :mod:`backend.app.llm.openai_judge` so the budget gate + capability
    cache fire on every LLM-fill call.

    The hybrid converter does NOT need ``query_text`` in
    :class:`FeatureVec`; the caller (worker) supplies the
    ``(query_id, doc_id, query_text)`` tuples to ``llm_rate`` from its
    own per-query loop.

    Pairs with ``impression_count == 0`` are routed to ``llm_rate``
    (zero impressions means zero confidence in UBI signal even if the
    threshold is set very low). This matches the spec's "hybrid covers
    the long tail" framing.
    """

    def __init__(
        self,
        *,
        inner: SignalsConverter,
        llm_rate: LlmRateCallback,
        query_text_lookup: Callable[[str], str],
    ) -> None:
        """Construct a hybrid converter.

        Args:
            inner: the pure-UBI converter wrapped for above-threshold pairs.
            llm_rate: async callback the worker supplies; closes over
                ``rate_query_batch`` + the daily-budget gate + the
                AsyncOpenAI client. The converter does NOT construct any
                of these; see the anti-pattern guard in the module docstring.
            query_text_lookup: synchronous resolver ``query_id -> query_text``
                so the converter can build the ``llm_rate`` payload from
                feature keys alone. The worker passes a closure over the
                ``query_set.queries`` rows it already loaded.
        """
        self._inner = inner
        self._llm_rate = llm_rate
        self._lookup_query_text = query_text_lookup

    @staticmethod
    def build_inner(
        kind: Literal["ctr_threshold", "dwell_time"],
    ) -> SignalsConverter:
        """Factory for the inner converter when the worker is constructing a hybrid.

        Resolves ``ctr_threshold`` → :class:`CtrThresholdConverter`,
        ``dwell_time`` → :class:`DwellTimeThresholdConverter`. Raises
        ``ValueError`` on any other kind (defensive — the spec locks
        the wire enum to these two for inner, and the request validator
        in :mod:`backend.app.api.v1.schemas` already filters, but a
        local check makes the converter resilient to a refactor that
        widens the request enum without updating this map).
        """
        try:
            cls = _INNER_REGISTRY[kind]
        except KeyError as exc:
            raise ValueError(
                f"unknown hybrid inner converter kind {kind!r}; "
                f"supported: {sorted(_INNER_REGISTRY.keys())}"
            ) from exc
        return cls()

    async def convert(
        self,
        features: dict[tuple[str, str], FeatureVec],
        config: ConverterConfig,
    ) -> dict[tuple[str, str], int]:
        """Split head/tail at ``llm_fill_threshold``; await ``llm_rate`` only for the tail."""
        threshold_raw = config.extra.get("llm_fill_threshold", _HYBRID_LLM_FILL_THRESHOLD_DEFAULT)
        try:
            threshold = int(threshold_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"converter_config.llm_fill_threshold must be an int, got {threshold_raw!r}"
            ) from exc
        if threshold < 1:
            raise ValueError(f"converter_config.llm_fill_threshold must be >= 1, got {threshold}")

        head_pairs: dict[tuple[str, str], FeatureVec] = {}
        tail_pairs: dict[tuple[str, str], FeatureVec] = {}
        for pair, fvec in features.items():
            if fvec.impression_count >= threshold:
                head_pairs[pair] = fvec
            else:
                tail_pairs[pair] = fvec

        head_ratings = await self._inner.convert(head_pairs, config)

        if tail_pairs:
            tail_payload = [
                (query_id, doc_id, self._lookup_query_text(query_id))
                for query_id, doc_id in tail_pairs
            ]
            tail_ratings = await self._llm_rate(tail_payload)
        else:
            tail_ratings = {}

        # Head wins on collision — impossible by construction (head + tail
        # partition the input) but explicit so a future refactor that breaks
        # the partition surfaces as a wrong-but-consistent rating, not a
        # silent drop.
        merged: dict[tuple[str, str], int] = dict(tail_ratings)
        merged.update(head_ratings)
        return merged
