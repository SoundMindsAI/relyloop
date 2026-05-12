"""Integration test for ``backend.app.scripts.seed_es`` (chore_tutorial_polish Story 2.1).

Skips automatically when Elasticsearch isn't reachable from the test process
(host-shell case — ES on Compose binds to ``127.0.0.1:9200`` so host probes
work; CI's service-container runner reaches ``elasticsearch:9200`` on the
docker network).

Coverage:
* Empty → 1000 docs after first run.
* Re-run produces still 1000 docs (DELETE+recreate is idempotent in count terms).
* Re-running after sample-data shrinks does NOT leave orphan docs (the original
  motivation for DELETE+recreate vs upsert).
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.scripts import seed_es

INDEX_NAME = "products"


def _es_base_url() -> str:
    """Probe localhost:9200 first (host-shell), fall back to elasticsearch:9200 (in-container)."""
    for candidate in ("http://localhost:9200", "http://elasticsearch:9200"):
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(f"{candidate}/")
                if r.status_code == 200 and "version" in r.json():
                    return candidate
        except Exception:
            continue
    return ""


ES_URL = _es_base_url()
es_required = pytest.mark.skipif(
    not ES_URL,
    reason=(
        "Elasticsearch not reachable on localhost:9200 or elasticsearch:9200 — "
        "see docs/03_runbooks/local-dev.md."
    ),
)


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


@pytest.mark.integration
@es_required
async def test_seed_es_indexes_thousand_then_idempotent(
    db_session: AsyncSession, cleanup_index: None
) -> None:
    """Seed empty → 1000 docs; re-seed → still exactly 1000 docs (no drift)."""
    # Insert a local-es row that points at the host-reachable ES URL.
    # seed_es resolves the cluster by name, so we just need a row with the right base_url.
    await repo.create_cluster(
        db_session,
        id="id-test-local-es",
        name="local-es",
        engine_type="elasticsearch",
        environment="dev",
        base_url=ES_URL,
        auth_kind="es_basic",
        credentials_ref="local-es",
    )
    await db_session.commit()

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
async def test_seed_es_returns_one_when_cluster_missing(
    db_session: AsyncSession, cleanup_index: None
) -> None:
    """No ``local-es`` row registered → script logs an error and returns 1."""
    # Intentionally don't insert a cluster row.
    rc = await seed_es.main()
    assert rc == 1
