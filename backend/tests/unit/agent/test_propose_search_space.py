"""Unit tests for ``propose_search_space_impl`` (feat_agent_propose_search_space Story 3.2).

Covers every spec FR-2 / FR-3 path: arg validation, all 5 error codes,
heuristic-only happy path, prior-study narrowing (linear + log), prior-study
out-of-bounds skip, missing-trial graceful degrade, template-mismatch
graceful degrade, returned-grounding shape, registry sanity, mutation-set
exclusion, and the read-only guarantee (``ctx.db.commit()`` never called).

The tool's DB calls are stubbed via AsyncMock — this is a pure unit test
covering the orchestration logic; the round-trip through real Postgres is
covered by the integration test in Story 4.2.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.agent.confirmation import MUTATING_TOOL_NAMES
from backend.app.agent.tools import TOOL_ARG_MODELS, TOOL_REGISTRY, TOOLS
from backend.app.agent.tools.studies.propose_search_space import (
    PROPOSE_SEARCH_SPACE_TOOL,
    ProposeSearchSpaceArgs,
    propose_search_space_impl,
)
from backend.app.domain.study.search_space import SearchSpace


def _detail(exc: HTTPException) -> dict[str, Any]:
    """Cast HTTPException.detail to dict for index-typed assertions."""
    return cast(dict[str, Any], exc.detail)


def _uuid() -> str:
    return str(uuid4())


def _make_template(*, declared_params: dict[str, str]) -> Any:
    """Return a stub query_template row with the given declared_params."""
    template = AsyncMock()
    template.id = _uuid()
    template.name = "test_template_v1"
    template.declared_params = declared_params
    return template


def _make_cluster() -> Any:
    cluster = AsyncMock()
    cluster.id = _uuid()
    return cluster


def _make_study(*, template_id: str, best_trial_id: str | None = None) -> Any:
    study = AsyncMock()
    study.id = _uuid()
    study.template_id = template_id
    study.best_trial_id = best_trial_id
    return study


def _make_trial(*, params: dict[str, Any]) -> Any:
    trial = AsyncMock()
    trial.id = _uuid()
    trial.params = params
    return trial


_REPO_PATH = "backend.app.agent.tools.studies.propose_search_space.repo"


def _patch_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    template: Any = None,
    cluster: Any = None,
    judgment_list: Any = None,
    study: Any = None,
    trial: Any = None,
) -> None:
    """Patch the repo calls inside the tool module with AsyncMock returns."""
    monkeypatch.setattr(f"{_REPO_PATH}.get_query_template", AsyncMock(return_value=template))
    monkeypatch.setattr(f"{_REPO_PATH}.get_cluster", AsyncMock(return_value=cluster))
    monkeypatch.setattr(f"{_REPO_PATH}.get_judgment_list", AsyncMock(return_value=judgment_list))
    monkeypatch.setattr(f"{_REPO_PATH}.get_study", AsyncMock(return_value=study))
    monkeypatch.setattr(f"{_REPO_PATH}.get_trial", AsyncMock(return_value=trial))


# ---------------------------------------------------------------------------
# Registry sanity (AC-11)
# ---------------------------------------------------------------------------


class TestRegistrySanity:
    def test_tool_count_advanced_to_20(self) -> None:
        assert len(TOOLS) == 20
        assert len(TOOL_REGISTRY) == 20
        assert len(TOOL_ARG_MODELS) == 20

    def test_propose_search_space_registered_under_canonical_name(self) -> None:
        assert "propose_search_space" in TOOL_REGISTRY
        assert TOOL_REGISTRY["propose_search_space"] is propose_search_space_impl
        assert TOOL_ARG_MODELS["propose_search_space"] is ProposeSearchSpaceArgs

    def test_tool_definition_well_formed(self) -> None:
        assert PROPOSE_SEARCH_SPACE_TOOL["function"]["name"] == "propose_search_space"
        schema = cast(dict[str, Any], PROPOSE_SEARCH_SPACE_TOOL["function"]["parameters"])
        assert "properties" in schema
        props = cast(dict[str, Any], schema["properties"])
        assert "template_id" in props
        assert "cluster_id" in props
        assert "judgment_list_id" in props
        assert "prior_study_id" in props

    def test_not_in_mutating_set(self) -> None:
        """propose_search_space is read-only and must NOT require confirmation."""
        assert "propose_search_space" not in MUTATING_TOOL_NAMES


# ---------------------------------------------------------------------------
# Error codes (AC-6, AC-12, AC-13)
# ---------------------------------------------------------------------------


class TestErrorCodes:
    async def test_template_not_found(self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_repo(monkeypatch, template=None)
        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        with pytest.raises(HTTPException) as exc:
            await propose_search_space_impl(args, fake_ctx)
        assert exc.value.status_code == 404
        assert _detail(exc.value)["error_code"] == "TEMPLATE_NOT_FOUND"
        assert _detail(exc.value)["retryable"] is False

    async def test_cluster_not_found(self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        template = _make_template(declared_params={"boost_title": "float"})
        _patch_repo(monkeypatch, template=template, cluster=None)
        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        with pytest.raises(HTTPException) as exc:
            await propose_search_space_impl(args, fake_ctx)
        assert exc.value.status_code == 404
        assert _detail(exc.value)["error_code"] == "CLUSTER_NOT_FOUND"

    async def test_judgment_list_not_found(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_repo(
            monkeypatch,
            template=_make_template(declared_params={"boost_title": "float"}),
            cluster=_make_cluster(),
            judgment_list=None,
        )
        args = ProposeSearchSpaceArgs(
            template_id=uuid4(), cluster_id=uuid4(), judgment_list_id=uuid4()
        )
        with pytest.raises(HTTPException) as exc:
            await propose_search_space_impl(args, fake_ctx)
        assert exc.value.status_code == 404
        assert _detail(exc.value)["error_code"] == "JUDGMENT_LIST_NOT_FOUND"

    async def test_prior_study_not_found(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_repo(
            monkeypatch,
            template=_make_template(declared_params={"boost_title": "float"}),
            cluster=_make_cluster(),
            study=None,
        )
        args = ProposeSearchSpaceArgs(
            template_id=uuid4(), cluster_id=uuid4(), prior_study_id=uuid4()
        )
        with pytest.raises(HTTPException) as exc:
            await propose_search_space_impl(args, fake_ctx)
        assert exc.value.status_code == 404
        assert _detail(exc.value)["error_code"] == "STUDY_NOT_FOUND"

    async def test_invalid_search_space_empty_declared_params(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-12 — empty declared_params surfaces as INVALID_SEARCH_SPACE 400."""
        _patch_repo(
            monkeypatch,
            template=_make_template(declared_params={}),
            cluster=_make_cluster(),
        )
        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        with pytest.raises(HTTPException) as exc:
            await propose_search_space_impl(args, fake_ctx)
        assert exc.value.status_code == 400
        assert _detail(exc.value)["error_code"] == "INVALID_SEARCH_SPACE"
        assert "empty declared_params" in _detail(exc.value)["message"]

    async def test_invalid_search_space_cap_aware_overflow(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-13 — 8 fall-through floats → cap-aware exhausted → INVALID_SEARCH_SPACE 400."""
        eight_floats = {chr(ord("a") + i): "float" for i in range(8)}
        _patch_repo(
            monkeypatch,
            template=_make_template(declared_params=eight_floats),
            cluster=_make_cluster(),
        )
        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        with pytest.raises(HTTPException) as exc:
            await propose_search_space_impl(args, fake_ctx)
        assert exc.value.status_code == 400
        assert _detail(exc.value)["error_code"] == "INVALID_SEARCH_SPACE"
        assert "cap-aware fallback exhausted" in _detail(exc.value)["message"]


# ---------------------------------------------------------------------------
# Happy paths (AC-1, AC-5, AC-7)
# ---------------------------------------------------------------------------


class TestHappyPaths:
    async def test_heuristic_only_no_prior_study(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-1 — three declared_params produce the spec-expected starter space."""
        template = _make_template(
            declared_params={
                "title_boost": "float",
                "min_should_match": "int",
                "fuzziness": "string",
            }
        )
        cluster = _make_cluster()
        _patch_repo(monkeypatch, template=template, cluster=cluster)

        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        result = await propose_search_space_impl(args, fake_ctx)

        params = result["search_space"]["params"]
        assert params["title_boost"] == {
            "type": "float",
            "low": 0.5,
            "high": 10.0,
            "log": True,
        }
        assert params["min_should_match"] == {"type": "int", "low": 0, "high": 5}
        assert params["fuzziness"] == {
            "type": "categorical",
            "choices": ["AUTO", "0", "1", "2"],
        }
        # Grounding shape (AC-7)
        grounding = result["grounding"]
        assert grounding["template_name"] == template.name
        assert grounding["used_prior_study_id"] is None
        assert grounding["narrowed_param_names"] == []
        assert grounding["cap_aware_fallback_param_names"] == []
        assert grounding["prior_study_template_mismatch"] is False

    async def test_returned_search_space_is_create_study_compatible(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-7 — result.search_space passes SearchSpace.model_validate."""
        _patch_repo(
            monkeypatch,
            template=_make_template(declared_params={"boost_title": "float"}),
            cluster=_make_cluster(),
        )
        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        result = await propose_search_space_impl(args, fake_ctx)
        SearchSpace.model_validate(result["search_space"])  # raises on failure

    async def test_prior_study_with_no_best_trial_degrades(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5 — prior_study_id resolves but best_trial_id is None → heuristic-only."""
        template_id = uuid4()
        template = _make_template(declared_params={"tie_breaker": "float"})
        prior = _make_study(template_id=str(template_id), best_trial_id=None)
        _patch_repo(monkeypatch, template=template, cluster=_make_cluster(), study=prior)

        args = ProposeSearchSpaceArgs(
            template_id=template_id, cluster_id=uuid4(), prior_study_id=uuid4()
        )
        result = await propose_search_space_impl(args, fake_ctx)
        assert result["grounding"]["used_prior_study_id"] == str(prior.id)
        assert result["grounding"]["narrowed_param_names"] == []
        # Heuristic-only starter — bounds unchanged.
        assert result["search_space"]["params"]["tie_breaker"]["low"] == 0.0
        assert result["search_space"]["params"]["tie_breaker"]["high"] == 1.0


# ---------------------------------------------------------------------------
# Prior-study narrowing (AC-2, AC-3, AC-4)
# ---------------------------------------------------------------------------


class TestPriorStudyNarrowing:
    async def test_linear_float_narrowed(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2 — tie_breaker [0, 1] + winner 0.4 → [0.2, 0.6]."""
        template_id = uuid4()
        template = _make_template(declared_params={"tie_breaker": "float"})
        prior = _make_study(template_id=str(template_id), best_trial_id=_uuid())
        trial = _make_trial(params={"tie_breaker": 0.4})
        _patch_repo(
            monkeypatch,
            template=template,
            cluster=_make_cluster(),
            study=prior,
            trial=trial,
        )

        args = ProposeSearchSpaceArgs(
            template_id=template_id, cluster_id=uuid4(), prior_study_id=uuid4()
        )
        result = await propose_search_space_impl(args, fake_ctx)
        assert result["grounding"]["narrowed_param_names"] == ["tie_breaker"]
        params = result["search_space"]["params"]
        assert params["tie_breaker"]["low"] == pytest.approx(0.2)
        assert params["tie_breaker"]["high"] == pytest.approx(0.6)

    async def test_winner_out_of_bounds_skipped(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4 — winner outside the starter bounds → skip + not in narrowed list."""
        template_id = uuid4()
        template = _make_template(declared_params={"min_should_match": "int"})
        prior = _make_study(template_id=str(template_id), best_trial_id=_uuid())
        trial = _make_trial(params={"min_should_match": 8})  # outside [0, 5]
        _patch_repo(
            monkeypatch,
            template=template,
            cluster=_make_cluster(),
            study=prior,
            trial=trial,
        )

        args = ProposeSearchSpaceArgs(
            template_id=template_id, cluster_id=uuid4(), prior_study_id=uuid4()
        )
        result = await propose_search_space_impl(args, fake_ctx)
        assert result["grounding"]["narrowed_param_names"] == []
        params = result["search_space"]["params"]
        assert params["min_should_match"]["low"] == 0
        assert params["min_should_match"]["high"] == 5


# ---------------------------------------------------------------------------
# Graceful degrade — template mismatch + missing trial (AC-14, AC-15)
# ---------------------------------------------------------------------------


class TestGracefulDegrade:
    async def test_prior_template_mismatch_degrades_with_warn(
        self,
        fake_ctx: Any,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC-14 — different template → no narrowing, grounding flag, WARN log."""
        requested_template_id = uuid4()
        template = _make_template(declared_params={"tie_breaker": "float"})
        template.id = str(requested_template_id)
        prior_template_id = uuid4()
        prior = _make_study(template_id=str(prior_template_id), best_trial_id=_uuid())
        _patch_repo(monkeypatch, template=template, cluster=_make_cluster(), study=prior)

        import logging

        caplog.set_level(logging.WARNING)

        args = ProposeSearchSpaceArgs(
            template_id=requested_template_id,
            cluster_id=uuid4(),
            prior_study_id=uuid4(),
        )
        result = await propose_search_space_impl(args, fake_ctx)
        assert result["grounding"]["prior_study_template_mismatch"] is True
        assert result["grounding"]["used_prior_study_id"] == str(prior.id)
        assert result["grounding"]["narrowed_param_names"] == []
        assert any("prior_template_mismatch" in r.message for r in caplog.records), (
            "WARN log must fire when template mismatches"
        )

    async def test_missing_trial_row_degrades_with_warn(
        self,
        fake_ctx: Any,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC-15 — best_trial_id set but trial row gone → degrade + WARN."""
        template_id = uuid4()
        template = _make_template(declared_params={"tie_breaker": "float"})
        prior = _make_study(template_id=str(template_id), best_trial_id=_uuid())
        _patch_repo(
            monkeypatch,
            template=template,
            cluster=_make_cluster(),
            study=prior,
            trial=None,  # cascade-delete race
        )

        import logging

        caplog.set_level(logging.WARNING)

        args = ProposeSearchSpaceArgs(
            template_id=template_id, cluster_id=uuid4(), prior_study_id=uuid4()
        )
        result = await propose_search_space_impl(args, fake_ctx)
        assert result["grounding"]["narrowed_param_names"] == []
        assert result["grounding"]["used_prior_study_id"] == str(prior.id)
        assert any("missing_winner_trial" in r.message for r in caplog.records), (
            "WARN log must fire when trial row is missing"
        )


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly:
    async def test_db_commit_never_called(
        self, fake_ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """propose_search_space MUST NOT commit (read-only)."""
        _patch_repo(
            monkeypatch,
            template=_make_template(declared_params={"boost_title": "float"}),
            cluster=_make_cluster(),
        )
        commit_mock = AsyncMock()
        monkeypatch.setattr(fake_ctx.db, "commit", commit_mock)

        args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
        await propose_search_space_impl(args, fake_ctx)
        assert commit_mock.call_count == 0
