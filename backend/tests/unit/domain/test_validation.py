"""Unit tests for backend.app.domain.git.validation (Story 1.4)."""

from __future__ import annotations

import pytest

from backend.app.domain.git.validation import (
    InvalidConfigPathError,
    UnsupportedProviderError,
    validate_config_path,
    validate_repo_url,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/relyloop/configs", ("relyloop", "configs")),
        ("https://github.com/relyloop/configs.git", ("relyloop", "configs")),
        ("https://github.com/Org-Name/repo.with.dots", ("Org-Name", "repo.with.dots")),
        ("https://github.com/a/b", ("a", "b")),
    ],
)
def test_validate_repo_url_accepts_github(url: str, expected: tuple[str, str]) -> None:
    assert validate_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/foo/bar",
        "https://bitbucket.org/foo/bar",
        "git@github.com:foo/bar.git",  # SSH form rejected (PAT-over-HTTPS only)
        "http://github.com/foo/bar",  # http:// rejected (https-only)
        "https://github.com/foo",  # missing repo segment
        "https://github.com/",  # empty
        "not-a-url",
    ],
)
def test_validate_repo_url_rejects_non_github(url: str) -> None:
    with pytest.raises(UnsupportedProviderError):
        validate_repo_url(url)


@pytest.mark.parametrize(
    "path",
    [
        "configs/relevance.yml",
        "single.yaml",
        "deep/nested/path/to/file.json",
        "name_with_underscores.yml",
        "name-with-hyphens.yml",
    ],
)
def test_validate_config_path_accepts_safe_paths(path: str) -> None:
    validate_config_path(path)  # no exception


@pytest.mark.parametrize(
    "path",
    [
        "../escape.yml",
        "configs/../etc/passwd",
        "configs/../../secrets",
        "..",
    ],
)
def test_validate_config_path_rejects_traversal(path: str) -> None:
    with pytest.raises(InvalidConfigPathError):
        validate_config_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "",  # empty
        "configs/file with spaces.yml",
        "configs/$(whoami).yml",
        "configs/`id`.yml",
        "configs/file;rm.yml",
        "configs/file|cat.yml",
        "configs/file&bg.yml",
    ],
)
def test_validate_config_path_rejects_metacharacters(path: str) -> None:
    with pytest.raises(InvalidConfigPathError):
        validate_config_path(path)
