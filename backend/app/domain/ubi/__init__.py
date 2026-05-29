"""``domain/ubi/`` — pure-domain UBI library (feat_ubi_judgments Story 1.2).

This package implements the engine-neutral User Behavior Insights (UBI)
substrate that powers click-derived judgment lists. It is **pure-domain**:
no DB access, no HTTP, no LLM client construction. The hybrid converter
accepts an *injected* async callback (``llm_rate``) so the I/O-bound
LLM-fill calls live in the worker, not the converter.

**Async-Protocol exception to the "domain is synchronous" rule.** The
parent ``backend.app.domain`` package docstring states "every module
here is synchronous and deterministic." This module breaks that rule
deliberately: :class:`SignalsConverter.convert` is async because the
hybrid converter awaits an injected LLM callback for below-threshold
pairs. Keeping the Protocol async lets the worker treat all three
concrete converters uniformly (``await converter.convert(...)``)
without branching on kind. The pure-UBI converters
(:class:`CtrThresholdConverter`, :class:`DwellTimeThresholdConverter`)
are trivially async — they ``return`` without awaiting anything. The
"no I/O" rule still holds at the module boundary: the I/O is in the
caller-supplied callback, not in the converter code path.

Exports:

* :class:`FeatureVec` — Pydantic per-(query, doc) feature vector
* :func:`aggregate_features` — pure aggregation of raw UBI events
  into per-pair :class:`FeatureVec`
* :class:`SignalsConverter` — async Protocol; ratings out of
  ``{0, 1, 2, 3}``
* :class:`CtrThresholdConverter` — position-bias-corrected CTR →
  rating (pure UBI)
* :class:`DwellTimeThresholdConverter` — dwell-time → rating
  (pure UBI)
* :class:`HybridUbiLlmConverter` — UBI head + LLM tail; awaits
  the injected ``llm_rate`` callback for below-threshold pairs
* :class:`ConverterConfig` — JSON-serializable converter config
* :func:`load_position_bias_prior` — loads the optional
  operator-supplied Wang-Bendersky position-bias prior
"""

from __future__ import annotations

from backend.app.domain.ubi.converter import (
    ConverterConfig,
    CtrThresholdConverter,
    DwellTimeThresholdConverter,
    HybridUbiLlmConverter,
    LlmRateCallback,
    SignalsConverter,
)
from backend.app.domain.ubi.features import FeatureVec, aggregate_features
from backend.app.domain.ubi.position_bias_prior import load_position_bias_prior

__all__ = [
    "ConverterConfig",
    "CtrThresholdConverter",
    "DwellTimeThresholdConverter",
    "FeatureVec",
    "HybridUbiLlmConverter",
    "LlmRateCallback",
    "SignalsConverter",
    "aggregate_features",
    "load_position_bias_prior",
]
