# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared Postgres advisory-lock helper.

Verifies the lock-key derivation that three workers (orchestrator,
digest, git_pr) now share via ``acquire_advisory_xact_lock`` matches the
prior inlined ``blake2b -> signed int64`` computation, and that the
``prefix`` argument partitions the lock space as the callers rely on.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from backend.app.db.advisory_lock import acquire_advisory_xact_lock


def _expected_key(text_input: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(text_input.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )


class _FakeResult:
    def scalar_one(self) -> bool:
        return True


class _FakeSession:
    """Captures the bound parameters passed to ``execute``."""

    def __init__(self) -> None:
        self.captured_params: dict[str, Any] | None = None

    async def execute(self, _stmt: Any, params: dict[str, Any]) -> _FakeResult:
        self.captured_params = params
        return _FakeResult()


@pytest.mark.asyncio
async def test_lock_key_matches_legacy_orchestrator_derivation() -> None:
    """No prefix reproduces the orchestrator's bare-study_id key (cycle-2 F6)."""
    db = _FakeSession()
    async with acquire_advisory_xact_lock(db, key="study-123") as acquired:  # type: ignore[arg-type]
        assert acquired is True
    assert db.captured_params == {"k": _expected_key("study-123")}


@pytest.mark.asyncio
async def test_prefix_partitions_lock_space() -> None:
    """The digest / config-repo prefixes yield keys disjoint from the bare key."""
    bare = _FakeSession()
    digest = _FakeSession()
    config_repo = _FakeSession()

    async with acquire_advisory_xact_lock(bare, key="id-1"):  # type: ignore[arg-type]
        pass
    async with acquire_advisory_xact_lock(digest, key="id-1", prefix="digest:"):  # type: ignore[arg-type]
        pass
    async with acquire_advisory_xact_lock(config_repo, key="id-1", prefix="config-repo:"):  # type: ignore[arg-type]
        pass

    assert bare.captured_params is not None
    assert digest.captured_params is not None
    assert config_repo.captured_params is not None
    assert digest.captured_params == {"k": _expected_key("digest:id-1")}
    assert config_repo.captured_params == {"k": _expected_key("config-repo:id-1")}
    keys = {
        bare.captured_params["k"],
        digest.captured_params["k"],
        config_repo.captured_params["k"],
    }
    assert len(keys) == 3
