# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Engine-backed headroom-test helpers for the demo-scenarios harness.

Lands with ``feat_studies_convergence_visibility`` Epic 2 Story 2.3 (scaffold).

The headroom test asserts FR-5 deterministically WITHOUT running the optimizer:
for each enriched ``SCENARIOS`` entry, render the scenario's template with the
baseline (midpoint) params and with a hand-picked "better" param set, evaluate
NDCG@10 against the authored docs+judgments via the shipped eval engine, and
assert ``0.40 <= baseline <= 0.70``, ``better - baseline >= 0.10``, and
``better < 0.99``. This is the cheap CI gate that pins enrichment quality — the
``@pytest.mark.slow`` end-to-end seed test exercises the full optimizer for ONE
representative scenario; the headroom test covers all five.

Indexing helpers below talk to the local ES/OS/Solr containers (or the CI
service containers) using raw httpx — no basic-auth header — because the local
Compose + CI containers all run security-disabled. This mirrors
``backend/app/scripts/seed_es.py``'s and
``backend/tests/integration/fixtures/es_overlap_probe.py``'s precedent (D-1 of
``infra_study_preflight_real_engine_integration``).

The actual ``render`` + ``search_batch`` calls go through the engine adapter
(``ElasticAdapter`` / ``SolrAdapter``) so the harness exercises the same code
paths the live optimizer hits.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any, cast

import httpx
import structlog

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.protocol import (
    EngineType,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    SearchAdapter,
)
from backend.app.adapters.solr import SolrAdapter
from backend.app.eval.scoring import score

logger = structlog.get_logger(__name__)

# Configset source root mirrors backend/app/scripts/seed_solr_products.py — the
# checked-in configsets the local Solr loads from when its collections are
# created. The headroom test reuses ``relyloop_products`` (same configset the
# acme-kb-docs-solr demo scenario uses) so the schema (title, description,
# bullet_points, category, in_stock) matches the scenario's authored docs.
_CONFIGSET_SOURCE_ROOT = Path(__file__).resolve().parents[4] / "docker" / "solr" / "configsets"


# ---------------------------------------------------------------------------
# ES / OpenSearch helpers
# ---------------------------------------------------------------------------


