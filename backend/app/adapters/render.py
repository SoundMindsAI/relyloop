# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared Jinja query-template rendering for search-engine adapters."""

from __future__ import annotations

from typing import Any

from backend.app.adapters.protocol import ParamValue, QueryTemplate
from backend.app.domain.query.render import render_template
from backend.app.domain.study.normalizers import (
    DEFAULT_NORMALIZER,
    normalize_pipeline,
    steps_for_label,
)


def render_template_to_dict(
    template: QueryTemplate,
    params: dict[str, ParamValue],
    query_text: str,
) -> dict[str, Any]:
    """Pre-render hook shared by every engine adapter's ``render``.

    Pops the reserved ``query_normalizer`` off a LOCAL copy of ``params``
    (never mutating the caller's dict) and applies it to ``query_text``
    before the Jinja context is built. The value is either a Phase-1 bundle
    string OR a typed-pipeline powerset label
    (feat_query_normalizer_typed_pipeline Story 1.4); both resolve through
    ``steps_for_label`` -> ``normalize_pipeline``, so a winning non-bundle
    label (e.g. ``"lowercase+strip_punctuation"``) applies correctly instead
    of raising. The default ``"none"`` is a verbatim pass-through.

    Validates that every declared param is supplied (``query_normalizer`` is
    excluded — it is consumed here, never present in the render context),
    then renders the template body to the JSON-decoded dict.

    Each adapter performs its own engine-specific post-processing on the
    returned dict (Elastic returns it as the query body verbatim; Solr runs
    the LTR pre-flight + pivots unified keys to Solr request params).

    Raises:
        ValueError: when ``query_normalizer`` is a non-str (only reachable via
            a direct DB mutation; FR-2 guarantees a str on the create path),
            when required template params are missing, or when the Jinja
            render fails (``StrictUndefined`` surfaces as ``UndefinedError``,
            wrapped here so the service / API translate to one error code).
    """
    from jinja2 import UndefinedError

    local_params = dict(params)
    choice = local_params.pop("query_normalizer", DEFAULT_NORMALIZER)
    if not isinstance(choice, str):
        raise ValueError(f"unknown normalizer: {choice!r}")
    normalized_query_text = normalize_pipeline(query_text, steps_for_label(choice))

    missing = set(template.declared_params) - set(local_params.keys()) - {"query_normalizer"}
    if missing:
        raise ValueError(f"render: missing required template params: {sorted(missing)}")

    context: dict[str, Any] = {**local_params, "query_text": normalized_query_text}
    try:
        return render_template(template.body, context)
    except UndefinedError as exc:
        raise ValueError(f"render: undefined parameter — {exc}") from exc
