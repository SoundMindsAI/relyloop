# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Telemetry tests for ``agent.search_space_proposed`` (Story 3.3 / spec FR-6).

The propose-side tool emits one INFO event per successful invocation tagged
with ``ctx.conversation_id``. Tests assert:

- Happy-path emits the event with the expected ``conversation_id`` + field shape.
- Prior-study narrowing emits with non-empty ``narrowed_param_names``.
- Template-mismatch path still emits the INFO event (with empty narrowed list)
  PLUS the separate WARN ``agent.propose_search_space.prior_template_mismatch``.
- Logger failure is swallowed (telemetry never blocks dispatch).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.app.agent.tools.studies.propose_search_space import (
    ProposeSearchSpaceArgs,
    propose_search_space_impl,
)


def _uuid() -> str:
    return str(uuid4())


def _make_template(*, declared_params: dict[str, str]) -> Any:
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
    monkeypatch.setattr(f"{_REPO_PATH}.get_query_template", AsyncMock(return_value=template))
    monkeypatch.setattr(f"{_REPO_PATH}.get_cluster", AsyncMock(return_value=cluster))
    monkeypatch.setattr(f"{_REPO_PATH}.get_judgment_list", AsyncMock(return_value=judgment_list))
    monkeypatch.setattr(f"{_REPO_PATH}.get_study", AsyncMock(return_value=study))
    monkeypatch.setattr(f"{_REPO_PATH}.get_trial", AsyncMock(return_value=trial))


async def test_emits_info_event_on_happy_path(
    fake_ctx: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Heuristic-only success → INFO ``agent.search_space_proposed`` with ctx.conversation_id."""
    _patch_repo(
        monkeypatch,
        template=_make_template(declared_params={"title_boost": "float"}),
        cluster=_make_cluster(),
    )
    caplog.set_level(logging.INFO, logger="backend.app.agent.tools.studies.propose_search_space")
    args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
    await propose_search_space_impl(args, fake_ctx)

    matches = [r for r in caplog.records if "agent.search_space_proposed" in r.message]
    assert len(matches) == 1
    record = matches[0]
    assert record.levelno == logging.INFO
    assert f"conversation_id={fake_ctx.conversation_id}" in record.message
    assert "narrowed_param_names=[]" in record.message


async def test_emits_event_with_narrowed_names_on_prior_study(
    fake_ctx: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Prior-study narrowing → INFO event lists the narrowed param names."""
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
    caplog.set_level(logging.INFO, logger="backend.app.agent.tools.studies.propose_search_space")
    args = ProposeSearchSpaceArgs(
        template_id=template_id, cluster_id=uuid4(), prior_study_id=uuid4()
    )
    await propose_search_space_impl(args, fake_ctx)

    matches = [r for r in caplog.records if "agent.search_space_proposed" in r.message]
    assert len(matches) == 1
    assert "narrowed_param_names=['tie_breaker']" in matches[0].message


async def test_template_mismatch_emits_both_info_and_warn(
    fake_ctx: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Template mismatch fires the WARN AND still emits the INFO event."""
    requested_id = uuid4()
    template = _make_template(declared_params={"tie_breaker": "float"})
    template.id = str(requested_id)
    prior = _make_study(template_id=str(uuid4()), best_trial_id=_uuid())
    _patch_repo(monkeypatch, template=template, cluster=_make_cluster(), study=prior)
    caplog.set_level(logging.INFO, logger="backend.app.agent.tools.studies.propose_search_space")

    args = ProposeSearchSpaceArgs(
        template_id=requested_id, cluster_id=uuid4(), prior_study_id=uuid4()
    )
    await propose_search_space_impl(args, fake_ctx)

    warn_msgs = [r for r in caplog.records if "prior_template_mismatch" in r.message]
    info_msgs = [r for r in caplog.records if "agent.search_space_proposed" in r.message]
    assert len(warn_msgs) == 1 and warn_msgs[0].levelno == logging.WARNING
    assert len(info_msgs) == 1 and info_msgs[0].levelno == logging.INFO


async def test_logger_failure_is_swallowed(fake_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the logger raises, the impl still returns its result (telemetry never blocks)."""
    _patch_repo(
        monkeypatch,
        template=_make_template(declared_params={"title_boost": "float"}),
        cluster=_make_cluster(),
    )

    import backend.app.agent.tools.studies.propose_search_space as tool_mod

    monkeypatch.setattr(
        tool_mod.logger,
        "info",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("structlog blew up")),
    )
    args = ProposeSearchSpaceArgs(template_id=uuid4(), cluster_id=uuid4())
    result = await propose_search_space_impl(args, fake_ctx)
    assert "search_space" in result and "grounding" in result
