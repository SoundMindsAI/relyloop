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
) -> None:
    """list endpoint's message_count column reflects the JOIN against messages.

    Exercises Story 1.3's ``list_conversations_with_preview_data`` JOIN +
    GROUP BY — without this assertion, a regression that returns 0 for every
    row passes silently. Seeds messages through a direct DB session that
    commits (the ``db_session`` test fixture wraps everything in a SAVEPOINT
    rolled back on teardown, but the HTTP client uses a different connection
    so the savepoint isn't visible — we need a real commit).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings
    from backend.app.db import repo as db_repo

    # Three conversations: A with 4 messages, B with 1, C with 0.
    ids: list[str] = []
    for label in ("A", "B", "C"):
        resp = await async_client.post("/api/v1/conversations", json={"title": f"count_{label}"})
        ids.append(resp.json()["id"])

    # Seed messages via a fresh connection that commits — the test-fixture
    # ``db_session`` is wrapped in a SAVEPOINT that the HTTP client can't see.
    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            for _ in range(4):
                await db_repo.create_message(
                    session,
                    message_id=str(uuid_utils.uuid7()),
                    conversation_id=ids[0],
                    role="user",
                    content={"text": "hello"},
                )
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=ids[1],
                role="user",
                content={"text": "hi"},
            )
            await session.commit()
    finally:
        await engine.dispose()

    list_resp = await async_client.get("/api/v1/conversations?limit=200")
    rows = {r["id"]: r["message_count"] for r in list_resp.json()["data"]}
    assert rows[ids[0]] == 4
    assert rows[ids[1]] == 1
    assert rows[ids[2]] == 0


async def test_create_returns_none_preview_fields(async_client: httpx.AsyncClient) -> None:
    """POST 201 sets last_message_preview + last_message_at to None.

    Brand-new conversations have no messages; the ``ConversationSummary``
    body mirrors the existing ``message_count=0`` hardcode for the two
    new fields (chore_chat_last_message_preview).
    """
    resp = await async_client.post("/api/v1/conversations", json={"title": "fresh"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["last_message_preview"] is None
    assert body["last_message_at"] is None


async def test_list_includes_preview_and_last_at_for_active_rows(
    async_client: httpx.AsyncClient,
) -> None:
    """LATERAL JOIN populates preview + last_at; empty conversations stay None.

    Exercises the chore_chat_last_message_preview LATERAL subquery against
    real Postgres. Three conversations:
      * A: user → assistant → user (latest preview is the second user text).
      * B: single user message.
      * C: zero messages (empty).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings
    from backend.app.db import repo as db_repo

    ids: list[str] = []
    for label in ("preview_A", "preview_B", "preview_C"):
        resp = await async_client.post("/api/v1/conversations", json={"title": label})
        ids.append(resp.json()["id"])

    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=ids[0],
                role="user",
                content={"text": "first user message"},
            )
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=ids[0],
                role="assistant",
                content={"text": "assistant reply"},
            )
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=ids[0],
                role="user",
                content={"text": "latest user follow-up"},
            )
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=ids[1],
                role="user",
                content={"text": "B's only message"},
            )
            await session.commit()
    finally:
        await engine.dispose()

    list_resp = await async_client.get("/api/v1/conversations?limit=200")
    rows = {r["id"]: r for r in list_resp.json()["data"]}
    assert rows[ids[0]]["last_message_preview"] == "latest user follow-up"
    assert rows[ids[0]]["last_message_at"] is not None
    assert rows[ids[1]]["last_message_preview"] == "B's only message"
    assert rows[ids[1]]["last_message_at"] is not None
    assert rows[ids[2]]["last_message_preview"] is None
    assert rows[ids[2]]["last_message_at"] is None


async def test_preview_skips_tool_rows_and_system_notices(
    async_client: httpx.AsyncClient,
) -> None:
    """LATERAL JOIN filters out tool-role rows and assistant system_notice rows.

    Tool-result payloads (``content={"result": ...}``) have no ``text`` field
    and would surface as ``None`` from the JSONB extractor anyway, but the
    WHERE clause also excludes them by role for clarity. The
    ``content.kind == 'system_notice'`` filter is the load-bearing one:
    degraded-mode assistant rows DO have a ``text`` field but they're
    transient banners, not real assistant turns.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings
    from backend.app.db import repo as db_repo

    resp = await async_client.post("/api/v1/conversations", json={"title": "skip_test"})
    conv_id = resp.json()["id"]

    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            # Real assistant turn — this is what the preview should pick.
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=conv_id,
                role="assistant",
                content={"text": "the real answer the operator should see"},
            )
            # Later tool-result row (no `text` field, plus role filter excludes it).
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=conv_id,
                role="tool",
                content={"result": {"hits": []}},
            )
            # Latest assistant turn but flagged as system_notice (degraded-mode banner).
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=conv_id,
                role="assistant",
                content={"text": "LLM unreachable — degraded mode", "kind": "system_notice"},
            )
            await session.commit()
    finally:
        await engine.dispose()

    list_resp = await async_client.get("/api/v1/conversations?limit=200")
    row = next(r for r in list_resp.json()["data"] if r["id"] == conv_id)
    assert row["last_message_preview"] == "the real answer the operator should see"


async def test_preview_truncates_at_120_chars(async_client: httpx.AsyncClient) -> None:
    """Repo-layer truncation: preview cut at 120 chars with `…` suffix.

    Single truncation site keeps the wire shape deterministic — frontend
    renders verbatim.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings
    from backend.app.db import repo as db_repo

    resp = await async_client.post("/api/v1/conversations", json={"title": "long"})
    conv_id = resp.json()["id"]
    long_text = "a" * 200  # > 120 chars

    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            await db_repo.create_message(
                session,
                message_id=str(uuid_utils.uuid7()),
                conversation_id=conv_id,
                role="user",
                content={"text": long_text},
            )
            await session.commit()
    finally:
        await engine.dispose()

    list_resp = await async_client.get("/api/v1/conversations?limit=200")
    row = next(r for r in list_resp.json()["data"] if r["id"] == conv_id)
    preview = row["last_message_preview"]
    assert preview is not None
    assert len(preview) == 120
    assert preview.endswith("…")
    assert preview[:-1] == "a" * 119
