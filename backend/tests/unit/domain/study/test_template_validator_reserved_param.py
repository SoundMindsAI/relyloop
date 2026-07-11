# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the _RESERVED_NONRENDER_PARAMS extension (FR-2, Story 1.3).

Two behaviors:
  (a) declaring query_normalizer WITHOUT referencing it in the body parses
      cleanly (the reserved key is exempt from the unused-declaration check);
  (b) referencing {{ query_normalizer }} in the body raises
      ReservedParamReferenced.
"""

from __future__ import annotations

import pytest

from backend.app.domain.study.template_validator import (
    ReservedParamReferenced,
    validate_template_body,
)


def test_declared_but_unreferenced_reserved_param_parses_clean() -> None:
    # (a) query_normalizer declared, not used in body -> no DeclaredParamUnused.
    validate_template_body(
        '{"q": {{ query_text | tojson }}}',
        {"query_normalizer": "string"},
    )


def test_referenced_reserved_param_raises() -> None:
    # (b) body substitutes the reserved key -> hard error.
    with pytest.raises(ReservedParamReferenced) as exc:
        validate_template_body(
            '{"q": "{{ query_normalizer }}"}',
            {"query_normalizer": "string"},
        )
    assert "query_normalizer" in str(exc.value)


def test_mixed_reserved_exempt_and_real_param_used() -> None:
    # (c) query_normalizer exempt from unused-check; title_boost IS referenced
    # so the unused-declaration check passes for it too.
    validate_template_body(
        '{"q": {{ query_text | tojson }}, "boost": "{{ title_boost }}"}',
        {"query_normalizer": "string", "title_boost": "float"},
    )


def test_reserved_exempt_but_other_unused_still_raises() -> None:
    # The exemption is scoped to reserved params only — a genuinely unused
    # non-reserved declaration still raises DeclaredParamUnused.
    from backend.app.domain.study.template_validator import DeclaredParamUnused

    with pytest.raises(DeclaredParamUnused):
        validate_template_body(
            '{"q": {{ query_text | tojson }}}',
            {"query_normalizer": "string", "title_boost": "float"},
        )
