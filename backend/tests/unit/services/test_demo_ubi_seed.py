# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for `backend.app.services.demo_ubi_seed` and the canonical
UBI index-mapping file.

Story 1.1 (FR-1) — canonical mapping round-trip test pinned by name.
Story 1.3 helper tests are added in the same file (extends here).

Both the Playwright helper (`ui/tests/e2e/helpers/seed_ubi.ts`) and the
Python engine-write helper load the same `samples/ubi_index_mappings.json`.
This test catches drift between the JSON file and the original shape the
Playwright helper used to inline at lines 25-48.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.app.domain.demo.synthetic_ubi import UbiEventRow, UbiQueryRow
from backend.app.services.demo_ubi_seed import (
    DEMO_UBI_SCENARIO_ALLOWLIST,
    DemoUbiSeedError,
    ensure_ubi_indices,
    seed_synthetic_ubi,
)

# Repo-root-relative path. The Python helper resolves to /app/samples/...
# in-container; tests resolve to <repo>/samples/...
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MAPPING_FILE = _REPO_ROOT / "samples" / "ubi_index_mappings.json"


# The original shape inlined in seed_ubi.ts lines 25-48 before FR-1 lifted
# it into a canonical JSON file. If this dict ever changes, BOTH the JSON
# file AND the TS helper MUST be updated in lockstep; the spec's CLI-vs-
# home-button parity rule depends on byte-equivalent mappings.
_EXPECTED_SHAPE: dict[str, dict[str, object]] = {
    "ubi_queries": {
        "mappings": {
            "properties": {
                "query_id": {"type": "keyword"},
                "user_query": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "application": {"type": "keyword"},
                "timestamp": {"type": "date"},
            }
        }
    },
    "ubi_events": {
        "mappings": {
            "properties": {
                "query_id": {"type": "keyword"},
                "action_name": {"type": "keyword"},
                "object_id": {"type": "keyword"},
                "application": {"type": "keyword"},
                "position": {"type": "integer"},
                "dwell_seconds": {"type": "float"},
                "timestamp": {"type": "date"},
            }
        }
    },
}


def test_mapping_file_round_trips_to_seed_ubi_helper_shape() -> None:
    """FR-1: canonical JSON mapping file deep-equals the original
    `seed_ubi.ts` inline shape.

    This is the explicit test name required by spec FR-1
    (`backend/tests/unit/services/test_demo_ubi_seed.py::
    test_mapping_file_round_trips_to_seed_ubi_helper_shape`).
    """
    assert _MAPPING_FILE.exists(), f"canonical UBI mapping file missing at {_MAPPING_FILE!s}"
    parsed = json.loads(_MAPPING_FILE.read_text(encoding="utf-8"))
    assert parsed == _EXPECTED_SHAPE, (
        "samples/ubi_index_mappings.json drifted from the original "
        "ui/tests/e2e/helpers/seed_ubi.ts inline shape. "
        f"Got: {json.dumps(parsed, indent=2)}"
    )


def test_mapping_file_has_both_top_level_keys() -> None:
    """Defensive: confirm the file has exactly the two expected top-level
    keys. Catches a structural drift even before the deep-equality check
    (e.g., a malformed wrapper key added by hand)."""
    parsed = json.loads(_MAPPING_FILE.read_text(encoding="utf-8"))
    assert set(parsed.keys()) == {"ubi_queries", "ubi_events"}, (
        f"unexpected top-level keys: {sorted(parsed.keys())!r}"
    )


# ============================================================================
# Story 1.3 — `seed_synthetic_ubi` + `ensure_ubi_indices` helper tests (FR-3).
# ============================================================================


_DEMO_PAIRS_ALLOW: list[tuple[str, str]] = sorted(DEMO_UBI_SCENARIO_ALLOWLIST)


def _mock_response(
    status_code: int, text: str = "", json_body: dict[str, object] | None = None
) -> MagicMock:
    """Build a MagicMock that mimics httpx.Response well enough for our tests."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


def _mock_client(responses: list[MagicMock]) -> MagicMock:
    """An AsyncMock httpx client whose put/post return the queued responses."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.put = AsyncMock(side_effect=responses[:])
    client.post = AsyncMock(side_effect=responses[:])
    return client


def _q(application: str = "products") -> UbiQueryRow:
    return UbiQueryRow(
        query_id="q-1",
        user_query="test",
        application=application,
        timestamp="2026-05-29T12:34:56+00:00",
    )


def _ev(application: str = "products") -> UbiEventRow:
    return UbiEventRow(
        query_id="q-1",
        action_name="impression",
        object_id="d-1",
        application=application,
        timestamp="2026-05-29T12:34:56+00:00",
        position=1,
    )


