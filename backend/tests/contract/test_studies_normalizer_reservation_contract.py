# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the three new normalizer error codes (FR-2, Story 2.1).

Asserts the spec §8.3 envelope verbatim for:
  * ``NORMALIZER_CHOICE_INVALID`` (400) — POST /api/v1/studies
  * ``NORMALIZER_PARAM_SHAPE`` (400) — POST /api/v1/studies
  * ``RESERVED_PARAM_REFERENCED`` (400) — POST /api/v1/query-templates

The two studies codes fire AFTER ``validate_against_template`` (so a seeded
cluster + template declaring ``query_normalizer`` is required to reach them);
the query-template code is pure-validation (no seeding). Also asserts the
precedence guard: ``INVALID_SEARCH_SPACE`` wins on an unrelated shape error.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — reservation paths flow through get_db dependency",
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


def _assert_envelope(detail: dict[str, object], code: str) -> None:
    assert detail["error_code"] == code
    assert isinstance(detail["message"], str) and detail["message"]
    assert detail["retryable"] is False


async def _seed_cluster_and_template() -> tuple[str, str]:
    """Seed a cluster + a template that declares ``query_normalizer``.

    Returns ``(cluster_id, template_id)``. The template declares ONLY
    ``query_normalizer`` so a search space containing just that key passes
    ``validate_against_template`` and reaches the reservation check.
    """
    from backend.app.db import repo
    from backend.app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"norm-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"norm-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match": {"title": "{{ query_text }}"}}}',
            declared_params={"query_normalizer": "string"},
            version=1,
        )
        await db.commit()
        return cluster.id, template.id


def _study_body(
    cluster_id: str, template_id: str, normalizer_param: dict[str, object]
) -> dict[str, object]:
    return {
        "name": "norm-reservation",
        "cluster_id": cluster_id,
        "target": "stub-index",
        "template_id": template_id,
        "query_set_id": "00000000-0000-7000-8000-000000000002",
        "judgment_list_id": "00000000-0000-7000-8000-000000000003",
        "search_space": {"params": {"query_normalizer": normalizer_param}},
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }


async def test_normalizer_choice_invalid_envelope(
    async_client: httpx.AsyncClient,
) -> None:
    cluster_id, template_id = await _seed_cluster_and_template()
    body = _study_body(
        cluster_id,
        template_id,
        {"type": "categorical", "choices": ["none", "stem"]},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    _assert_envelope(detail, "NORMALIZER_CHOICE_INVALID")
    assert "stem" in detail["message"]


async def test_normalizer_param_shape_envelope(
    async_client: httpx.AsyncClient,
) -> None:
    cluster_id, template_id = await _seed_cluster_and_template()
    body = _study_body(
        cluster_id,
        template_id,
        {"type": "float", "low": 0.1, "high": 1.0},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    _assert_envelope(detail, "NORMALIZER_PARAM_SHAPE")
    assert "FloatParam" in detail["message"]


async def test_valid_subset_passes_reservation_then_fails_later_fk(
    async_client: httpx.AsyncClient,
) -> None:
    """A valid subset clears the reservation gate; the request then proceeds
    to the query_set FK lookup (404), proving the reservation check did NOT
    reject a legal choice set."""
    cluster_id, template_id = await _seed_cluster_and_template()
    body = _study_body(
        cluster_id,
        template_id,
        {"type": "categorical", "choices": ["none", "lowercase+trim"]},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    # Past the reservation gate — the missing query_set FK is the next failure.
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_reserved_param_referenced_envelope(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": f"reserved-{uuid.uuid4().hex[:8]}",
            "engine_type": "elasticsearch",
            "body": '{"q": "{{ query_normalizer }}"}',
            "declared_params": {"query_normalizer": "string"},
        },
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    _assert_envelope(detail, "RESERVED_PARAM_REFERENCED")
    assert "query_normalizer" in detail["message"]


async def test_invalid_search_space_precedence_over_normalizer_codes(
    async_client: httpx.AsyncClient,
) -> None:
    """A structurally-invalid SearchSpace surfaces INVALID_SEARCH_SPACE first —
    the normalizer reservation check never runs on an unvalidated space."""
    cluster_id, template_id = await _seed_cluster_and_template()
    body = _study_body(cluster_id, template_id, {"type": "categorical"})  # choices missing
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "INVALID_SEARCH_SPACE"
