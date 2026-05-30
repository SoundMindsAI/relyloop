# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``parse_repository_full_name`` (feat_github_webhook Story 1.2)."""

from __future__ import annotations

import pytest

from backend.app.domain.git import parse_repository_full_name


def test_canonical_owner_repo() -> None:
    assert parse_repository_full_name("octocat/hello-world") == ("octocat", "hello-world")


def test_owner_with_hyphens() -> None:
    assert parse_repository_full_name("foo-bar/baz") == ("foo-bar", "baz")


def test_repo_with_dots() -> None:
    """Repo names commonly contain dots (e.g. dotfiles, my.project)."""
    assert parse_repository_full_name("user/dotfiles.config") == ("user", "dotfiles.config")


def test_uppercase_is_lowercased() -> None:
    """GitHub URLs canonicalise to lowercase for comparison purposes."""
    assert parse_repository_full_name("OctoCat/Hello-World") == ("octocat", "hello-world")


def test_trailing_dot_git_is_stripped() -> None:
    """Some upstream sources send the ``.git`` suffix; strip it for parity."""
    assert parse_repository_full_name("octocat/hello-world.git") == ("octocat", "hello-world")


def test_whitespace_is_stripped() -> None:
    assert parse_repository_full_name("  octocat/hello  ") == ("octocat", "hello")


def test_https_url_returns_none() -> None:
    """HTTPS URLs are validate_repo_url's job — this parser only takes the short form."""
    assert parse_repository_full_name("https://github.com/octocat/hello") is None


def test_ssh_url_returns_none() -> None:
    """SSH URLs (``git@github.com:owner/repo.git``) return None — not supported in MVP1."""
    assert parse_repository_full_name("git@github.com:octocat/hello.git") is None


def test_enterprise_host_returns_none() -> None:
    """Domain-shaped owner (a dot in the owner segment) is rejected."""
    assert parse_repository_full_name("github.acme.com/octocat/hello") is None


def test_missing_slash_returns_none() -> None:
    assert parse_repository_full_name("octocat") is None


def test_three_segments_returns_none() -> None:
    """``owner/repo/extra`` is not the canonical short form."""
    assert parse_repository_full_name("owner/repo/extra") is None


def test_empty_returns_none() -> None:
    assert parse_repository_full_name("") is None


def test_just_slash_returns_none() -> None:
    assert parse_repository_full_name("/") is None


def test_leading_slash_owner_returns_none() -> None:
    assert parse_repository_full_name("/owner/repo") is None


def test_trailing_slash_with_empty_repo_returns_none() -> None:
    assert parse_repository_full_name("owner/") is None


@pytest.mark.parametrize(
    "value",
    [
        "owner-/repo",  # trailing hyphen on owner — _FULL_NAME_PATTERN forbids it
        "-owner/repo",  # leading hyphen on owner — forbidden
    ],
)
def test_invalid_owner_handles_return_none(value: str) -> None:
    assert parse_repository_full_name(value) is None
