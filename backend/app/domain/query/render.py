"""Pure Jinja → JSON renderer for query templates.

Story 2.4 of infra_adapter_elastic established this; feat_study_lifecycle
Phase 2 Story 1.2 swapped the underlying Environment to
``SandboxedEnvironment``.

The template body is Jinja2 source whose evaluated output must be a JSON
object (the engine-native query body). Missing parameters surface loudly
via ``StrictUndefined``. **Rendering uses ``SandboxedEnvironment``** so a
template stored before Phase 2's create-time validator existed (or that
slipped past it via a future regression) cannot escape the sandbox at
runtime — defense-in-depth per spec §10 Threat 3.

The create-time validator lives in
``backend.app.domain.study.template_validator`` (Story 1.2); both share
the same ``SandboxedEnvironment``-based attribute / call restrictions.

Living in ``backend.app.domain`` per CLAUDE.md "Domain Layer": no I/O, no
async, deterministic. Easy to unit-test without fixtures.
"""

from __future__ import annotations

import json
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

_SANDBOX_ENV = SandboxedEnvironment(undefined=StrictUndefined)
"""Module-level sandboxed environment. The validator
(:mod:`backend.app.domain.study.template_validator`) uses its own
sandbox instance for parse-time AST inspection; this one is for runtime
rendering. Both share the same sandbox semantics (forbid attribute
access on built-ins, forbid dunder access, etc.)."""


def render_template(template_body: str, context: dict[str, Any]) -> dict[str, Any]:
    """Render ``template_body`` with ``context``; return the JSON-decoded result.

    Raises:
        jinja2.UndefinedError: when the template references a parameter that
            is not present in ``context`` (the caller translates to
            ``ValueError``).
        jinja2.SecurityError: when a sandbox restriction fires at render
            time (e.g. attribute access that slipped past the create-time
            validator).
        json.JSONDecodeError: when the rendered string is not a valid JSON
            object.
    """
    rendered = _SANDBOX_ENV.from_string(template_body).render(**context)
    parsed = json.loads(rendered)
    if not isinstance(parsed, dict):
        raise ValueError(f"render_template: expected a JSON object, got {type(parsed).__name__}")
    return parsed
