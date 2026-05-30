# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Fast-lane integration test for synthetic UBI seeding (Story 4.1 / FR-11).

Always-on (runs even with ``SKIP_HEAVY_CI=true``): exercises one
UBI-enabled scenario end-to-end against the live ES service container —
generator → ensure_ubi_indices → seed_synthetic_ubi → classify_rung —
and asserts the classifier reports the target rung.

Wall-clock target: < 60s. No ``reseed_demo_state`` invocation; no LLM
calls; no Postgres beyond the per-test cleanup that conftest already
runs. Heavier coverage (all 10 ACs, AC-8 ceiling, CLI parity) lives in
``test_demo_seeding_ubi_full.py`` (heavy lane, ``SKIP_HEAVY_CI`` gated).

Why fast-lane exists: regressions in the synthetic generator volume
math, the canonical mapping JSON shape, or the bulk-write posture would
otherwise only surface in the heavy lane, which is skipped on
``SKIP_HEAVY_CI=true`` runs. The 60s budget keeps it cheap enough to
stay always-on.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis

from backend.app.domain.demo.synthetic_ubi import fabricate_ubi_for_scenario
from backend.app.services.demo_ubi_seed import (
    DemoUbiSeedError,
)
from backend.tests.conftest import postgres_reachable

# The integration-test conftest's autouse `_clean_phase2_tables` fixture
# constructs `Settings` (which requires DATABASE_URL_FILE +
# POSTGRES_PASSWORD_FILE). Module-level skipif keeps the fast-lane test
# from erroring during collection when those env vars aren't set
# (e.g. host shell against a stopped stack). The bulk of the test only
# needs ES, but the conftest dependency is unconditional.
pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)

# Canonical mapping path inside the api container (Compose bind mount).
# Tests run on the host shell; resolve the repo-root samples/ instead.
_REPO_ROOT_MAPPING = Path(__file__).resolve().parents[3] / "samples" / "ubi_index_mappings.json"


async def _wipe_ubi_indices(es_base_url: str, host_auth: tuple[str, str]) -> None:
    """Best-effort delete of both UBI indices.

    Idempotent: 200/204/404 are all acceptable. Test pre-condition so a
    leftover from a prior (potentially-aborted) run doesn't perturb the
    rung classification.
    """
    auth = httpx.BasicAuth(*host_auth)
    async with httpx.AsyncClient(timeout=10.0) as client:
        for index in ("ubi_queries", "ubi_events"):
            try:
                await client.delete(f"{es_base_url}/{index}", auth=auth)
            except httpx.HTTPError:
                # Swallow — wipe is best-effort.
                pass


