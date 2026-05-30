# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Engine-write helper for synthetic UBI demo data (Story 1.3 / FR-3).

This module is **install-side / seed-only** — it never runs as part of
the runtime adapter Protocol (Absolute Rule #4). It bulk-writes the
synthetic UBI rows produced by
:mod:`backend.app.domain.demo.synthetic_ubi` directly into the demo
Elasticsearch container via ``httpx.AsyncClient``, using the same
posture
:func:`backend.app.services.demo_seeding.run_demo_reseed_cleanup`
already uses for its DELETE calls.

Public surface:

* ``DEMO_UBI_SCENARIO_ALLOWLIST`` — the three ``(scenario_slug,
  target_application)`` pairs the helper accepts (D-2 / D-5).
* ``ensure_ubi_indices(...)`` — create the two indices with the
  canonical mapping; tolerates 400 ``resource_already_exists_exception``.
* ``seed_synthetic_ubi(...)`` — bulk-write queries + events to the
  engine. Refuses non-allowlisted pairs with ``ValueError``;
  normalizes ``application`` on every row to ``target_application``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Final

import httpx

from backend.app.domain.demo.synthetic_ubi import UbiEventRow, UbiQueryRow

logger = logging.getLogger(__name__)


class DemoUbiSeedError(RuntimeError):
    """Raised on unrecoverable engine errors during UBI bulk write.

    Mirrors the ``DemoSeedingError`` shape used by ``demo_seeding`` so the
    route handler's existing 503 SEED_FAILED path stays uniform.
    """


# (scenario_slug, target_application) pairs that may legitimately receive
# synthetic UBI. Gating on the pair (not the target alone) prevents the
# name-collision misuse mode where a non-demo cluster with the same
# target index name slips past a bare-target check.
DEMO_UBI_SCENARIO_ALLOWLIST: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("acme-products-prod", "products"),
        ("corp-docs-search", "docs-articles"),
        ("jobs-marketplace-prod", "job-listings"),
    }
)


# In-container path: ``demo_seeding._SAMPLES_DIR`` is ``/app/samples``
# (Compose bind-mount of the repo's ``samples/`` directory). Tests run
# locally; they exercise the helper logic with this path patched.
_MAPPING_PATH: Final[Path] = Path("/app/samples/ubi_index_mappings.json")

_INDEX_QUERIES: Final[str] = "ubi_queries"
_INDEX_EVENTS: Final[str] = "ubi_events"


def _load_mappings(mapping_path: Path = _MAPPING_PATH) -> dict[str, dict[str, object]]:
    """Read the canonical mapping JSON.

    Separated out so unit tests can pass a tmp_path-mounted file via the
    optional ``mapping_path`` argument without touching the in-container
    default.
    """
    result: dict[str, dict[str, object]] = json.loads(mapping_path.read_text(encoding="utf-8"))
    return result


def _httpx_basic_auth(host_auth: tuple[str, str]) -> httpx.BasicAuth:
    return httpx.BasicAuth(*host_auth)


async def ensure_ubi_indices(
    *,
    engine_client: httpx.AsyncClient,
    engine_base_url: str,
    host_auth: tuple[str, str],
    mapping_path: Path = _MAPPING_PATH,
) -> None:
    """Create the two UBI indices with the canonical mapping.

    Idempotent: tolerates ``HTTP 400 resource_already_exists_exception``.
    Any other non-2xx raises :class:`DemoUbiSeedError`.
    """
    mappings = _load_mappings(mapping_path)
    auth = _httpx_basic_auth(host_auth)
    for index_name in (_INDEX_QUERIES, _INDEX_EVENTS):
        resp = await engine_client.put(
            f"{engine_base_url}/{index_name}",
            json=mappings[index_name],
            auth=auth,
        )
        if resp.status_code in (200, 201):
            continue
        if resp.status_code == 400 and "resource_already_exists" in resp.text:
            # Tolerated — concurrent worker (or previous-run leftover) won.
            logger.debug(
                "ubi_seed_ensure_index_already_exists",
                extra={"index": index_name},
            )
            continue
        raise DemoUbiSeedError(
            f"ubi_seed/ensure_indices/{index_name}: HTTP {resp.status_code} {resp.text[:200]}"
        )


