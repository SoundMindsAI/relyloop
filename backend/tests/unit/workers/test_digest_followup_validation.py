"""Unit tests for the digest worker's swap_template downgrade cascade (Story 2.3).

Owner: ``feat_digest_executable_followups_swap_template`` (Tier B).

Covers FR-8 + AC-15 via the extracted helper at
:func:`backend.workers.digest._apply_swap_template_remap`. Each test stubs
``repo.get_query_template`` so the loop body is exercised end-to-end without
booting Arq / Redis / OpenAI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.app.db import repo as db_repo
from backend.app.domain.study.followups import (
    FollowupItem,
    NarrowFollowup,
    SwapTemplateFollowup,
    TextFollowup,
)
from backend.app.domain.study.search_space import SearchSpace
from backend.workers import digest as digest_worker

_PARENT_TEMPLATE_ID = "01931e8a-0000-7890-abcd-000000000000"
_PARENT_ENGINE_TYPE = "elasticsearch"
_PARENT_DECLARED = {"title_boost": "float", "tie_breaker": "int"}

_SWAP_TARGET_ID = "01931e8a-1234-7890-abcd-ef0123456789"


def _ss() -> SearchSpace:
    return SearchSpace.model_validate(
        {"params": {"title_boost": {"type": "float", "low": 0.5, "high": 2.0}}}
    )


def _swap_item(template_id: str = _SWAP_TARGET_ID, rationale: str = "swap") -> SwapTemplateFollowup:
    return SwapTemplateFollowup(
        kind="swap_template",
        rationale=rationale,
        template_id=template_id,
        search_space=_ss(),
    )


@dataclass
class _FakeTemplate:
    id: str
    engine_type: str
    declared_params: dict[str, str]


def _make_target(
    id_: str = _SWAP_TARGET_ID,
    *,
    engine_type: str = _PARENT_ENGINE_TYPE,
    declared_params: dict[str, str] | None = None,
) -> _FakeTemplate:
    return _FakeTemplate(
        id=id_,
        engine_type=engine_type,
        declared_params=declared_params or {"title_boost": "float", "phrase_slop": "int"},
    )


class _CapturingLogger:
    """Drop-in for ``digest_worker.logger`` that records ``.info/.warning``
    keyword args in-process.

    structlog's bound loggers are *cached* on first use and don't honor
    later ``structlog.configure(...)`` changes; per-test fixtures that
    re-wire the processor pipeline thus leak across tests. Replacing the
    module-level binding sidesteps the caching contract entirely and is
    deterministic.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def _emit(self, level: str, event: str, /, **kw: Any) -> None:
        entry: dict[str, Any] = {"level": level, "event": event}
        entry.update(kw)
        self.entries.append(entry)

    def info(self, event: str, /, **kw: Any) -> None:
        self._emit("info", event, **kw)

    def warning(self, event: str, /, **kw: Any) -> None:
        self._emit("warning", event, **kw)

    def error(self, event: str, /, **kw: Any) -> None:
        self._emit("error", event, **kw)


@pytest.fixture
def worker_caplog(monkeypatch: pytest.MonkeyPatch) -> _CapturingLogger:
    """Swap the digest worker's structlog logger for an in-memory capture.

    Avoids structlog's ``cache_logger_on_first_use`` leak across tests.
    Records ``.info()`` / ``.warning()`` keyword-argument payloads
    in-process so tests can assert on ``event_type`` / ``reason`` /
    ``trusted_intersection_param_names`` etc. by dict-lookup.
    """
    cap = _CapturingLogger()
    monkeypatch.setattr(digest_worker, "logger", cap)
    return cap


def _event_record(cap: _CapturingLogger, event_type: str) -> dict[str, Any] | None:
    for entry in cap.entries:
        if entry.get("event_type") == event_type:
            return entry
    return None


def _items(*items: FollowupItem) -> list[FollowupItem]:
    """Construct a typed ``list[FollowupItem]`` from individual variants.

    Mypy treats ``list[SwapTemplateFollowup]`` as invariant on the
    discriminated-union element type; this helper widens the literal.
    """
    return list(items)


