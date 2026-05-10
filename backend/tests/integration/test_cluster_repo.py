"""Cluster repo integration tests (infra_adapter_elastic Story 1.4).

Exercises every function in ``backend.app.db.repo.cluster`` against the
real test Postgres provisioned by CI. Skips automatically when Postgres
isn't host-reachable (the local laptop case — see ``docs/03_runbooks/
local-dev.md`` §"Local-vs-CI test layers").

The fixture ``db_session`` (in ``backend/tests/conftest.py``) wraps each
test in a SAVEPOINT-style transaction that's rolled back at teardown, so
tests don't leak rows between runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo


def _cluster_kwargs(name: str, *, cluster_id: str | None = None) -> dict[str, object]:
    """Minimal field set for a Cluster insert — keeps tests focused on repo logic."""
    return {
        "id": cluster_id or f"id-{name}",
        "name": name,
        "engine_type": "elasticsearch",
        "environment": "dev",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": f"ref-{name}",
    }


@pytest.mark.integration
class TestClusterRepoBasics:
    async def test_create_then_fetch_round_trip(self, db_session: AsyncSession) -> None:
        cluster = await repo.create_cluster(db_session, **_cluster_kwargs("alpha"))
        assert cluster.id == "id-alpha"
        assert cluster.deleted_at is None
        # commit the savepoint so subsequent queries in the same test see the row
        await db_session.commit()

        fetched = await repo.get_cluster(db_session, "id-alpha")
        assert fetched is not None
        assert fetched.name == "alpha"

        by_name = await repo.get_active_cluster_by_name(db_session, "alpha")
        assert by_name is not None
        assert by_name.id == "id-alpha"

    async def test_get_cluster_returns_none_for_missing(self, db_session: AsyncSession) -> None:
        assert await repo.get_cluster(db_session, "id-does-not-exist") is None

    async def test_count_clusters_excludes_soft_deleted(self, db_session: AsyncSession) -> None:
        await repo.create_cluster(db_session, **_cluster_kwargs("a"))
        await repo.create_cluster(db_session, **_cluster_kwargs("b"))
        await db_session.commit()

        assert await repo.count_clusters(db_session) == 2

        await repo.soft_delete_cluster(db_session, "id-a")
        await db_session.commit()
        assert await repo.count_clusters(db_session) == 1


@pytest.mark.integration
class TestClusterRepoSoftDelete:
    async def test_soft_delete_excludes_from_list_and_get(self, db_session: AsyncSession) -> None:
        await repo.create_cluster(db_session, **_cluster_kwargs("alpha"))
        await db_session.commit()

        deleted = await repo.soft_delete_cluster(db_session, "id-alpha")
        assert deleted is not None
        assert deleted.deleted_at is not None
        await db_session.commit()

        # get_cluster + get_active_cluster_by_name → None for soft-deleted.
        assert await repo.get_cluster(db_session, "id-alpha") is None
        assert await repo.get_active_cluster_by_name(db_session, "alpha") is None
        # list_clusters omits the row.
        assert all(c.id != "id-alpha" for c in await repo.list_clusters(db_session))

    async def test_get_any_cluster_by_name_returns_soft_deleted(
        self, db_session: AsyncSession
    ) -> None:
        """Used by registration to detect a soft-deleted same-name row."""
        await repo.create_cluster(db_session, **_cluster_kwargs("alpha"))
        await db_session.commit()
        await repo.soft_delete_cluster(db_session, "id-alpha")
        await db_session.commit()

        any_row = await repo.get_any_cluster_by_name(db_session, "alpha")
        assert any_row is not None
        assert any_row.deleted_at is not None

    async def test_revive_cluster_clears_deleted_at_and_updates_fields(
        self, db_session: AsyncSession
    ) -> None:
        await repo.create_cluster(db_session, **_cluster_kwargs("alpha"))
        await db_session.commit()
        await repo.soft_delete_cluster(db_session, "id-alpha")
        await db_session.commit()

        existing = await repo.get_any_cluster_by_name(db_session, "alpha")
        assert existing is not None
        revived = await repo.revive_cluster(
            db_session,
            existing,
            engine_type="opensearch",
            base_url="http://opensearch:9200",
            auth_kind="opensearch_basic",
            credentials_ref="new-ref",
        )
        await db_session.commit()
        assert revived.deleted_at is None
        assert revived.engine_type == "opensearch"
        assert revived.auth_kind == "opensearch_basic"
        # The revived row appears again in list_clusters.
        active_ids = [c.id for c in await repo.list_clusters(db_session)]
        assert "id-alpha" in active_ids


@pytest.mark.integration
class TestClusterRepoPagination:
    async def test_cursor_pagination_excludes_first_page(self, db_session: AsyncSession) -> None:
        """Page 2 (using page-1's last row as cursor) excludes page-1 ids."""
        # Seed three rows with controlled created_at offsets so ordering is deterministic.
        base = datetime.now(UTC)
        for i, name in enumerate(["c1", "c2", "c3"]):
            await repo.create_cluster(
                db_session,
                **_cluster_kwargs(name),
                created_at=base - timedelta(seconds=i),
            )
        await db_session.commit()

        page1 = await repo.list_clusters(db_session, limit=2)
        assert [c.name for c in page1] == ["c1", "c2"]
        last = page1[-1]
        page2 = await repo.list_clusters(db_session, limit=2, cursor=(last.created_at, last.id))
        page2_ids = [c.id for c in page2]
        # page-1 ids NOT in page-2.
        assert "id-c1" not in page2_ids
        assert "id-c2" not in page2_ids
        # page-2 has the remaining row.
        assert "id-c3" in page2_ids
