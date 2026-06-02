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
from typing import Any

import pytest

import backend.app.services.demo_seeding as demo_seeding
from backend.app.services.demo_seeding import (
    DEMO_RESEED_LOCK_KEY,
    DemoSeedingError,
    ReseedSummary,
    _resolve_engine_base_url,
    _seed_solr_scenario,
)
from scripts.seed_meaningful_demos import SCENARIOS, TRUNCATE_TABLES

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


# ---------------------------------------------------------------------------
# Solr scenario seeding branch (infra_adapter_solr Story A13 completion)
# ---------------------------------------------------------------------------


def _solr_scenario() -> dict[str, Any]:
    """Return the single MVP2 Solr scenario from the CLI's SCENARIOS list."""
    solr = [s for s in SCENARIOS if s.get("engine_type") == "solr"]
    assert len(solr) == 1, "expected exactly one Solr demo scenario"
    return solr[0]


def test_solr_scenario_has_no_index_mapping_but_carries_solr_hints() -> None:
    """The Solr scenario must NOT carry an ``index_mapping`` (Solr builds
    collections from configsets) — the absence is precisely what made the ES
    PUT-index path ``KeyError``. It must instead carry the ``solr_configset``
    hint the reseed branches on."""
    scenario = _solr_scenario()
    assert "index_mapping" not in scenario
    assert scenario["solr_configset"] == "relyloop_products"
    assert scenario["target"] == "acme-kb-docs"


@pytest.mark.asyncio
async def test_seed_solr_scenario_routes_through_solr_helpers_not_index_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_seed_solr_scenario`` must create the collection from the configset
    and bulk-index the unwrapped docs via the reused sync helpers — never
    touching ``scenario["index_mapping"]``.

    We patch the imported sync seed functions and assert: (a) the collection
    is created with the scenario's ``target`` + ``configset``; (b) the docs
    are flattened from the reseed ``{"id", "doc"}`` wrapper into Solr's flat
    shape (id merged into the body)."""
    ensure_calls: list[tuple[str, str]] = []
    index_calls: list[tuple[str, list[dict[str, Any]]]] = []

    def fake_ensure_collection(client: Any, collection: str, configset: str) -> None:
        ensure_calls.append((collection, configset))

    def fake_bulk_index(client: Any, collection: str, docs: list[dict[str, Any]]) -> None:
        index_calls.append((collection, docs))

    monkeypatch.setattr(demo_seeding, "_solr_ensure_collection", fake_ensure_collection)
    monkeypatch.setattr(demo_seeding, "_solr_bulk_index", fake_bulk_index)

    scenario = _solr_scenario()
    await _seed_solr_scenario(
        engine_base="http://solr:8983",
        target=scenario["target"],
        configset=scenario["solr_configset"],
        scenario_docs=scenario["docs"],
        host_auth=("solr", "solr"),
        slug=scenario["slug"],
    )

    # Collection created once from the configset.
    assert ensure_calls == [("acme-kb-docs", "relyloop_products")]

    # Docs bulk-indexed once into the target collection.
    assert len(index_calls) == 1
    collection, flat_docs = index_calls[0]
    assert collection == "acme-kb-docs"
    assert len(flat_docs) == len(scenario["docs"])
    # Each doc is flattened: id merged into the body, no nested "doc" key.
    first = flat_docs[0]
    assert first["id"] == "kb101"
    assert "doc" not in first
    assert first["title"] == "Identity Provider Wiring Reference Document"


@pytest.mark.asyncio
async def test_seed_solr_scenario_wraps_httpx_error_in_demo_seeding_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport failure from the reused sync helpers surfaces as a
    :class:`DemoSeedingError` (the orchestrator's 503 path), tagged with the
    scenario slug."""
    import httpx

    def boom(client: Any, collection: str, configset: str) -> None:
        raise httpx.ConnectError("solr unreachable")

    monkeypatch.setattr(demo_seeding, "_solr_ensure_collection", boom)
    monkeypatch.setattr(demo_seeding, "_solr_bulk_index", lambda *a, **k: None)

    with pytest.raises(DemoSeedingError, match="acme-kb-docs-solr/solr_seed"):
        await _seed_solr_scenario(
            engine_base="http://solr:8983",
            target="acme-kb-docs",
            configset="relyloop_products",
            scenario_docs=[],
            host_auth=("solr", "solr"),
            slug="acme-kb-docs-solr",
        )
