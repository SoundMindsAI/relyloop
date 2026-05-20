"""K_REQUIRED membership contract test.

chore_create_study_wizard_polish Story 1.2 / AC-13 backend half.

Asserts that the backend's ``ObjectiveSpec`` validator rejects
``ndcg`` / ``precision`` / ``recall`` without ``k`` (the ``_K_REQUIRED_METRICS``
frozenset at ``backend/app/api/v1/schemas.py:474``) and accepts all other
combinations of metric ± k. Paired with the frontend
``ui/src/__tests__/components/studies/k-required.test.ts`` (Story 3.2) that
asserts the frontend ``K_REQUIRED`` constant matches the same set.

Implementation note: ObjectiveSpec validation fires during Pydantic body
parsing (BEFORE the route handler), so failures surface via the project's
``RequestValidationError`` exception handler at
``backend/app/api/errors.py:108`` as HTTP 422 ``VALIDATION_ERROR``, NOT
the router-local ``_err()`` envelope used by the SEARCH_SPACE_* codes.

To assert the success path without seeding 6×6 = 36 entities, we send
fake UUIDs for the FK fields. Successful metric+k validation lands at the
cluster FK lookup → 404 CLUSTER_NOT_FOUND. A 422 VALIDATION_ERROR with the
``objective.k`` field in the error message means metric+k was the rejection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — POST /studies needs the DB-backed pipeline",
)


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


def _post_body(metric: str, k: int | None) -> dict[str, object]:
    """Construct a POST body with fake FK UUIDs.

    Metric+k validation fires at Pydantic body parsing (before FK lookups),
    so when it passes the next failure is the cluster FK lookup → 404.
    When it fails, we get 422 VALIDATION_ERROR before any FK is touched.
    """
    objective: dict[str, object] = {"metric": metric}
    if k is not None:
        objective["k"] = k
    return {
        "name": "k-required-membership-test",
        "cluster_id": str(uuid4()),
        "target": "fake-index",
        "template_id": str(uuid4()),
        "query_set_id": str(uuid4()),
        "judgment_list_id": str(uuid4()),
        "search_space": {"params": {"bm25_k1": {"type": "float", "low": 0.1, "high": 2.0}}},
        "objective": objective,
        "config": {"max_trials": 5},
    }


# ----------------------------------------------------------------------------
# Required-k tier: ndcg / precision / recall MUST reject k=None at body parse.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("metric", ["ndcg", "precision", "recall"])
async def test_required_k_metric_without_k_returns_422(
    async_client: httpx.AsyncClient, metric: str
) -> None:
    """Required-k tier: omitting k → 422 VALIDATION_ERROR at Pydantic body parse."""
    resp = await async_client.post("/api/v1/studies", json=_post_body(metric, None))
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["detail"]["error_code"] == "VALIDATION_ERROR"
    # Confirm it was the objective.k field that triggered the rejection
    assert (
        "objective.k" in body["detail"]["message"] or "k is required" in body["detail"]["message"]
    )


@pytest.mark.parametrize("metric", ["ndcg", "precision", "recall"])
async def test_required_k_metric_with_k_passes_body_validation(
    async_client: httpx.AsyncClient, metric: str
) -> None:
    """Required-k tier: with k=10 → body parse succeeds; cluster FK lookup is the next gate."""
    resp = await async_client.post("/api/v1/studies", json=_post_body(metric, 10))
    # Pydantic accepted the body; cluster FK lookup failed (fake UUID).
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


# ----------------------------------------------------------------------------
# Optional-k tier: map accepts both presence and absence of k.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("k", [None, 10])
async def test_map_with_or_without_k_passes_body_validation(
    async_client: httpx.AsyncClient, k: int | None
) -> None:
    """Optional-k tier: map accepts k=None (full-recall MAP) and k=10 (map@10)."""
    resp = await async_client.post("/api/v1/studies", json=_post_body("map", k))
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


# ----------------------------------------------------------------------------
# Ignored-k tier: mrr/err accept k=None and k=10 at the body-parse layer.
# (mrr scoring drops k; err scoring isn't implemented yet — both pass create-time.)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("metric", ["mrr", "err"])
@pytest.mark.parametrize("k", [None, 10])
async def test_ignored_k_metric_passes_body_validation(
    async_client: httpx.AsyncClient, metric: str, k: int | None
) -> None:
    """Ignored-k tier (mrr/err): k is silently accepted at create time (scoring layer drops it)."""
    resp = await async_client.post("/api/v1/studies", json=_post_body(metric, k))
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


# ----------------------------------------------------------------------------
# Sanity: fake UUIDs are syntactically valid; this isolates the test from
# UUID-parse VALIDATION_ERROR failures.
# ----------------------------------------------------------------------------


def test_fake_uuids_are_well_formed() -> None:
    body = _post_body("ndcg", 10)
    for key in ("cluster_id", "template_id", "query_set_id", "judgment_list_id"):
        UUID(str(body[key]))
