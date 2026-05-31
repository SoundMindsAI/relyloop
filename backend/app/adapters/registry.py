# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Engine + auth allowlists — the single service-layer source of truth.

Relocated here from ``backend/app/adapters/elastic.py`` by
``infra_adapter_solr`` Story A6 (spec FR-3). Keeping these global allowlists
in an ES-specific module forced non-Elastic code (the SolrAdapter, the cluster
service) to import ``ElasticAdapter`` internals. They are engine-neutral, so
they live in a neutral module.

``elastic.py`` re-exports these names for one release as a transitional shim
(bare re-export, no ``DeprecationWarning`` — module-level import-time warnings
are noisy across the test suite). New code imports from here.

**Scope boundary.** These are the SERVICE-LAYER allowlists used at cluster
registration time. They are distinct from the WIRE Literals in
``backend/app/api/v1/schemas.py`` (``EngineTypeWire`` / ``AuthKind``) that the
frontend ``ui/src/lib/enums.ts`` mirrors. The frontend ``cluster-auth.ts``
``ALLOWED_AUTH_PER_ENGINE`` map mirrors :data:`ALLOWED_AUTH_PER_ENGINE` here;
the two are drift-guarded by ``ui/src/__tests__/lib/cluster-auth.test.ts``.
"""

from __future__ import annotations

SUPPORTED_ENGINE_TYPES: frozenset[str] = frozenset({"elasticsearch", "opensearch", "solr"})
"""Wire-value source of truth for cluster registration. Mirrors the
``clusters_engine_type_check`` CHECK constraint (migration 0002 + 0022)."""

SUPPORTED_ENVIRONMENTS: frozenset[str] = frozenset({"prod", "staging", "dev"})
"""Mirrors ``clusters_environment_check``."""

SUPPORTED_AUTH_KINDS: frozenset[str] = frozenset(
    {"es_apikey", "es_basic", "opensearch_basic", "solr_basic", "solr_apikey"}
)
"""``auth_kind`` values implemented and usable today. ``solr_basic`` /
``solr_apikey`` added by ``infra_adapter_solr`` (Story A3/A6)."""

RESERVED_AUTH_KINDS: frozenset[str] = frozenset({"opensearch_sigv4"})
"""Wire values that pass the DB CHECK constraint but are not implemented.

The cluster service raises ``AuthKindNotSupported`` for these so the operator
gets a 400 with a clear message rather than a 500 from the adapter. The DB
CHECK allowlist is the UNION ``SUPPORTED_AUTH_KINDS | RESERVED_AUTH_KINDS``."""

ALLOWED_AUTH_PER_ENGINE: dict[str, frozenset[str]] = {
    "elasticsearch": frozenset({"es_apikey", "es_basic"}),
    "opensearch": frozenset({"opensearch_basic"}),  # + opensearch_sigv4 at MVP3
    "solr": frozenset({"solr_basic", "solr_apikey"}),
}
"""Cross-product allowlist enforced at registration time.

The DB ``auth_kind`` CHECK constraint accepts any wire value for any engine,
but pairing ``engine_type=opensearch`` with ``auth_kind=es_apikey`` (or
``engine_type=solr`` with ``auth_kind=es_basic``) is operator misconfiguration:
the labels exist precisely to distinguish which auth method goes with which
engine. The service layer rejects mismatched pairings with 400
``AUTH_KIND_NOT_SUPPORTED`` so the error surfaces at request time rather than
at the first probe.

Reserved kinds (``opensearch_sigv4``) are NOT enumerated here — they're
rejected earlier in ``register_cluster`` via ``RESERVED_AUTH_KINDS`` regardless
of engine."""
