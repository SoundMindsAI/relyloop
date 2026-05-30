# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cross-validate ``validate_repo_url`` and ``parse_repository_full_name`` parity.

feat_github_webhook spec FR-1 normalisation rule: the webhook receiver
must compare ``(owner, repo)`` extracted from ``config_repos.repo_url`` (via
``validate_repo_url``) against ``(owner, repo)`` extracted from the
webhook payload's ``repository.full_name`` (via
``parse_repository_full_name``). Both must produce the same tuple when
the inputs describe the same repo. This file is the regression gate for
that parity, plus the SSH + enterprise-host negative cases the spec §14
test matrix calls out.
"""

from __future__ import annotations

import pytest

from backend.app.domain.git import (
    UnsupportedProviderError,
    parse_repository_full_name,
    validate_repo_url,
)


@pytest.mark.parametrize(
    ("url", "full_name", "expected"),
    [
        ("https://github.com/octocat/hello", "octocat/hello", ("octocat", "hello")),
        ("https://github.com/octocat/hello.git", "octocat/hello", ("octocat", "hello")),
        ("https://github.com/Foo-Bar/Baz", "foo-bar/baz", ("foo-bar", "baz")),
        (
            "https://github.com/user/dotfiles.config",
            "user/dotfiles.config",
            ("user", "dotfiles.config"),
        ),
    ],
)
def test_parity_canonical_inputs(url: str, full_name: str, expected: tuple[str, str]) -> None:
    """The two parsers produce comparable ``(owner, repo)`` tuples (case-insensitive)."""
    url_owner, url_repo = validate_repo_url(url)
    full_owner_repo = parse_repository_full_name(full_name)
    assert full_owner_repo is not None
    # validate_repo_url preserves the input case; the canonical-comparison
    # rule is "lowercase both sides before comparing".
    assert (url_owner.lower(), url_repo.lower()) == expected
    assert full_owner_repo == expected


def test_ssh_url_rejected_by_both_parsers() -> None:
    """SSH form is not supported in MVP1 — both parsers must refuse it."""
    ssh = "git@github.com:octocat/hello.git"
    with pytest.raises(UnsupportedProviderError):
        validate_repo_url(ssh)
    assert parse_repository_full_name(ssh) is None


def test_enterprise_host_rejected_by_validate_repo_url() -> None:
    """``validate_repo_url`` accepts only ``https://github.com``; enterprise hosts raise."""
    with pytest.raises(UnsupportedProviderError):
        validate_repo_url("https://github.acme.com/octocat/hello")


def test_enterprise_short_form_rejected_by_parse_full_name() -> None:
    """A domain-shaped owner segment is rejected by the short-form parser."""
    assert parse_repository_full_name("github.acme.com/octocat/hello") is None