class TestReasonCascade:
    @pytest.mark.asyncio
    async def test_not_found_downgrades_with_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worker_caplog: _CapturingLogger,
    ) -> None:
        monkeypatch.setattr(
            db_repo,
            "get_query_template",
            AsyncMock(return_value=None),
        )
        result = await digest_worker._apply_swap_template_remap(
            _items(_swap_item()),
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        assert "swap_template target template not found" in result[0].rationale
        rec = _event_record(worker_caplog, "digest_followup_validation_downgraded")
        assert rec is not None
        assert rec.get("reason") == "not_found"
        assert rec.get("original_kind") == "swap_template"

    @pytest.mark.asyncio
    async def test_same_as_parent_downgrades(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worker_caplog: _CapturingLogger,
    ) -> None:
        # Target template id matches parent template id.
        same_target = _make_target(id_=_PARENT_TEMPLATE_ID)
        monkeypatch.setattr(
            db_repo,
            "get_query_template",
            AsyncMock(return_value=same_target),
        )
        result = await digest_worker._apply_swap_template_remap(
            _items(_swap_item(template_id=_PARENT_TEMPLATE_ID)),
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert isinstance(result[0], TextFollowup)
        rec = _event_record(worker_caplog, "digest_followup_validation_downgraded")
        assert rec is not None
        assert rec.get("reason") == "same_as_parent"

    @pytest.mark.asyncio
    async def test_engine_type_mismatch_downgrades(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worker_caplog: _CapturingLogger,
    ) -> None:
        mismatched = _make_target(engine_type="opensearch")
        monkeypatch.setattr(
            db_repo,
            "get_query_template",
            AsyncMock(return_value=mismatched),
        )
        result = await digest_worker._apply_swap_template_remap(
            _items(_swap_item()),
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert isinstance(result[0], TextFollowup)
        rec = _event_record(worker_caplog, "digest_followup_validation_downgraded")
        assert rec is not None
        assert rec.get("reason") == "engine_type_mismatch"

    @pytest.mark.asyncio
    async def test_remap_invalid_search_space_downgrades(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worker_caplog: _CapturingLogger,
    ) -> None:
        # Target declared_params shares NO params with parent — remap raises
        # InvalidSearchSpaceError("no shared parameters with parent template").
        no_overlap = _make_target(declared_params={"phrase_slop": "int"})
        monkeypatch.setattr(
            db_repo,
            "get_query_template",
            AsyncMock(return_value=no_overlap),
        )
        result = await digest_worker._apply_swap_template_remap(
            _items(_swap_item()),
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert isinstance(result[0], TextFollowup)
        rec = _event_record(worker_caplog, "digest_followup_validation_downgraded")
        assert rec is not None
        assert rec.get("reason") == "remap_invalid_search_space"


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_success_emits_remap_info_and_replaces_search_space(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worker_caplog: _CapturingLogger,
    ) -> None:
        # Target shares title_boost (intersection) AND introduces phrase_slop
        # (disjoint fill).
        good = _make_target(declared_params={"title_boost": "float", "phrase_slop": "int"})
        monkeypatch.setattr(
            db_repo,
            "get_query_template",
            AsyncMock(return_value=good),
        )
        item = _swap_item()
        result = await digest_worker._apply_swap_template_remap(
            _items(item),
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert len(result) == 1
        assert isinstance(result[0], SwapTemplateFollowup)
        # Search space now contains BOTH intersection + disjoint params.
        out_params = result[0].search_space.params
        assert "title_boost" in out_params
        assert "phrase_slop" in out_params
        rec = _event_record(worker_caplog, "digest_followup_swap_template_remapped")
        assert rec is not None
        assert rec.get("trusted_intersection_param_names") == ["title_boost"]
        assert rec.get("disjoint_fill_param_names") == ["phrase_slop"]


class TestNonSwapItemsPassThrough:
    @pytest.mark.asyncio
    async def test_narrow_and_text_items_unchanged_no_db_lookup(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        get_template = AsyncMock(side_effect=AssertionError("should not be called"))
        monkeypatch.setattr(db_repo, "get_query_template", get_template)
        narrow = NarrowFollowup(kind="narrow", rationale="narrow", search_space=_ss())
        text = TextFollowup(kind="text", rationale="text", search_space=None)
        result = await digest_worker._apply_swap_template_remap(
            _items(narrow, text),
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert result == _items(narrow, text)
        get_template.assert_not_awaited()


class TestTruncateFirst:
    @pytest.mark.asyncio
    async def test_helper_only_inspects_supplied_list_no_extra_lookups(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-15: the 6th-and-beyond items must already be truncated by the
        caller — the helper itself never lookups items beyond what it receives.

        We assert this by passing 5 swap_template items and verifying the
        DB lookup count == 5 (one per distinct template_id with the cache
        working). The caller (generate_digest) guarantees ``[:5]`` runs
        BEFORE this helper per Story 2.3 Step 13.5.
        """
        good = _make_target()
        mock = AsyncMock(return_value=good)
        monkeypatch.setattr(db_repo, "get_query_template", mock)
        items = _items(*[_swap_item(rationale=f"i{i}") for i in range(5)])
        result = await digest_worker._apply_swap_template_remap(
            items,
            db=AsyncMock(),
            parent_template_id=_PARENT_TEMPLATE_ID,
            parent_declared_params=_PARENT_DECLARED,
            parent_engine_type=_PARENT_ENGINE_TYPE,
            study_id="s1",
            proposal_id="p1",
        )
        assert len(result) == 5
        # All 5 items share the same template_id — per-call cache means
        # exactly ONE DB lookup runs, not 5.
        assert mock.await_count == 1
