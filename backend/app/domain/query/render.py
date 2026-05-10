"""Pure Jinja → JSON renderer for query templates (Story 2.4).

The template body is Jinja2 source whose evaluated output must be a JSON
object (the engine-native query body). Missing parameters surface loudly
via ``StrictUndefined`` — the adapter catches the resulting Jinja error and
re-raises as ``ValueError`` for the caller.

Living in ``backend.app.domain`` per CLAUDE.md "Domain Layer": no I/O, no
async, deterministic. Easy to unit-test without fixtures.
"""

from __future__ import annotations

import json
from typing import Any

from jinja2 import StrictUndefined, Template


def render_template(template_body: str, context: dict[str, Any]) -> dict[str, Any]:
    """Render ``template_body`` with ``context``; return the JSON-decoded result.

    Raises:
        jinja2.UndefinedError: when the template references a parameter that
            is not present in ``context`` (the caller translates to
            ``ValueError``).
        json.JSONDecodeError: when the rendered string is not a valid JSON
            object.
    """
    rendered = Template(template_body, undefined=StrictUndefined).render(**context)
    parsed = json.loads(rendered)
    if not isinstance(parsed, dict):
        raise ValueError(f"render_template: expected a JSON object, got {type(parsed).__name__}")
    return parsed
