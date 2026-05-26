"""Integration test for ``backend.app.scripts.seed_es`` (chore_tutorial_polish Story 2.1).

Skips automatically when Elasticsearch isn't reachable from the test process
(host-shell case — ES on Compose binds to ``127.0.0.1:9200`` so host probes
work; CI's service-container runner reaches ``elasticsearch:9200`` on the
docker network).

Coverage:
* Empty → 1000 docs after first run.
* Re-run produces still 1000 docs (DELETE+recreate is idempotent in count terms).
* Missing local-es cluster row → script returns 1 (the operator-skipped-step path).

Uses ``get_session_factory()`` directly rather than the ``db_session``
SAVEPOINT fixture: ``seed_es.main()`` opens its own session via
``get_session_factory()`` to look up the cluster, and a savepoint commit
isn't visible across sessions. The autouse ``_clean_phase2_tables``
conftest fixture truncates the clusters table after each test, so the
explicit insert here cleans up automatically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.scripts import seed_es
from backend.tests.integration.fixtures.es_reachability import _es_base_url, es_required

INDEX_NAME = "products"

ES_URL = _es_base_url()


@pytest.fixture
def cleanup_index() -> Iterator[None]:
    """Best-effort DELETE /products both before and after the test."""
    if ES_URL:
        with httpx.Client(timeout=10.0) as c:
            c.delete(f"{ES_URL}/{INDEX_NAME}")
    yield
    if ES_URL:
        with httpx.Client(timeout=10.0) as c:
            c.delete(f"{ES_URL}/{INDEX_NAME}")


@pytest_asyncio.fixture
async def real_db_session() -> AsyncIterator[AsyncSession]:
    """Direct session via get_session_factory() — commits real transactions
    so seed_es.main()'s separate session can see the inserted rows.

    Skips on host-shell runs where Postgres isn't resolvable (the conftest's
    db_session fixture already has this gate via postgres_reachable, but our
    real-session path bypasses it). Wipes the clusters table on entry so a
    leftover ``local-es`` row from a prior ``make seed-clusters`` run (with
    ``base_url=http://elasticsearch:9200``, unreachable from the host)
    doesn't shadow the test's own insert. Cleanup after the test is handled
    by the autouse ``_clean_phase2_tables`` conftest fixture.
    """
    from sqlalchemy import text

    from backend.tests.conftest import postgres_reachable

    if not postgres_reachable():
        pytest.skip(
            "Postgres not reachable — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
        )
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("DELETE FROM clusters"))
        await session.commit()
        yield session


@pytest.mark.integration
@es_required
async def test_seed_es_indexes_thousand_then_idempotent(
    real_db_session: AsyncSession, cleanup_index: None
) -> None:
    """Seed empty → 1000 docs; re-seed → still exactly 1000 docs (no drift)."""
    # Insert a local-es row that points at the host-reachable ES URL.
    # seed_es resolves the cluster by name, so we just need a row with the right base_url.
    await repo.create_cluster(
        real_db_session,
        id="id-test-local-es",
        name="local-es",
        engine_type="elasticsearch",
        environment="dev",
        base_url=ES_URL,
        auth_kind="es_basic",
        credentials_ref="local-es",
    )
    await real_db_session.commit()

    # First run.
    rc = await seed_es.main()
    assert rc == 0, "first seed_es.main() returned non-zero"

    with httpx.Client(timeout=10.0) as c:
        # Force a refresh before counting — the script does this internally too.
        c.post(f"{ES_URL}/{INDEX_NAME}/_refresh")
        r = c.get(f"{ES_URL}/{INDEX_NAME}/_count")
        assert r.status_code == 200, r.text
        first_count = r.json()["count"]
    assert first_count == 1000, f"expected 1000 docs after first run, got {first_count}"

    # Second run — count must stay at 1000.
    rc2 = await seed_es.main()
    assert rc2 == 0, "second seed_es.main() returned non-zero"
    with httpx.Client(timeout=10.0) as c:
        c.post(f"{ES_URL}/{INDEX_NAME}/_refresh")
        r = c.get(f"{ES_URL}/{INDEX_NAME}/_count")
        second_count = r.json()["count"]
    assert second_count == 1000, f"expected 1000 docs after re-seed, got {second_count}"


@pytest.mark.integration
@es_required
async def test_seed_es_returns_one_when_cluster_missing(cleanup_index: None) -> None:
    """No ``local-es`` row registered → script logs an error and returns 1.

    Wipes the clusters table to drop any leftover row from earlier runs
    (e.g. host operator running ``make seed-clusters`` before the test).
    """
    from sqlalchemy import text

    from backend.tests.conftest import postgres_reachable

    if not postgres_reachable():
        pytest.skip(
            "Postgres not reachable — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
        )
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("DELETE FROM clusters"))
        await session.commit()

    rc = await seed_es.main()
    assert rc == 1
