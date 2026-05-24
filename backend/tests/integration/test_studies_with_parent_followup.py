"""POST /api/v1/studies parent body integration test (Story 4.2).

Covers all four paths from spec §8.5 + the malformed-payload envelope
cases:

- Happy path: ``POST /studies`` with a valid ``parent`` persists both
  lineage columns on the new study row.
- Unknown ``parent.proposal_id`` → 404 ``PROPOSAL_NOT_FOUND`` (non-retryable).
- Existing proposal without digest → 404 ``DIGEST_NOT_FOUND`` (retryable).
- Stale ``followup_index`` → 422 ``FOLLOWUP_INDEX_OUT_OF_RANGE`` (non-retryable).
- Malformed ``parent`` body shapes → 422 ``VALIDATION_ERROR``
  (FastAPI's RequestValidationError handler).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)


@pytest.fixture(autouse=True)
def _default_overlap_probe_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the overlap probe so POST /studies isn't blocked by the empty-
    judgments 422.

    Mirrors the same autouse fixture in test_studies_api.py — without it
    every happy-path test in this module would 422 on
    INSUFFICIENT_JUDGMENT_OVERLAP because we don't seed judgments.
    """
    from backend.app.services.study_preflight import OverlapProbeResult

    async def fake_probe_passes(*args: object, **kwargs: object) -> OverlapProbeResult:
        return OverlapProbeResult(
            overlap_size=10,
            probed_doc_count=10,
            judged_doc_count=10,
            representative_query_id="01990000-0000-7000-8000-000000000099",
        )

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe_passes)


_VALID_SEARCH_SPACE = {
    "params": {
        "bm25_k1": {"type": "float", "low": 0.1, "high": 2.0},
    }
}


