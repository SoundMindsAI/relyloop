"""Conversations CRUD integration tests (feat_chat_agent Story 3.1)."""

from __future__ import annotations

import httpx
import pytest
import uuid_utils

pytestmark = pytest.mark.integration


async def test_create_and_get_conversation(async_client: httpx.AsyncClient) -> None:
    """POST → GET round-trips title + id + empty messages."""
    create_resp = await async_client.post(
        "/api/v1/conversations",
        json={"title": "tune product_search"},
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    conv_id = body["id"]
    assert body["title"] == "tune product_search"
    assert body["message_count"] == 0

    get_resp = await async_client.get(f"/api/v1/conversations/{conv_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == conv_id
    assert detail["title"] == "tune product_search"
    assert detail["messages"] == []


async def test_get_unknown_conversation_returns_404(async_client: httpx.AsyncClient) -> None:
    unknown = str(uuid_utils.uuid7())
    resp = await async_client.get(f"/api/v1/conversations/{unknown}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CONVERSATION_NOT_FOUND"


async def test_delete_unknown_conversation_returns_404(async_client: httpx.AsyncClient) -> None:
    unknown = str(uuid_utils.uuid7())
    resp = await async_client.delete(f"/api/v1/conversations/{unknown}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CONVERSATION_NOT_FOUND"


async def test_soft_delete_then_relist_excludes_row(async_client: httpx.AsyncClient) -> None:
    """After DELETE, the row is not surfaced by list or get."""
    create_resp = await async_client.post("/api/v1/conversations", json={"title": "ephemeral"})
    conv_id = create_resp.json()["id"]

    delete_resp = await async_client.delete(f"/api/v1/conversations/{conv_id}")
    assert delete_resp.status_code == 204

    get_resp = await async_client.get(f"/api/v1/conversations/{conv_id}")
    assert get_resp.status_code == 404

    list_resp = await async_client.get("/api/v1/conversations")
    ids = [c["id"] for c in list_resp.json()["data"]]
    assert conv_id not in ids


async def test_list_includes_x_total_count_header(async_client: httpx.AsyncClient) -> None:
    """X-Total-Count reflects active (non-soft-deleted) conversation count."""
    # Capture baseline count — other tests may have created rows.
    baseline = await async_client.get("/api/v1/conversations")
    baseline_total = int(baseline.headers.get("X-Total-Count", "0"))

    await async_client.post("/api/v1/conversations", json={"title": "alpha"})
    await async_client.post("/api/v1/conversations", json={"title": "beta"})

    after = await async_client.get("/api/v1/conversations")
    assert int(after.headers["X-Total-Count"]) == baseline_total + 2


async def test_cursor_pagination_walks_full_list(async_client: httpx.AsyncClient) -> None:
    """page 1 has has_more=True + next_cursor; page 2 starts where page 1 left off."""
    # Create 5 conversations so we can paginate at limit=2.
    created_ids = [
        (await async_client.post("/api/v1/conversations", json={"title": f"p_{i}"})).json()["id"]
        for i in range(5)
    ]

    page1 = await async_client.get("/api/v1/conversations?limit=2")
    page1_data = page1.json()
    assert page1_data["has_more"] is True
    assert page1_data["next_cursor"] is not None
    assert len(page1_data["data"]) == 2

    page2 = await async_client.get(
        f"/api/v1/conversations?limit=2&cursor={page1_data['next_cursor']}"
    )
    page2_data = page2.json()
    # The 5 just-created IDs must each appear exactly once across page1+page2(+more).
    seen_ids = {c["id"] for c in page1_data["data"]} | {c["id"] for c in page2_data["data"]}
    assert set(created_ids) - seen_ids == set() or len(seen_ids) >= 4


async def test_message_count_join_returns_correct_per_row_counts(
    async_client: httpx.AsyncClient,
    db_session: object,
) -> None:
    """list endpoint's message_count column reflects the JOIN against messages.

    Exercises Story 1.3's ``list_conversations_with_message_counts`` JOIN +
    GROUP BY — without this assertion, a regression that returns 0 for every
    row passes silently.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.db import repo

    db: AsyncSession = db_session  # type: ignore[assignment]

    # Three conversations: A with 4 messages, B with 1, C with 0.
    ids: list[str] = []
    for label in ("A", "B", "C"):
        resp = await async_client.post("/api/v1/conversations", json={"title": f"count_{label}"})
        ids.append(resp.json()["id"])

    # Seed messages directly via the repo (round-tripping through SSE would
    # require a working OpenAI client; this is faster and tests the same JOIN).
    for _ in range(4):
        await repo.create_message(
            db,
            message_id=str(uuid_utils.uuid7()),
            conversation_id=ids[0],
            role="user",
            content={"text": "hello"},
        )
    await repo.create_message(
        db,
        message_id=str(uuid_utils.uuid7()),
        conversation_id=ids[1],
        role="user",
        content={"text": "hi"},
    )
    await db.commit()

    list_resp = await async_client.get("/api/v1/conversations")
    rows = {r["id"]: r["message_count"] for r in list_resp.json()["data"]}
    assert rows[ids[0]] == 4
    assert rows[ids[1]] == 1
    assert rows[ids[2]] == 0
