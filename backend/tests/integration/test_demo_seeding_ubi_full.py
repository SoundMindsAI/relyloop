# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Heavy-lane integration test for the full UBI demo reseed (Story 4.2).

Gated by ``SKIP_HEAVY_CI`` so the always-on PR matrix can skip it; runs
in the heavy-lane CI job and on operator demand. Exercises the full
:func:`reseed_demo_state` orchestrator against real Postgres + ES +
Redis + OpenAI, asserting the Story 4.2 DoD:

- **AC-1 / AC-4 / AC-5** (engine-tolerant counts, infra_solr_ci_readiness):
  judgment-list + study counts are computed from the REACHABLE scenarios.
  In CI (Solr absent) that's **8/8** — 3 UBI scenarios × (LLM + UBI) = 6,
  + news LLM-only = 7, + rich = 8, with the Solr scenario skipped. On a full
  local stack (Solr up) it's **10/10** (+ Solr's LLM + UBI lists). The
  per-scenario reachability is taken from ``snapshot_engine_reachability``
  (the same probe the orchestrator uses), and ``scenarios_skipped`` is asserted
  to match the snapshot's unreachable set. UBI lists carry
  ``generation_params.generation_kind = "ubi"`` and the per-scenario
  ``converter``.
- **AC-2**: the rung classifier (via the real
  ``GET /clusters/{id}/ubi-readiness`` operator path) returns the
  expected rung for every REACHABLE scenario (acme=rung_3, jobs=rung_2,
  corp=rung_1, news=rung_0, rich=rung_0, solr=rung_2-when-reachable).
- **AC-8** (feat_demo_reseed_solr_and_steplog): full-reseed wall-clock < 3600s
  (hard assert per spec cycle-3 patch — NOT a p95 calculation). Ceiling
  raised from 1140s to 3600s alongside the
  ``DEMO_SMALL_STUDY_MAX_TRIALS`` 12 -> 50 bump
  (feat_studies_convergence_visibility Story 2.2 / D-9 — the seed
  wall-clock increase is explicitly accepted; smoke is opt-in/off so the
  default CI lanes are unaffected).
- **feat_studies_convergence_visibility AC-7 + AC-8**: read the persisted
  ``Study.baseline_metric`` / ``best_metric`` / ``convergence_verdict`` for
  acme-products-prod (the representative scenario picked per the plan's
  Testing workstream §3.2). Asserts the FR-5 bounds (no ceiling,
  >= 0.10 lift, baseline in [0.40, 0.70]) AND the FR-6 verdict
  (``trial_count == 50`` AND verdict in {``converged``,``still_improving``}).
  The per-scenario headroom test
  (``backend/tests/integration/test_demo_scenarios_headroom.py``) covers
  all 5 scenarios deterministically without running the optimizer; this
  heavy-lane assertion validates the full pipeline (Optuna -> trials ->
  persisted Study fields) end-to-end for one scenario.
- **AC-10**: a subsequent cleanup pass deletes both ``ubi_queries`` and
  ``ubi_events`` indices.

AC-9 (UBI judgment-list ``failed`` → ``DemoSeedingError``) is covered by
a focused, always-on poll-helper test in
``test_demo_seeding_ubi_fast.py`` (no full stack required) — see
``test_poll_judgment_list_failed_raises_demo_seeding_error`` there.

CLI parity (FR-5 / spec §4): the CLI's per-scenario flow at
``scripts/seed_meaningful_demos.py:seed_scenario`` calls the same
``_async_seed_synthetic_ubi`` wrapper around the same async helpers the
orchestrator uses. Behavioural parity is enforced by Story 2.5's code
mirroring + Story 2.1's SCENARIOS shape unit tests.

OpenAI is required for the hybrid converter path (corp + jobs) and the
rich scenario; the heavy-lane CI job provides it. Without it the hybrid
UBI lists fail and the reseed raises ``DemoSeedingError`` before the
assertions — that's the AC-9 contract, surfaced loudly rather than
silently producing 7/7.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from backend.tests.conftest import postgres_reachable

# Module-level guard. The heavy-lane test requires Postgres (orchestrator
# DB writes), Redis (lock + status), ES (engine writes + classifier), and
# OpenAI (hybrid converters + rich scenario).
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
    pytest.mark.skipif(
        os.environ.get("SKIP_HEAVY_CI") == "true",
        reason="SKIP_HEAVY_CI=true — heavy lane suppressed (state.md)",
    ),
]


