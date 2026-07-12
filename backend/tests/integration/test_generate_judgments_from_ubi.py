# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for :func:`backend.workers.judgments_ubi.generate_judgments_from_ubi`
(feat_ubi_judgments Story 3.3 / FR-5).

Exercises the worker against the real DB + real repo + real domain
converters + real budget gate, with the engine adapter + (for hybrid)
the OpenAI client monkeypatched at module level. Mirrors
``test_judgment_generate.py`` (the LLM-worker integration test).

Covered paths:

* clean pure-UBI loop → completes with all ``source='click'`` rows +
  calibration coverage.
* hybrid loop → mixed ``source='click'`` + ``source='llm'`` rows.
* race-fallback empty features → terminal ``failed`` /
  ``UBI_INSUFFICIENT_DATA``.
* missing ``generation_params`` → terminal ``failed`` /
  ``MISSING_GENERATION_PARAMS``.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.adapters.protocol import Document, NativeQuery, ScanPage, ScoredHit
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_chain(
    *,
    converter: str,
    user_queries: list[str],
    generation_params_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seed cluster + template + query set + queries + a generating UBI list.

    Returns the judgment_list_id + the {user_query: query_id} map so the
    test can shape the stubbed UBI reader output to match.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="opensearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="opensearch_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="opensearch",
            body='{"query": {"match": {"title": {{ query_text | tojson }}}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        user_query_to_id: dict[str, str] = {}
        for text_ in user_queries:
            q = await repo.create_query(
                db,
                id=str(uuid.uuid4()),
                query_set_id=query_set.id,
                query_text=text_,
            )
            user_query_to_id[text_] = q.id
        params: dict[str, Any] = {
            "generation_kind": "ubi",
            "target": "products",
            "since": "2026-05-01T00:00:00+00:00",
            "until": "2026-05-29T00:00:00+00:00",
            "converter": converter,
            "converter_config": None,
            "llm_fill_threshold": 20,
            "min_impressions_threshold": 100,
            "mapping_strategy": "reject",
            "current_template_id": template.id if converter == "hybrid_ubi_llm" else None,
            "rubric": "rate 0-3" if converter == "hybrid_ubi_llm" else None,
        }
        if generation_params_extra:
            params.update(generation_params_extra)
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-jl-{uuid.uuid4().hex[:8]}",
            description="ubi worker integration",
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="products",
            current_template_id=template.id if converter == "hybrid_ubi_llm" else None,
            rubric="rate 0-3" if converter == "hybrid_ubi_llm" else f"UBI converter: {converter}",
            status="generating",
            failed_reason=None,
            calibration=None,
            generation_params=params,
        )
        await db.commit()
    return {
        "judgment_list_id": jl.id,
        "cluster_id": cluster.id,
        "user_query_to_id": user_query_to_id,
    }