async def index_docs_es(
    base_url: str,
    index: str,
    docs: list[dict[str, Any]],
    mapping: dict[str, Any] | None = None,
) -> None:
    """Idempotently (re)create ``index`` and bulk-load ``docs``.

    DELETE accepts 200 or 404. PUT creates the index with the supplied
    ``mapping`` (callers pass the scenario's ``index_mapping``). Each entry in
    ``docs`` is a dict with keys ``id`` (string) and ``doc`` (the JSON body) —
    matching the shape ``SCENARIOS`` entries already use in
    ``scripts/seed_meaningful_demos.py``.

    Followed by an explicit ``/_refresh`` so the immediately-following ``_search``
    sees the documents.

    Raises on bulk errors — a partial-index failure would silently skew the
    headroom score and is exactly the case the test must not paper over.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        delete_resp = await client.delete(f"/{index}")
        if delete_resp.status_code not in (200, 404):
            raise RuntimeError(
                f"index_docs_es: DELETE /{index} returned "
                f"{delete_resp.status_code}: {delete_resp.text[:200]}"
            )
        create_body: dict[str, Any] = mapping if mapping is not None else {}
        create_resp = await client.put(f"/{index}", json=create_body)
        create_resp.raise_for_status()

        if docs:
            body_lines: list[str] = []
            for entry in docs:
                body_lines.append(json.dumps({"index": {"_index": index, "_id": entry["id"]}}))
                body_lines.append(json.dumps(entry["doc"]))
            bulk_resp = await client.post(
                "/_bulk",
                content=("\n".join(body_lines) + "\n").encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
            bulk_resp.raise_for_status()
            payload = bulk_resp.json()
            if payload.get("errors"):
                first_error = next(
                    (
                        item["index"].get("error")
                        for item in payload.get("items", [])
                        if isinstance(item, dict)
                        and isinstance(item.get("index"), dict)
                        and "error" in item["index"]
                    ),
                    None,
                )
                raise RuntimeError(f"index_docs_es: /_bulk reported errors; first: {first_error}")

        refresh_resp = await client.post(f"/{index}/_refresh")
        refresh_resp.raise_for_status()


async def delete_index_es(base_url: str, index: str) -> None:
    """Best-effort DELETE for ``finally:`` cleanup; swallows transport errors.

    Re-raising in ``finally`` would mask the original assertion failure (a
    headroom miss followed by an engine restart would surface as
    ``ConnectError`` instead of ``AssertionError``). The per-test
    uuid-suffixed index name is the isolation guarantee.
    """
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            resp = await client.delete(f"/{index}")
            if resp.status_code not in (200, 404):
                logger.warning(
                    "headroom_harness.cleanup.unexpected_status",
                    engine="elastic",
                    index=index,
                    status_code=resp.status_code,
                    body=resp.text[:200],
                )
    except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "headroom_harness.cleanup.transport_error",
            engine="elastic",
            index=index,
            error_type=type(exc).__name__,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Solr helpers
# ---------------------------------------------------------------------------


def _zip_configset(configset_name: str) -> bytes:
    """Build the in-memory zip body for Solr's Configset UPLOAD API.

    Mirrors ``backend/app/scripts/seed_solr_products.py:_ensure_configset``:
    files at the zip ROOT (NOT under a ``conf/`` prefix) — otherwise core
    creation fails with "Can't find resource 'solrconfig.xml'".
    """
    conf_dir = _CONFIGSET_SOURCE_ROOT / configset_name / "conf"
    if not conf_dir.is_dir():
        raise RuntimeError(f"configset source dir not found: {conf_dir}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(conf_dir.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(conf_dir)))
    buf.seek(0)
    return buf.getvalue()


async def index_docs_solr(
    base_url: str,
    collection: str,
    configset: str,
    docs: list[dict[str, Any]],
) -> None:
    """Idempotently (re)create ``collection`` from ``configset`` and bulk-load ``docs``.

    Uploads the configset to ZooKeeper if not already present (cloud mode
    requires it), CREATEs the collection (idempotent — treats "already exists"
    as success), then POSTs the docs to ``/update?commit=true``. Docs are the
    same shape ES uses: a list of ``{"id": str, "doc": {...}}``; for Solr the
    inner ``doc`` is merged with ``id`` to form the upsert payload (Solr's
    update handler is upsert-by-uniqueKey).
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        # Configset upload — skip when already present.
        listed = await client.get("/solr/admin/configs", params={"action": "LIST"})
        listed.raise_for_status()
        configsets = listed.json().get("configSets") or []
        if configset not in configsets:
            zipped = _zip_configset(configset)
            upload_resp = await client.post(
                "/solr/admin/configs",
                params={"action": "UPLOAD", "name": configset},
                content=zipped,
                headers={"Content-Type": "application/octet-stream"},
            )
            upload_resp.raise_for_status()

        # Collection CREATE — idempotent.
        coll_resp = await client.get("/solr/admin/collections", params={"action": "LIST"})
        coll_resp.raise_for_status()
        if collection not in (coll_resp.json().get("collections") or []):
            create_resp = await client.get(
                "/solr/admin/collections",
                params={
                    "action": "CREATE",
                    "name": collection,
                    "numShards": "1",
                    "replicationFactor": "1",
                    "collection.configName": configset,
                },
            )
            if not (create_resp.status_code == 400 and "already exists" in create_resp.text):
                create_resp.raise_for_status()

        # Bulk index — Solr upsert by uniqueKey (id).
        payload = [{"id": entry["id"], **entry["doc"]} for entry in docs]
        if payload:
            update_resp = await client.post(
                f"/solr/{collection}/update",
                params={"commit": "true"},
                content=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            update_resp.raise_for_status()


async def delete_collection_solr(base_url: str, collection: str) -> None:
    """Best-effort DELETE for ``finally:`` cleanup; swallows transport errors."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            resp = await client.get(
                "/solr/admin/collections",
                params={"action": "DELETE", "name": collection},
            )
            # Solr returns 200 with an embedded error body when the collection
            # doesn't exist — accept that as a successful cleanup.
            if resp.status_code != 200:
                logger.warning(
                    "headroom_harness.cleanup.unexpected_status",
                    engine="solr",
                    collection=collection,
                    status_code=resp.status_code,
                    body=resp.text[:200],
                )
    except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "headroom_harness.cleanup.transport_error",
            engine="solr",
            collection=collection,
            error_type=type(exc).__name__,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Adapter + scoring helpers
# ---------------------------------------------------------------------------


def build_adapter(
    engine_type: EngineType,
    base_url: str,
    auth_kind: str,
    credentials_ref: str,
) -> SearchAdapter:
    """Construct the appropriate adapter for the headroom test.

    ``credentials_ref`` resolves through the same ``cluster_credentials.yaml``
    the live stack uses — local Compose mounts it via ``secrets/`` and CI's
    pr.yml writes a matching one (the ``local-es`` / ``local-opensearch`` /
    ``local-solr`` entries are seeded by ``scripts/install.sh`` / the
    pr.yml "Write file-based secrets" step). The Authorization header the
    adapter computes from those creds is ignored by the security-disabled
    local + CI containers (per CLAUDE.md "Common Pitfalls").
    """
    if engine_type == "solr":
        return SolrAdapter(
            cluster_id=str(uuid.uuid4()),
            engine_type=engine_type,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=None,
        )
    return ElasticAdapter(
        cluster_id=str(uuid.uuid4()),
        engine_type=engine_type,
        base_url=base_url,
        auth_kind=auth_kind,
        credentials_ref=credentials_ref,
        engine_config=None,
    )


def build_template(scenario: dict[str, Any]) -> QueryTemplate:
    """Pydantic ``QueryTemplate`` constructed from the scenario literal.

    The ``SCENARIOS`` literal at ``scripts/seed_meaningful_demos.py`` carries
    ``template_name``, ``template_body``, ``template_declared_params``, and
    ``engine_type`` — exactly the four fields the adapter ``render`` call
    consumes.
    """
    return QueryTemplate(
        name=cast("str", scenario["template_name"]),
        engine_type=cast("EngineType", scenario["engine_type"]),
        body=cast("str", scenario["template_body"]),
        declared_params=cast("dict[str, str]", scenario["template_declared_params"]),
    )


def build_qrels(scenario: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Translate ``judgments_map`` into the ``{qid: {doc_id: rating}}`` shape ``score()`` expects.

    Query identity is by position in ``scenario["queries"]`` (string index) so
    the qrels keys match the ``query_id`` the test constructs in
    :func:`run_scenario_metric`.
    """
    out: dict[str, dict[str, int]] = {}
    for query_idx, doc_id, rating in scenario["judgments_map"]:
        qid = str(query_idx)
        out.setdefault(qid, {})[doc_id] = int(rating)
    return out


async def run_scenario_metric(
    adapter: SearchAdapter,
    scenario: dict[str, Any],
    params: dict[str, ParamValue],
    target: str,
    *,
    top_k: int = 10,
    metric: str = "ndcg@10",
) -> float:
    """Render the scenario's template with ``params``, search, score, and return the metric.

    Builds one ``NativeQuery`` per query in ``scenario["queries"]`` using the
    query-index (string) as ``query_id`` — that string is the join key against
    :func:`build_qrels`'s output, exactly mirroring the live optimizer's qid
    plumbing (the live path uses ``str(QuerySet.queries[i].id)`` but the join
    key shape — string — is the same).
    """
    template = build_template(scenario)
    queries: list[NativeQuery] = []
    for query_idx, query_record in enumerate(scenario["queries"]):
        rendered = adapter.render(template, params, query_record["query_text"])
        queries.append(NativeQuery(query_id=str(query_idx), body=rendered.body))

    hits = await adapter.search_batch(target=target, queries=queries, top_k=top_k)
    run: dict[str, dict[str, float]] = {
        qid: {hit.doc_id: float(hit.score) for hit in hit_list} for qid, hit_list in hits.items()
    }
    qrels = build_qrels(scenario)
    scored = score(qrels, run, {metric})
    return float(scored["aggregate"][metric])


async def cleanup_target(scenario: dict[str, Any], base_url: str, target: str) -> None:
    """Dispatch ``delete_*`` per engine_type — used in test ``finally:`` blocks."""
    if scenario["engine_type"] == "solr":
        await delete_collection_solr(base_url, target)
    else:
        await delete_index_es(base_url, target)


__all__ = [
    "build_adapter",
    "build_qrels",
    "build_template",
    "cleanup_target",
    "delete_collection_solr",
    "delete_index_es",
    "index_docs_es",
    "index_docs_solr",
    "run_scenario_metric",
]