# --- Allowlist guard ---


@pytest.mark.parametrize("scenario_slug,target", _DEMO_PAIRS_ALLOW)
async def test_seed_synthetic_ubi_accepts_allowlisted_pairs(
    scenario_slug: str, target: str
) -> None:
    """All 3 (scenario, target) pairs from D-2 are allowed."""
    # Two PUTs (ensure not invoked here) + two POSTs (queries + events bulk)
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[
            _mock_response(200, json_body={"errors": False}),
            _mock_response(200, json_body={"errors": False}),
        ]
    )
    result = await seed_synthetic_ubi(
        engine_client=client,
        engine_base_url="http://localhost:9200",
        host_auth=("elastic", "changeme"),
        scenario_slug=scenario_slug,
        target_application=target,
        queries=[_q(target)],
        events=[_ev(target)],
    )
    assert result == 1


@pytest.mark.parametrize(
    "scenario_slug,target",
    [
        # Each demo slug paired with the WRONG target (cross-product).
        ("acme-products-prod", "docs-articles"),
        ("acme-products-prod", "job-listings"),
        ("corp-docs-search", "products"),
        ("jobs-marketplace-prod", "products"),
        # A non-demo (production-shaped) slug + a demo target name.
        ("prod-acme-products", "products"),
        # Completely unknown pair.
        ("totally-unknown", "random-index"),
        # Demo target with no slug.
        ("", "products"),
        # The OS demo cluster (deliberately excluded — kept rung_0).
        ("news-search-staging", "news-articles"),
    ],
)
async def test_seed_synthetic_ubi_rejects_non_allowlisted_pairs(
    scenario_slug: str, target: str
) -> None:
    """The guard rejects every pair not in the 3-entry allowlist."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock()
    with pytest.raises(ValueError, match="refuses non-demo"):
        await seed_synthetic_ubi(
            engine_client=client,
            engine_base_url="http://localhost:9200",
            host_auth=("elastic", "changeme"),
            scenario_slug=scenario_slug,
            target_application=target,
            queries=[_q(target)],
            events=[_ev(target)],
        )
    # No engine call should have been made — guard fires before I/O.
    client.post.assert_not_called()


def test_allowlist_is_frozenset() -> None:
    """The allowlist MUST be a frozenset (immutable, hashable)."""
    assert isinstance(DEMO_UBI_SCENARIO_ALLOWLIST, frozenset)
    assert len(DEMO_UBI_SCENARIO_ALLOWLIST) == 3


# --- NDJSON shape ---


async def test_bulk_body_uses_refresh_wait_for_query_param() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[
            _mock_response(200, json_body={"errors": False}),
            _mock_response(200, json_body={"errors": False}),
        ]
    )
    await seed_synthetic_ubi(
        engine_client=client,
        engine_base_url="http://localhost:9200",
        host_auth=("elastic", "changeme"),
        scenario_slug="acme-products-prod",
        target_application="products",
        queries=[_q()],
        events=[_ev()],
    )
    # Both POSTs MUST include params={"refresh": "wait_for"}.
    for call in client.post.call_args_list:
        assert call.kwargs.get("params") == {"refresh": "wait_for"}


async def test_bulk_body_uses_ndjson_content_type() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[
            _mock_response(200, json_body={"errors": False}),
            _mock_response(200, json_body={"errors": False}),
        ]
    )
    await seed_synthetic_ubi(
        engine_client=client,
        engine_base_url="http://localhost:9200",
        host_auth=("elastic", "changeme"),
        scenario_slug="acme-products-prod",
        target_application="products",
        queries=[_q()],
        events=[_ev()],
    )
    for call in client.post.call_args_list:
        assert call.kwargs.get("headers", {}).get("Content-Type") == "application/x-ndjson"


async def test_bulk_body_has_trailing_newline_and_index_action() -> None:
    """ES _bulk REQUIRES a trailing newline; without it the last row is
    silently dropped on some ES versions. The first line MUST be an
    ``{"index": {}}`` action line (not ``create`` / ``update`` / etc)."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[
            _mock_response(200, json_body={"errors": False}),
            _mock_response(200, json_body={"errors": False}),
        ]
    )
    await seed_synthetic_ubi(
        engine_client=client,
        engine_base_url="http://localhost:9200",
        host_auth=("elastic", "changeme"),
        scenario_slug="acme-products-prod",
        target_application="products",
        queries=[_q()],
        events=[_ev()],
    )
    for call in client.post.call_args_list:
        body = call.kwargs.get("content", "")
        assert body.endswith("\n"), f"body missing trailing newline: {body!r}"
        assert not body.endswith("\n\n"), "body has double trailing newline (allocator drift?)"
        first_line = body.splitlines()[0]
        assert first_line == '{"index": {}}', (
            f"first NDJSON line should be index action, got: {first_line!r}"
        )