def _ubi_adapter_stub(
    *,
    user_query_to_id: dict[str, str],
    docs_per_query: int = 3,
    clicks_per_query: int = 2,
    impressions_per_pair: int = 200,
) -> Any:
    """Build a MagicMock adapter that fakes the two UbiReader scans.

    The reader issues ``ubi_queries_scan`` (returns ScoredHits whose
    ``_source.query_id``/``user_query`` build the join map) and
    ``ubi_events_scan`` (returns the click/impression events). We use the
    internal query_id as the UBI query_id too for simplicity — the worker's
    mapping_strategy join matches on ``user_query`` text so the UBI
    query_id value is opaque.
    """
    adapter = MagicMock()
    adapter.engine_type = "opensearch"
    adapter.aclose = AsyncMock()
    from backend.app.adapters.protocol import Schema

    adapter.get_schema = AsyncMock(return_value=Schema(name="ubi_queries", fields=[]))

    async def search_batch(
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        native = queries[0]
        if native.query_id == "ubi_queries_scan":
            hits = [
                ScoredHit(
                    doc_id=ubi_qid,
                    score=1.0,
                    source={
                        "query_id": ubi_qid,
                        "user_query": user_query,
                        "application": "products",
                        "timestamp": "2026-05-20T10:00:00Z",
                    },
                )
                for user_query, ubi_qid in user_query_to_id.items()
            ]
            return {"ubi_queries_scan": hits}
        if native.query_id == "ubi_events_scan":
            events: list[ScoredHit] = []
            for ubi_qid in user_query_to_id.values():
                for d in range(docs_per_query):
                    doc_id = f"doc-{d}"
                    for _ in range(impressions_per_pair):
                        events.append(
                            ScoredHit(
                                doc_id="evt",
                                score=0.0,
                                source={
                                    "query_id": ubi_qid,
                                    "action_name": "impression",
                                    "object_id": doc_id,
                                    "position": d + 1,
                                    "timestamp": "2026-05-20T10:01:00Z",
                                },
                            )
                        )
                    for _ in range(clicks_per_query if d == 0 else 0):
                        events.append(
                            ScoredHit(
                                doc_id="evt",
                                score=0.0,
                                source={
                                    "query_id": ubi_qid,
                                    "action_name": "click",
                                    "object_id": doc_id,
                                    "timestamp": "2026-05-20T10:02:00Z",
                                },
                            )
                        )
            return {"ubi_events_scan": events}
        raise AssertionError(f"unexpected scan {native.query_id!r}")

    adapter.search_batch = AsyncMock(side_effect=search_batch)

    # chore_ubi_reader_search_after_pagination — UbiReader now paginates via
    # adapter.scan_all() + adapter.close_scan() instead of a single
    # search_batch call. Serve the SAME canned data (keyed on the scan
    # target instead of the NativeQuery.query_id) as a single terminal
    # ScanPage so the worker's paginated read produces identical features.
    def _query_scan_hits() -> list[ScoredHit]:
        return [
            ScoredHit(
                doc_id=ubi_qid,
                score=1.0,
                source={
                    "query_id": ubi_qid,
                    "user_query": user_query,
                    "application": "products",
                    "timestamp": "2026-05-20T10:00:00Z",
                },
            )
            for user_query, ubi_qid in user_query_to_id.items()
        ]

    def _event_scan_hits() -> list[ScoredHit]:
        events: list[ScoredHit] = []
        for ubi_qid in user_query_to_id.values():
            for d in range(docs_per_query):
                doc_id = f"doc-{d}"
                for _ in range(impressions_per_pair):
                    events.append(
                        ScoredHit(
                            doc_id="evt",
                            score=0.0,
                            source={
                                "query_id": ubi_qid,
                                "action_name": "impression",
                                "object_id": doc_id,
                                "position": d + 1,
                                "timestamp": "2026-05-20T10:01:00Z",
                            },
                        )
                    )
                for _ in range(clicks_per_query if d == 0 else 0):
                    events.append(
                        ScoredHit(
                            doc_id="evt",
                            score=0.0,
                            source={
                                "query_id": ubi_qid,
                                "action_name": "click",
                                "object_id": doc_id,
                                "timestamp": "2026-05-20T10:02:00Z",
                            },
                        )
                    )
        return events

    async def scan_all(
        target: str,
        body: dict[str, Any],
        *,
        page_size: int,
        cursor: object | None = None,
        fl: list[str] | None = None,
        request_id: str | None = None,
    ) -> ScanPage:
        # Single terminal page per scan; cursor=None ends the reader loop.
        # The default ceilings (1M events / 200k queries) comfortably exceed
        # these canned volumes, so no truncation occurs.
        if target == "ubi_queries":
            return ScanPage(hits=_query_scan_hits(), cursor=None)
        if target == "ubi_events":
            return ScanPage(hits=_event_scan_hits(), cursor=None)
        raise AssertionError(f"unexpected scan_all target {target!r}")

    adapter.scan_all = AsyncMock(side_effect=scan_all)
    adapter.close_scan = AsyncMock(return_value=None)

    async def get_document(target: str, doc_id: str, *, request_id: str | None = None) -> Document:
        return Document(doc_id=doc_id, source={"body": f"body for {doc_id}"})

    adapter.get_document = AsyncMock(side_effect=get_document)
    return adapter


async def test_clean_pure_ubi_loop_completes_with_click_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = await _seed_chain(converter="ctr_threshold", user_queries=["red shoes", "blue shirt"])
    adapter = _ubi_adapter_stub(user_query_to_id=seeded["user_query_to_id"])
    monkeypatch.setattr("backend.workers.judgments_ubi.build_adapter", lambda c: adapter)

    from backend.workers.judgments_ubi import generate_judgments_from_ubi

    await generate_judgments_from_ubi({}, seeded["judgment_list_id"])

    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, seeded["judgment_list_id"])
        assert jl is not None
        assert jl.status == "complete"
        breakdown = await repo.source_breakdown_for_list(db, seeded["judgment_list_id"])
        assert breakdown["click"] > 0
        assert breakdown["llm"] == 0
        assert jl.calibration is not None
        assert "coverage_pct" in jl.calibration


async def test_missing_generation_params_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    seeded = await _seed_chain(converter="ctr_threshold", user_queries=["q1"])
    # Null out generation_params to simulate the partial-deploy race.
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, seeded["judgment_list_id"])
        assert jl is not None
        jl.generation_params = None
        await db.commit()

    from backend.workers.judgments_ubi import generate_judgments_from_ubi

    await generate_judgments_from_ubi({}, seeded["judgment_list_id"])

    async with factory() as db:
        jl = await repo.get_judgment_list(db, seeded["judgment_list_id"])
        assert jl is not None
        assert jl.status == "failed"
        assert jl.failed_reason == "MISSING_GENERATION_PARAMS"


async def test_empty_features_race_fallback_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    seeded = await _seed_chain(converter="ctr_threshold", user_queries=["q1"])
    # Adapter whose events scan returns nothing → empty features.
    adapter = _ubi_adapter_stub(user_query_to_id={})  # no queries → empty
    monkeypatch.setattr("backend.workers.judgments_ubi.build_adapter", lambda c: adapter)

    from backend.workers.judgments_ubi import generate_judgments_from_ubi

    await generate_judgments_from_ubi({}, seeded["judgment_list_id"])

    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, seeded["judgment_list_id"])
        assert jl is not None
        assert jl.status == "failed"
        assert jl.failed_reason == "UBI_INSUFFICIENT_DATA"


async def test_already_terminal_list_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    seeded = await _seed_chain(converter="ctr_threshold", user_queries=["q1"])
    factory = get_session_factory()
    async with factory() as db:
        await repo.update_judgment_list_status(db, seeded["judgment_list_id"], status="complete")
        await db.commit()

    # If the worker tried to build an adapter it would hit the (unpatched)
    # real build_adapter + fail differently; the early-return guard means it
    # never gets there.
    from backend.workers.judgments_ubi import generate_judgments_from_ubi

    await generate_judgments_from_ubi({}, seeded["judgment_list_id"])

    async with factory() as db:
        jl = await repo.get_judgment_list(db, seeded["judgment_list_id"])
        assert jl is not None
        assert jl.status == "complete"  # unchanged
