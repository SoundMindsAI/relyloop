"""Git repo URL + config-path validators (feat_github_pr_worker Story 1.4).

Two validators called from the config-repos API surface and the open_pr
worker boot path:

- ``validate_repo_url(url)`` enforces the MVP1 GitHub-only constraint
  (GitLab + Bitbucket arrive in MVP3 per the canonical release matrix)
  and returns the parsed ``(owner, repo)`` tuple the worker uses to
  construct the GitHub API URLs.
- ``validate_config_path(path)`` rejects path-traversal attempts
  (``..``) and shell metacharacters in ``clusters.config_path`` (spec
  §10 mitigation 2 — path-traversal is the only operator-supplied path
  the worker concatenates into the local clone's filesystem).

Both raise specific subclasses of :class:`ValueError` so the API layer
can map them to the right error code without a stringly-typed parse.
"""

from __future__ import annotations

import re

_GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+?)(?:\.git)?$"
)
_CONFIG_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_./-]+$")


class UnsupportedProviderError(ValueError):
    """Raised when ``repo_url`` doesn't match the GitHub host pattern."""


class InvalidConfigPathError(ValueError):
    """Raised when ``clusters.config_path`` fails the traversal guard."""


def validate_repo_url(url: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` parsed from a GitHub HTTPS URL.

    Raises:
        UnsupportedProviderError: ``url`` isn't an https://github.com URL
            in the canonical ``owner/repo`` shape. GitLab + Bitbucket
            arrive at MVP3.
    """
    match = _GITHUB_URL_PATTERN.match(url)
    if not match:
        raise UnsupportedProviderError(
            f"repo_url {url!r} is not a GitHub URL; GitLab + Bitbucket arrive at MVP3"
        )
    return match.group(1), match.group(2)


def validate_config_path(path: str) -> None:
    """Reject path-traversal and shell metacharacters in operator-supplied paths.

    Raises:
        InvalidConfigPathError: ``path`` is empty, contains characters
            outside ``[A-Za-z0-9_./-]``, or contains a ``..`` segment.
    """
    if not path or not _CONFIG_PATH_PATTERN.match(path):
        raise InvalidConfigPathError(
            f"config_path {path!r} contains disallowed characters; "
            "allowed: alphanumerics, underscore, dot, slash, hyphen"
        )
    if ".." in path.split("/"):
        raise InvalidConfigPathError(f"config_path {path!r} contains '..' traversal segment")
