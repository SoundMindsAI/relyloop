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

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Final

import httpx

from backend.app.domain.demo.synthetic_ubi import UbiEventRow, UbiQueryRow
from backend.app.scripts.seed_solr_products import (
    _bulk_index_products as _solr_bulk_index,
)
from backend.app.scripts.seed_solr_products import (
    _ensure_collection as _solr_ensure_collection,
)

logger = logging.getLogger(__name__)

# Engine-type discriminator. ES + OpenSearch share the same `_bulk` NDJSON +
# PUT-index path (the default branch); Solr builds collections from configsets
# and indexes via the JSON update handler. Kept as a module constant so the
# branch is a single named comparison, not a repeated string literal.
_SOLR_ENGINE: Final[str] = "solr"

# Solr's `relyloop_ubi` configset (docker/solr/configsets/relyloop_ubi/conf/).
# Both UBI collections are created from it — same configset the local
# `seed_solr_products` CLI uses (seed_solr_products.py:155-157).
_SOLR_UBI_CONFIGSET: Final[str] = "relyloop_ubi"


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
        # infra_adapter_solr Story A13: Solr KB scenario gets synthetic UBI
        # (rung_2 + hybrid_ubi_llm) so the demo exercises Solr's first-party
        # solr.UBIComponent path. See spec §19 decision log + the slug parity
        # CI guard at scripts/ci/verify_demo_slug_parity.sh.
        ("acme-kb-docs-solr", "acme-kb-docs"),
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


def _ensure_solr_ubi_collections_sync(
    engine_base_url: str,
    host_auth: tuple[str, str],
) -> None:
    """Blocking Solr UBI-collection ensure (runs in :func:`asyncio.to_thread`).

    Reuses the canonical sync ``_ensure_collection`` from
    ``seed_solr_products`` — it uploads the ``relyloop_ubi`` configset to
    ZooKeeper, then CREATEs each collection (idempotent on "already
    exists"). Mirrors ``seed_solr_products.py:155-157`` exactly.
    """
    with httpx.Client(base_url=engine_base_url, timeout=30.0, auth=host_auth) as client:
        _solr_ensure_collection(client, _INDEX_QUERIES, _SOLR_UBI_CONFIGSET)
        _solr_ensure_collection(client, _INDEX_EVENTS, _SOLR_UBI_CONFIGSET)


async def ensure_ubi_indices(
    *,
    engine_client: httpx.AsyncClient,
    engine_base_url: str,
    host_auth: tuple[str, str],
    engine_type: str,
    mapping_path: Path = _MAPPING_PATH,
) -> None:
    """Create the two UBI indices/collections.

    * ES / OpenSearch: ``PUT /{index}`` with the canonical mapping from
      ``samples/ubi_index_mappings.json``. Idempotent — tolerates
      ``HTTP 400 resource_already_exists_exception``.
    * Solr: CREATE ``ubi_queries`` + ``ubi_events`` from the
      ``relyloop_ubi`` configset (reuses ``seed_solr_products``'s sync
      ``_ensure_collection`` via ``asyncio.to_thread``). Idempotent —
      ``_ensure_collection`` treats "already exists" as success.

    Any unrecoverable engine error raises :class:`DemoUbiSeedError` with a
    ``ubi_seed/ensure_indices/{collection}: ...`` prefix.
    """
    if engine_type == _SOLR_ENGINE:
        try:
            await asyncio.to_thread(_ensure_solr_ubi_collections_sync, engine_base_url, host_auth)
        except httpx.HTTPError as exc:
            raise DemoUbiSeedError(
                f"ubi_seed/ensure_indices/{_INDEX_QUERIES}+{_INDEX_EVENTS}: {exc}"
            ) from exc
        return

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


def _to_solr_date(value: object) -> object:
    """Normalize an ISO-8601 timestamp to Solr's ``DatePointField`` format.

    The synthetic-UBI generator stamps rows via ``datetime.isoformat()``,
    which renders the UTC offset as ``+00:00``. Solr's ``DatePointField``
    only accepts the canonical ``...Z`` form (and rejects ``+00:00`` with
    "Invalid Date String"). ES/OpenSearch's ``date`` type tolerates both,
    so this conversion is Solr-only. Non-string / non-``+00:00`` values
    pass through untouched.
    """
    if isinstance(value, str) and value.endswith("+00:00"):
        return value[: -len("+00:00")] + "Z"
    return value