# Per-scenario rung expectations (AC-2 / D-2). `acme-products-rich-prod`
# is the rich scenario — LLM-only, no synthetic UBI (D-12), so rung_0.
# `acme-kb-docs-solr` is the MVP2 Solr scenario (rung_2 + hybrid converter,
# per seed_meaningful_demos.py); covered only when Solr is reachable
# (infra_solr_ci_readiness Story 1.4 / AC-5).
_EXPECTED_RUNGS: dict[str, str] = {
    "acme-products-prod": "rung_3",
    "corp-docs-search": "rung_1",
    "jobs-marketplace-prod": "rung_2",
    "news-search-staging": "rung_0",
    "acme-products-rich-prod": "rung_0",
    "acme-kb-docs-solr": "rung_2",
}

# Per-scenario target index (the UBI `application` filter).
_SCENARIO_TARGET: dict[str, str] = {
    "acme-products-prod": "products",
    "corp-docs-search": "docs-articles",
    "jobs-marketplace-prod": "job-listings",
    "news-search-staging": "news-articles",
    "acme-products-rich-prod": "acme-products-rich",
    "acme-kb-docs-solr": "acme-kb-docs",
}

# Per-scenario UBI converter expectations (AC-1 / D-2).
_EXPECTED_UBI_CONVERTERS: dict[str, str] = {
    "acme-products-prod": "ctr_threshold",
    "corp-docs-search": "hybrid_ubi_llm",
    "jobs-marketplace-prod": "hybrid_ubi_llm",
    "acme-kb-docs-solr": "hybrid_ubi_llm",
}


async def _discover_cluster_id(api_client: Any, name: str) -> str:
    resp = await api_client.get("/api/v1/clusters", params={"limit": 50})
    resp.raise_for_status()
    for row in resp.json()["data"]:
        if row["name"] == name:
            return str(row["id"])
    raise AssertionError(f"cluster {name!r} not found after reseed")


async def _discover_query_set_id(api_client: Any, cluster_id: str) -> str:
    resp = await api_client.get(
        "/api/v1/query-sets", params={"cluster_id": cluster_id, "limit": 10}
    )
    resp.raise_for_status()
    rows = resp.json()["data"]
    assert rows, f"no query set for cluster {cluster_id}"
    return str(rows[0]["id"])