# --- application normalization (defense-in-depth FR-3 contract) ---


async def test_application_tag_normalized_to_target() -> None:
    """If a row arrives with the wrong ``application`` value, the helper
    silently overrides it to ``target_application``. The generator
    already sets the right value, but the helper is the contract
    boundary — a future generator drift would otherwise leak the wrong
    tag into the index.
    """
    captured: list[str] = []

    async def capture_post(*args, **kwargs):
        body = kwargs.get("content", "")
        captured.append(body)
        return _mock_response(200, json_body={"errors": False})

    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=capture_post)
    # Rows tagged with the WRONG application — should be normalized.
    bad_q = UbiQueryRow(
        query_id="q-1",
        user_query="x",
        application="WRONG",
        timestamp="2026-05-29T12:34:56+00:00",
    )
    bad_e = UbiEventRow(
        query_id="q-1",
        action_name="click",
        object_id="d-1",
        application="WRONG",
        timestamp="2026-05-29T12:34:56+00:00",
    )
    await seed_synthetic_ubi(
        engine_client=client,
        engine_base_url="http://localhost:9200",
        host_auth=("elastic", "changeme"),
        scenario_slug="acme-products-prod",
        target_application="products",
        queries=[bad_q],
        events=[bad_e],
    )
    # Both bulk bodies should contain only "application":"products" — the WRONG
    # tag was scrubbed.
    for body in captured:
        assert '"application":"products"' in body
        assert '"application":"WRONG"' not in body


# --- Engine error handling ---


async def test_bulk_error_raises_demo_ubi_seed_error() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[
            _mock_response(400, text="bulk index_not_found_exception"),
        ]
    )
    with pytest.raises(DemoUbiSeedError, match="bulk_write"):
        await seed_synthetic_ubi(
            engine_client=client,
            engine_base_url="http://localhost:9200",
            host_auth=("elastic", "changeme"),
            scenario_slug="acme-products-prod",
            target_application="products",
            queries=[_q()],
            events=[_ev()],
        )


async def test_bulk_per_item_errors_raise_demo_ubi_seed_error() -> None:
    """ES returns HTTP 200 with ``errors: true`` for per-item failures
    even when the request itself succeeded. We must NOT silently accept
    that — partial writes corrupt the rung classification."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[
            _mock_response(
                200,
                json_body={
                    "errors": True,
                    "items": [{"index": {"error": "mapper_parsing_exception"}}],
                },
            ),
        ]
    )
    with pytest.raises(DemoUbiSeedError, match="per-item errors"):
        await seed_synthetic_ubi(
            engine_client=client,
            engine_base_url="http://localhost:9200",
            host_auth=("elastic", "changeme"),
            scenario_slug="acme-products-prod",
            target_application="products",
            queries=[_q()],
            events=[_ev()],
        )


# --- ensure_ubi_indices ---


async def test_ensure_ubi_indices_tolerates_resource_already_exists(tmp_path: Path) -> None:
    """The PUT must accept HTTP 400 with ``resource_already_exists`` and
    move on — that's the concurrent-worker-already-won case."""
    # Write a tmp mapping file so we don't touch /app/samples/ in tests.
    mapping_path = tmp_path / "ubi_index_mappings.json"
    mapping_path.write_text(json.dumps(_EXPECTED_SHAPE))
    client = MagicMock(spec=httpx.AsyncClient)
    client.put = AsyncMock(
        side_effect=[
            _mock_response(
                400,
                text="resource_already_exists_exception: index [ubi_queries/uuid] already exists",
            ),
            _mock_response(200),
        ]
    )
    # Should NOT raise.
    await ensure_ubi_indices(
        engine_client=client,
        engine_base_url="http://localhost:9200",
        host_auth=("elastic", "changeme"),
        mapping_path=mapping_path,
    )
    assert client.put.await_count == 2


async def test_ensure_ubi_indices_raises_on_other_4xx(tmp_path: Path) -> None:
    mapping_path = tmp_path / "ubi_index_mappings.json"
    mapping_path.write_text(json.dumps(_EXPECTED_SHAPE))
    client = MagicMock(spec=httpx.AsyncClient)
    client.put = AsyncMock(
        side_effect=[
            _mock_response(403, text="forbidden"),
        ]
    )
    with pytest.raises(DemoUbiSeedError, match="ensure_indices"):
        await ensure_ubi_indices(
            engine_client=client,
            engine_base_url="http://localhost:9200",
            host_auth=("elastic", "changeme"),
            mapping_path=mapping_path,
        )
