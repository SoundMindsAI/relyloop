"""GitHub ``repository.full_name`` parser (feat_github_webhook Story 1.2).

The GitHub webhook payload's ``repository.full_name`` field is the
canonical ``owner/repo`` short form (no scheme, no host, no ``.git``
suffix). The webhook receiver pairs this with
:func:`backend.app.domain.git.validation.validate_repo_url` on the
``config_repos.repo_url`` side and compares the two ``(owner, repo)``
tuples case-insensitively.

This helper is intentionally tight in scope: it only parses the bare
``owner/repo`` form. HTTPS URLs, SSH URLs, and enterprise-host URLs all
return ``None`` — those forms go through ``validate_repo_url``, not here.
Two parsers, one purpose each, no duplicate URL regex (per the spec FR-1
normalization rule and the implementation plan's cross-model review F1).
"""

from __future__ import annotations

import re

# Canonical GitHub-handle pattern. GitHub permits alphanumerics + hyphens
# in owner names (no leading/trailing hyphen, no consecutive hyphens at
# the GitHub layer — we accept the looser canonical-handle regex here and
# rely on actual GitHub to reject invalid handles). Repo names accept
# alphanumerics, dots, underscores, and hyphens. The optional ``.git``
# suffix is stripped before the match.
_FULL_NAME_PATTERN = re.compile(r"^([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/([a-z0-9._-]+)$")


def parse_repository_full_name(value: str) -> tuple[str, str] | None:
    """Parse GitHub's ``repository.full_name`` (``owner/repo``) form.

    Args:
        value: Expected canonical short form, e.g. ``"octocat/Hello-World"``.
            Whitespace and case are normalised. A trailing ``.git`` is
            stripped.

    Returns:
        ``(owner, repo)`` lowercased on success, or ``None`` for:
            * any input containing ``://`` (looks like a URL — use
              ``validate_repo_url`` instead),
            * any input containing ``:`` (SSH URL form),
            * any input with a dot in the owner component (would shadow a
              host name),
            * malformed input (missing slash, multiple slashes, empty
              parts, etc.).
    """
    if not value:
        return None
    candidate = value.strip().lower()
    if "://" in candidate or ":" in candidate:
        return None
    if candidate.endswith(".git"):
        candidate = candidate[: -len(".git")]
    match = _FULL_NAME_PATTERN.match(candidate)
    if match is None:
        return None
    owner, repo = match.group(1), match.group(2)
    if "." in owner:
        # Domain-shaped owner — refuse so future enterprise-host inputs
        # don't quietly succeed against this short-form parser.
        return None
    return owner, repo