@pytest.mark.asyncio
async def test_full_reseed_produces_8_lists_8_studies_per_rung_correct(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Drive the orchestrator end-to-end + assert AC-1, AC-2, AC-7, AC-8, AC-10.

    Note: this test is intentionally long (13-19 minutes). It uses the
    SAME public surface the route handler does — calling
    :func:`reseed_demo_state` directly with a fresh engine + api client
    + DB session. Skipping the Arq queue path keeps the test
    self-contained (no separate worker process required).
    """
    import httpx
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings
    from backend.app.services.demo_seeding import (
        _RICH_SCENARIO_SLUG,
        SCENARIOS,
        ReseedStatusResponse,
        reseed_demo_state,
        run_demo_reseed_cleanup,
        snapshot_engine_reachability,
    )
    from backend.tests.integration.fixtures.es_overlap_probe import (
        _check_local_es_credentials_or_skip,
    )

    _check_local_es_credentials_or_skip()

    # Engine-tolerance (infra_solr_ci_readiness Story 1.4): probe which engines
    # are reachable using the SAME helper + resolved URLs the orchestrator uses,
    # so the test's predicted skip-set/counts match what the reseed actually
    # does. The snapshot is slug-keyed and includes the rich ESCI scenario.
    snapshot = await snapshot_engine_reachability(SCENARIOS)
    expected_skipped = {slug for slug, ok in snapshot.items() if not ok}

    # ES is the dominant engine — every ES-backed scenario (incl. rich) plus the
    # cluster-credential plumbing depends on it. Without ANY ES-backed scenario
    # reachable there's nothing meaningful to validate, so skip the whole test
    # (this replaces the former host-first _es_base_url() gate). In CI ES is
    # always up, so only Solr skips.
    es_backed_reachable = any(
        snapshot.get(scenario["slug"])
        for scenario in SCENARIOS
        if scenario["engine_type"] == "elasticsearch"
    ) or snapshot.get(_RICH_SCENARIO_SLUG, False)
    if not es_backed_reachable:
        pytest.skip("No Elasticsearch-backed scenario reachable; see docs/03_runbooks/local-dev.md")

    # Expected judgment-list / study counts from the REACHABLE scenarios only.
    # Each SCENARIOS entry contributes 2 (LLM + UBI) when it carries a
    # ubi_target_rung, else 1 (LLM-only); the rich scenario is LLM-only (1).
    expected_count = 0
    for scenario in SCENARIOS:
        if snapshot[str(scenario["slug"])]:
            expected_count += 2 if scenario.get("ubi_target_rung") else 1
    if snapshot[_RICH_SCENARIO_SLUG]:
        expected_count += 1

    settings = get_settings()
    pg_engine = create_async_engine(settings.database_url, future=True)
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    started_at = time.monotonic()
    try:
        async with factory() as db:
            async with (
                httpx.AsyncClient(base_url="http://localhost:8000", timeout=60.0) as api_client,
                httpx.AsyncClient(timeout=60.0) as engine_client,
            ):
                # Capture the latest progress so we can assert scenarios_skipped
                # (it lives on the progress ReseedStatusResponse, not the summary).
                last_progress: list[ReseedStatusResponse] = []

                async def status_callback(progress: object) -> None:
                    if isinstance(progress, ReseedStatusResponse):
                        last_progress.append(progress)

                with caplog.at_level("WARNING", logger="backend.app.services.demo_seeding"):
                    summary = await reseed_demo_state(
                        db=db,
                        api_client=api_client,
                        engine_client=engine_client,
                        status_callback=status_callback,
                    )
                duration_s = time.monotonic() - started_at

                # AC-7: when any scenario was skipped (CI posture: Solr absent),
                # exactly one partial-completion WARN is emitted. When all engines
                # are reachable (full local stack), no such WARN.
                partial_warns = [
                    r
                    for r in caplog.records
                    if r.getMessage() == "demo_reseed_partial_completion_engines_unreachable"
                ]
                if expected_skipped:
                    assert len(partial_warns) == 1, (
                        f"AC-7: expected exactly one partial-completion WARN; "
                        f"got {len(partial_warns)}"
                    )
                else:
                    assert not partial_warns, "no partial WARN expected when all engines reachable"

                # The reseed's actual skip-set must match the test's prediction.
                assert last_progress, "status_callback never received a progress update"
                actual_skipped = set(last_progress[-1].scenarios_skipped)
                assert actual_skipped == expected_skipped, (
                    f"reseed skip-set {actual_skipped} != predicted {expected_skipped}"
                )

                # AC-1 / AC-4 / AC-5: judgment-list + study counts equal the
                # per-reachable-scenario computation (8/8 in CI without Solr,
                # 10/10 with Solr up).
                jl_count = await db.scalar(text("SELECT COUNT(*) FROM judgment_lists"))
                study_count = await db.scalar(text("SELECT COUNT(*) FROM studies"))
                assert jl_count == expected_count, (
                    f"expected exactly {expected_count} judgment lists; got {jl_count} "
                    f"(reachable scenarios: {sorted(s for s, ok in snapshot.items() if ok)})"
                )
                assert study_count == expected_count, (
                    f"expected exactly {expected_count} studies; got {study_count}"
                )

                # AC-1 (continued): per UBI-enabled REACHABLE scenario, two
                # lists — one LLM (NULL generation_params) + one UBI with the
                # right converter.
                for slug, expected_converter in _EXPECTED_UBI_CONVERTERS.items():
                    if not snapshot.get(slug, False):
                        continue  # scenario's engine was unreachable -> not seeded
                    rows = (
                        await db.execute(
                            text(
                                "SELECT jl.generation_params "
                                "FROM judgment_lists jl "
                                "JOIN clusters c ON jl.cluster_id = c.id "
                                "WHERE c.name = :slug"
                            ),
                            {"slug": slug},
                        )
                    ).all()
                    gps = [row[0] for row in rows]
                    assert len(gps) == 2, f"expected 2 judgment lists for {slug}; got {len(gps)}"
                    assert any(g is None for g in gps), (
                        f"{slug}: missing LLM list (NULL generation_params)"
                    )
                    ubi_gp = next(g for g in gps if g is not None)
                    assert ubi_gp.get("generation_kind") == "ubi", (
                        f"{slug}: UBI list missing generation_kind=ubi"
                    )
                    assert ubi_gp.get("converter") == expected_converter, (
                        f"{slug}: UBI converter drift "
                        f"(expected {expected_converter}, got {ubi_gp.get('converter')!r})"
                    )

                # AC-2: the rung classifier (via the real operator
                # endpoint, which acquires the per-cluster adapter
                # internally — works for the OpenSearch news cluster too)
                # returns the expected rung for every REACHABLE scenario.
                for slug, expected_rung in _EXPECTED_RUNGS.items():
                    if not snapshot.get(slug, False):
                        continue  # unreachable engine -> scenario was skipped
                    cluster_id = await _discover_cluster_id(api_client, slug)
                    qs_id = await _discover_query_set_id(api_client, cluster_id)
                    readiness = await api_client.get(
                        f"/api/v1/clusters/{cluster_id}/ubi-readiness",
                        params={"query_set_id": qs_id, "target": _SCENARIO_TARGET[slug]},
                    )
                    readiness.raise_for_status()
                    actual_rung = readiness.json()["rung"]
                    assert actual_rung == expected_rung, (
                        f"AC-2 rung drift for {slug}: expected {expected_rung}, got {actual_rung}"
                    )

                # feat_studies_convergence_visibility AC-7 + AC-8: read the
                # persisted `Study.baseline_metric`/`best_metric`/`convergence_
                # verdict` for ONE representative reachable scenario and assert
                # the FR-5 / FR-6 bounds:
                #
                #   AC-7: best_metric < 0.99 (no ceiling), best_metric -
                #         baseline_metric >= 0.10 absolute lift, and
                #         0.40 <= baseline_metric <= 0.70.
                #   AC-8: trial_count == DEMO_SMALL_STUDY_MAX_TRIALS (50) AND
                #         convergence_verdict in {"converged","still_improving"}
                #         (NOT "too_few_trials" — that was the degenerate state
                #         the bump fixes).
                #
                # We target acme-products-prod because it's the first reachable
                # scenario across both the CI lane (no Solr) and a full local
                # stack — the per-scenario headroom test
                # (test_demo_scenarios_headroom.py) covers all 5 deterministically
                # without running the optimizer; this heavy-lane assertion
                # validates the full pipeline (Optuna → trials → persisted
                # Study.baseline_metric / best_metric / convergence_verdict)
                # for one. Picking a single scenario keeps the assertion cost
                # bounded (no extra DB queries beyond the one we need).
                from backend.app.db.models.study import Study
                from backend.app.domain.study.convergence import classify_convergence

                acme_cluster_id = await _discover_cluster_id(api_client, "acme-products-prod")
                acme_study_row = (
                    await db.execute(
                        text(
                            "SELECT id, baseline_metric, best_metric, "
                            "objective, status "
                            "FROM studies "
                            "WHERE cluster_id = :cluster_id "
                            "  AND status = 'completed' "
                            "  AND name LIKE '%(LLM)' "
                            "LIMIT 1"
                        ),
                        {"cluster_id": acme_cluster_id},
                    )
                ).first()
                assert acme_study_row is not None, (
                    "acme-products-prod has no completed LLM study after reseed "
                    "— prerequisite for the AC-7 / AC-8 assertions"
                )
                acme_study_id = acme_study_row.id
                acme_baseline = acme_study_row.baseline_metric
                acme_best = acme_study_row.best_metric
                assert acme_baseline is not None, (
                    f"acme study {acme_study_id} missing baseline_metric — "
                    "baseline-trial path did not persist"
                )
                assert acme_best is not None, (
                    f"acme study {acme_study_id} missing best_metric — "
                    "no completed optimization trial"
                )
                lift = float(acme_best) - float(acme_baseline)
                # FSCV AC-7: bounds match the per-scenario headroom test.
                assert 0.40 <= float(acme_baseline) <= 0.70, (
                    f"FSCV AC-7 baseline drift — acme-products-prod baseline_metric="
                    f"{acme_baseline} outside [0.40, 0.70]; the demo enrichment "
                    f"regressed (or the optimizer got an unfair head start)"
                )
                assert lift >= 0.10, (
                    f"FSCV AC-7 lift bound — acme-products-prod best-baseline="
                    f"{lift:.4f} below 0.10; the optimizer failed to find "
                    f"the headroom Story 2.1 authored"
                )
                assert float(acme_best) < 0.99, (
                    f"FSCV AC-7 ceiling bound — acme-products-prod best_metric="
                    f"{acme_best} pinned at the ceiling; the demo regressed "
                    f"back to the degenerate state"
                )

                # FSCV AC-8: trial_count == 50 AND verdict != too_few_trials.
                # Route the assertion through the LIVE list-endpoint path
                # (``count_trials_for_studies`` + ``resolve_list_convergence_verdicts``)
                # so a regression in the list wiring fails this heavy-lane
                # assertion too, not just the per-scenario headroom test (per
                # GPT-5.5 phase-gate cycle-1 F2). Mirrors the live
                # ``list_studies`` builder: repo.count then service.resolve.
                from backend.app.db import repo as live_repo
                from backend.app.services.study_convergence import (
                    resolve_list_convergence_verdicts,
                )

                # Need the Study ORM row (not a raw SQL Row) for
                # resolve_list_convergence_verdicts — it reads .id, .status,
                # .objective, .config.
                acme_study = await live_repo.get_study(db, str(acme_study_id))
                assert acme_study is not None, (
                    f"acme study {acme_study_id} disappeared between SELECT and "
                    "get_study — DB churn race?"
                )
                trial_counts = await live_repo.count_trials_for_studies(db, [str(acme_study_id)])
                acme_trial_counts = trial_counts.get(str(acme_study_id))
                assert acme_trial_counts is not None, (
                    f"count_trials_for_studies returned no entry for {acme_study_id}"
                )
                # ``total`` matches StudySummary.trial_count exactly
                # (non-baseline rows; FR-1 / spec §13).
                assert acme_trial_counts.total == 50, (
                    f"FSCV AC-8 trial_count drift — acme-products-prod ran "
                    f"{acme_trial_counts.total} non-baseline trials, not 50; "
                    f"the DEMO_SMALL_STUDY_MAX_TRIALS bump regressed"
                )
                verdicts_map = await resolve_list_convergence_verdicts(
                    db, [acme_study], trial_counts
                )
                acme_verdict = verdicts_map.get(str(acme_study_id))
                assert acme_verdict is not None, (
                    "FSCV AC-8 — list-endpoint resolver returned None verdict "
                    "for acme-products-prod despite >= 50 complete trials; "
                    "this is the path StudySummary.convergence_verdict "
                    "exercises (regression in list wiring would surface here)"
                )
                assert acme_verdict in ("converged", "still_improving"), (
                    f"FSCV AC-8 verdict drift — acme-products-prod resolved to "
                    f"verdict={acme_verdict!r}; the bump to 50 trials should "
                    f"clear too_few_trials"
                )

                # Silence the unused-import lints — both symbols are referenced
                # in the docstring/commentary above to document the wire shape
                # this block reads; the actual call goes through the resolver
                # (which itself calls classify_convergence internally).
                _ = Study
                _ = classify_convergence

                # AC-8 (feat_demo_reseed_solr_and_steplog): hard wall-clock
                # ceiling. Raised from 1140s to 3600s alongside the
                # DEMO_SMALL_STUDY_MAX_TRIALS 12 -> 50 bump (Story 2.2 / D-9
                # accepts the seed wall-clock increase explicitly). The
                # heavy-lane test is the only consumer; smoke is opt-in/off
                # by default per state.md so the bump does not regress the
                # default CI lanes.
                assert duration_s < 3600, (
                    f"reseed wall-clock {duration_s:.1f}s exceeded AC-8 ceiling 3600s"
                )
                print(f"\nfull-reseed duration: {duration_s:.1f}s (AC-8 ceiling 3600s)")

                # AC-10: cleanup pass deletes both UBI indices. The UBI
                # collections live on ES; resolve the same in-container ES URL
                # the orchestrator uses.
                from backend.app.services.demo_seeding import _resolve_engine_base_url
                from scripts.seed_meaningful_demos import ES

                es_base_url = _resolve_engine_base_url(ES)
                await run_demo_reseed_cleanup(engine_client)
                for index in ("ubi_queries", "ubi_events"):
                    resp = await engine_client.get(f"{es_base_url}/{index}")
                    assert resp.status_code == 404, (
                        f"cleanup did not delete {index!r}: HTTP {resp.status_code}"
                    )
    finally:
        await pg_engine.dispose()

    assert summary.duration_ms > 0
    assert summary.studies_completed == expected_count
