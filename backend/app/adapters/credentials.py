"""Cluster credential resolution (infra_adapter_elastic Story 2.1).

Reads the YAML body resolved by ``Settings.cluster_credentials_yaml``. The
mounted file is a top-level mapping ``{ref: {…}}`` where ``ref`` matches a
cluster row's ``credentials_ref`` column.

Failures raise ``CredentialsMissing`` so callers can translate to the
documented spec §7.5 error code (the registration service surfaces it as
``CLUSTER_UNREACHABLE`` per the F8 fix in cycle 1 of plan §11).
"""

from __future__ import annotations

from typing import Any, cast

import yaml

from backend.app.core.settings import get_settings


class CredentialsMissing(LookupError):
    """No credentials YAML mounted, or the requested ref is absent from the mounted YAML."""


def resolve_credentials(auth_kind: str, credentials_ref: str) -> dict[str, Any]:
    """Resolve a ``credentials_ref`` to its credential dict.

    Args:
        auth_kind: One of ``es_apikey | es_basic | opensearch_basic | opensearch_sigv4``.
            Used by callers to validate the returned dict's shape. This function
            does not check it — the dict shape is validated where it's consumed
            (``ElasticAdapter._build_auth_headers``).
        credentials_ref: The key into the mounted YAML mapping.

    Returns:
        The credential dict for the given ``credentials_ref``.

    Raises:
        CredentialsMissing: when the mounted YAML is absent or the ref is missing.
    """
    body = get_settings().cluster_credentials_yaml
    if body is None:
        raise CredentialsMissing(
            f"cluster_credentials_yaml is not mounted; "
            f"{credentials_ref!r} cannot be resolved (auth_kind={auth_kind!r})"
        )
    parsed = yaml.safe_load(body) or {}
    if not isinstance(parsed, dict):
        raise CredentialsMissing(
            f"cluster_credentials_yaml is not a top-level mapping; got {type(parsed).__name__}"
        )
    if credentials_ref not in parsed:
        raise CredentialsMissing(
            f"credentials_ref {credentials_ref!r} not found in mounted YAML "
            f"(auth_kind={auth_kind!r})"
        )
    entry = parsed[credentials_ref]
    # Per GPT-5.5 final-review F4: validate the inner entry shape so a
    # malformed YAML entry surfaces as CredentialsMissing (translated to
    # 503 CLUSTER_UNREACHABLE upstream) rather than a downstream KeyError /
    # TypeError leaking as an opaque 500. Error messages name the missing
    # key but never echo the secret value (CLAUDE.md Rule #10).
    if not isinstance(entry, dict):
        raise CredentialsMissing(
            f"credentials_ref {credentials_ref!r} is not a mapping; got {type(entry).__name__}"
        )
    required: tuple[str, ...]
    if auth_kind == "es_apikey":
        required = ("api_key",)
    elif auth_kind in ("es_basic", "opensearch_basic"):
        required = ("username", "password")
    else:
        # Unknown / reserved auth_kind — adapter constructor rejects before
        # this branch is reachable, but be defensive.
        required = ()
    missing = [k for k in required if k not in entry]
    if missing:
        raise CredentialsMissing(
            f"credentials_ref {credentials_ref!r} is missing required "
            f"fields for auth_kind={auth_kind!r}: {missing}"
        )
    return cast(dict[str, Any], entry)
