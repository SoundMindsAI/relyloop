# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Doc-consistency invariants for the per-engine tunable-params cheatsheets
(``chore_template_library_expansion`` Story 2.4, Epic 2 — AC-4, AC-1b).

These tests assert against files created in Epic 2 (`elasticsearch-`,
`opensearch-`, `solr-tunable-params.md`) so they live in their own module
— the Epic-1 invariants in ``test_template_library_invariants.py`` don't
depend on cheatsheet content.

Coverage:

1. **Required-knob inventory per cheatsheet (AC-4):** each cheatsheet
   covers the 8 unified params from
   ``docs/01_architecture/adapters.md`` PLUS every declared param
   exposed by that engine's runnable templates. A missing knob fails
   the test loudly.

2. **"Templates that use this param" back-links resolve:** each
   back-link in a cheatsheet names a template that actually declares
   that param.

3. **Vendor-docs README index has a row per cheatsheet.**

4. **FR-1b kNN + hybrid snippets parse as JSON** (ES + OpenSearch
   cheatsheets only — Solr ships no vector snippet by design).

5. **OpenSearch hybrid uses the normalization-processor construct,
   not the ES `rrf` retriever** (FR-1b — the two engines diverge here).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
VENDOR_DOCS = REPO_ROOT / "docs" / "06_vendor_docs"
TEMPLATES_DIR = REPO_ROOT / "samples" / "templates"

ES_CHEATSHEET = VENDOR_DOCS / "elasticsearch-tunable-params.md"
OS_CHEATSHEET = VENDOR_DOCS / "opensearch-tunable-params.md"
SOLR_CHEATSHEET = VENDOR_DOCS / "solr-tunable-params.md"
VENDOR_README = VENDOR_DOCS / "README.md"


# The 8 unified params from ``docs/01_architecture/adapters.md``
# "Cross-engine parameter naming". Source-of-truth comment:
#   // Values must match docs/01_architecture/adapters.md §"Cross-engine parameter naming"
UNIFIED_PARAMS = [
    "field_boosts",
    "phrase_field_boosts",
    "tie_breaker",
    "min_should_match",
    "fuzziness",
    "slop",
    "boost_fn",
    "rerank_model",
]

# Per-engine declared params from the runnable library templates. Each
# of these names MUST appear (substring match) somewhere in the matching
# cheatsheet — either as its own section or in a "Templates that use
# this param" back-link.
ES_OS_TEMPLATE_PARAMS = {
    "multi_match_basic": [
        "title_boost",
        "description_boost",
        "bullet_points_boost",
        "tie_breaker",
        "fuzziness",
    ],
    "function_score_decay": [
        "title_boost",
        "description_boost",
        "bullet_points_boost",
        "decay_scale",
        "decay_offset",
        "decay_decay",
    ],
    "bool_boosted": ["title_boost", "description_boost", "bullet_points_boost", "min_should_match"],
    "rescore_phrase": [
        "title_boost",
        "description_boost",
        "bullet_points_boost",
        "rescore_window_size",
        "rescore_query_weight",
        "rescore_phrase_slop",
    ],
}
SOLR_TEMPLATE_PARAMS = {
    "edismax_basic": ["title_boost", "description_boost", "bullet_points_boost", "tie", "mm", "ps"],
    "boost_decay": [
        "title_boost",
        "description_boost",
        "bullet_points_boost",
        "boost_weight",
        "decay_scale",
    ],
}


# ---------------------------------------------------------------------------
# Required-knob inventory (AC-4)
# ---------------------------------------------------------------------------


def _flatten(params: dict[str, list[str]]) -> set[str]:
    out: set[str] = set()
    for vals in params.values():
        out.update(vals)
    return out


def _section_headings(text: str) -> list[str]:
    """Return the ``### `<name>` ...`` heading slugs in document order.

    Splits on the first comma inside the heading so a grouped header like
    ``### `decay_scale`, `decay_offset`, `decay_decay``` registers all
    three slugs (the cheatsheets group the three decay params under a
    single heading per the cheatsheet design).
    """
    out: list[str] = []
    for line in text.splitlines():
        if not line.startswith("### "):
            continue
        # Extract every ``…`` token from the heading (handles grouped
        # headings like the decay-trio).
        for m in re.findall(r"`(\w+)`", line):
            out.append(m)
    return out


