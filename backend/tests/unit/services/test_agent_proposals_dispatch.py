# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for agent_proposals_dispatch (feat_chat_agent Story 2.4)."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.app.services import agent_proposals_dispatch as dispatch


def _proposal(**overrides: Any) -> MagicMock:
    p = MagicMock()
    p.id = "prop_1"
    p.status = "pending"
    p.cluster_id = "clu_1"
    p.pr_open_error = None
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _cluster(**overrides: Any) -> MagicMock:
    c = MagicMock()
    c.id = "clu_1"
    c.config_repo_id = "cfg_1"
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _config_repo(auth_ref: str = "test_pat") -> MagicMock:
    cr = MagicMock()
    cr.auth_ref = auth_ref
    return cr


def _detail(exc: HTTPException) -> dict[str, Any]:
    return cast(dict[str, Any], exc.detail)


def _patch_proposal(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    monkeypatch.setattr(
        "backend.app.services.agent_proposals_dispatch.repo.get_proposal",
        AsyncMock(return_value=value),
    )


def _patch_cluster(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    monkeypatch.setattr(
        "backend.app.services.agent_proposals_dispatch.repo.get_cluster",
        AsyncMock(return_value=value),
    )


def _patch_config_repo(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    monkeypatch.setattr(
        "backend.app.services.agent_proposals_dispatch.repo.get_config_repo",
        AsyncMock(return_value=value),
    )


@pytest.mark.asyncio
async def test_proposal_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_proposal(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 404
    assert _detail(ei.value)["error_code"] == "PROPOSAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_invalid_state_transition_when_not_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_proposal(monkeypatch, _proposal(status="pr_merged"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 409
    assert _detail(ei.value)["error_code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.asyncio
async def test_cluster_has_no_config_repo_when_cluster_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 422
    assert _detail(ei.value)["error_code"] == "CLUSTER_HAS_NO_CONFIG_REPO"


@pytest.mark.asyncio
async def test_cluster_has_no_config_repo_when_config_repo_id_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, _cluster(config_repo_id=None))
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 422
    assert _detail(ei.value)["error_code"] == "CLUSTER_HAS_NO_CONFIG_REPO"


@pytest.mark.asyncio
async def test_cluster_has_no_config_repo_when_lookup_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, _cluster())
    _patch_config_repo(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 422
    assert _detail(ei.value)["error_code"] == "CLUSTER_HAS_NO_CONFIG_REPO"


@pytest.mark.asyncio
async def test_github_not_configured_when_pat_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, _cluster())
    _patch_config_repo(monkeypatch, _config_repo("absent_pat"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 503
    assert _detail(ei.value)["error_code"] == "GITHUB_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_queue_unavailable_when_arq_pool_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "test_pat").write_text("token-value")
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, _cluster())
    _patch_config_repo(monkeypatch, _config_repo("test_pat"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=None, proposal_id="prop_1")
    assert ei.value.status_code == 503
    assert _detail(ei.value)["error_code"] == "QUEUE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_happy_path_enqueues_with_static_job_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "test_pat").write_text("token-value")
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, _cluster())
    _patch_config_repo(monkeypatch, _config_repo("test_pat"))
    arq_pool = AsyncMock()
    arq_pool.enqueue_job = AsyncMock(return_value=MagicMock())
    result = await dispatch.open_pr(db=AsyncMock(), arq_pool=arq_pool, proposal_id="prop_1")
    assert result.proposal_id == "prop_1"
    assert result.status == "pending"
    arq_pool.enqueue_job.assert_called_once()
    _, kwargs = arq_pool.enqueue_job.call_args
    assert kwargs["_job_id"] == "open_pr:prop_1"


@pytest.mark.asyncio
async def test_retry_after_failure_salts_job_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "test_pat").write_text("token-value")
    _patch_proposal(monkeypatch, _proposal(pr_open_error="github rate limited"))
    _patch_cluster(monkeypatch, _cluster())
    _patch_config_repo(monkeypatch, _config_repo("test_pat"))
    arq_pool = AsyncMock()
    arq_pool.enqueue_job = AsyncMock(return_value=MagicMock())
    await dispatch.open_pr(db=AsyncMock(), arq_pool=arq_pool, proposal_id="prop_1")
    _, kwargs = arq_pool.enqueue_job.call_args
    assert kwargs["_job_id"].startswith("open_pr:prop_1:retry-")
    assert len(kwargs["_job_id"].split("retry-")[1]) == 8


@pytest.mark.asyncio
async def test_enqueue_raise_becomes_queue_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "test_pat").write_text("token-value")
    _patch_proposal(monkeypatch, _proposal())
    _patch_cluster(monkeypatch, _cluster())
    _patch_config_repo(monkeypatch, _config_repo("test_pat"))
    arq_pool = AsyncMock()
    arq_pool.enqueue_job = AsyncMock(side_effect=RuntimeError("connection refused"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.open_pr(db=AsyncMock(), arq_pool=arq_pool, proposal_id="prop_1")
    assert ei.value.status_code == 503
    assert _detail(ei.value)["error_code"] == "QUEUE_UNAVAILABLE"


def test_read_auth_secret_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))
    (tmp_path / "outside").write_text("outside-secret")
    assert dispatch.read_auth_secret("../outside") is None


def test_read_auth_secret_returns_content_for_valid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))
    (secrets_dir / "my_pat").write_text("ghp_abcdef\n")
    assert dispatch.read_auth_secret("my_pat") == "ghp_abcdef"


def test_read_auth_secret_returns_none_for_empty_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))
    (secrets_dir / "my_pat").write_text("  \n  ")
    assert dispatch.read_auth_secret("my_pat") is None


def test_read_auth_secret_empty_ref_is_none() -> None:
    assert dispatch.read_auth_secret("") is None


def test_read_auth_secret_is_not_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))
    (secrets_dir / "subdir").mkdir()
    assert dispatch.read_auth_secret("subdir") is None
