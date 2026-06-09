# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""PR-body "Operator-side requirement" section tests (FR-4, Story 2.1).

Covers AC-7 (section + chosen line + BOTH Python and JS reference blocks),
AC-6 (absent key → no section), the ``none`` branch (explanatory line, no
snippet), AC-13 (a non-bundle pipeline label renders both blocks with no
KeyError), the defense-in-depth unknown-value fall-through, and the I-3
invariant (manual bodies never render the section).
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.domain.study.normalizers import (
    NormalizerStep,
    build_js_snippet,
    build_python_snippet,
    steps_for_label,
)
from backend.workers.git_pr import (
    _render_pr_body_manual,
    _render_pr_body_study_backed,
)

_PROPOSAL = SimpleNamespace(metric_delta={"ndcg@10": {"baseline": 0.5, "achieved": 0.62}})
_STUDY = SimpleNamespace(id="study-abc", name="prod-en-v1")
_DIGEST = SimpleNamespace(suggested_followups=[])


def _render(config_diff: dict[str, object]) -> str:
    return _render_pr_body_study_backed(
        proposal=_PROPOSAL,
        study=_STUDY,
        digest=_DIGEST,
        config_diff=config_diff,
        chart_md="",
        base_url=None,
    )


def test_section_renders_both_python_and_js_blocks() -> None:
    body = _render(
        {
            "query_normalizer": {"from": "none", "to": "lowercase+trim+expand_contractions"},
            "title_boost": {"from": 1.0, "to": 1.5},
        }
    )
    assert "## Operator-side requirement" in body
    assert "**Chosen normalizer:** `lowercase+trim+expand_contractions`" in body
    assert "### Python" in body
    assert "```python" in body
    assert "### JavaScript / TypeScript" in body
    assert "```javascript" in body
    # The GENERATED snippets are embedded verbatim.
    steps = steps_for_label("lowercase+trim+expand_contractions")
    assert build_python_snippet(steps) in body
    assert build_js_snippet(steps) in body


def test_section_omitted_when_key_absent() -> None:
    body = _render({"title_boost": {"from": 1.0, "to": 1.5}})
    assert "## Operator-side requirement" not in body


def test_none_renders_without_snippet() -> None:
    body = _render({"query_normalizer": {"from": "lowercase", "to": "none"}})
    assert "## Operator-side requirement" in body
    assert (
        "**Chosen normalizer:** `none`. No production-side change is required — "
        "the loop confirmed the un-normalized query already wins." in body
    )
    assert "```python" not in body
    assert "```javascript" not in body


def test_ac13_non_bundle_label_renders_both_blocks() -> None:
    # A powerset label Phase 1 never enumerated must render both blocks
    # without KeyError (the generator is label-driven, not dict-keyed).
    body = _render({"query_normalizer": {"from": "none", "to": "lowercase+strip_punctuation"}})
    assert "**Chosen normalizer:** `lowercase+strip_punctuation`" in body
    assert "### Python" in body and "### JavaScript / TypeScript" in body
    steps = steps_for_label("lowercase+strip_punctuation")
    assert build_python_snippet(steps) in body
    assert build_js_snippet(steps) in body


def test_defense_in_depth_unknown_value_falls_through_to_none() -> None:
    # An unresolvable "to" (unreachable in normal flow) renders the none
    # branch (no snippet) rather than raising on label resolution.
    body = _render({"query_normalizer": {"from": "none", "to": "stem"}})
    assert "## Operator-side requirement" in body
    assert "No production-side change is required" in body
    assert "```python" not in body


def test_i3_manual_body_never_renders_section() -> None:
    proposal = SimpleNamespace(metric_delta={})
    body = _render_pr_body_manual(
        proposal=proposal,
        config_diff={"query_normalizer": {"from": "none", "to": "lowercase"}},
    )
    assert "## Operator-side requirement" not in body


def test_single_step_label_embeds_its_snippets() -> None:
    body = _render({"query_normalizer": {"from": "none", "to": "lowercase"}})
    assert "**Chosen normalizer:** `lowercase`" in body
    steps = [NormalizerStep.lowercase]
    assert build_python_snippet(steps) in body
    assert build_js_snippet(steps) in body
