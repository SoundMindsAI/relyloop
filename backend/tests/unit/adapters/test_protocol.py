"""SearchAdapter Protocol + Pydantic types — unit tests (Story 1.1, FR-1)."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from backend.app.adapters.protocol import (
    AdapterDocumentHit,
    Document,
    DocumentPage,
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

    async def get_document(
        self,
        target: str,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> Document | None:
        return None

    async def list_documents(
        self,
        target: str,
        *,
        search_after: list[object] | None = None,
        limit: int = 25,
        fields: list[str] | None = None,
        request_id: str | None = None,
    ) -> DocumentPage:
        return DocumentPage(hits=[], total=0)


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
    for name in (
        "health_check",
        "list_targets",
        "get_schema",
        "search_batch",
        "explain",
        "get_document",
        "list_documents",
    ):
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


class TestDocument:
    """feat_index_document_browser Story 1.1 — Document model shape + invariants."""

    def test_valid(self) -> None:
        d = Document(doc_id="prod-001", source={"title": "Apple Watch"})
        assert d.doc_id == "prod-001"
        assert d.source == {"title": "Apple Watch"}

    def test_source_can_be_none(self) -> None:
        """``_source: false`` indexes return source=None — not an error."""
        d = Document(doc_id="prod-001", source=None)
        assert d.source is None

    def test_doc_id_empty_string_rejected(self) -> None:
        """Field(min_length=1) on doc_id enforces non-empty (spec FR-1 + cycle-3 F6)."""
        with pytest.raises(ValidationError):
            Document(doc_id="", source={})


class TestAdapterDocumentHit:
    """feat_index_document_browser Story 1.1 — list page hit shape."""

    def test_valid(self) -> None:
        h = AdapterDocumentHit(doc_id="prod-001", source={"x": 1}, sort=["prod-001"])
        assert h.sort == ["prod-001"]

    def test_sort_required(self) -> None:
        """``sort`` must be present — the router relies on it for cursor encoding."""
        with pytest.raises(ValidationError):
            AdapterDocumentHit(doc_id="prod-001", source={})  # type: ignore[call-arg]

    def test_doc_id_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdapterDocumentHit(doc_id="", source={}, sort=["x"])


class TestDocumentPage:
    """feat_index_document_browser Story 1.1 — paginated list page wrapper."""

    def test_valid_empty(self) -> None:
        p = DocumentPage(hits=[], total=0)
        assert p.hits == []
        assert p.total == 0

    def test_valid_with_hits(self) -> None:
        h1 = AdapterDocumentHit(doc_id="a", source=None, sort=["a"])
        h2 = AdapterDocumentHit(doc_id="b", source=None, sort=["b"])
        p = DocumentPage(hits=[h1, h2], total=2)
        assert len(p.hits) == 2

    def test_no_last_sort_field(self) -> None:
        """The cycle-2 F1 fix removed `last_sort` — per-hit sort replaces it."""
        p = DocumentPage(hits=[], total=0)
        assert not hasattr(p, "last_sort")


class TestAdapterErrors:
    """feat_create_study_target_autocomplete Story B1: TargetsForbiddenError is
    a distinct exception class so routers can translate ACL restrictions
    (403 TARGETS_FORBIDDEN, retryable=false) separately from connection
    failures (503 CLUSTER_UNREACHABLE, retryable=true).
    """

    def test_targets_forbidden_is_distinct_class(self) -> None:
        from backend.app.adapters.errors import (
            ClusterUnreachableError,
            TargetNotFoundError,
            TargetsForbiddenError,
        )

        # Not a subclass of either sibling — distinct dispatch in router.
        assert not issubclass(TargetsForbiddenError, ClusterUnreachableError)
        assert not issubclass(TargetsForbiddenError, TargetNotFoundError)
        assert not issubclass(ClusterUnreachableError, TargetsForbiddenError)
        assert not issubclass(TargetNotFoundError, TargetsForbiddenError)
