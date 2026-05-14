"""Integration tests for /api/v1/query-sets/{set_id}/queries* (feat_query_inline_crud).

Covers ACs 1–17 + 24 (cross-set anti-enumeration) + 25–26 (?since) + 28
(empty-PATCH no-op) at the router layer. All assertions go through the
``async_client`` httpx wrapper so the full FastAPI request/response
pipeline (Pydantic validation, error envelope, ``X-Total-Count`` header,
OpenAPI ``responses`` wiring) is exercised end-to-end.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
import uuid_utils

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_set(num_queries: int = 3) -> tuple[str, list[str]]:
    """Seed cluster → query_set → N queries; return (set_id, [query_ids])."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qrt-c-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qrt-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        query_ids: list[str] = []
        for i in range(num_queries):
            q = await repo.create_query(
                db,
                id=str(uuid_utils.uuid7()),
                query_set_id=qs.id,
                query_text=f"q-{i}",
                reference_answer=None if i % 2 == 0 else f"ref-{i}",
                query_metadata={"i": i} if i % 2 == 0 else None,
            )
            query_ids.append(q.id)
            # Ensure distinct UUIDv7 ms timestamps so ?since-filter
            # boundary tests (AC-25, AC-26) don't flake when two queries
            # share the same 48-bit ms prefix. Matches the precedent at
            # backend/tests/integration/test_phase2_repos.py:131 — same
            # "ms-collision under fast CI execution" failure mode.
            # See planned_features/bug_query_inline_crud_since_filter_uuidv7_ms_collision/.
            await asyncio.sleep(0.01)
        await db.commit()
    return qs.id, query_ids


async def _seed_judgment_for(set_id: str, query_id: str) -> str:
    """Create a judgment_list + 1 judgment referencing ``query_id``. Returns jl.id."""
    factory = get_session_factory()
    async with factory() as db:
        qs = await repo.get_query_set(db, set_id)
        assert qs is not None
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qrt-jl-{uuid.uuid4().hex[:8]}",
            query_set_id=set_id,
            cluster_id=qs.cluster_id,
            target="t",
            rubric="r",
            status="complete",
        )
        await repo.create_judgment(
            db,
            id=str(uuid_utils.uuid7()),
            judgment_list_id=jl.id,
            query_id=query_id,
            doc_id="doc-1",
            rating=2,
            source="llm",
            rater_ref="openai:test",
        )
        await db.commit()
        return jl.id


# ===========================================================================
# GET /api/v1/query-sets/{set_id}/queries — ACs 1–4 + 25–26
# ===========================================================================


async def test_ac_1_list_with_judgment_count(async_client: httpx.AsyncClient) -> None:
    set_id, [q1, q2, q3] = await _seed_set(3)
    await _seed_judgment_for(set_id, q1)
    # q2 → 0 judgments, q3 → 0 judgments (only q1 has one)

    resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    body = resp.json()
    counts_by_id = {r["id"]: r["judgment_count"] for r in body["data"]}
    assert counts_by_id == {q1: 1, q2: 0, q3: 0}
    assert body["next_cursor"] is None
    assert body["has_more"] is False


async def test_ac_2_cursor_pagination(async_client: httpx.AsyncClient) -> None:
    set_id, query_ids = await _seed_set(5)

    resp1 = await async_client.get(f"/api/v1/query-sets/{set_id}/queries?limit=3")
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert len(body1["data"]) == 3
    assert body1["has_more"] is True
    assert body1["next_cursor"] is not None
    assert [r["id"] for r in body1["data"]] == query_ids[:3]

    resp2 = await async_client.get(
        f"/api/v1/query-sets/{set_id}/queries?limit=3&cursor={body1['next_cursor']}"
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert [r["id"] for r in body2["data"]] == query_ids[3:]
    # No row appears in both pages.
    assert set(r["id"] for r in body1["data"]).isdisjoint({r["id"] for r in body2["data"]})


async def test_ac_3_invalid_cursor_422(async_client: httpx.AsyncClient) -> None:
    set_id, _ = await _seed_set(1)
    resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries?cursor=not-base64-at-all")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error_code"] == "VALIDATION_ERROR"
    assert detail["retryable"] is False


