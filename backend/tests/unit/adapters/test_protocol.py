"""SearchAdapter Protocol + Pydantic types — unit tests (Story 1.1, FR-1)."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from backend.app.adapters.protocol import (
    EngineType,
    ExplainTree,
    FieldSpec,
    HealthStatus,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    Schema,
    ScoredHit,
    SearchAdapter,
    TargetInfo,
)


class _StubAdapter:
    """Async-correct stub used to verify the Protocol's @runtime_checkable contract.

    isinstance(stub, SearchAdapter) returns True only when:
    - All declared attributes/methods exist on the stub.
    - The async ones are coroutine functions; the sync ones are not.
    """

    engine_type: EngineType = "elasticsearch"

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        return HealthStatus(status="green", version="9.4.0", checked_at="2026-05-09T00:00:00Z")

    async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]:
        return []

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        return Schema(name=target, fields=[])

    def list_query_parsers(self) -> list[str]:
        return ["match"]

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery:
        return NativeQuery(query_id=template.name, body={})

    async def search_batch(
        self,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        return {q.query_id: [] for q in queries}

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        return ExplainTree(doc_id=doc_id, matched=False, value=0.0, description="")


# -----------------------------------------------------------------------------
# Protocol shape
# -----------------------------------------------------------------------------


def test_stub_satisfies_protocol() -> None:
    """A stub with the right shape passes isinstance via @runtime_checkable."""
    stub = _StubAdapter()
    assert isinstance(stub, SearchAdapter)


def test_async_methods_are_coroutines() -> None:
    """Lock in the async contract — these methods MUST be coroutines.

    runtime_checkable Protocol does not enforce async-ness at type level
    (it only checks attribute presence). This test exists so future refactors
    can't accidentally make an I/O method synchronous.
    """
    stub = _StubAdapter()
    for name in ("health_check", "list_targets", "get_schema", "search_batch", "explain"):
        method = getattr(stub, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"


def test_sync_methods_are_not_coroutines() -> None:
    """Pure methods (render, list_query_parsers) MUST stay sync."""
    stub = _StubAdapter()
    for name in ("render", "list_query_parsers"):
        method = getattr(stub, name)
        assert not inspect.iscoroutinefunction(method), f"{name} must be sync"


# -----------------------------------------------------------------------------
# Pydantic types — valid + invalid cases for each
# -----------------------------------------------------------------------------


class TestHealthStatus:
    def test_valid_green(self) -> None:
        h = HealthStatus(status="green", version="9.4.0", checked_at="2026-05-09T00:00:00Z")
        assert h.status == "green"
        assert h.error is None

    def test_valid_unreachable(self) -> None:
        h = HealthStatus(status="unreachable", checked_at="2026-05-09T00:00:00Z", error="boom")
        assert h.status == "unreachable"
        assert h.error == "boom"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HealthStatus(status="purple", checked_at="2026-05-09T00:00:00Z")


class TestFieldSpec:
    def test_valid(self) -> None:
        f = FieldSpec(name="title", type="text", analyzer="standard")
        assert f.analyzer == "standard"

    def test_minimal_no_analyzer(self) -> None:
        f = FieldSpec(name="price", type="float")
        assert f.analyzer is None

    def test_invalid_missing_required(self) -> None:
        with pytest.raises(ValidationError):
            FieldSpec(name="title")  # type: ignore[call-arg]


class TestSchema:
    def test_valid(self) -> None:
        s = Schema(name="products", fields=[FieldSpec(name="title", type="text")])
        assert len(s.fields) == 1


class TestNativeQuery:
    def test_valid(self) -> None:
        q = NativeQuery(query_id="q1", body={"query": {"match_all": {}}})
        assert q.query_id == "q1"

    def test_body_must_be_dict(self) -> None:
        with pytest.raises(ValidationError):
            NativeQuery(query_id="q1", body="not a dict")


class TestScoredHit:
    def test_valid(self) -> None:
        h = ScoredHit(doc_id="abc", score=1.5, source={"title": "x"})
        assert h.score == 1.5

    def test_minimal(self) -> None:
        h = ScoredHit(doc_id="abc", score=0.0)
        assert h.source is None


class TestExplainTree:
    def test_leaf(self) -> None:
        t = ExplainTree(doc_id="abc", matched=True, value=1.0, description="leaf")
        assert t.details == []

    def test_recursive(self) -> None:
        child = ExplainTree(doc_id="abc", matched=True, value=0.5, description="child")
        parent = ExplainTree(
            doc_id="abc", matched=True, value=1.0, description="parent", details=[child]
        )
        assert parent.details[0].description == "child"


class TestTargetInfo:
    def test_valid(self) -> None:
        t = TargetInfo(name="products", doc_count=1000)
        assert t.doc_count == 1000


class TestQueryTemplate:
    def test_valid(self) -> None:
        qt = QueryTemplate(
            name="multi_match_v1",
            engine_type="elasticsearch",
            body="{}",
            declared_params={"boost": "float"},
        )
        assert qt.engine_type == "elasticsearch"

    def test_invalid_engine_type(self) -> None:
        with pytest.raises(ValidationError):
            QueryTemplate(
                name="x",
                engine_type="solr",
                body="{}",
                declared_params={},
            )
