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
