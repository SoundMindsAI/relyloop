"""Default-value picker for query-template params (feat_digest_proposal Story 2.1).

Originally inlined as ``_compute_default_params`` in
:mod:`backend.workers.judgments` (feat_llm_judgments Story 2.1, GPT-5.5
cycle 2 F2). Lifted here in feat_digest_proposal so both the judgments
worker AND the digest worker can compute the same per-param defaults
without duplicating the policy.

Pure-Python; no DB; no async — consumed by both worker jobs.

Policy (per the original feat_llm_judgments cycle 2 F2 adjudication —
the spec said "default params" but didn't enumerate the policy):

* numeric ranges → midpoint of [min, max]
* booleans → ``False``
* categoricals → first listed value
* anything else (missing / malformed schema entry) → leave the param
  absent so the template's own ``{% if ... %}`` fallback kicks in
"""

from __future__ import annotations

from typing import Any, cast


def compute_default_params(template_row: Any) -> dict[str, Any]:
    """Pick safe default values for a template's declared params.

    Args:
        template_row: a :class:`backend.app.db.models.query_template.QueryTemplate`
            row (or any object exposing a ``declared_params`` attribute as
            a JSONB-shaped dict). Each entry is shaped like:

            .. code-block:: json

                {"bm25_k1": {"type": "float", "min": 0.5, "max": 2.5},
                 "use_phrase": {"type": "bool"},
                 "operator": {"type": "categorical", "values": ["AND", "OR"]}}

    Returns:
        ``{param_name: default_value}`` for every declared param the
        policy can default. Missing / malformed schema entries are
        omitted so the template's own fallback applies.
    """
    declared: dict[str, Any] = cast(dict[str, Any], template_row.declared_params) or {}
    params: dict[str, Any] = {}
    for name, schema in declared.items():
        if not isinstance(schema, dict):
            continue
        kind = schema.get("type")
        if kind == "int":
            lo = schema.get("min")
            hi = schema.get("max")
            if isinstance(lo, int) and isinstance(hi, int):
                params[name] = (lo + hi) // 2
        elif kind == "float":
            lo = schema.get("min")
            hi = schema.get("max")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                params[name] = (float(lo) + float(hi)) / 2.0
        elif kind == "bool":
            params[name] = False
        elif kind == "categorical":
            values = schema.get("values")
            if isinstance(values, list) and values:
                params[name] = values[0]
    return params


__all__ = ["compute_default_params"]
