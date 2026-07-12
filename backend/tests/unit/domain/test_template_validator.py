# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``backend.app.domain.study.template_validator`` unit tests (Story 1.2).

Covers the three validation stages:

1. Jinja parse errors → :exc:`InvalidTemplateSyntax`.
2. AST walk rejecting Call / Getattr / dunder-name references →
   :exc:`InvalidTemplateSyntax` (AC-7 + C2-F6 cycle-2).
3. Declared/undeclared cross-check → :exc:`UndeclaredParamUsed` /
   :exc:`DeclaredParamUnused`.

The AC-7 test is the critical one: without the AST walk, the validator
would surface ``{{ os.system(...) }}`` as ``UndeclaredParamUsed("os")``
because ``os`` isn't in ``declared_params`` — the AC explicitly requires
``INVALID_TEMPLATE_SYNTAX``.
"""

from __future__ import annotations

import pytest

from backend.app.domain.study.template_validator import (
    DeclaredParamUnused,
    InvalidTemplateSyntax,
    UndeclaredParamUsed,
    UnsafeQueryTextInterpolation,
    validate_template_body,
)

# AC-7: sandbox-illegal expressions must surface as InvalidTemplateSyntax
# regardless of whether the offending identifier is in declared_params.


def test_ac7_os_system_call_rejected() -> None:
    with pytest.raises(InvalidTemplateSyntax, match="call expression"):
        validate_template_body("{{ os.system('rm -rf /') }}", {})


def test_dunder_class_access_rejected() -> None:
    with pytest.raises(InvalidTemplateSyntax, match="attribute access"):
        validate_template_body('{{ "".__class__ }}', {})


def test_method_call_rejected_even_when_object_declared() -> None:
    """Function/method calls are forbidden even if the object IS declared.

    Sandbox forbids invocation in query templates regardless of whether
    the receiver is a declared param.
    """
    with pytest.raises(InvalidTemplateSyntax, match="call expression"):
        validate_template_body("{{ obj.method() }}", {"obj": "string"})


def test_dunder_name_reference_rejected_even_when_declared() -> None:
    """C2-F6 cycle-2: any ``_``-prefixed name is rejected at AST level."""
    with pytest.raises(InvalidTemplateSyntax, match="dunder/private name"):
        validate_template_body("{{ _secret }}", {"_secret": "string"})


def test_syntactic_error_rejected() -> None:
    with pytest.raises(InvalidTemplateSyntax, match="parse error"):
        validate_template_body("{% for x %}", {})


# Declared / undeclared cross-check


def test_undeclared_param_used() -> None:
    with pytest.raises(UndeclaredParamUsed, match="foo"):
        validate_template_body('{"x": "{{ foo }}"}', {})


def test_declared_param_unused() -> None:
    with pytest.raises(DeclaredParamUnused, match="bar"):
        validate_template_body('{"x": {{ query_text | tojson }}}', {"bar": "string"})


def test_implicit_query_text_does_not_need_declaration() -> None:
    """``query_text`` is implicit — every template renders against it."""
    validate_template_body('{"x": {{ query_text | tojson }}}', {})


# query_text injection guard — raw interpolation is rejected, `| tojson` passes.


def test_raw_query_text_rejected() -> None:
    """A raw ``{{ query_text }}`` inside a JSON string is an injection vector."""
    with pytest.raises(UnsafeQueryTextInterpolation, match="tojson"):
        validate_template_body('{"query": "{{ query_text }}"}', {})


def test_query_text_with_non_tojson_filter_rejected() -> None:
    """A filter chain that doesn't end in ``tojson`` is still unsafe."""
    with pytest.raises(UnsafeQueryTextInterpolation, match="tojson"):
        validate_template_body('{"query": "{{ query_text | upper }}"}', {})


def test_query_text_tojson_accepted() -> None:
    validate_template_body('{"query": {{ query_text | tojson }}}', {})


def test_query_text_chained_then_tojson_accepted() -> None:
    validate_template_body('{"query": {{ query_text | trim | tojson }}}', {})


# Happy paths


def test_happy_path_with_declared_param() -> None:
    validate_template_body(
        '{"query": {"match": {"title": {{ query_text | tojson }}, "boost": {{ boost }}}}}',
        {"boost": "float"},
    )


def test_happy_path_no_params_no_declarations() -> None:
    """A static template body is valid (e.g. `{}` for a match-all)."""
    validate_template_body('{"query": {"match_all": {}}}', {})


def test_multiple_declared_params_all_used() -> None:
    validate_template_body(
        '{"q": {{ query_text | tojson }}, "b": {{ boost }}, "k": {{ k }}}',
        {"boost": "float", "k": "int"},
    )