def _to_solr_docs(rows: list[dict[str, object]], collection: str) -> list[dict[str, object]]:
    """Shape normalized UBI rows into Solr update docs.

    The ``relyloop_ubi`` configset declares ``id`` as a required
    ``uniqueKey`` and the UBI rows carry no ``id`` (the ES path uses
    ``{"index": {}}`` auto-id). Synthesize a stable, collision-resistant
    ``id`` per doc (``{collection}-{ordinal}``) and rewrite the
    ``timestamp`` to Solr's ``...Z`` date form. Every other field name
    already matches the configset schema (query_id / user_query /
    application / action_name / object_id / position / dwell_seconds).
    """
    out: list[dict[str, object]] = []
    for ordinal, row in enumerate(rows):
        # Include ``application`` (unique per scenario) in the synthesized id —
        # ``ubi_queries`` / ``ubi_events`` are SHARED collections across all
        # scenarios, so a bare ``{collection}-{ordinal}`` would collide (and
        # silently overwrite) when a second Solr scenario seeds into them.
        app = row.get("application", "default")
        doc: dict[str, object] = {"id": f"{collection}-{app}-{ordinal}", **row}
        if "timestamp" in doc:
            doc["timestamp"] = _to_solr_date(doc["timestamp"])
        out.append(doc)
    return out


def _seed_solr_ubi_sync(
    engine_base_url: str,
    host_auth: tuple[str, str],
    queries_docs: list[dict[str, object]],
    events_docs: list[dict[str, object]],
) -> None:
    """Blocking Solr UBI write (runs in :func:`asyncio.to_thread`).

    Reuses ``seed_solr_products``'s sync ``_bulk_index_products`` — it
    ``POST``s the doc list to ``/solr/{collection}/update?commit=true``
    with a JSON body (NOT ES ``_bulk`` NDJSON). One commit per collection.
    """
    with httpx.Client(base_url=engine_base_url, timeout=30.0, auth=host_auth) as client:
        if queries_docs:
            _solr_bulk_index(client, _INDEX_QUERIES, queries_docs)
        if events_docs:
            _solr_bulk_index(client, _INDEX_EVENTS, events_docs)


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
    engine_type: str,
    scenario_slug: str,
    target_application: str,
    queries: list[UbiQueryRow],
    events: list[UbiEventRow],
) -> int:
    """Bulk-write synthetic queries + events.

    Returns the number of events written.

    * ES / OpenSearch: ``POST /{index}/_bulk`` NDJSON (auto-id rows).
    * Solr: ``POST /solr/{collection}/update?commit=true`` with a JSON
      doc array (synthesized ``id`` uniqueKey, ``...Z`` timestamps).

    Raises:
        ValueError: if ``(scenario_slug, target_application)`` is not in
            :data:`DEMO_UBI_SCENARIO_ALLOWLIST`.
        DemoUbiSeedError: on engine write HTTP errors.
    """
    pair = (scenario_slug, target_application)
    if pair not in DEMO_UBI_SCENARIO_ALLOWLIST:
        raise ValueError(
            f"seed_synthetic_ubi refuses non-demo (scenario, target): "
            f"({scenario_slug!r}, {target_application!r}) not in "
            f"DEMO_UBI_SCENARIO_ALLOWLIST"
        )

    queries_payload = _normalize_application(queries, target_application)
    events_payload = _normalize_application(events, target_application)

    if engine_type == _SOLR_ENGINE:
        queries_docs = _to_solr_docs(queries_payload, _INDEX_QUERIES)
        events_docs = _to_solr_docs(events_payload, _INDEX_EVENTS)
        try:
            await asyncio.to_thread(
                _seed_solr_ubi_sync,
                engine_base_url,
                host_auth,
                queries_docs,
                events_docs,
            )
        except httpx.HTTPError as exc:
            # Keep the bulk_write/{collection} prefix uniform with the ES
            # path so the orchestrator's attribution + 503 stays the same.
            # httpx.HTTPStatusError carries the failing request URL; fall
            # back to the queries collection when it's a transport error
            # (httpx.HTTPError.request raises RuntimeError when unset, so
            # guard the access rather than relying on a default).
            collection = _INDEX_QUERIES
            try:
                request_url = str(exc.request.url)
            except RuntimeError:
                request_url = ""
            if f"/solr/{_INDEX_EVENTS}/" in request_url:
                collection = _INDEX_EVENTS
            raise DemoUbiSeedError(f"ubi_seed/bulk_write/{collection}: {exc}") from exc
        return len(events)

    auth = _httpx_basic_auth(host_auth)

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
