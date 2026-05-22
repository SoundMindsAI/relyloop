"""Spec §7.5 error-code matrix for the Phase 2 API surface (Story 3.5).

The DB-dependent codes are exercised at the integration layer
(``backend/tests/integration/test_*_api.py``). This module asserts the
pure-contract codes reachable via the FastAPI app without writing rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — error-code paths flow through get_db dependency",
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


async def test_invalid_template_syntax_via_call(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "bad-call",
            "engine_type": "elasticsearch",
            "body": "{{ foo() }}",
            "declared_params": {"foo": "callable"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


async def test_invalid_template_syntax_via_attribute(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "bad-attr",
            "engine_type": "elasticsearch",
            "body": "{{ x.y }}",
            "declared_params": {"x": "string"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


async def test_undeclared_param_used(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "undecl",
            "engine_type": "elasticsearch",
            "body": '{"query": "{{ undeclared }}"}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "UNDECLARED_PARAM_USED"


async def test_declared_param_unused(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "unused",
            "engine_type": "elasticsearch",
            "body": '{"query": "{{ query_text }}"}',
            "declared_params": {"orphan": "string"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "DECLARED_PARAM_UNUSED"


async def test_trials_list_invalid_sort_key_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Bad ``?sort=`` value → 422 VALIDATION_ERROR before the study lookup."""
    fake = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.get(f"/api/v1/studies/{fake}/trials?sort=unknown")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_query_set_bulk_missing_query_set_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """POST /queries on unknown query_set → 404 QUERY_SET_NOT_FOUND.

    The INVALID_CSV content-type path requires a real query_set; that
    surface is covered in integration's ``test_csv_upload.py``."""
    fake = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.post(
        f"/api/v1/query-sets/{fake}/queries",
        content=b"not really a csv",
        headers={"Content-Type": "text/xml"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_insufficient_judgment_overlap_envelope_shape(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``feat_study_preflight_overlap_probe`` FR-3 — the new 422 envelope
    matches the canonical ``{error_code, message, retryable}`` shape and
    the message includes the spec-mandated ``X of N probed`` +
    ``judged_doc_count=N`` substrings.

    Hermetic: seeds the minimum FK rows that pass earlier checks, then
    monkeypatches ``probe_judgment_overlap`` to return an insufficient
    ``OverlapProbeResult``. No real cluster is contacted.
    """
    import uuid

    from backend.app.db import repo
    from backend.app.db.session import get_session_factory
    from backend.app.services.study_preflight import OverlapProbeResult

    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"err-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"err-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={"bm25_k1": "float"},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"err-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"err-jl-{uuid.uuid4().hex[:8]}",
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

    async def fake_probe(*args, **kwargs):  # noqa: ARG001
        return OverlapProbeResult(
            overlap_size=0,
            probed_doc_count=3,
            judged_doc_count=3,
            representative_query_id="01990000-0000-7000-8000-000000000099",
        )

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)

    body = {
        "name": "envelope-shape",
        "cluster_id": cluster.id,
        "target": "stub-index",
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": judgment_list.id,
        "search_space": {"params": {"bm25_k1": {"type": "float", "low": 0.1, "high": 2.0}}},
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "INSUFFICIENT_JUDGMENT_OVERLAP"
    assert detail["retryable"] is False
    assert "0 of 3 probed" in detail["message"]
    assert "judged_doc_count=3" in detail["message"]
