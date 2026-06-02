# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Regression test for ``apply_study_renames`` on study-less Solr results.

``infra_adapter_solr`` Story A13 added the ``acme-kb-docs-solr`` scenario,
whose ``_seed_solr_scenario_minimum`` registers a cluster + template but
creates **no study** (operators start it from the UI after
``make seed-solr``). Its result dict carries no ``study_name`` / ``study_id``.

The downstream consumers in :func:`scripts.seed_meaningful_demos.main` —
:func:`~scripts.seed_meaningful_demos.apply_study_renames` and the
``=== seed complete ===`` summary loop — assumed every result was
study-bearing and crashed with ``KeyError: 'study_name'`` once Solr was
reachable (i.e. on every local ``make seed-demo`` with the Solr container
up). These tests pin that study-less entries are skipped instead.
"""

from __future__ import annotations

import scripts.seed_meaningful_demos as mod


def test_apply_study_renames_skips_study_less_solr_entry(monkeypatch) -> None:
    """Renames run only for study-bearing entries; Solr-minimum is skipped.

    Before the fix, the Solr-minimum dict (no ``study_name``) raised
    ``KeyError`` mid-loop, aborting the whole seed at the final step.
    """
    psql_calls: list[str] = []
    monkeypatch.setattr(mod, "_psql", lambda sql: psql_calls.append(sql))

    study_bearing = {
        "slug": "acme-products-prod",
        "study_id": "019e8875-4be3-74d2-8b38-d47626b86fe0",
        "study_name": "tune-product-title-boost-baseline (LLM)",
    }
    solr_minimum = {
        "scenario": "acme-kb-docs-solr",
        "cluster_id": "019e8877-93d2-7e80-8fc8-d3cdedddb91f",
        "template_id": "019e8877-93e0-7553-861d-1e3b10005772",
        "skipped_index_path": True,
        "next_step": "Run `make seed-solr`, then create the demo study via the UI.",
    }

    # Must not raise — the study-less entry is skipped, not dereferenced.
    mod.apply_study_renames([study_bearing, solr_minimum])

    assert len(psql_calls) == 1, "exactly one UPDATE — only the study-bearing entry"
    assert study_bearing["study_id"] in psql_calls[0]
    assert "tune-product-title-boost-baseline (LLM)" in psql_calls[0]


def test_apply_study_renames_skips_partial_study_dict(monkeypatch) -> None:
    """A dict with ``study_name`` but no ``study_id`` is skipped, not crashed.

    Guards on BOTH keys the rename body dereferences (Gemini review on
    PR #419) so the consumer is robust to any partial dict, consistent with
    the summary loop's ``study_id`` guard — not just the exact Solr-minimum
    shape (which carries neither key).
    """
    psql_calls: list[str] = []
    monkeypatch.setattr(mod, "_psql", lambda sql: psql_calls.append(sql))

    partial = {"slug": "broken", "study_name": "has-name-no-id"}

    mod.apply_study_renames([partial])  # must not raise KeyError on study_id

    assert psql_calls == [], "partial dict (no study_id) must be skipped"


def test_solr_minimum_result_shape_has_no_study_keys() -> None:
    """Pin the contract the rename/summary guards rely on.

    ``_seed_solr_scenario_minimum`` returns dicts WITHOUT ``study_name`` /
    ``study_id``; the guards key off exactly that absence. If a future edit
    adds those keys, this test flags that the guard condition needs review.
    """
    import inspect

    src = inspect.getsource(mod._seed_solr_scenario_minimum)
    # The returned dict literal must not introduce study_name / study_id —
    # the consumers distinguish study-less entries by their absence.
    assert "study_name" not in src
    assert "study_id" not in src
    # And it must carry the keys the summary fallback reads.
    assert "scenario" in src
    assert "next_step" in src
