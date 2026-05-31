# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.services.demo_seeding``.

Story 1.1 (feat_home_demo_reseed_endpoint). Pure-function coverage only —
no DB, no HTTP. The orchestrator's full behavior is exercised by the
Story 3.2 integration tests against a real Postgres + ES + OS.

Test cases:

* :func:`_resolve_engine_base_url` — happy ES, happy OS, ValueError on
  unrecognized URL.
* :data:`DEMO_RESEED_LOCK_KEY` — deterministic blake2b → signed-int64
  derivation (regression guard against accidentally changing the key).
* :class:`ReseedSummary` — construction + ``model_dump()`` shape.
* :data:`TRUNCATE_TABLES` — mirror of spec §9's 10-tuple (guards
  against a silent CLI refactor that would diverge spec from runtime).
"""

from __future__ import annotations

import hashlib

import pytest

from backend.app.services.demo_seeding import (
    DEMO_RESEED_LOCK_KEY,
    ReseedSummary,
    _resolve_engine_base_url,
)
from scripts.seed_meaningful_demos import TRUNCATE_TABLES

# ---------------------------------------------------------------------------
# _resolve_engine_base_url
# ---------------------------------------------------------------------------


def test_resolve_engine_base_url_es() -> None:
    assert _resolve_engine_base_url("http://localhost:9200") == "http://elasticsearch:9200"


def test_resolve_engine_base_url_os() -> None:
    # Note: the host-side ``:9201`` is the OS port-mapping (avoiding collision
    # with ES); inside the Compose network OS still listens on the default 9200.
    assert _resolve_engine_base_url("http://localhost:9201") == "http://opensearch:9200"


def test_resolve_engine_base_url_solr() -> None:
    # Regression: the MVP2 ``acme-kb-docs-solr`` demo scenario carries
    # ``host_base_url = http://localhost:8983``; without the mapping entry the
    # reseed raised ``Unrecognized engine host URL`` on the Solr scenario.
    # Solr's host and container ports match (8983:8983) — no remap.
    assert _resolve_engine_base_url("http://localhost:8983") == "http://solr:8983"


def test_resolve_engine_base_url_unknown_raises() -> None:
    """An unrecognized URL must raise ``ValueError`` — the orchestrator
    unwraps this to a :class:`DemoSeedingError` for the 503 path."""
    with pytest.raises(ValueError, match="Unrecognized engine host URL"):
        _resolve_engine_base_url("http://example.com:9200")


# ---------------------------------------------------------------------------
# DEMO_RESEED_LOCK_KEY — deterministic derivation
# ---------------------------------------------------------------------------


def test_demo_reseed_lock_key_is_deterministic_blake2b_signed_int64() -> None:
    """Regression guard: the key derivation is committed here so a future
    refactor doesn't silently change the lock identity (which would break
    in-flight reseeds across an upgrade)."""
    expected = int.from_bytes(
        hashlib.blake2b(b"demo:reseed", digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    assert DEMO_RESEED_LOCK_KEY == expected


def test_demo_reseed_lock_key_is_within_signed_int64_range() -> None:
    """Postgres ``pg_try_advisory_lock(bigint)`` accepts the full signed
    int64 range — assert the derived key fits so the SQL call cannot
    overflow at runtime."""
    assert -(2**63) <= DEMO_RESEED_LOCK_KEY < 2**63


# ---------------------------------------------------------------------------
# ReseedSummary
# ---------------------------------------------------------------------------


def test_reseed_summary_construction_and_dump() -> None:
    summary = ReseedSummary(
        clusters_created=4,
        query_sets_created=4,
        studies_completed=4,
        proposals_created=4,
        duration_ms=7_000,
    )
    dumped = summary.model_dump()
    assert dumped == {
        "clusters_created": 4,
        "query_sets_created": 4,
        "studies_completed": 4,
        "proposals_created": 4,
        "duration_ms": 7_000,
    }


def test_reseed_summary_rejects_unknown_field() -> None:
    """``extra='forbid'`` — guards against accidentally smuggling extra
    keys into the API response body."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReseedSummary(
            clusters_created=4,
            query_sets_created=4,
            studies_completed=4,
            proposals_created=4,
            duration_ms=7_000,
            unexpected_field="x",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# TRUNCATE_TABLES — mirror of spec §9 closed set
# ---------------------------------------------------------------------------


def test_truncate_tables_matches_spec_section_9() -> None:
    """Spec §9 lists exactly these 10 tables in this order. If the CLI
    refactors the constant, this test fails loudly so the spec + the
    reseed service can be updated together."""
    assert TRUNCATE_TABLES == (
        "proposals",
        "digests",
        "trials",
        "studies",
        "judgments",
        "judgment_lists",
        "queries",
        "query_sets",
        "query_templates",
        "clusters",
    )
