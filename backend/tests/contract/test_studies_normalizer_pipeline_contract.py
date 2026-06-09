# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the typed-pipeline study-create paths (Story 1.3).

Asserts the canonical error envelope (spec §8.3) and the D-8 no-new-error-code
contract across both failure codes:

  * AC-12 misplaced pipeline key → ``INVALID_SEARCH_SPACE`` (400)
  * duplicate step → ``INVALID_SEARCH_SPACE`` (400, via Pydantic model_validate)
  * ``query_normalizer`` declared as a FloatParam → ``NORMALIZER_PARAM_SHAPE``
    (400) with the broadened message naming ``NormalizerPipelineParam``
  * a valid pipeline under the reserved key → ``201`` study created
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
    reason="Postgres not reachable — study-create flows through get_db dependency",
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


async def _seed(declared_params: dict[str, str]) -> dict[str, str]:
    """Seed cluster + template (+ query_set + judgment_list) for POST /studies."""
    from backend.app.db import repo
    from backend.app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"np-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"np-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match": {"title": "{{ query_text }}"}}}',
            declared_params=declared_params,
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"np-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"np-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
        return {
            "cluster_id": cluster.id,
            "template_id": template.id,
            "query_set_id": query_set.id,
            "judgment_list_id": judgment_list.id,
        }


def _study_body(ids: dict[str, str], search_space_params: dict[str, object]) -> dict[str, object]:
    return {
        "name": "np-study",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": {"params": search_space_params},
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }


async def test_misplaced_pipeline_key_is_invalid_search_space(
    async_client: httpx.AsyncClient,
) -> None:
    # AC-12: a normalizer_pipeline under a non-reserved (but declared) key.
    ids = await _seed({"boost": "string"})
    body = _study_body(
        ids,
        {"boost": {"type": "normalizer_pipeline", "steps": ["lowercase", "trim"]}},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    _assert_envelope(detail, "INVALID_SEARCH_SPACE")
    assert "query_normalizer" in detail["message"]
    assert "boost" in detail["message"]


async def test_duplicate_step_is_invalid_search_space(
    async_client: httpx.AsyncClient,
) -> None:
    # Duplicate steps fail at SearchSpace.model_validate → INVALID_SEARCH_SPACE
    # (D-8: rides the existing code, no new one).
    ids = await _seed({"query_normalizer": "string"})
    body = _study_body(
        ids,
        {"query_normalizer": {"type": "normalizer_pipeline", "steps": ["lowercase", "lowercase"]}},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    _assert_envelope(resp.json()["detail"], "INVALID_SEARCH_SPACE")


async def test_wrong_shape_names_pipeline_in_param_shape_message(
    async_client: httpx.AsyncClient,
) -> None:
    ids = await _seed({"query_normalizer": "string"})
    body = _study_body(ids, {"query_normalizer": {"type": "float", "low": 0.1, "high": 1.0}})
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    _assert_envelope(detail, "NORMALIZER_PARAM_SHAPE")
    assert "NormalizerPipelineParam" in detail["message"]
    assert "FloatParam" in detail["message"]


async def test_valid_pipeline_creates_study(
    async_client: httpx.AsyncClient,
) -> None:
    ids = await _seed({"query_normalizer": "string"})
    body = _study_body(
        ids,
        {"query_normalizer": {"type": "normalizer_pipeline", "steps": ["lowercase", "trim"]}},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["id"]
    # The pipeline declaration round-trips into the persisted search_space.
    assert payload["search_space"]["params"]["query_normalizer"] == {
        "type": "normalizer_pipeline",
        "steps": ["lowercase", "trim"],
    }