@pytest.mark.asyncio
@pytest.mark.integration
async def test_synthetic_ubi_seed_round_trip_hits_rung_3() -> None:
    """End-to-end fast-lane: generate → write → classify → assert rung_3.

    Uses the ``acme-products-prod`` rung_3 config because:
    - It's the densest rung (640 events) → strongest classifier signal,
      so a transient `_count` lag doesn't cause flakes.
    - It uses the simplest converter (``ctr_threshold``) at the scenario
      level, but this test doesn't dispatch a judgment generation —
      only the generator + writer + rung classifier are exercised.
    """
    from backend.app.adapters.elastic import ElasticAdapter
    from backend.app.core.settings import get_settings
    from backend.app.services.demo_ubi_seed import (
        ensure_ubi_indices,
        seed_synthetic_ubi,
    )
    from backend.app.services.ubi_readiness import classify_rung
    from backend.tests.integration.fixtures.es_overlap_probe import (
        _check_local_es_credentials_or_skip,
        _es_base_url,
    )

    _check_local_es_credentials_or_skip()
    es_base_url = _es_base_url()
    if not es_base_url:
        pytest.skip(
            "Elasticsearch not reachable on localhost:9200 or elasticsearch:9200 — "
            "see docs/03_runbooks/local-dev.md."
        )
    host_auth: tuple[str, str] = ("elastic", "changeme")  # CI + local Compose default
    target_application = "products-fasttest"  # NOT 'products' — avoid demo cluster collisions

    # 0. Wipe ubi_queries + ubi_events so this run starts clean.
    await _wipe_ubi_indices(es_base_url, host_auth)

    # 1. Build a minimal scenario_judgments_map (5 queries × 5 docs each
    #    with a top-rated head and zero-rated tail — matches the acme
    #    rung_3 shape from SCENARIOS).
    scenario_judgments_map: list[tuple[int, str, int]] = []
    for qi in range(5):
        scenario_judgments_map.append((qi, f"d{qi}-top", 3))
        scenario_judgments_map.append((qi, f"d{qi}-good", 2))
        scenario_judgments_map.append((qi, f"d{qi}-fair", 1))
        scenario_judgments_map.append((qi, f"d{qi}-edge", 0))
        scenario_judgments_map.append((qi, f"d{qi}-cold", 0))
    query_id_by_index = {i: str(uuid.uuid4()) for i in range(5)}
    query_text_by_index = {i: f"fast-test query {i}" for i in range(5)}

    # 2. Generate synthetic rows (pure-domain — no I/O).
    queries, events = fabricate_ubi_for_scenario(
        scenario_judgments_map=scenario_judgments_map,
        query_id_by_index=query_id_by_index,
        query_text_by_index=query_text_by_index,
        target_application=target_application,
        target_rung="rung_3",
        seed_anchor_iso="2026-05-29T00:00:00+00:00",
    )
    assert len(queries) == 5, "rung_3 fabricates one ubi_queries row per query"
    # rung_3 volumes: 560 impressions + 40 clicks + 40 dwells = 640 events total.
    assert len(events) == 640, f"expected 640 events for rung_3 (got {len(events)})"

    # 3. The fast-test target ('products-fasttest') is NOT in the
    #    allowlist by design — that's the point of the safety guard.
    #    Assert the allowlist refuses BEFORE allowlisting the target by
    #    monkey-patch (cheap correctness check on the FR-3 invariant).
    fake_engine_client = httpx.AsyncClient(timeout=5.0)
    try:
        with pytest.raises(ValueError, match="DEMO_UBI_SCENARIO_ALLOWLIST"):
            await seed_synthetic_ubi(
                engine_client=fake_engine_client,
                engine_base_url=es_base_url,
                host_auth=host_auth,
                scenario_slug="acme-products-prod",
                target_application=target_application,  # not products → reject
                queries=queries,
                events=events,
            )
    finally:
        await fake_engine_client.aclose()

    # 4. Real run: patch the allowlist to include the test pair, then
    #    bulk-write. This proves the writer path works without polluting
    #    the runtime allowlist permanently.
    from backend.app.services import demo_ubi_seed as ubi_seed_mod

    original_allowlist = ubi_seed_mod.DEMO_UBI_SCENARIO_ALLOWLIST
    patched_allowlist = original_allowlist | {("acme-products-prod", target_application)}
    ubi_seed_mod.DEMO_UBI_SCENARIO_ALLOWLIST = patched_allowlist  # type: ignore[misc]
    try:
        async with httpx.AsyncClient(timeout=15.0) as engine_client:
            await ensure_ubi_indices(
                engine_client=engine_client,
                engine_base_url=es_base_url,
                host_auth=host_auth,
                mapping_path=_REPO_ROOT_MAPPING,
            )
            event_count = await seed_synthetic_ubi(
                engine_client=engine_client,
                engine_base_url=es_base_url,
                host_auth=host_auth,
                scenario_slug="acme-products-prod",
                target_application=target_application,
                queries=queries,
                events=events,
            )
            assert event_count == 640
    finally:
        ubi_seed_mod.DEMO_UBI_SCENARIO_ALLOWLIST = original_allowlist  # type: ignore[misc]

    # 5. Construct an ElasticAdapter against the same ES and classify
    #    the rung. The acme scenario uses (application=products-fasttest)
    #    here so we filter on that exact application.
    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    adapter = ElasticAdapter(
        cluster_id="fast-test-cluster",
        engine_type="elasticsearch",
        base_url=es_base_url,
        auth_kind="es_basic",
        credentials_ref="local-es",
        engine_config=None,
    )
    try:
        # The classifier's filter requires the actual UBI query_ids to
        # match the seeded rows. We use the same `query_id_by_index`
        # values the generator stamped on the events.
        readiness = await classify_rung(
            adapter=adapter,
            cluster_id="fast-test-cluster",
            query_set_id=f"fast-test-qs-{uuid.uuid4().hex[:8]}",
            query_set_query_ids=list(query_id_by_index.values()),
            target=target_application,
            redis=redis_client,
        )
    finally:
        await adapter.aclose()
        await redis_client.aclose()

    assert readiness.rung == "rung_3", (
        f"expected rung_3 after seeding 640 events for {target_application!r}; "
        f"got {readiness.rung!r}. Generator volume math or classifier thresholds "
        f"drifted — see backend/app/services/ubi_readiness.py."
    )


