"""``backend.app.domain.query.render`` unit tests (Story 2.4).

Pure-function tests of the Jinja-to-dict rendering path. The adapter-level
contract (param-validation + error wrapping) is tested separately in
``test_elastic_render.py``.
"""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from backend.app.domain.query.render import render_template


def test_renders_simple_template() -> None:
    rendered = render_template(
        '{"query": {"match": {"title": "{{ query_text }}"}}}',
        {"query_text": "shoes"},
    )
    assert rendered == {"query": {"match": {"title": "shoes"}}}


def test_strict_undefined_raises() -> None:
    with pytest.raises(UndefinedError):
        render_template(
            '{"query": {"match": {"title": "{{ missing }}"}}}',
            {},
        )


def test_non_object_output_raises() -> None:
    with pytest.raises(ValueError, match="expected a JSON object"):
        render_template('"just a string"', {})


def test_invalid_json_raises_json_error() -> None:
    import json

    with pytest.raises(json.JSONDecodeError):
        render_template("{not: valid json}", {})


def test_field_boost_template() -> None:
    """Canonical multi_match template with field_boosts."""
    body = (
        '{"query": {"multi_match": {"query": "{{ query_text }}", '
        '"fields": [{% for f in field_boosts %}'
        '"{{ f.name }}^{{ f.boost }}"{% if not loop.last %},{% endif %}'
        "{% endfor %}]}}}"
    )
    rendered = render_template(
        body,
        {
            "query_text": "shoes",
            "field_boosts": [
                {"name": "title", "boost": 2.0},
                {"name": "description", "boost": 1.0},
            ],
        },
    )
    assert rendered == {
        "query": {
            "multi_match": {
                "query": "shoes",
                "fields": ["title^2.0", "description^1.0"],
            }
        }
    }
