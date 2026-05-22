"""Unit tests for ``backend.app.services.study_preflight.probe_judgment_overlap``.

Verifies the probe orchestration with mocked repo + adapter dependencies.
No DB needed. Real-engine and end-to-end behavior is covered by the
integration suite in ``backend/tests/integration/test_studies_api.py``.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest
import structlog

from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.adapters.protocol import ScoredHit
from backend.app.db.models import Cluster
from backend.app.services import study_preflight
from backend.tests._log_helpers import assert_log_level, find_log_events


def _cluster() -> Cluster:
    """Build a minimal Cluster ORM object (no DB session needed)."""
    c = Cluster()
    c.id = "01990000-0000-7000-8000-00000000c001"
    c.name = "test-cluster"
    return c


class _FakeAdapter:
    """Lightweight stand-in for ElasticAdapter — only ``search_batch`` is used."""

    def __init__(
        self, *, response: dict[str, list[ScoredHit]] | None = None, raises: Exception | None = None
    ) -> None:
        self._response = response or {}
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def search_batch(self, **kwargs: Any) -> dict[str, list[ScoredHit]]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._response

    async def aclose(self) -> None:
        return None


def _fake_acquire_adapter(adapter: _FakeAdapter):
    """Return an async-context-manager callable that yields ``adapter``."""

    @contextlib.asynccontextmanager
    async def cm(_cluster: Cluster):
        yield adapter

    return cm


class TestProbeJudgmentOverlap:
    async def test_happy_path_returns_overlap_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """3 hits returned → overlap_size=3; dict-key unpack via .get("overlap_probe", [])."""
        cluster = _cluster()

        async def fake_find(db, *, query_set_id, judgment_list_id):  # noqa: ARG001
            return "01990000-0000-7000-8000-000000000099"

        async def fake_count(db, list_id, qid):  # noqa: ARG001
            return 5

        async def fake_list_doc_ids(db, list_id, qid, *, limit):  # noqa: ARG001
            return ["d1", "d2", "d3", "d4", "d5"][:limit]

        adapter = _FakeAdapter(
            response={
                "overlap_probe": [
                    ScoredHit(doc_id="d1", score=1.0),
                    ScoredHit(doc_id="d2", score=1.0),
                    ScoredHit(doc_id="d3", score=1.0),
                ]
            }
        )

        monkeypatch.setattr("backend.app.db.repo.find_first_judged_query", fake_find)
        monkeypatch.setattr("backend.app.db.repo.count_judgments_for_list_and_query", fake_count)
        monkeypatch.setattr(
            "backend.app.db.repo.list_doc_ids_for_list_and_query", fake_list_doc_ids
        )
        monkeypatch.setattr(study_preflight, "acquire_adapter", _fake_acquire_adapter(adapter))

        result = await study_preflight.probe_judgment_overlap(
            db=None,  # type: ignore[arg-type]
            cluster=cluster,
            judgment_list_id="01990000-0000-7000-8000-0000000000aa",
            query_set_id="01990000-0000-7000-8000-0000000000bb",
            target="products",
        )

        assert result is not None
        assert result.overlap_size == 3
        assert result.probed_doc_count == 5
        assert result.judged_doc_count == 5
        assert result.representative_query_id == "01990000-0000-7000-8000-000000000099"
        # Adapter received exactly one search_batch call with the locked shape.
        assert len(adapter.calls) == 1
        call = adapter.calls[0]
        assert call["target"] == "products"
        assert call["strict_errors"] is True
        assert call["timeout"] == study_preflight.PROBE_TIMEOUT_S
        assert call["top_k"] == 5
        assert len(call["queries"]) == 1
        native = call["queries"][0]
        assert native.query_id == "overlap_probe"
        assert native.body == {
            "query": {"ids": {"values": ["d1", "d2", "d3", "d4", "d5"]}},
            "size": 5,
        }

    async def test_unexpected_dict_key_falls_back_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adapter returns hits under a wrong key → overlap_size=0 via .get() fallback.

        Locks the defensive ``result.get("overlap_probe", [])`` semantics so a
        future refactor that switches to ``result["overlap_probe"]`` (which
        would raise KeyError, surfacing as a 500) gets caught by this test.
        """
        cluster = _cluster()

        async def fake_find(db, *, query_set_id, judgment_list_id):  # noqa: ARG001
            return "qid-1"

        async def fake_count(db, list_id, qid):  # noqa: ARG001
            return 1

        async def fake_list_doc_ids(db, list_id, qid, *, limit):  # noqa: ARG001
            return ["d1"]

        adapter = _FakeAdapter(response={"different_key": [ScoredHit(doc_id="d1", score=1.0)]})

        monkeypatch.setattr("backend.app.db.repo.find_first_judged_query", fake_find)
        monkeypatch.setattr("backend.app.db.repo.count_judgments_for_list_and_query", fake_count)
        monkeypatch.setattr(
            "backend.app.db.repo.list_doc_ids_for_list_and_query", fake_list_doc_ids
        )
        monkeypatch.setattr(study_preflight, "acquire_adapter", _fake_acquire_adapter(adapter))

        result = await study_preflight.probe_judgment_overlap(
            db=None,  # type: ignore[arg-type]
            cluster=cluster,
            judgment_list_id="jl-1",
            query_set_id="qs-1",
            target="products",
        )

        assert result is not None
        assert result.overlap_size == 0
        assert result.probed_doc_count == 1
        assert result.judged_doc_count == 1
        assert result.representative_query_id == "qid-1"

    async def test_empty_judgments_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``find_first_judged_query`` returns None → sentinel result, no adapter call,
        INFO log emitted with the spec's field set."""
        cluster = _cluster()

        async def fake_find(db, *, query_set_id, judgment_list_id):  # noqa: ARG001
            return None

        # Stand-in that fails if invoked. acquire_adapter must NOT be called on
        # the empty path.
        @contextlib.asynccontextmanager
        async def acquire_adapter_should_not_be_called(_c):  # noqa: ARG001
            if True:  # keep the yield reachable for the typechecker
                raise AssertionError("acquire_adapter must not be called on the empty path")
            yield  # type: ignore[unreachable]

        monkeypatch.setattr("backend.app.db.repo.find_first_judged_query", fake_find)
        monkeypatch.setattr(
            study_preflight, "acquire_adapter", acquire_adapter_should_not_be_called
        )

        with structlog.testing.capture_logs() as cap:
            result = await study_preflight.probe_judgment_overlap(
                db=None,  # type: ignore[arg-type]
                cluster=cluster,
                judgment_list_id="jl-1",
                query_set_id="qs-1",
                target="products",
            )

        assert result is not None
        assert result.overlap_size == 0
        assert result.probed_doc_count == 0
        assert result.judged_doc_count == 0
        assert result.representative_query_id is None

        empty_events = find_log_events(cap, event="studies.preflight.overlap_probe.empty")
        assert len(empty_events) == 1
        ev = empty_events[0]
        assert ev["study_judgment_list_id"] == "jl-1"
        assert ev["study_query_set_id"] == "qs-1"
        assert_log_level(ev, "info")

    async def test_cluster_unreachable_returns_none_and_warns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adapter raises ClusterUnreachableError → probe returns None and emits a
        WARN log with the documented field set and reason='unreachable'."""
        cluster = _cluster()

        async def fake_find(db, *, query_set_id, judgment_list_id):  # noqa: ARG001
            return "qid-1"

        async def fake_count(db, list_id, qid):  # noqa: ARG001
            return 5

        async def fake_list_doc_ids(db, list_id, qid, *, limit):  # noqa: ARG001
            return ["d1", "d2", "d3", "d4", "d5"]

        adapter = _FakeAdapter(raises=ClusterUnreachableError("simulated"))

        monkeypatch.setattr("backend.app.db.repo.find_first_judged_query", fake_find)
        monkeypatch.setattr("backend.app.db.repo.count_judgments_for_list_and_query", fake_count)
        monkeypatch.setattr(
            "backend.app.db.repo.list_doc_ids_for_list_and_query", fake_list_doc_ids
        )
        monkeypatch.setattr(study_preflight, "acquire_adapter", _fake_acquire_adapter(adapter))

        with structlog.testing.capture_logs() as cap:
            result = await study_preflight.probe_judgment_overlap(
                db=None,  # type: ignore[arg-type]
                cluster=cluster,
                judgment_list_id="jl-1",
                query_set_id="qs-1",
                target="products",
            )

        assert result is None
        skipped_events = find_log_events(cap, event="studies.preflight.overlap_probe.skipped")
        assert len(skipped_events) == 1
        ev = skipped_events[0]
        assert_log_level(ev, "warning")
        assert ev["reason"] == "unreachable"
        assert ev["study_judgment_list_id"] == "jl-1"
        assert ev["study_query_set_id"] == "qs-1"
        assert ev["study_target"] == "products"
        assert ev["cluster_id"] == cluster.id
        assert ev["cluster_name"] == "test-cluster"
