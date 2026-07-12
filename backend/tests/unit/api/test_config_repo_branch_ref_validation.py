# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Security audit 2026-07-11 finding #7 — git-ref-safe pattern on the config-repo
branch fields (``default_branch`` / ``pr_base_branch``). These flow as
positional git arguments in the open_pr worker; a value beginning with ``-``
could be parsed by git as an option (``--upload-pack=...`` argument injection).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.api.v1.schemas.proposals import CreateConfigRepoRequest


def _mk(**overrides: str) -> CreateConfigRepoRequest:
    base = dict(name="repo", repo_url="https://github.com/a/b", auth_ref="ref")
    base.update(overrides)
    return CreateConfigRepoRequest(**base)


@pytest.mark.parametrize("branch", ["main", "develop", "feature/new-thing", "release-1.2.3"])
def test_valid_branch_names_accepted(branch: str) -> None:
    repo = _mk(default_branch=branch, pr_base_branch=branch)
    assert repo.pr_base_branch == branch


@pytest.mark.parametrize(
    "branch",
    ["--upload-pack=/tmp/x", "-x", "..", "/etc/passwd", ".hidden", "a b", "a;rm -rf /"],
)
def test_unsafe_branch_names_rejected(branch: str) -> None:
    with pytest.raises(ValidationError):
        _mk(pr_base_branch=branch)
    with pytest.raises(ValidationError):
        _mk(default_branch=branch)