def _request_body(
    *,
    seeded: dict[str, str],
    parent: dict[str, object] | None,
    name_suffix: str = "child",
) -> dict[str, object]:
    body: dict[str, object] = {
        "name": f"followup-test-{name_suffix}-{uuid.uuid4().hex[:8]}",
        "cluster_id": seeded["cluster_id"],
        "target": "stub-index",
        "template_id": seeded["template_id"],
        "query_set_id": seeded["query_set_id"],
        "judgment_list_id": seeded["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
        "config": {"max_trials": 5},
    }
    if parent is not None:
        body["parent"] = parent
    return body


async def _seed_parent_chain() -> dict[str, str]:
    """Seed cluster + template (1 declared param) + query_set + judgment_list +
    a completed study + a pending proposal.

    Returns dict with ``cluster_id``, ``template_id``, ``query_set_id``,
    ``judgment_list_id``, ``study_id``, ``proposal_id``.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"fp-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"fp-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={"bm25_k1": "float"},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"fp-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"fp-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        study_id = str(uuid.uuid4())
        await repo.create_study(
            db,
            id=study_id,
            name=f"fp-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            search_space=_VALID_SEARCH_SPACE,
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 5},
            status="completed",
            optuna_study_name=study_id,
        )
        proposal = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            study_trial_id=None,
            cluster_id=cluster.id,
            template_id=template.id,
            config_diff={},
            metric_delta=None,
            status="pending",
        )
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": judgment_list.id,
        "study_id": study_id,
        "proposal_id": proposal.id,
    }


async def _seed_digest_with_one_followup(study_id: str) -> None:
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            text(
                "INSERT INTO digests (id, study_id, narrative, parameter_importance, "
                "recommended_config, suggested_followups, generated_by, generated_at) "
                "VALUES (:id, :sid, 'n', '{}'::jsonb, '{}'::jsonb, "
                'CAST(\'[{"kind": "text", "rationale": "try X", "search_space": null}]\' '
                "AS jsonb), 'openai:gpt-4o-2024-08-06', NOW())"
            ),
            {"id": str(uuid.uuid4()), "sid": study_id},
        )
        await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestStudiesWithParentFollowup:
    async def test_happy_path_persists_lineage(self, async_client: httpx.AsyncClient) -> None:
        seeded = await _seed_parent_chain()
        await _seed_digest_with_one_followup(seeded["study_id"])

        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": seeded["proposal_id"], "followup_index": 0},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 201, response.text
        new_id = response.json()["id"]

        factory = get_session_factory()
        async with factory() as db:
            new_study = await db.get(Study, new_id)
            assert new_study is not None
            assert new_study.parent_proposal_id == seeded["proposal_id"]
            assert new_study.parent_proposal_followup_index == 0

    async def test_unknown_proposal_id_returns_404_proposal_not_found(
        self, async_client: httpx.AsyncClient
    ) -> None:
        seeded = await _seed_parent_chain()
        await _seed_digest_with_one_followup(seeded["study_id"])

        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": str(uuid.uuid4()), "followup_index": 0},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 404, response.text
        detail = response.json()["detail"]
        assert detail["error_code"] == "PROPOSAL_NOT_FOUND"
        assert detail["retryable"] is False

    async def test_proposal_without_digest_returns_404_digest_not_found(
        self, async_client: httpx.AsyncClient
    ) -> None:
        # Seed a proposal but do NOT seed a digest.
        seeded = await _seed_parent_chain()
        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": seeded["proposal_id"], "followup_index": 0},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 404, response.text
        detail = response.json()["detail"]
        assert detail["error_code"] == "DIGEST_NOT_FOUND"
        assert detail["retryable"] is True

    async def test_stale_followup_index_returns_422(self, async_client: httpx.AsyncClient) -> None:
        seeded = await _seed_parent_chain()
        # Digest has 1 followup at index 0; ask for index 1.
        await _seed_digest_with_one_followup(seeded["study_id"])

        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": seeded["proposal_id"], "followup_index": 1},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["error_code"] == "FOLLOWUP_INDEX_OUT_OF_RANGE"
        assert detail["retryable"] is False

    async def test_omitted_parent_preserves_existing_behavior(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """No `parent` → study created with NULL lineage columns (regression check)."""
        seeded = await _seed_parent_chain()
        body = _request_body(seeded=seeded, parent=None, name_suffix="no-parent")
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 201, response.text
        new_id = response.json()["id"]
        factory = get_session_factory()
        async with factory() as db:
            new_study = await db.get(Study, new_id)
            assert new_study is not None
            assert new_study.parent_proposal_id is None
            assert new_study.parent_proposal_followup_index is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestMalformedParentBodyEnvelope:
    """FastAPI's RequestValidationError → canonical VALIDATION_ERROR 422 envelope."""

    async def test_short_proposal_id_returns_validation_error(
        self, async_client: httpx.AsyncClient
    ) -> None:
        seeded = await _seed_parent_chain()
        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": "short", "followup_index": 0},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 422
        body_json = response.json()
        assert body_json["detail"]["error_code"] == "VALIDATION_ERROR"
        assert body_json["detail"]["retryable"] is False

    async def test_negative_followup_index_returns_validation_error(
        self, async_client: httpx.AsyncClient
    ) -> None:
        seeded = await _seed_parent_chain()
        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": str(uuid.uuid4()), "followup_index": -1},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 422
        body_json = response.json()
        assert body_json["detail"]["error_code"] == "VALIDATION_ERROR"
        assert body_json["detail"]["retryable"] is False

    async def test_non_string_proposal_id_returns_validation_error(
        self, async_client: httpx.AsyncClient
    ) -> None:
        seeded = await _seed_parent_chain()
        body = _request_body(
            seeded=seeded,
            parent={"proposal_id": 123, "followup_index": 0},
        )
        response = await async_client.post("/api/v1/studies", json=body)
        assert response.status_code == 422
        body_json = response.json()
        assert body_json["detail"]["error_code"] == "VALIDATION_ERROR"
        assert body_json["detail"]["retryable"] is False
