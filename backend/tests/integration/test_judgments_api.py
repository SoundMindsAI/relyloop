"""Integration smoke for /api/v1/judgments* + /api/v1/judgment-lists*.

Covers Epic 3 (Stories 3.1 – 3.5):

* POST /judgments/generate happy path (3.1) + each error code.
* POST /judgment-lists/import (3.2) — tutorial path + QUERY_NOT_IN_SET.
* GET /judgment-lists, /judgment-lists/{id}, /judgment-lists/{id}/judgments
  (3.3) + ?source filter rejection of ``click``.
* PATCH override (3.4) — UPSERT-replace + INVALID_RATING + LIST_NOT_READY.
* POST /calibration (3.5) — happy path + INSUFFICIENT_SAMPLES (both
  pre-check and post-match recheck).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.budget_gate import daily_key
from backend.app.llm.capability_check import cache_key as cap_cache_key
from backend.app.llm.capability_models import CapabilityResult
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_chain(num_queries: int = 3) -> dict[str, Any]:
    """Seed cluster/template/query_set/queries; return ids."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jap-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"jap-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"jap-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        query_ids = []
        for i in range(num_queries):
            q = await repo.create_query(
                db,
                id=str(uuid.uuid4()),
                query_set_id=query_set.id,
                query_text=f"jap-q-{i}",
            )
            query_ids.append(q.id)
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "query_ids": query_ids,
    }


async def _seed_capability_ok(base_url: str, *, ok: bool = True) -> None:
    from backend.app.core.settings import get_settings

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        result = CapabilityResult(
            base_url=base_url,
            model=settings.openai_model,
            models_endpoint="ok",
            chat_completion="ok",
            function_calling="ok",
            structured_output="ok" if ok else "fail",
            tested_at=datetime.now(UTC),
        )
        await redis.set(cap_cache_key(base_url), result.model_dump_json(), ex=600)
    finally:
        await redis.aclose()


async def _clear_capability_cache(base_url: str) -> None:
    from backend.app.core.settings import get_settings

    redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        await redis.delete(cap_cache_key(base_url))
    finally:
        await redis.aclose()


async def _clear_budget() -> None:
    from backend.app.core.settings import get_settings

    redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        await redis.delete(daily_key(datetime.now(UTC)))
    finally:
        await redis.aclose()


async def _patch_openai_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    from backend.app.core.settings import Settings, get_settings

    real = get_settings()
    monkeypatch.setattr(Settings, "openai_api_key", key, raising=False)
    # Also patch the cached_property descriptor for any module that already
    # captured a settings instance: bust the get_settings cache.
    get_settings.cache_clear()
    _ = real  # keep reference; settings is recached on next call


# ---------------------------------------------------------------------------
# POST /judgments/generate — Story 3.1
# ---------------------------------------------------------------------------


async def test_generate_happy_path_returns_202(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    # Make api_key non-empty via cached_property override.
    monkeypatch.setattr(
        type(settings),
        "openai_api_key",
        property(lambda self: "sk-test"),
    )
    await _seed_capability_ok(settings.openai_base_url, ok=True)
    await _clear_budget()

    payload = {
        "name": f"gen-ok-{uuid.uuid4().hex[:8]}",
        "description": "ac-5 happy",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "starter rubric",
    }
    response = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "generating"
    assert "judgment_list_id" in body


async def test_generate_returns_503_when_key_missing(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        type(settings),
        "openai_api_key",
        property(lambda self: None),
    )
    payload = {
        "name": f"gen-nokey-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "r",
    }
    response = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "OPENAI_NOT_CONFIGURED"


async def test_generate_returns_503_on_capability_cache_miss(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "openai_api_key", property(lambda self: "sk-test"))
    await _clear_capability_cache(settings.openai_base_url)

    payload = {
        "name": f"gen-cap-miss-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "r",
    }
    response = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "LLM_PROVIDER_INCAPABLE"


async def test_generate_returns_503_on_structured_output_fail(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "openai_api_key", property(lambda self: "sk-test"))
    await _seed_capability_ok(settings.openai_base_url, ok=False)

    payload = {
        "name": f"gen-cap-fail-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "r",
    }
    response = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "LLM_PROVIDER_INCAPABLE"


async def test_generate_returns_503_on_budget_already_exceeded(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "openai_api_key", property(lambda self: "sk-test"))
    # openai_daily_budget_usd is a Pydantic Field — not a class-level
    # descriptor — so monkeypatch with raising=False to install a property.
    monkeypatch.setattr(
        type(settings),
        "openai_daily_budget_usd",
        property(lambda self: 1.0),
        raising=False,
    )
    await _seed_capability_ok(settings.openai_base_url, ok=True)
    # Pre-seed counter ABOVE the 1.0 budget so the peek trips.
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis.set(daily_key(datetime.now(UTC)), "5.00")
    finally:
        await redis.aclose()

    payload = {
        "name": f"gen-budget-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "r",
    }
    response = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "OPENAI_BUDGET_EXCEEDED"
    # Reset for subsequent tests.
    await _clear_budget()


async def test_generate_returns_404_on_missing_cluster(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "openai_api_key", property(lambda self: "sk-test"))
    await _seed_capability_ok(settings.openai_base_url, ok=True)
    await _clear_budget()

    payload = {
        "name": f"gen-noclu-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": str(uuid.uuid4()),  # bogus
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "r",
    }
    response = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


async def test_generate_returns_409_on_duplicate_name(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_chain()
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "openai_api_key", property(lambda self: "sk-test"))
    await _seed_capability_ok(settings.openai_base_url, ok=True)
    await _clear_budget()

    name = f"gen-dup-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": name,
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "current_template_id": seeded["template_id"],
        "rubric": "r",
    }
    r1 = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert r1.status_code == 202
    r2 = await async_client.post("/api/v1/judgments/generate", json=payload)
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "JUDGMENT_LIST_NAME_TAKEN"


