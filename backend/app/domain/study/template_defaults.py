"""Default-value picker for query-template params (feat_digest_proposal Story 2.1).

Originally inlined as ``_compute_default_params`` in
:mod:`backend.workers.judgments` (feat_llm_judgments Story 2.1, GPT-5.5
cycle 2 F2). Lifted here in feat_digest_proposal so both the judgments
worker AND the digest worker can compute the same per-param defaults
without duplicating the policy.

Pure-Python; no DB; no async — consumed by both worker jobs.

Two ``declared_params`` shapes are supported because the
``query_templates`` API stores the simple form (``dict[str, str]``
where each value is a type-name) while internal callers and tests
sometimes carry the rich form (``dict[str, dict[str, Any]]`` with
min/max/values). The rich form yields midpoints / first-categorical;
the simple form yields per-type fallback defaults.

Policy:

* Rich-form numeric ranges → midpoint of [min, max]
* Rich-form ``bool`` → ``False``
* Rich-form ``categorical`` → first listed value
* Simple-form (``"int"`` / ``"float"`` / ``"bool"`` / ``"string"``)
  → per-type fallback (see ``_SIMPLE_FORM_DEFAULTS``)
* Anything else (malformed entry, unknown type) → leave the param
  absent so the template's own ``{% if ... %}`` fallback kicks in.
"""

from __future__ import annotations

from typing import Any, cast

# Per-type fallback values used when ``declared_params`` is stored in
# the API's simple form (``{"foo": "float"}``) and so carries no range
# / categorical metadata. These match the values most query templates
# tolerate as a "neutral" pass — boost factors of 1.0, false flags,
# empty filter strings. Without this fallback, every API-created
# template that declares any optimization params would fail
# ``adapter.render`` with ``missing required template params``
# (bug_judgment_template_default_params_contract).
_SIMPLE_FORM_DEFAULTS: dict[str, Any] = {
    "int": 1,
    "float": 1.0,
    "bool": False,
    "string": "",
}


def compute_default_params(template_row: Any) -> dict[str, Any]:
    """Pick safe default values for a template's declared params.

    Args:
        template_row: a :class:`backend.app.db.models.query_template.QueryTemplate`
            row (or any object exposing a ``declared_params`` attribute as
            a JSONB-shaped dict). Two shapes are accepted:

            **Rich form** (internal callers, fixture-built rows):

            .. code-block:: json

                {"bm25_k1": {"type": "float", "min": 0.5, "max": 2.5},
                 "use_phrase": {"type": "bool"},
                 "operator": {"type": "categorical", "values": ["AND", "OR"]}}

            **Simple form** (API-stored — ``POST /api/v1/query-templates``
            accepts ``declared_params: dict[str, str]``):

            .. code-block:: json

                {"title_boost": "float", "use_phrase": "bool"}

    Returns:
        ``{param_name: default_value}`` for every declared param the
        policy can default. Malformed / unknown-type entries are
        omitted so the template's own fallback applies.
    """
    declared: dict[str, Any] = cast(dict[str, Any], template_row.declared_params) or {}
    params: dict[str, Any] = {}
    for name, schema in declared.items():
        if isinstance(schema, str):
            # Simple form: type-name string. API-stored templates always
            # land here.
            if schema in _SIMPLE_FORM_DEFAULTS:
                params[name] = _SIMPLE_FORM_DEFAULTS[schema]
            continue
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
