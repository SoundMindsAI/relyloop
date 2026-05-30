# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0007_conversations_messages`` migration test (feat_chat_agent Story 1.1).

Asserts the schema shape of the ``conversations`` + ``messages`` tables created
by ``migrations/versions/0007_conversations_messages.py``:

* both tables exist after ``upgrade head``; both gone after ``downgrade -1``
* NOT NULL coverage on the required columns
* CHECK constraint ``messages_role_check`` rejects roles outside
  ``{user, assistant, tool}``
* FK ``messages.conversation_id → conversations.id ON DELETE CASCADE`` deletes
  children on parent purge
* index ``messages_conversation_idx`` exists

Mirrors ``test_judgments_migration.py`` so the local-vs-CI skip semantics match.
"""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.app.core.settings import get_settings

REPO = Path(__file__).resolve().parents[3]


def _postgres_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001
        return False
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "Postgres not reachable from this process — see "
        "docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
    ),
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )


def _sync_database_url() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def restore_head() -> Iterator[None]:
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


@pytest.mark.integration
class TestSchemaCreation:
    """Both tables exist after upgrade head; gone after downgrade -1."""

    def test_upgrade_creates_both_tables(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                names = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' "
                            "AND table_name IN ('conversations', 'messages')"
                        )
                    ).fetchall()
                }
                assert names == {"conversations", "messages"}
        finally:
            engine.dispose()

    def test_downgrade_drops_both_tables(self, restore_head: None) -> None:
        # Downgrade target is `0006_proposals_pr_url_idx` — i.e. one
        # revision BEFORE the 0007 conversations+messages migration.
        # `downgrade -1` was the right target when 0007 was head, but
        # feat_data_table_primitive extended the chain to 0013, so we
        # use an explicit revision id here to stay correct as more
        # migrations land on top.
        _alembic("upgrade", "head")
        _alembic("downgrade", "0006")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                names = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' "
                            "AND table_name IN ('conversations', 'messages')"
                        )
                    ).fetchall()
                }
                assert names == set(), (
                    "conversations + messages should be dropped by downgrade to 0006"
                )
        finally:
            engine.dispose()

    def test_roundtrip(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "0006")
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                names = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' "
                            "AND table_name IN ('conversations', 'messages')"
                        )
                    ).fetchall()
                }
                assert names == {"conversations", "messages"}
        finally:
            engine.dispose()


@pytest.mark.integration
class TestColumnsAndConstraints:
    """NOT NULL coverage + CHECK + index inventory."""

    def test_conversations_not_null_coverage(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='conversations' "
                        "ORDER BY column_name"
                    )
                ).fetchall()
                nullable = {row[0]: row[1] for row in rows}
                for required in ("id", "created_at"):
                    assert nullable.get(required) == "NO", f"{required} should be NOT NULL"
                for optional in ("title", "deleted_at"):
                    assert nullable.get(optional) == "YES", f"{optional} should be NULL-able"
        finally:
            engine.dispose()

    def test_messages_not_null_coverage(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='messages' "
                        "ORDER BY column_name"
                    )
                ).fetchall()
                nullable = {row[0]: row[1] for row in rows}
                for required in (
                    "id",
                    "conversation_id",
                    "role",
                    "content",
                    "created_at",
                ):
                    assert nullable.get(required) == "NO", f"{required} should be NOT NULL"
                assert nullable.get("tool_calls") == "YES", "tool_calls should be NULL-able"
        finally:
            engine.dispose()

    def test_role_check_present(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                names = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid = 'messages'::regclass AND contype = 'c'"
                        )
                    ).fetchall()
                }
                assert "messages_role_check" in names
        finally:
            engine.dispose()

    def test_conversation_index_present(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename='messages' AND indexname='messages_conversation_idx'"
                    )
                ).fetchone()
                assert row is not None, "messages_conversation_idx should exist"
        finally:
            engine.dispose()


@pytest.mark.integration
class TestRuntimeBehavior:
    """Live INSERT/DELETE behavior verifies CHECK + CASCADE FK contracts."""

    def test_role_check_rejects_unknown(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            convo_id = str(uuid.uuid4())
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO conversations (id, title, created_at) "
                        "VALUES (:id, 'mig-test', NOW())"
                    ),
                    {"id": convo_id},
                )
            with pytest.raises(IntegrityError):
                with engine.begin() as inner:
                    inner.execute(
                        text(
                            "INSERT INTO messages (id, conversation_id, role, content, "
                            "created_at) VALUES (:id, :convo, 'system', "
                            '\'{"text": "x"}\'::jsonb, NOW())'
                        ),
                        {"id": str(uuid.uuid4()), "convo": convo_id},
                    )
        finally:
            engine.dispose()

    def test_role_check_accepts_three_values(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            convo_id = str(uuid.uuid4())
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO conversations (id, title, created_at) "
                        "VALUES (:id, 'mig-test', NOW())"
                    ),
                    {"id": convo_id},
                )
                for role in ("user", "assistant", "tool"):
                    conn.execute(
                        text(
                            "INSERT INTO messages (id, conversation_id, role, content, "
                            "created_at) VALUES (:id, :convo, :role, "
                            '\'{"text": "x"}\'::jsonb, NOW())'
                        ),
                        {"id": str(uuid.uuid4()), "convo": convo_id, "role": role},
                    )
        finally:
            engine.dispose()

    def test_cascade_on_conversation_delete(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            convo_id = str(uuid.uuid4())
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO conversations (id, title, created_at) "
                        "VALUES (:id, 'mig-cascade', NOW())"
                    ),
                    {"id": convo_id},
                )
                for _ in range(3):
                    conn.execute(
                        text(
                            "INSERT INTO messages (id, conversation_id, role, content, "
                            "created_at) VALUES (:id, :convo, 'user', "
                            '\'{"text": "x"}\'::jsonb, NOW())'
                        ),
                        {"id": str(uuid.uuid4()), "convo": convo_id},
                    )
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM conversations WHERE id = :id"),
                    {"id": convo_id},
                )
                count = conn.execute(
                    text("SELECT COUNT(*) FROM messages WHERE conversation_id = :id"),
                    {"id": convo_id},
                ).scalar_one()
                assert count == 0, "CASCADE should have removed child messages"
        finally:
            engine.dispose()