def _normalize_application(
    rows: list[UbiQueryRow] | list[UbiEventRow], target: str
) -> list[dict[str, object]]:
    """Convert frozen dataclass rows to dict with ``application`` overwritten.

    Defense-in-depth — the generator already sets ``application``
    correctly, but FR-3 makes the helper the contract boundary so a
    future generator drift (or a hand-built row passed by a test) cannot
    leak the wrong tag.
    """
    out: list[dict[str, object]] = []
    for row in rows:
        d = asdict(row)
        d["application"] = target
        # Strip None-valued optional fields (``position`` / ``dwell_seconds``
        # on rows that don't carry them) so the bulk body matches the
        # mapping's expected shape — Elasticsearch tolerates explicit nulls
        # on numeric fields but the round-trip is cleaner without them.
        out.append({k: v for k, v in d.items() if v is not None})
    return out


def _build_bulk_ndjson(rows: list[dict[str, object]]) -> str:
    """Alternate ``{"index": {}}`` action lines with row payloads.

    Elasticsearch's ``_bulk`` API REQUIRES a trailing newline; without it,
    some ES versions silently drop the last row. The trailing newline is
    asserted by a dedicated unit test.
    """
    lines: list[str] = []
    for row in rows:
        lines.append('{"index": {}}')
        lines.append(json.dumps(row, separators=(",", ":")))
    return "\n".join(lines) + "\n"


async def seed_synthetic_ubi(
    *,
    engine_client: httpx.AsyncClient,
    engine_base_url: str,
    host_auth: tuple[str, str],
    scenario_slug: str,
    target_application: str,
    queries: list[UbiQueryRow],
    events: list[UbiEventRow],
) -> int:
    """Bulk-write synthetic queries + events.

    Returns the number of events written.

    Raises:
        ValueError: if ``(scenario_slug, target_application)`` is not in
            :data:`DEMO_UBI_SCENARIO_ALLOWLIST`.
        DemoUbiSeedError: on engine ``_bulk`` HTTP errors.
    """
    pair = (scenario_slug, target_application)
    if pair not in DEMO_UBI_SCENARIO_ALLOWLIST:
        raise ValueError(
            f"seed_synthetic_ubi refuses non-demo (scenario, target): "
            f"({scenario_slug!r}, {target_application!r}) not in "
            f"DEMO_UBI_SCENARIO_ALLOWLIST"
        )

    auth = _httpx_basic_auth(host_auth)
    queries_payload = _normalize_application(queries, target_application)
    events_payload = _normalize_application(events, target_application)

    for index_name, payload in (
        (_INDEX_QUERIES, queries_payload),
        (_INDEX_EVENTS, events_payload),
    ):
        if not payload:
            continue
        body = _build_bulk_ndjson(payload)
        resp = await engine_client.post(
            f"{engine_base_url}/{index_name}/_bulk",
            params={"refresh": "wait_for"},
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
            auth=auth,
        )
        if resp.status_code not in (200, 201):
            raise DemoUbiSeedError(
                f"ubi_seed/bulk_write/{index_name}: HTTP {resp.status_code} {resp.text[:200]}"
            )
        # ES returns 200 with `errors: true` for per-item errors even when
        # the request itself succeeded. Surface those explicitly with a
        # sampled error payload so the operator can diagnose mapping /
        # parsing issues without rerunning under verbose tracing (per
        # Gemini Code Assist review on PR #320).
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("errors"):
            sample_err: object = None
            items = data.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict) or not item:
                        continue
                    op_result = next(iter(item.values()))
                    if isinstance(op_result, dict) and "error" in op_result:
                        sample_err = op_result["error"]
                        break
            err_details = f" (sample: {sample_err})" if sample_err is not None else ""
            raise DemoUbiSeedError(
                f"ubi_seed/bulk_write/{index_name}: per-item errors in response"
                f"{err_details} ({len(payload)} rows attempted)"
            )

    return len(events)


__all__ = [
    "DEMO_UBI_SCENARIO_ALLOWLIST",
    "DemoUbiSeedError",
    "ensure_ubi_indices",
    "seed_synthetic_ubi",
]
