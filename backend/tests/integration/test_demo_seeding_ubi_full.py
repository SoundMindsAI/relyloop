# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Heavy-lane integration test for the full UBI demo reseed (Story 4.2).

Gated by ``SKIP_HEAVY_CI`` so the always-on PR matrix can skip it; runs
in the heavy-lane CI job and on operator demand. Exercises the full
:func:`reseed_demo_state` orchestrator against real Postgres + ES +
Redis + OpenAI, asserting the Story 4.2 DoD:

- **AC-1**: exactly 8 judgment lists + 8 studies (3 UBI scenarios ×
  (LLM + UBI) = 6, + news LLM-only = 7, + rich scenario = 8). The three
  UBI lists carry ``generation_params.generation_kind = "ubi"`` and the
  per-scenario ``converter``.
- **AC-2**: the rung classifier (via the real
  ``GET /clusters/{id}/ubi-readiness`` operator path) returns the
  expected rung per scenario (acme=rung_3, jobs=rung_2, corp=rung_1,
  news=rung_0, rich=rung_0).
- **AC-8**: full-reseed wall-clock < 1140s (hard assert per spec cycle-3
  patch — NOT a p95 calculation).
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
_EXPECTED_RUNGS: dict[str, str] = {
    "acme-products-prod": "rung_3",
    "corp-docs-search": "rung_1",
    "jobs-marketplace-prod": "rung_2",
    "news-search-staging": "rung_0",
    "acme-products-rich-prod": "rung_0",
}

# Per-scenario target index (the UBI `application` filter).
_SCENARIO_TARGET: dict[str, str] = {
    "acme-products-prod": "products",
    "corp-docs-search": "docs-articles",
    "jobs-marketplace-prod": "job-listings",
    "news-search-staging": "news-articles",
    "acme-products-rich-prod": "acme-products-rich",
}

# Per-scenario UBI converter expectations (AC-1 / D-2).
_EXPECTED_UBI_CONVERTERS: dict[str, str] = {
    "acme-products-prod": "ctr_threshold",
    "corp-docs-search": "hybrid_ubi_llm",
    "jobs-marketplace-prod": "hybrid_ubi_llm",
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
async def test_full_reseed_produces_8_lists_8_studies_per_rung_correct() -> None:
    """Drive the orchestrator end-to-end + assert AC-1, AC-2, AC-8, AC-10.

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
        reseed_demo_state,
        run_demo_reseed_cleanup,
    )
    from backend.tests.integration.fixtures.es_overlap_probe import (
        _check_local_es_credentials_or_skip,
        _es_base_url,
    )

    _check_local_es_credentials_or_skip()
    es_base_url = _es_base_url()
    if not es_base_url:
        pytest.skip("Elasticsearch unreachable; see docs/03_runbooks/local-dev.md")

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

                async def status_callback(_progress: object) -> None:
                    return None

                summary = await reseed_demo_state(
                    db=db,
                    api_client=api_client,
                    engine_client=engine_client,
                    status_callback=status_callback,
                )
                duration_s = time.monotonic() - started_at

                # AC-1: exactly 8 judgment lists + 8 studies. 3 UBI
                # scenarios × (LLM + UBI) = 6, + news LLM-only = 7, + rich
                # = 8. A count of 7 means the rich scenario silently
                # failed (it's tolerated by the orchestrator) — surface
                # that loudly rather than passing on a degraded demo.
                jl_count = await db.scalar(text("SELECT COUNT(*) FROM judgment_lists"))
                study_count = await db.scalar(text("SELECT COUNT(*) FROM studies"))
                assert jl_count == 8, (
                    f"expected exactly 8 judgment lists; got {jl_count} "
                    "(7 usually means the rich scenario failed — check OpenAI "
                    "key + samples/products.json)"
                )
                assert study_count == 8, (
                    f"expected exactly 8 studies; got {study_count} "
                    "(7 usually means the rich scenario failed)"
                )

                # AC-1 (continued): per UBI-enabled scenario, two lists —
                # one LLM (NULL generation_params) + one UBI with the
                # right converter.
                for slug, expected_converter in _EXPECTED_UBI_CONVERTERS.items():
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
                # returns the expected rung for every scenario.
                for slug, expected_rung in _EXPECTED_RUNGS.items():
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

                # AC-8: hard wall-clock ceiling (spec cycle-3 patch — hard
                # assert, not p95).
                assert duration_s < 1140, (
                    f"reseed wall-clock {duration_s:.1f}s exceeded AC-8 ceiling 1140s"
                )
                print(f"\nfull-reseed duration: {duration_s:.1f}s (AC-8 ceiling 1140s)")

                # AC-10: cleanup pass deletes both UBI indices.
                await run_demo_reseed_cleanup(engine_client)
                for index in ("ubi_queries", "ubi_events"):
                    resp = await engine_client.get(f"{es_base_url}/{index}")
                    assert resp.status_code == 404, (
                        f"cleanup did not delete {index!r}: HTTP {resp.status_code}"
                    )
    finally:
        await pg_engine.dispose()

    assert summary.duration_ms > 0
    assert summary.studies_completed == 8
