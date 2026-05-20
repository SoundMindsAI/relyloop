"""Adapter domain exceptions (infra_adapter_elastic Story 2.1+).

Single import path so the adapter, services, and routers translate engine
failures to spec §7.5 error codes consistently.

* ``ClusterUnreachableError`` — connection / auth / 5xx failure → 503
  ``CLUSTER_UNREACHABLE`` at the router (Story 2.1).
* ``TargetNotFoundError`` — index/collection 404 → 404 ``TARGET_NOT_FOUND``
  at the router (Story 2.3 extension).
* ``TargetsForbiddenError`` — cluster denied the listing call (401/403 from
  ``_cat/indices``) → 403 ``TARGETS_FORBIDDEN`` at the router
  (``feat_create_study_target_autocomplete`` Story B1). Distinct from
  ``ClusterUnreachableError`` so the frontend can route ACL-restricted
  clusters to manual-mode input rather than retrying.
* ``InvalidQueryDSLError`` — per-query parse failure when the caller passes
  ``strict_errors=True`` (run_query API path) → 400 ``INVALID_QUERY_DSL``
  at the router (Story 2.5 extension).
* ``QueryTimeoutError`` — read timeout while waiting on the engine → 504
  ``QUERY_TIMEOUT`` at the router (Story 2.5 extension).

The classes are named, not value-typed, so callers can ``raise`` and
``except`` against the precise failure mode rather than string-matching
the message.
"""

from __future__ import annotations


class ClusterUnreachableError(Exception):
    """Cluster connection / auth / 5xx failure. Maps to 503 CLUSTER_UNREACHABLE."""


class TargetNotFoundError(LookupError):
    """Target index/collection not found on the cluster. Maps to 404 TARGET_NOT_FOUND."""

    def __init__(self, target: str) -> None:
        """Capture the missing ``target`` name for downstream router translation."""
        super().__init__(target)
        self.target = target


class TargetsForbiddenError(Exception):
    """Cluster denied the listing call (401/403 from ``_cat/indices``).

    Maps to 403 TARGETS_FORBIDDEN, ``retryable=false`` at the router. The
    frontend auto-engages manual-mode target entry on this code; retrying
    will not help because the cluster's ACL is the cause.
    """


class InvalidQueryDSLError(Exception):
    """Engine rejected a query body as malformed (top-level 400 or per-query parse).

    Surfaces only when ``search_batch(strict_errors=True)`` (the run_query API
    path); the hot path (Optuna trial runner) silently records empty hits.
    """


class QueryTimeoutError(Exception):
    """Read timeout while waiting on the engine. Maps to 504 QUERY_TIMEOUT."""
