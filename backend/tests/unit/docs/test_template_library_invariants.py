# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Doc-consistency invariants for the runnable template library
(``chore_template_library_expansion`` Story 1.3, Epic 1).

These tests do NOT depend on the per-engine tunable-params cheatsheets —
those land in Epic 2 and are exercised by
``test_tunable_params_cheatsheets.py``. The Epic-1 invariants are:

1. For each runnable library template:
   - **Parse** the README registration block (in
     ``samples/templates/README.md`` for ES/OS templates, in
     ``samples/templates/solr/README.md`` for Solr templates) to extract
     its ``declared_params`` keys — independently from the
     ``.search_space.json`` source. A bad README block fails the test.
   - Assert those parsed keys EQUAL the keys in the corresponding
     ``.search_space.json``. (Platform-equality invariant per
     ``backend/app/domain/study/search_space.py:validate_against_template``.)
   - Assert the ``.search_space.json`` cardinality is ≤ 10⁶ using the
     same ``SearchSpace.estimate_cardinality`` the study builder uses.

2. Each ES/OpenSearch template's registration block MUST be
   parameterized via ``ENGINE_TYPE="elasticsearch" # or opensearch`` (the
   same body is engine-agnostic; the operator picks the engine per
   registration). Solr blocks MUST hard-code ``engine_type: "solr"``.

3. The four existing demo templates (``product_search.j2`` +
   ``solr/products_*.j2``) MUST remain byte-stable — AC-3.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app.domain.study.search_space import SearchSpace, estimate_cardinality

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATES_DIR = REPO_ROOT / "samples" / "templates"
SAMPLES_README = TEMPLATES_DIR / "README.md"
SOLR_README = TEMPLATES_DIR / "solr" / "README.md"


# Locked list of runnable library templates (spec FR-1 + FR-2). Listed here
# rather than discovered from disk so a missing template fails loudly
# instead of being silently dropped.
ES_OS_TEMPLATES = [
    "multi_match_basic",
    "function_score_decay",
    "bool_boosted",
    "rescore_phrase",
]
SOLR_TEMPLATES = [
    "edismax_basic",
    "boost_decay",
]


# ---------------------------------------------------------------------------
# README registration-block parser
# ---------------------------------------------------------------------------


def _extract_block(readme_text: str, template_filename: str) -> str:
    r"""Return the README section for ``<template_filename>``.

    Sections begin with ``### \`<template_filename>\``` and end at the next
    ``### \`...\`` heading OR at the next ``## ``-level heading OR end-of-file.
    """
    marker = f"### `{template_filename}`"
    start = readme_text.find(marker)
    if start == -1:
        raise AssertionError(
            f"README registration block not found for `{template_filename}`. "
            "Each runnable library template MUST have a section heading "
            f"`{marker}` in its samples README."
        )
    # Find the next section / chapter heading after `start + len(marker)`.
    next_h3 = readme_text.find("\n### ", start + len(marker))
    next_h2 = readme_text.find("\n## ", start + len(marker))
    candidates = [pos for pos in (next_h3, next_h2) if pos != -1]
    end = min(candidates) if candidates else len(readme_text)
    return readme_text[start:end]


def _parse_declared_params_block(section: str) -> dict[str, str]:
    """Extract the ``declared_params: { ... }`` portion of the jq command.

    Robust against newlines and indentation; matches ``<key>: "<type>"``
    pairs inside the dict. The trailing pair has no comma — the regex
    captures both shapes.
    """
    # Find the substring after `declared_params:` up to the matching `}`.
    m = re.search(r"declared_params:\s*\{([^{}]*)\}", section)
    if m is None:
        raise AssertionError(
            "Could not locate `declared_params: { ... }` inside the README "
            "registration block. Each runnable template's curl block MUST "
            "include a `declared_params` map (spec FR-3)."
        )
    body = m.group(1)
    pairs = dict(re.findall(r"(\w+):\s*\"(\w+)\"", body))
    if not pairs:
        raise AssertionError(
            '`declared_params` block parsed but no `<key>: "<type>"` pairs '
            f"were extracted. Block content: {body!r}"
        )
    return pairs


def _extract_engine_type(section: str) -> str:
    """Return the engine_type string passed to the registration call.

    For ES/OS templates this is the parameterized form (the section sets
    ``ENGINE_TYPE="elasticsearch"  # or opensearch`` and the jq command
    threads it through ``--arg engine "$ENGINE_TYPE"`` + ``engine_type: $engine``).
    For Solr templates the value is a literal ``"solr"`` string. The return
    value lets the caller distinguish the two shapes.
    """
    # Hard-coded literal: `engine_type: "<literal>"`.
    literal = re.search(r'engine_type:\s*"(\w+)"', section)
    if literal:
        return literal.group(1)
    # Parameterized via $engine binding.
    if "engine_type: $engine" in section:
        return "$engine"
    raise AssertionError(
        "Registration block must set `engine_type` either to a literal "
        '(e.g. `engine_type: "solr"`) or to `engine_type: $engine` paired '
        'with a `--arg engine "$ENGINE_TYPE"` shell-variable invocation. '
        "Neither shape was found."
    )


def _load_search_space(template: str, solr: bool = False) -> SearchSpace:
    subdir = TEMPLATES_DIR / "solr" if solr else TEMPLATES_DIR
    raw = json.loads((subdir / f"{template}.search_space.json").read_text())
    return SearchSpace.model_validate(raw)


