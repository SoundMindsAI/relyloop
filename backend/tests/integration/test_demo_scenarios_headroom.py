# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Engine-backed headroom test for the 5 small demo SCENARIOS.

Lands with ``feat_studies_convergence_visibility`` Epic 2 Stories 2.1 + 2.3
(scaffold + finalize). The deterministic CI guard for FR-5:

  Given a scenario's authored docs + graded judgments, AND a hand-picked
  "better" param set demonstrating tunable headroom,
  When we evaluate NDCG@10 against the live engine for both the equal-
       midpoint baseline params and the better params,
  Then ``0.40 <= baseline <= 0.70``, ``better - baseline >= 0.10``, and
       ``better < 0.99``.

The 4 ES/OpenSearch scenarios are hard CI gates (the ``pr.yml`` backend job
runs ES + OS service containers, so the ``@es_required`` / ``@opensearch_required``
markers don't skip in CI). The Solr scenario skip-gates when no Solr is
reachable (the backend CI lane has no Solr container per
``infra_solr_ci_readiness``); locally it runs against ``localhost:8983``.

The optimizer is NOT exercised here — that's covered by the ``@pytest.mark.slow``
end-to-end seed test (``test_demo_seeding_ubi_full.py``) for ONE representative
scenario plus the manual ``make seed-demo FORCE=1`` operator-path at release
gate. The headroom test pins the **data-design** quality: if the baseline is
already optimal there's nothing for the optimizer to find, and if the better
params don't actually beat the baseline by ``>= 0.10`` the FR-5 promise is
empty.

Baseline params are computed exactly as the live ``run_baseline`` worker
computes them — geometric-mean midpoints via
:func:`backend.app.domain.study.baseline_resolver.resolve_baseline_params`.
For the demo's log-scale Float [0.5, 5.0] boosts this resolves to
``sqrt(0.5 * 5.0) ≈ 1.5811`` for every boost (so the baseline ranks with all
boosts equal). The "better" params in ``_BETTER_PARAMS`` were tuned by hand
against this exact harness until all bounds held.
"""

from __future__ import annotations

import math
import os
import uuid
from typing import Any

import pytest

from backend.app.adapters.protocol import ParamValue
from backend.tests.integration.fixtures.es_reachability import _es_base_url
from backend.tests.integration.fixtures.headroom_harness import (
    build_adapter,
    cleanup_target,
    index_docs_es,
    index_docs_solr,
    run_scenario_metric,
)
from backend.tests.integration.fixtures.opensearch_reachability import (
    _opensearch_base_url,
)
from backend.tests.integration.fixtures.solr_reachability import (
    _solr_base_url,
    solr_required,
)

# Import SCENARIOS from the seed script (single source of truth — FR-7). The
# script is under ``scripts/`` which isn't a package, so the import goes via
# the same path ``backend.app.services.demo_seeding`` uses.
from scripts.seed_meaningful_demos import SCENARIOS

# ---------------------------------------------------------------------------
# Search-space + "better" param bookkeeping
# ---------------------------------------------------------------------------

# Mirrors the demo's tunable-param shape:
# ``scripts/seed_meaningful_demos.py:_create_one_study`` constructs a
# SearchSpace from each scenario's ``template_declared_params`` with float
# bounds [0.5, 5.0] and ``log=True``. The baseline midpoint for that span is
# ``sqrt(0.5 * 5.0) ≈ 1.5811`` per scenario param.
_DEMO_FLOAT_LOW = 0.5
_DEMO_FLOAT_HIGH = 5.0


# Hand-picked "better" params per scenario — tuned by repeatedly running the
# harness until all three bounds (0.40 <= baseline <= 0.70; better - baseline
# >= 0.10; better < 0.99) held against the enriched docs + judgments.
#
# Source-of-truth: per-scenario ``template_declared_params`` in
# ``scripts/seed_meaningful_demos.py`` SCENARIOS literal. Keys here MUST be a
# subset of those param names.
_BETTER_PARAMS: dict[str, dict[str, ParamValue]] = {
    # The enriched scenarios all use the same data-design pattern: each query
    # has a "best answer" doc whose query terms live in the description/body/
    # bullet field (NOT the title) and a "decoy" doc whose query terms are
    # densely packed into the title but whose description is shallow. At the
    # equal-midpoint baseline the title-decoys win on raw BM25 (title is a
    # short field → higher per-term BM25 score), so the baseline NDCG lands in
    # the 0.4-0.7 zone. Tuning the title boost DOWN and the description/body/
    # bullet boost UP re-ranks the description-rich best answer above the
    # title-decoy → headroom appears.
    "acme-products-prod": {"title_boost": 0.5, "description_boost": 5.0},
    # corp-docs only exposes title_boost. Lower it so the body (which holds
    # the rich help-center answer text) carries the ranking.
    "corp-docs-search": {"title_boost": 0.5},
    # news-search: lower title_boost so the body (where the lead paragraph
    # paraphrases the query) drives ranking. Freshness decay is fixed in the
    # template's function_score wrapper.
    "news-search-staging": {"title_boost": 0.5},
    # jobs-marketplace: low title boost + low company boost shifts weight to
    # the rich job-description text (description's field weight is fixed at
    # 1.0 in the template, so dropping the tunable boosts gives description
    # the relative lead).
    "jobs-marketplace-prod": {"title_boost": 0.5, "company_boost": 0.5},
    # acme-kb-docs-solr: low title + high bullet_points lets the bullet list
    # (which carries the step-by-step answer) outrank decoys that only echo
    # the query in the title.
    "acme-kb-docs-solr": {"title_boost": 0.5, "bullet_points_boost": 5.0},
}


def _scenarios_by_slug() -> dict[str, dict[str, Any]]:
    return {s["slug"]: s for s in SCENARIOS}


def _baseline_params(scenario: dict[str, Any]) -> dict[str, ParamValue]:
    """Resolve the baseline param vector exactly as the live worker does.

    The demo's ``_create_one_study`` (in ``scripts/seed_meaningful_demos.py``)
    builds a SearchSpace with one ``FloatParam(low=0.5, high=5.0, log=True)``
    per declared param. Tier (a) of the baseline resolver
    (``backend/app/domain/study/baseline_resolver.py:_midpoint``) computes the
    geometric mean ``sqrt(low * high)`` for a log-uniform float — for the demo's
    [0.5, 5.0] span this is ``sqrt(2.5) ≈ 1.5811`` for every boost.

    Computed inline here (instead of importing
    :func:`resolve_baseline_params`) because that helper takes a DB session +
    Study row and walks the FR-3 4-tier fallback; the headroom test only needs
    Tier (a) and would otherwise have to fabricate a Study row to use the
    public API. The constant is asserted in
    :func:`test_baseline_midpoint_matches_resolver` so any future change to
    ``_midpoint`` surfaces here.
    """
    midpoint = math.sqrt(_DEMO_FLOAT_LOW * _DEMO_FLOAT_HIGH)
    return {name: midpoint for name in scenario["template_declared_params"]}


# Scenario indexing dispatch ------------------------------------------------


async def _index_for_scenario(scenario: dict[str, Any], base_url: str, target: str) -> None:
    """Dispatch the engine-specific index helper.

    ES / OpenSearch use the scenario's ``index_mapping``; Solr uses the
    scenario's ``solr_configset`` (the checked-in configset the configset
    upload helper zips and uploads to ZooKeeper).
    """
    engine_type = scenario["engine_type"]
    if engine_type == "solr":
        await index_docs_solr(
            base_url=base_url,
            collection=target,
            configset=scenario["solr_configset"],
            docs=scenario["docs"],
        )
    else:
        await index_docs_es(
            base_url=base_url,
            index=target,
            docs=scenario["docs"],
            mapping=scenario.get("index_mapping"),
        )


# ---------------------------------------------------------------------------
# Per-scenario tests
# ---------------------------------------------------------------------------


_BOUND_BASELINE_MIN = 0.40
_BOUND_BASELINE_MAX = 0.70
_BOUND_LIFT_MIN = 0.10
_BOUND_BETTER_MAX = 0.99


def _assert_headroom(
    slug: str,
    baseline: float,
    better: float,
) -> None:
    """Assert all three FR-5 bounds with a single composite error message.

    The error message dumps both metric values so a failing scenario lands
    actionable signal in the test log without re-running.
    """
    msg = (
        f"[{slug}] headroom bounds violated — "
        f"baseline={baseline:.4f}, better={better:.4f}, lift={better - baseline:+.4f}; "
        f"required: {_BOUND_BASELINE_MIN} <= baseline <= {_BOUND_BASELINE_MAX}, "
        f"better - baseline >= {_BOUND_LIFT_MIN}, better < {_BOUND_BETTER_MAX}"
    )
    assert _BOUND_BASELINE_MIN <= baseline <= _BOUND_BASELINE_MAX, msg
    assert better - baseline >= _BOUND_LIFT_MIN, msg
    assert better < _BOUND_BETTER_MAX, msg


async def _run_headroom(scenario: dict[str, Any], base_url: str) -> None:
    """Index docs, score baseline + better, assert bounds, clean up."""
    slug = scenario["slug"]
    target_suffix = uuid.uuid4().hex[:8]
    # Solr collection names disallow dots; the suffix keeps ES + OS names too.
    target = f"headroom-{slug.replace('.', '-')}-{target_suffix}"
    adapter = build_adapter(
        engine_type=scenario["engine_type"],
        base_url=base_url,
        auth_kind=scenario["auth_kind"],
        credentials_ref=scenario["credentials_ref"],
    )
    try:
        await _index_for_scenario(scenario, base_url, target)
        baseline_params = _baseline_params(scenario)
        better_params = _BETTER_PARAMS[slug]
        baseline_score = await run_scenario_metric(
            adapter=adapter,
            scenario=scenario,
            params=baseline_params,
            target=target,
        )
        better_score = await run_scenario_metric(
            adapter=adapter,
            scenario=scenario,
            params=better_params,
            target=target,
        )
        _assert_headroom(slug, baseline_score, better_score)
    finally:
        await cleanup_target(scenario, base_url, target)


# Per-engine tests live in separate functions (not parameterized over engine
# type) so each carries its own ``@es_required`` / ``@opensearch_required`` /
# ``@solr_required`` marker — Pytest's parametrize doesn't compose with
# per-case skip markers ergonomically. The set of scenarios per engine is
# stable (the SCENARIOS literal is single-sourced) so the test count is
# transparent and grep-able.
#
# ES/OpenSearch hard-gate (plan D-18 / GPT-5.5 cycle-1 F1): in CI the
# `pr.yml` workflow declares ES + OS as service containers, so a missing
# probe URL means the container failed to come up — a CI-infra regression
# that MUST fail loudly, not silently skip. The ``_require_es_or_fail`` /
# ``_require_opensearch_or_fail`` helpers route the failure based on the
# ``CI`` env var (GitHub Actions sets ``CI=true``; same precedent as
# ``backend/tests/integration/fixtures/es_overlap_probe.py``'s
# ``_check_local_es_credentials_or_skip``). Solr stays skip-only — backend
# CI has no Solr container per ``infra_solr_ci_readiness``.


def _require_es_or_fail() -> str:
    """Return the ES base URL; in CI fail hard when unreachable, locally skip.

    Plan §6 + D-18: ES/OS scenarios are hard CI gates; an unreachable ES
    container is a CI infrastructure failure, NOT a tolerable skip. The
    ``@es_required`` marker silently skips when ``_es_base_url()`` returns
    empty — fine for a developer who hasn't run ``make up`` locally, but
    a CI regression hider. This helper routes the unreachable case to
    ``pytest.fail`` when ``CI=true`` (the GHA-set env var the rest of the
    repo already discriminates on — see ``es_overlap_probe.py`` for the
    precedent).
    """
    base_url = _es_base_url()
    if base_url:
        return base_url
    msg = (
        "ES unreachable at localhost:9200 / elasticsearch:9200 — the "
        "pr.yml backend job declares an `elasticsearch` service container "
        "(see .github/workflows/pr.yml); if you see this in CI the "
        "container failed to come up. Per plan D-18 the 4 ES/OS headroom "
        "scenarios are hard CI gates."
    )
    if os.environ.get("CI") == "true":
        pytest.fail(msg)
    pytest.skip(msg)


def _require_opensearch_or_fail() -> str:
    """OpenSearch sibling of :func:`_require_es_or_fail`; same CI-fail semantics."""
    base_url = _opensearch_base_url()
    if base_url:
        return base_url
    msg = (
        "OpenSearch unreachable at localhost:9201 / opensearch:9200 — the "
        "pr.yml backend job declares an `opensearch` service container "
        "(see .github/workflows/pr.yml); if you see this in CI the "
        "container failed to come up. Per plan D-18 the 4 ES/OS headroom "
        "scenarios are hard CI gates."
    )
    if os.environ.get("CI") == "true":
        pytest.fail(msg)
    pytest.skip(msg)


# acme-products-prod — Elasticsearch.
@pytest.mark.integration
async def test_headroom_acme_products_prod() -> None:
    scenario = _scenarios_by_slug()["acme-products-prod"]
    base_url = _require_es_or_fail()
    await _run_headroom(scenario, base_url)


# corp-docs-search — Elasticsearch.
@pytest.mark.integration
async def test_headroom_corp_docs_search() -> None:
    scenario = _scenarios_by_slug()["corp-docs-search"]
    base_url = _require_es_or_fail()
    await _run_headroom(scenario, base_url)


# news-search-staging — OpenSearch.
@pytest.mark.integration
async def test_headroom_news_search_staging() -> None:
    scenario = _scenarios_by_slug()["news-search-staging"]
    base_url = _require_opensearch_or_fail()
    await _run_headroom(scenario, base_url)


# jobs-marketplace-prod — Elasticsearch.
@pytest.mark.integration
async def test_headroom_jobs_marketplace_prod() -> None:
    scenario = _scenarios_by_slug()["jobs-marketplace-prod"]
    base_url = _require_es_or_fail()
    await _run_headroom(scenario, base_url)


# acme-kb-docs-solr — Apache Solr (skip-gates when Solr is unreachable; D-18).
@pytest.mark.integration
@solr_required
async def test_headroom_acme_kb_docs_solr() -> None:
    scenario = _scenarios_by_slug()["acme-kb-docs-solr"]
    base_url = _solr_base_url()
    assert base_url, "solr_required marker should have skipped"
    await _run_headroom(scenario, base_url)


# ---------------------------------------------------------------------------
# Parity guard — pin the inlined midpoint against the live resolver
# ---------------------------------------------------------------------------


def test_baseline_midpoint_matches_resolver() -> None:
    """Pin :func:`_baseline_params` against the live ``_midpoint`` helper.

    :func:`_baseline_params` inlines the geometric-mean formula instead of
    importing the public :func:`resolve_baseline_params` (which requires a DB
    session + Study row). This test pins the inlined formula against the
    domain layer's private ``_midpoint`` helper so any future change to the
    midpoint policy surfaces as a test failure here rather than as silently
    drifting headroom-baseline values.
    """
    from backend.app.domain.study.baseline_resolver import _midpoint
    from backend.app.domain.study.search_space import FloatParam

    declared_param = FloatParam(type="float", low=_DEMO_FLOAT_LOW, high=_DEMO_FLOAT_HIGH, log=True)
    expected = _midpoint(declared_param)
    actual = math.sqrt(_DEMO_FLOAT_LOW * _DEMO_FLOAT_HIGH)
    assert actual == pytest.approx(expected, rel=1e-9)