async def test_ac_4_missing_set_returns_query_set_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    fake_set = str(uuid_utils.uuid7())
    resp = await async_client.get(f"/api/v1/query-sets/{fake_set}/queries")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_patch_missing_parent_set_returns_query_set_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    """GPT-5.5 phase-1 F1: PATCH against a nonexistent parent set → 404 QUERY_SET_NOT_FOUND."""
    fake_set = str(uuid_utils.uuid7())
    fake_qid = str(uuid_utils.uuid7())
    resp = await async_client.patch(
        f"/api/v1/query-sets/{fake_set}/queries/{fake_qid}",
        json={"query_text": "x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_delete_missing_parent_set_returns_query_set_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    """GPT-5.5 phase-1 F1: DELETE against a nonexistent parent set → 404 QUERY_SET_NOT_FOUND."""
    fake_set = str(uuid_utils.uuid7())
    fake_qid = str(uuid_utils.uuid7())
    resp = await async_client.delete(f"/api/v1/query-sets/{fake_set}/queries/{fake_qid}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_get_limit_zero_returns_422(async_client: httpx.AsyncClient) -> None:
    """GPT-5.5 phase-1 F2: ?limit=0 is below the ge=1 bound."""
    set_id, _ = await _seed_set(1)
    resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries?limit=0")
    assert resp.status_code == 422


async def test_get_limit_above_max_returns_422(async_client: httpx.AsyncClient) -> None:
    """GPT-5.5 phase-1 F2: ?limit=201 is above the le=200 bound."""
    set_id, _ = await _seed_set(1)
    resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries?limit=201")
    assert resp.status_code == 422


async def test_get_since_malformed_returns_422(async_client: httpx.AsyncClient) -> None:
    """GPT-5.5 phase-1 F2: malformed ?since= fails Pydantic datetime coercion."""
    set_id, _ = await _seed_set(1)
    resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries?since=not-a-date")
    assert resp.status_code == 422


async def test_ac_25_since_lower_bound_inclusive(async_client: httpx.AsyncClient) -> None:
    """``?since`` filter respects UUIDv7 lower-bound. The filter is inclusive.

    Per GPT-5.5 phase-1 F5: tighten the assertion. We construct the
    ``?since`` value by subtracting 1ms from q[2]'s timestamp so the
    boundary is unambiguously **before** q[2] — meaning q[2] MUST be
    included (along with q[3], q[4]). Total = 3 rows exactly.
    """
    set_id, query_ids = await _seed_set(5)

    # Extract q[2]'s embedded UUIDv7 timestamp (first 48 bits in ms).
    hex_no_dashes = query_ids[2].replace("-", "")
    ts_ms = int(hex_no_dashes[:12], 16)

    # Subtract 1ms so the ?since boundary is strictly before q[2].
    since_iso = datetime.fromtimestamp((ts_ms - 1) / 1000.0, tz=UTC).isoformat()

    resp = await async_client.get(
        f"/api/v1/query-sets/{set_id}/queries",
        params={"since": since_iso},
    )
    assert resp.status_code == 200
    body = resp.json()
    returned_ids = [r["id"] for r in body["data"]]
    # q[2], q[3], q[4] all included; q[0], q[1] excluded.
    assert query_ids[2] in returned_ids
    assert query_ids[3] in returned_ids
    assert query_ids[4] in returned_ids
    assert query_ids[0] not in returned_ids
    assert query_ids[1] not in returned_ids
    assert int(resp.headers["X-Total-Count"]) == 3


async def test_ac_26_since_plus_cursor_compose(async_client: httpx.AsyncClient) -> None:
    """``?since`` is honoured on the second page (no rows from before reappear)."""
    set_id, query_ids = await _seed_set(8)

    hex_no_dashes = query_ids[1].replace("-", "")
    ts_ms = int(hex_no_dashes[:12], 16)
    since_iso = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).isoformat()

    resp1 = await async_client.get(
        f"/api/v1/query-sets/{set_id}/queries",
        params={"since": since_iso, "limit": 3},
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    page1_ids = [r["id"] for r in body1["data"]]
    assert body1["has_more"] is True
    # No rows before q[1] should appear.
    assert query_ids[0] not in page1_ids

    resp2 = await async_client.get(
        f"/api/v1/query-sets/{set_id}/queries",
        params={"since": since_iso, "limit": 3, "cursor": body1["next_cursor"]},
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    page2_ids = [r["id"] for r in body2["data"]]
    assert query_ids[0] not in page2_ids  # ?since still in effect on page 2


# ===========================================================================
# PATCH /api/v1/query-sets/{set_id}/queries/{query_id} — ACs 5–12 + 28
# ===========================================================================


async def test_ac_5_patch_query_text_only(async_client: httpx.AsyncClient) -> None:
    set_id, [q1, *_] = await _seed_set(2)
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q1}",
        json={"query_text": "new text"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_text"] == "new text"
    # q1 seed: reference_answer=None, query_metadata={"i":0} — unchanged.
    assert body["reference_answer"] is None
    assert body["query_metadata"] == {"i": 0}


async def test_ac_6_patch_query_metadata_whole_object_replace(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(2)
    # q1 seed: query_metadata={"i":0}.  Replace WHOLE object — no deep merge.
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q1}",
        json={"query_metadata": {"new_key": "v"}},
    )
    assert resp.status_code == 200
    assert resp.json()["query_metadata"] == {"new_key": "v"}
    assert "i" not in resp.json()["query_metadata"]


async def test_ac_7_patch_null_reference_answer_clears(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [_, q2, *_] = await _seed_set(3)
    # q2 seed: reference_answer="ref-1"
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q2}",
        json={"reference_answer": None},
    )
    assert resp.status_code == 200
    assert resp.json()["reference_answer"] is None


async def test_ac_8_patch_omitted_key_preserves_value(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [_, q2, *_] = await _seed_set(3)
    # q2 seed: reference_answer="ref-1". Patch only query_text → reference_answer unchanged.
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q2}",
        json={"query_text": "changed"},
    )
    assert resp.status_code == 200
    assert resp.json()["reference_answer"] == "ref-1"


async def test_ac_9_patch_empty_query_text_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(1)
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q1}",
        json={"query_text": ""},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_ac_10_patch_extra_field_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(1)
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q1}",
        json={"id": "new-uuid"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_ac_11_patch_missing_query_404(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, _ = await _seed_set(1)
    fake_qid = str(uuid_utils.uuid7())
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{fake_qid}",
        json={"query_text": "x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_NOT_FOUND"


async def test_ac_12_patch_cross_set_returns_query_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    """Q1 exists in S1; PATCH via /query-sets/S2/queries/Q1 → 404 QUERY_NOT_FOUND."""
    set_id_a, [q_a, *_] = await _seed_set(1)
    set_id_b, _ = await _seed_set(1)
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id_b}/queries/{q_a}",
        json={"query_text": "x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_NOT_FOUND"


async def test_ac_28_patch_empty_body_is_no_op(async_client: httpx.AsyncClient) -> None:
    set_id, [q1, *_] = await _seed_set(1)
    # q1 seed: query_text="q-0", reference_answer=None, query_metadata={"i":0}
    resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q1}",
        json={},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_text"] == "q-0"
    assert body["reference_answer"] is None
    assert body["query_metadata"] == {"i": 0}


# ===========================================================================
# DELETE /api/v1/query-sets/{set_id}/queries/{query_id} — ACs 13–17 + 24
# ===========================================================================


async def test_ac_13_delete_no_judgments_returns_204(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(2)
    resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert resp.status_code == 204
    assert resp.content == b""

    # Verify via LIST that x-total-count decremented and the row is gone.
    list_resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries")
    assert int(list_resp.headers["X-Total-Count"]) == 1
    assert q1 not in {r["id"] for r in list_resp.json()["data"]}

    # PATCH on the deleted query → 404 (existence probe).
    patch_resp = await async_client.patch(
        f"/api/v1/query-sets/{set_id}/queries/{q1}",
        json={"query_text": "x"},
    )
    assert patch_resp.status_code == 404


async def test_ac_14_delete_with_judgments_returns_409(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(1)
    jl_id = await _seed_judgment_for(set_id, q1)

    resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "QUERY_HAS_JUDGMENTS"
    assert detail["retryable"] is False
    assert len(detail["judgment_lists"]) == 1
    assert detail["judgment_lists"][0]["id"] == jl_id
    assert detail["overflow_count"] == 0

    # Row STILL EXISTS — verify via LIST.
    list_resp = await async_client.get(f"/api/v1/query-sets/{set_id}/queries")
    assert q1 in {r["id"] for r in list_resp.json()["data"]}


async def test_ac_15_delete_with_many_lists_overflow(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(1)
    factory = get_session_factory()
    async with factory() as db:
        qs = await repo.get_query_set(db, set_id)
        assert qs is not None
        for i in range(15):
            jl = await repo.create_judgment_list(
                db,
                id=str(uuid_utils.uuid7()),
                name=f"qrt-many-{i:03d}-{uuid.uuid4().hex[:4]}",
                query_set_id=set_id,
                cluster_id=qs.cluster_id,
                target="t",
                rubric="r",
                status="complete",
            )
            await repo.create_judgment(
                db,
                id=str(uuid_utils.uuid7()),
                judgment_list_id=jl.id,
                query_id=q1,
                doc_id=f"doc-{i}",
                rating=2,
                source="llm",
                rater_ref="openai:test",
            )
        await db.commit()

    resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert len(detail["judgment_lists"]) == 10
    assert detail["overflow_count"] == 5


async def test_ac_16_delete_missing_query_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, _ = await _seed_set(1)
    fake_qid = str(uuid_utils.uuid7())
    resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{fake_qid}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_NOT_FOUND"


async def test_ac_17_delete_second_time_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    set_id, [q1, *_] = await _seed_set(1)
    first = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert first.status_code == 204
    second = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert second.status_code == 404
    assert second.json()["detail"]["error_code"] == "QUERY_NOT_FOUND"


async def test_ac_24_delete_cross_set_returns_query_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    set_id_a, [q_a, *_] = await _seed_set(1)
    set_id_b, _ = await _seed_set(1)
    resp = await async_client.delete(f"/api/v1/query-sets/{set_id_b}/queries/{q_a}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_NOT_FOUND"
    # Q_a STILL EXISTS in set A.
    list_resp = await async_client.get(f"/api/v1/query-sets/{set_id_a}/queries")
    assert q_a in {r["id"] for r in list_resp.json()["data"]}


# ===========================================================================
# GPT-5.5 phase-1 F3: structlog event assertions on PATCH / DELETE / 409
# ===========================================================================


async def test_patch_emits_query_updated_structlog(
    async_client: httpx.AsyncClient,
) -> None:
    """PATCH success emits ``query_updated`` with fields_changed; no values logged."""
    import structlog

    set_id, [q1, *_] = await _seed_set(1)
    with structlog.testing.capture_logs() as captured:
        resp = await async_client.patch(
            f"/api/v1/query-sets/{set_id}/queries/{q1}",
            json={"query_text": "redact-me", "reference_answer": "secret-ref"},
        )
    assert resp.status_code == 200

    events = [e for e in captured if e.get("event") == "query_updated"]
    assert len(events) == 1, f"expected 1 query_updated event; got {len(events)}"
    e = events[0]
    assert e["query_set_id"] == set_id
    assert e["query_id"] == q1
    assert sorted(e["fields_changed"]) == ["query_text", "reference_answer"]
    assert "latency_ms" in e

    # Defense-in-depth: no log record contains the VALUES.
    for record in captured:
        record_str = repr(record)
        assert "redact-me" not in record_str, f"query_text value leaked: {record!r}"
        assert "secret-ref" not in record_str, f"reference_answer value leaked: {record!r}"


async def test_delete_204_emits_query_deleted_structlog(
    async_client: httpx.AsyncClient,
) -> None:
    """DELETE 204 emits ``query_deleted`` with ``had_judgments=False``."""
    import structlog

    set_id, [q1, *_] = await _seed_set(1)
    with structlog.testing.capture_logs() as captured:
        resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert resp.status_code == 204

    events = [e for e in captured if e.get("event") == "query_deleted"]
    assert len(events) == 1
    assert events[0]["query_set_id"] == set_id
    assert events[0]["query_id"] == q1
    assert events[0]["had_judgments"] is False


async def test_delete_409_emits_query_deleted_blocked_structlog(
    async_client: httpx.AsyncClient,
) -> None:
    """DELETE 409 emits ``query_deleted_blocked`` with ``had_judgments=True`` + counts."""
    import structlog

    set_id, [q1, *_] = await _seed_set(1)
    await _seed_judgment_for(set_id, q1)

    with structlog.testing.capture_logs() as captured:
        resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{q1}")
    assert resp.status_code == 409

    events = [e for e in captured if e.get("event") == "query_deleted_blocked"]
    assert len(events) == 1
    e = events[0]
    assert e["had_judgments"] is True
    assert e["list_count"] == 1
    assert e["judgment_count"] == 1
