# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""infra_adapter_solr Story A6 — engine/auth allowlists relocated to registry.py.

Asserts:
1. ``registry.py`` is the canonical source and includes Solr values.
2. ``elastic.py`` re-exports resolve to the SAME object (transitional shim,
   no drift). No ``DeprecationWarning`` is asserted (bare re-export per
   plan cycle-2 C2-B4).
3. The cross-product ``ALLOWED_AUTH_PER_ENGINE`` admits Solr auth kinds and
   rejects mismatched pairings.
"""

from __future__ import annotations

from backend.app.adapters import elastic, registry


def test_registry_is_canonical_source_with_solr() -> None:
    assert registry.SUPPORTED_ENGINE_TYPES == frozenset({"elasticsearch", "opensearch", "solr"})
    assert "solr_basic" in registry.SUPPORTED_AUTH_KINDS
    assert "solr_apikey" in registry.SUPPORTED_AUTH_KINDS
    # opensearch_sigv4 stays reserved (DB CHECK accepts it; adapter rejects).
    assert registry.RESERVED_AUTH_KINDS == frozenset({"opensearch_sigv4"})


def test_db_check_allowlist_is_the_union() -> None:
    # The clusters_auth_kind_check CHECK contains SUPPORTED | RESERVED.
    db_check_values = registry.SUPPORTED_AUTH_KINDS | registry.RESERVED_AUTH_KINDS
    assert db_check_values == frozenset(
        {
            "es_apikey",
            "es_basic",
            "opensearch_basic",
            "opensearch_sigv4",
            "solr_basic",
            "solr_apikey",
        }
    )


def test_elastic_reexports_are_the_same_objects() -> None:
    # The transitional shim must not introduce a second copy that can drift.
    assert elastic.SUPPORTED_ENGINE_TYPES is registry.SUPPORTED_ENGINE_TYPES
    assert elastic.SUPPORTED_AUTH_KINDS is registry.SUPPORTED_AUTH_KINDS
    assert elastic.RESERVED_AUTH_KINDS is registry.RESERVED_AUTH_KINDS
    assert elastic.ALLOWED_AUTH_PER_ENGINE is registry.ALLOWED_AUTH_PER_ENGINE
    assert elastic.SUPPORTED_ENVIRONMENTS is registry.SUPPORTED_ENVIRONMENTS


def test_allowed_auth_per_engine_solr_pairing() -> None:
    assert registry.ALLOWED_AUTH_PER_ENGINE["solr"] == frozenset({"solr_basic", "solr_apikey"})
    # Cross-engine mismatch: solr does not accept es/opensearch auth kinds.
    assert "es_apikey" not in registry.ALLOWED_AUTH_PER_ENGINE["solr"]
    assert "opensearch_basic" not in registry.ALLOWED_AUTH_PER_ENGINE["solr"]
    # And the existing engines are unchanged (regression guard).
    assert registry.ALLOWED_AUTH_PER_ENGINE["elasticsearch"] == frozenset({"es_apikey", "es_basic"})
    assert registry.ALLOWED_AUTH_PER_ENGINE["opensearch"] == frozenset({"opensearch_basic"})