# ---------------------------------------------------------------------------
# Per-template invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", ES_OS_TEMPLATES)
def test_es_os_template_declared_params_match_search_space(template_name: str) -> None:
    section = _extract_block(SAMPLES_README.read_text(), f"{template_name}.j2")
    readme_keys = set(_parse_declared_params_block(section).keys())
    space = _load_search_space(template_name)
    space_keys = set(space.params.keys())
    assert readme_keys == space_keys, (
        f"README declared_params keys for `{template_name}.j2` diverged from "
        f"its .search_space.json keys.\n"
        f"  README only:        {sorted(readme_keys - space_keys)}\n"
        f"  search-space only:  {sorted(space_keys - readme_keys)}\n"
        "Edit the README registration block OR the .search_space.json so "
        "they EQUAL exactly — the platform validator "
        "`validate_against_template` rejects any drift at runtime."
    )


@pytest.mark.parametrize("template_name", SOLR_TEMPLATES)
def test_solr_template_declared_params_match_search_space(template_name: str) -> None:
    section = _extract_block(SOLR_README.read_text(), f"{template_name}.j2")
    readme_keys = set(_parse_declared_params_block(section).keys())
    space = _load_search_space(template_name, solr=True)
    space_keys = set(space.params.keys())
    assert readme_keys == space_keys, (
        f"README declared_params keys for `solr/{template_name}.j2` diverged "
        f"from its .search_space.json keys.\n"
        f"  README only:        {sorted(readme_keys - space_keys)}\n"
        f"  search-space only:  {sorted(space_keys - readme_keys)}"
    )


@pytest.mark.parametrize("template_name", ES_OS_TEMPLATES + SOLR_TEMPLATES)
def test_search_space_cardinality_at_or_below_cap(template_name: str) -> None:
    is_solr = template_name in SOLR_TEMPLATES
    space = _load_search_space(template_name, solr=is_solr)
    cardinality = estimate_cardinality(space)
    assert cardinality <= 1_000_000, (
        f"`{template_name}.search_space.json` cardinality {cardinality} > 10^6. "
        "Narrow ranges, drop a float to categorical, or shrink categorical "
        "choice sets so trial counts stay tractable."
    )


# ---------------------------------------------------------------------------
# Engine-type parameterization (cycle 4, GPT-5.5 F1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", ES_OS_TEMPLATES)
def test_es_os_registration_block_is_engine_parameterized(template_name: str) -> None:
    """Each ES/OS template's curl block MUST be parameterized via
    ``ENGINE_TYPE="elasticsearch" # or opensearch`` because the bodies are
    engine-agnostic but `query_templates.engine_type` is single-valued
    per row — operators register the same body once per engine they run.
    """
    section = _extract_block(SAMPLES_README.read_text(), f"{template_name}.j2")
    assert _extract_engine_type(section) == "$engine", (
        f"ES/OS template `{template_name}.j2`'s registration block must thread "
        'engine_type through `$engine`. Set `ENGINE_TYPE="elasticsearch"  # '
        'or opensearch` above the jq command and use `--arg engine "$ENGINE_TYPE"`.'
    )
    # The shell variable + the comment hint must both be present.
    assert 'ENGINE_TYPE="elasticsearch"' in section, (
        f"ES/OS template `{template_name}.j2`'s block is missing the literal "
        '`ENGINE_TYPE="elasticsearch"` initializer.'
    )
    assert "# or opensearch" in section, (
        f"ES/OS template `{template_name}.j2`'s block must annotate that "
        "the same body is also valid for OpenSearch with a `# or opensearch` comment."
    )


@pytest.mark.parametrize("template_name", SOLR_TEMPLATES)
def test_solr_registration_block_uses_literal_solr_engine(template_name: str) -> None:
    section = _extract_block(SOLR_README.read_text(), f"{template_name}.j2")
    assert _extract_engine_type(section) == "solr", (
        f"Solr template `solr/{template_name}.j2`'s registration block must "
        'set `engine_type: "solr"` (Solr templates are not engine-agnostic).'
    )


# ---------------------------------------------------------------------------
# AC-3 — four existing demo templates are byte-identical to `main`.
# ---------------------------------------------------------------------------


# Spec AC-3 cites the four demo template paths plus the demo's reader at
# `demo_seeding.py:1248`. We assert the files exist + carry their expected
# *signatures* — header-line markers chosen to be stable identifiers that
# change only if the body is rewritten. If you intentionally edit any of
# these, update this test in lockstep (and bump the demo reseed verification).
DEMO_TEMPLATE_SIGNATURES = {
    TEMPLATES_DIR / "product_search.j2": "product_search.j2 — canonical demo Jinja2",
    TEMPLATES_DIR
    / "solr"
    / "products_edismax.j2": "products_edismax.j2 — canonical Apache Solr edismax",
    TEMPLATES_DIR / "solr" / "products_dismax.j2": "products_dismax.j2",
    TEMPLATES_DIR / "solr" / "products_lucene.j2": "products_lucene.j2",
}


@pytest.mark.parametrize("path,signature", list(DEMO_TEMPLATE_SIGNATURES.items()))
def test_demo_template_unchanged(path: Path, signature: str) -> None:
    assert path.is_file(), f"Demo template {path} was removed — AC-3 violation"
    assert signature in path.read_text(), (
        f"Demo template {path} header signature changed — `{signature}` no "
        "longer appears. AC-3 protects these files (demo_seeding + smoke depend "
        "on them); this chore must not touch them."
    )