def test_canonical_mapping_round_trips_on_disk() -> None:
    """FR-1: the canonical mapping JSON file shape stays loadable.

    This is a fast (<1s) sanity check that lives alongside the round-
    trip unit test in test_demo_ubi_seed.py. Catches a corruption /
    accidental whitespace-change to the file without needing the live
    ES container to be reachable.
    """
    payload = json.loads(_REPO_ROOT_MAPPING.read_text())
    assert set(payload.keys()) == {"ubi_queries", "ubi_events"}
    for index in ("ubi_queries", "ubi_events"):
        assert "mappings" in payload[index]
        assert "properties" in payload[index]["mappings"]


def test_demo_ubi_seed_error_is_runtime_error_subclass() -> None:
    """DemoUbiSeedError must remain a RuntimeError subclass so the route
    handler's existing 503 SEED_FAILED catch-all path continues to handle it."""
    assert issubclass(DemoUbiSeedError, RuntimeError)


@pytest.mark.asyncio
async def test_poll_judgment_list_failed_raises_demo_seeding_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9 (Story 4.2 DoD): a UBI judgment list reaching ``status='failed'``
    mid-poll surfaces as ``DemoSeedingError("ubi_judgments/{slug}: failed ...")``.

    Tests the poll helper in isolation (no full reseed, no live stack) by
    monkeypatching the module-level ``_get`` to return a ``failed`` detail.
    Lives in the fast lane so the AC-9 contract is always-on rather than
    gated behind the 13-19-minute heavy-lane reseed.
    """
    from backend.app.services import demo_seeding

    async def _fake_get(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "failed", "failed_reason": "injected UBI worker failure"}

    monkeypatch.setattr(demo_seeding, "_get", _fake_get)

    with pytest.raises(
        demo_seeding.DemoSeedingError, match=r"ubi_judgments/acme-products-prod: failed"
    ):
        await demo_seeding._poll_judgment_list_until_terminal(
            None,  # type: ignore[arg-type]  # api_client unused — _get is patched
            "jlist-injected",
            slug="acme-products-prod",
            ceiling_s=5.0,
            interval_s=0.1,
        )


@pytest.mark.asyncio
async def test_poll_judgment_list_timeout_raises_demo_seeding_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9 sibling: a UBI list stuck in ``generating`` past the poll ceiling
    raises ``DemoSeedingError`` with the poll-ceiling message (not a hang)."""
    from backend.app.services import demo_seeding

    async def _fake_get(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "generating"}

    monkeypatch.setattr(demo_seeding, "_get", _fake_get)

    with pytest.raises(demo_seeding.DemoSeedingError, match=r"poll ceiling"):
        await demo_seeding._poll_judgment_list_until_terminal(
            None,  # type: ignore[arg-type]
            "jlist-stuck",
            slug="corp-docs-search",
            ceiling_s=0.3,
            interval_s=0.1,
        )