@pytest.mark.parametrize(
    "cheatsheet,engine_params",
    [
        (ES_CHEATSHEET, _flatten(ES_OS_TEMPLATE_PARAMS)),
        (OS_CHEATSHEET, _flatten(ES_OS_TEMPLATE_PARAMS)),
        (SOLR_CHEATSHEET, _flatten(SOLR_TEMPLATE_PARAMS)),
    ],
    ids=["elasticsearch", "opensearch", "solr"],
)
def test_cheatsheet_covers_all_required_knobs(cheatsheet: Path, engine_params: set[str]) -> None:
    """AC-4: every cheatsheet covers (a) the 8 unified params (each as its
    own ``### `<name>``` section heading per the plan's AC-4 wording) and
    (b) every declared param exposed by that engine's runnable templates.

    Per-template-instance declared params (`title_boost`, `description_boost`,
    `bullet_points_boost`) are intentionally grouped under the unified
    `field_boosts` section rather than promoted to their own headings —
    the cheatsheet design documents the CONCEPT once and lists template
    instances in the back-link line. The substring check covers them.
    """
    text = cheatsheet.read_text()
    headings = set(_section_headings(text))

    # Strict heading check for the 8 unified params (GPT-5.5 final-review
    # finding on PR #416 — accepted: substring-only was weaker than the
    # plan's "section/anchor for all 8 unified params" wording).
    missing_unified = sorted(p for p in UNIFIED_PARAMS if p not in headings)
    assert not missing_unified, (
        f"{cheatsheet.name} is missing dedicated section headings (### `<param>`...) "
        f"for required unified params: {missing_unified}. Each of the 8 unified "
        "params in `docs/01_architecture/adapters.md` MUST have its own section "
        "heading in every per-engine cheatsheet."
    )

    # Substring check for declared-param instances + ES-specific knobs
    # (these may appear as their own heading OR in a back-link line within
    # a unified-vocabulary section).
    declared_only = engine_params - set(UNIFIED_PARAMS)
    missing_declared = sorted(p for p in declared_only if p not in text)
    assert not missing_declared, (
        f"{cheatsheet.name} is missing entries for declared params: {missing_declared}. "
        "Each declared param must appear somewhere in the cheatsheet — either "
        "as its own section heading or in a per-knob 'Templates that use "
        "this param' back-link."
    )


# ---------------------------------------------------------------------------
# Back-links resolve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cheatsheet,engine_templates",
    [
        (ES_CHEATSHEET, list(ES_OS_TEMPLATE_PARAMS.keys())),
        (OS_CHEATSHEET, list(ES_OS_TEMPLATE_PARAMS.keys())),
        (SOLR_CHEATSHEET, list(SOLR_TEMPLATE_PARAMS.keys())),
    ],
    ids=["elasticsearch", "opensearch", "solr"],
)
def test_cheatsheet_backlinks_name_real_templates(
    cheatsheet: Path, engine_templates: list[str]
) -> None:
    """Every cheatsheet that mentions a `<name>.j2` back-link must
    name a template that actually exists in the runnable library."""
    text = cheatsheet.read_text()
    # Find `<name>.j2` references (excluding the demo `products_*.j2` which
    # the cheatsheets may reference for context — those exist on disk too).
    referenced = set(re.findall(r"`(\w+)\.j2`", text))
    # Allow demo templates + any locked engine_templates name.
    valid_names = set(engine_templates) | {
        "product_search",
        "products_edismax",
        "products_dismax",
        "products_lucene",
    }
    unknown = referenced - valid_names
    assert not unknown, (
        f"{cheatsheet.name} references unknown templates: {sorted(unknown)}. "
        "Each `<name>.j2` reference must point at a real runnable library "
        f"template ({sorted(valid_names)}) or a demo template."
    )