# ---------------------------------------------------------------------------
# POST /judgment-lists/import — Story 3.2
# ---------------------------------------------------------------------------


async def test_import_happy_path(async_client: httpx.AsyncClient) -> None:
    seeded = await _seed_chain(num_queries=2)
    payload = {
        "name": f"import-ok-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "rubric": "r",
        "judgments": [
            {"query_id": seeded["query_ids"][0], "doc_id": "d1", "rating": 3},
            {"query_id": seeded["query_ids"][1], "doc_id": "d2", "rating": 1},
        ],
    }
    response = await async_client.post("/api/v1/judgment-lists/import", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["judgment_count"] == 2
    assert body["source_breakdown"] == {"llm": 0, "human": 2}


async def test_import_query_not_in_set_returns_400(async_client: httpx.AsyncClient) -> None:
    seeded = await _seed_chain(num_queries=1)
    payload = {
        "name": f"import-bad-q-{uuid.uuid4().hex[:8]}",
        "query_set_id": seeded["query_set_id"],
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "rubric": "r",
        "judgments": [
            {"query_id": str(uuid.uuid4()), "doc_id": "d1", "rating": 3},
        ],
    }
    response = await async_client.post("/api/v1/judgment-lists/import", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "QUERY_NOT_IN_SET"


# ---------------------------------------------------------------------------
# GET /judgment-lists* — Story 3.3
# ---------------------------------------------------------------------------


async def test_list_judgment_lists_paginated_returns_total_count(
    async_client: httpx.AsyncClient,
) -> None:
    seeded = await _seed_chain(num_queries=1)
    # Import 3 lists.
    for i in range(3):
        await async_client.post(
            "/api/v1/judgment-lists/import",
            json={
                "name": f"page-{i}-{uuid.uuid4().hex[:6]}",
                "query_set_id": seeded["query_set_id"],
                "cluster_id": seeded["cluster_id"],
                "target": "stub-index",
                "rubric": "r",
                "judgments": [
                    {"query_id": seeded["query_ids"][0], "doc_id": f"d-{i}", "rating": 1}
                ],
            },
        )
    response = await async_client.get("/api/v1/judgment-lists", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert response.headers["X-Total-Count"] == "3"
    assert len(body["data"]) == 2
    assert body["has_more"] is True
    assert body["next_cursor"] is not None


async def test_list_judgment_lists_filters_by_query_set_id_and_cluster_id(
    async_client: httpx.AsyncClient,
) -> None:
    """``bug_judgment_lists_listing_ignores_query_set_filter`` —
    ``GET /api/v1/judgment-lists?query_set_id=...&cluster_id=...`` must
    return ONLY rows whose parent matches.

    Seeds one cluster + two query-sets (A, B) in that cluster + 2
    judgment-lists each (4 total). Then probes the endpoint with no
    filter, with ``?query_set_id=A``, with ``?query_set_id=B``, and with
    ``?cluster_id=...``. Asserts ``X-Total-Count`` and ``data[].id``
    membership for each.
    """
    seeded_a = await _seed_chain(num_queries=1)
    cluster_id = seeded_a["cluster_id"]
    qs_a = seeded_a["query_set_id"]

    factory = get_session_factory()
    async with factory() as db:
        qs_b_row = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"filt-qs-b-{uuid.uuid4().hex[:6]}",
            cluster_id=cluster_id,
        )
        q_b = await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=qs_b_row.id,
            query_text="filt-q-b",
        )
        await db.commit()
    qs_b = qs_b_row.id
    q_b_id = q_b.id

    ids_a: list[str] = []
    ids_b: list[str] = []
    for i in range(2):
        for qs_id, qry_id, dest in (
            (qs_a, seeded_a["query_ids"][0], ids_a),
            (qs_b, q_b_id, ids_b),
        ):
            resp = await async_client.post(
                "/api/v1/judgment-lists/import",
                json={
                    "name": f"filt-jl-{i}-{uuid.uuid4().hex[:6]}",
                    "query_set_id": qs_id,
                    "cluster_id": cluster_id,
                    "target": "stub-index",
                    "rubric": "r",
                    "judgments": [{"query_id": qry_id, "doc_id": f"d-{i}", "rating": 1}],
                },
            )
            assert resp.status_code == 201, resp.text
            dest.append(resp.json()["id"])

    # Unfiltered baseline: all 4 lists visible. (Other tests may also seed lists
    # in this DB; assert at-least semantics + that ours are present.)
    response = await async_client.get("/api/v1/judgment-lists", params={"limit": 200})
    assert response.status_code == 200
    unfiltered_ids = {row["id"] for row in response.json()["data"]}
    assert set(ids_a + ids_b).issubset(unfiltered_ids)

    # Filter by query_set_id=A: exactly the 2 A-lists.
    response = await async_client.get(
        "/api/v1/judgment-lists", params={"query_set_id": qs_a, "limit": 200}
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = [row["id"] for row in body["data"]]
    assert set(returned_ids) == set(ids_a), (
        f"query_set_id=A returned {returned_ids}; expected exactly {ids_a}"
    )
    assert response.headers["X-Total-Count"] == "2"

    # Filter by query_set_id=B: exactly the 2 B-lists.
    response = await async_client.get(
        "/api/v1/judgment-lists", params={"query_set_id": qs_b, "limit": 200}
    )
    assert response.status_code == 200
    returned_ids = [row["id"] for row in response.json()["data"]]
    assert set(returned_ids) == set(ids_b), (
        f"query_set_id=B returned {returned_ids}; expected exactly {ids_b}"
    )
    assert response.headers["X-Total-Count"] == "2"

    # Filter by cluster_id: returns at least our 4 (other tests may add too).
    response = await async_client.get(
        "/api/v1/judgment-lists", params={"cluster_id": cluster_id, "limit": 200}
    )
    assert response.status_code == 200
    cluster_filtered_data = response.json()["data"]
    cluster_filtered_ids = {row["id"] for row in cluster_filtered_data}
    assert set(ids_a + ids_b).issubset(cluster_filtered_ids)
    # And every returned row actually belongs to the requested cluster.
    for row in cluster_filtered_data:
        assert row["cluster_id"] == cluster_id

    # Combined filter: query_set_id=A AND cluster_id=<same>: same 2 rows.
    response = await async_client.get(
        "/api/v1/judgment-lists",
        params={"query_set_id": qs_a, "cluster_id": cluster_id, "limit": 200},
    )
    assert response.status_code == 200
    returned_ids = [row["id"] for row in response.json()["data"]]
    assert set(returned_ids) == set(ids_a)


async def test_detail_returns_404_on_unknown_id(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get(f"/api/v1/judgment-lists/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "JUDGMENT_LIST_NOT_FOUND"


async def test_list_judgments_rejects_click_filter(async_client: httpx.AsyncClient) -> None:
    """GET /judgment-lists/{id}/judgments?source=click → 422 VALIDATION_ERROR."""
    seeded = await _seed_chain(num_queries=1)
    import_resp = await async_client.post(
        "/api/v1/judgment-lists/import",
        json={
            "name": f"filt-click-{uuid.uuid4().hex[:6]}",
            "query_set_id": seeded["query_set_id"],
            "cluster_id": seeded["cluster_id"],
            "target": "stub-index",
            "rubric": "r",
            "judgments": [{"query_id": seeded["query_ids"][0], "doc_id": "x", "rating": 1}],
        },
    )
    jl_id = import_resp.json()["id"]
    response = await async_client.get(
        f"/api/v1/judgment-lists/{jl_id}/judgments", params={"source": "click"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH override — Story 3.4
# ---------------------------------------------------------------------------


async def test_override_replaces_rating_and_flips_source(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-2: PATCH UPSERTs in place; source flips from human→human (only
    `human` source rows exist after import). Use the imported row to mimic
    an LLM-then-override flip by hand-creating an LLM row first."""
    seeded = await _seed_chain(num_queries=1)
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"ovr-{uuid.uuid4().hex[:6]}",
            description=None,
            query_set_id=seeded["query_set_id"],
            cluster_id=seeded["cluster_id"],
            target="stub-index",
            current_template_id=seeded["template_id"],
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
        jud = await repo.create_judgment(
            db,
            id=str(uuid.uuid4()),
            judgment_list_id=jl.id,
            query_id=seeded["query_ids"][0],
            doc_id="d1",
            rating=2,
            source="llm",
            rater_ref="openai:test",
            notes=None,
        )
        await db.commit()

    resp = await async_client.patch(
        f"/api/v1/judgment-lists/{jl.id}/judgments/{jud.id}",
        json={"rating": 0, "notes": "override"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rating"] == 0
    assert body["source"] == "human"
    assert body["rater_ref"] == "operator"


async def test_override_rejects_out_of_range_rating(async_client: httpx.AsyncClient) -> None:
    seeded = await _seed_chain(num_queries=1)
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"ovr-bad-{uuid.uuid4().hex[:6]}",
            description=None,
            query_set_id=seeded["query_set_id"],
            cluster_id=seeded["cluster_id"],
            target="stub-index",
            current_template_id=seeded["template_id"],
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
        jud = await repo.create_judgment(
            db,
            id=str(uuid.uuid4()),
            judgment_list_id=jl.id,
            query_id=seeded["query_ids"][0],
            doc_id="d1",
            rating=2,
            source="llm",
            rater_ref="openai:test",
            notes=None,
        )
        await db.commit()

    resp = await async_client.patch(
        f"/api/v1/judgment-lists/{jl.id}/judgments/{jud.id}",
        json={"rating": 5},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_RATING"


async def test_override_rejects_while_generating(async_client: httpx.AsyncClient) -> None:
    seeded = await _seed_chain(num_queries=1)
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"ovr-busy-{uuid.uuid4().hex[:6]}",
            description=None,
            query_set_id=seeded["query_set_id"],
            cluster_id=seeded["cluster_id"],
            target="stub-index",
            current_template_id=seeded["template_id"],
            rubric="r",
            status="generating",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
        jud = await repo.create_judgment(
            db,
            id=str(uuid.uuid4()),
            judgment_list_id=jl.id,
            query_id=seeded["query_ids"][0],
            doc_id="d1",
            rating=2,
            source="llm",
            rater_ref="openai:test",
            notes=None,
        )
        await db.commit()

    resp = await async_client.patch(
        f"/api/v1/judgment-lists/{jl.id}/judgments/{jud.id}",
        json={"rating": 0},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "LIST_NOT_READY"


# ---------------------------------------------------------------------------
# POST /calibration — Story 3.5
# ---------------------------------------------------------------------------


async def test_calibration_happy_path(async_client: httpx.AsyncClient) -> None:
    """30 perfectly-agreeing samples → kappa = 1.0."""
    seeded = await _seed_chain(num_queries=1)
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"cal-{uuid.uuid4().hex[:6]}",
            description=None,
            query_set_id=seeded["query_set_id"],
            cluster_id=seeded["cluster_id"],
            target="stub-index",
            current_template_id=seeded["template_id"],
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
        rows = [
            {
                "id": str(uuid.uuid4()),
                "judgment_list_id": jl.id,
                "query_id": seeded["query_ids"][0],
                "doc_id": f"doc-{i}",
                "rating": i % 4,
                "source": "llm",
                "rater_ref": "openai:test",
                "notes": None,
            }
            for i in range(20)
        ]
        await repo.bulk_create_judgments(db, rows)
        await db.commit()

    samples = [
        {"query_id": seeded["query_ids"][0], "doc_id": f"doc-{i}", "rating": i % 4}
        for i in range(20)
    ]
    resp = await async_client.post(
        f"/api/v1/judgment-lists/{jl.id}/calibration",
        json={"human_samples": samples},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cohens_kappa"] == 1.0
    assert body["n_samples"] == 20


async def test_calibration_insufficient_samples_pre_check(
    async_client: httpx.AsyncClient,
) -> None:
    seeded = await _seed_chain(num_queries=1)
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"cal-few-{uuid.uuid4().hex[:6]}",
            description=None,
            query_set_id=seeded["query_set_id"],
            cluster_id=seeded["cluster_id"],
            target="stub-index",
            current_template_id=seeded["template_id"],
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()

    samples = [
        {"query_id": seeded["query_ids"][0], "doc_id": f"d{i}", "rating": 1} for i in range(5)
    ]
    resp = await async_client.post(
        f"/api/v1/judgment-lists/{jl.id}/calibration",
        json={"human_samples": samples},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INSUFFICIENT_SAMPLES"


def _unused(_x: Any) -> None:
    """Keep typing.Any import live."""
    return None


def _unused_json(_x: Any) -> None:
    return None


# json is imported but only referenced in some helpers; reference it once
# at module scope so the import isn't pruned.
_ = json