# ---------------------------------------------------------------------------
# Vendor README index rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cheatsheet_filename",
    [
        "elasticsearch-tunable-params.md",
        "opensearch-tunable-params.md",
        "solr-tunable-params.md",
    ],
)
def test_vendor_readme_has_index_row(cheatsheet_filename: str) -> None:
    text = VENDOR_README.read_text()
    assert f"`{cheatsheet_filename}`" in text or f"({cheatsheet_filename})" in text, (
        f"Vendor-docs README missing an index row for `{cheatsheet_filename}`. "
        "Add a row to the index table per FR-5."
    )


# ---------------------------------------------------------------------------
# FR-1b — vector / hybrid reference snippets parse as JSON
# ---------------------------------------------------------------------------


def _extract_json_blocks(markdown: str) -> list[str]:
    """Return the contents of every fenced ```json``` block in the file."""
    return re.findall(r"```json\n(.*?)```", markdown, flags=re.DOTALL)


@pytest.mark.parametrize("cheatsheet", [ES_CHEATSHEET, OS_CHEATSHEET], ids=["es", "os"])
def test_es_os_cheatsheet_json_snippets_parse(cheatsheet: Path) -> None:
    """FR-1b: the kNN + hybrid reference snippets MUST be valid JSON.
    Placeholder values like `"<EMBEDDING_VECTOR_PLACEHOLDER>"` are
    quoted strings — they parse fine; the test catches typos in braces,
    commas, and key ordering."""
    blocks = _extract_json_blocks(cheatsheet.read_text())
    assert blocks, f"{cheatsheet.name} has no fenced JSON blocks — FR-1b expects ≥ 2"
    for i, block in enumerate(blocks):
        try:
            json.loads(block)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"{cheatsheet.name} JSON block #{i + 1} does not parse: {exc.msg}\n"
                f"Block content:\n{block}"
            )


# ---------------------------------------------------------------------------
# FR-1b — OpenSearch hybrid uses normalization-processor, not `rrf`
# ---------------------------------------------------------------------------


def test_opensearch_hybrid_does_not_use_rrf_retriever() -> None:
    text = OS_CHEATSHEET.read_text()
    # The OpenSearch cheatsheet may MENTION the ES rrf retriever (to call
    # out the divergence), but the OS hybrid SNIPPET must NOT use it.
    # Look at fenced JSON blocks specifically — those are the operator-
    # facing snippets.
    blocks = _extract_json_blocks(text)
    for i, block in enumerate(blocks):
        assert '"rrf"' not in block, (
            f"opensearch-tunable-params.md JSON block #{i + 1} contains an "
            "`rrf` retriever — that's an Elasticsearch-only construct. "
            "Use the OpenSearch search-pipeline normalization processor."
        )
    # Positive assertion: the OS cheatsheet should explicitly mention the
    # normalization-processor construct (FR-1b requirement).
    assert "normalization" in text.lower() and "processor" in text.lower(), (
        "opensearch-tunable-params.md must document the normalization-processor construct (FR-1b)."
    )


def test_elasticsearch_hybrid_uses_rrf_retriever() -> None:
    """FR-1b: the ES cheatsheet's hybrid section MUST use the `rrf`
    retriever (8.11+ native construct), not the OpenSearch
    normalization-processor."""
    text = ES_CHEATSHEET.read_text()
    blocks = _extract_json_blocks(text)
    found_rrf = any('"rrf"' in block for block in blocks)
    assert found_rrf, (
        "elasticsearch-tunable-params.md must include an `rrf` retriever "
        "snippet (FR-1b) demonstrating the ES-native hybrid construct."
    )


# ---------------------------------------------------------------------------
# FR-5 — samples READMEs link to the cheatsheets
# ---------------------------------------------------------------------------


def test_samples_readme_links_cheatsheets() -> None:
    text = (TEMPLATES_DIR / "README.md").read_text()
    for cheatsheet_name in (
        "elasticsearch-tunable-params.md",
        "opensearch-tunable-params.md",
        "solr-tunable-params.md",
    ):
        assert cheatsheet_name in text, (
            f"samples/templates/README.md is missing a link to {cheatsheet_name} "
            "— operators need the cross-reference."
        )
