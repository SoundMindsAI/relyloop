# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Test-only ES bulk-index + per-test seed helpers for the overlap-probe rewrite.

Lands with ``infra_study_preflight_real_engine_integration`` Story 1.2 (FR-2 + FR-6).

Provides three async helpers consumed by Story 1.3's rewrites of AC-1..AC-4b
in ``backend/tests/integration/test_studies_api.py``:

- :func:`seed_minimum_for_overlap_probe_real_engine` — sibling to the existing
  ``_seed_minimum_for_post_studies()`` helper, but seeds a cluster pointing at
  the real ES service container (``credentials_ref="local-es"``) with a
  per-test uuid-suffixed ``target`` index name.
- :func:`bulk_index_overlap_probe_docs` — DELETE+PUT+optional-``/_bulk``+refresh
  the per-test index, scoped to the small (<250-doc) per-test workload. Mirrors
  the NDJSON pattern at ``backend/app/scripts/seed_es.py:78-91``.
- :func:`delete_overlap_probe_index` — idempotent DELETE used in ``finally:``
  blocks. Swallows transport-level errors so the original test failure isn't
  masked by a follow-up ``ConnectError``.

Engine-specific code via raw ``httpx`` outside the ``SearchAdapter`` Protocol
is allowed here because (a) this is test-time-only code, (b) the established
``seed_es.py`` script + ``test_seed_es.py`` already do the same for analogous
purposes, (c) bulk-index is intentionally NOT on the Protocol per spec D-1
("the Protocol's role is engine-agnostic query-time search; bulk-index is
test-time concern that doesn't generalize across ElasticAdapter +
SolrAdapter").

No basic-auth headers — CI runs ES with ``xpack.security.enabled: "false"``
(see ``.github/workflows/pr.yml``) and local Compose follows CLAUDE.md's
"Do not install ES + OpenSearch with security plugins enabled in the local
Compose" rule, matching ``seed_es.py:48``'s no-auth precedent.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest
import structlog
import yaml

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory

# Re-exports so callers can `from fixtures.es_overlap_probe import es_required`
# without needing to know the separate reachability module exists.
from backend.tests.integration.fixtures.es_reachability import _es_base_url, es_required

__all__ = [
    "_es_base_url",
    "es_required",
    "seed_minimum_for_overlap_probe_real_engine",
    "bulk_index_overlap_probe_docs",
    "delete_overlap_probe_index",
]

logger = structlog.get_logger(__name__)


def _missing_local_es_message(action_verb: str) -> str:
    """Return the operator-guidance string used by FR-6's skip + RuntimeError paths.

    The substrings ``local-es``, ``cluster_credentials.yaml``, and
    ``scripts/install.sh`` are required by AC-INFRA-6's assertion (the local
    skip path). The CI-loud-failure path additionally requires
    ``workflow regression``, ``Seed cluster credentials``, and
    ``.github/workflows/pr.yml`` (the workflow-file pointer FR-6's RuntimeError
    branch is tested against).
    """
    return (
        f"Cannot {action_verb} overlap-probe real-engine tests: "
        "the mounted cluster_credentials.yaml is missing the `local-es:` entry. "
        "Locally, run `bash scripts/install.sh` to (re)generate "
        "`./secrets/cluster_credentials.yaml` with the local-es defaults. "
        "In CI, this indicates a workflow regression — see the "
        "'Seed cluster credentials' step in `.github/workflows/pr.yml`."
    )


def _check_local_es_credentials_or_skip() -> None:
    """Pre-flight check called by ``seed_minimum_for_overlap_probe_real_engine``.

    Reads ``Settings.cluster_credentials_yaml`` (the ``@cached_property`` at
    ``backend/app/core/settings.py:361`` which returns the FILE CONTENT as a
    YAML string, not the path — set via ``CLUSTER_CREDENTIALS_FILE``). YAML-
    parses it and checks for a top-level ``local-es`` key.

    On failure (mount missing, YAML invalid, parsed value not a dict, or
    ``local-es`` key absent):
      - in CI (``os.environ.get("CI") == "true"``): raise ``RuntimeError`` with
        the workflow-regression message so CI fails loudly.
      - elsewhere: ``pytest.skip(...)`` with operator guidance directing the
        user to ``bash scripts/install.sh``.
    """

    def _route_failure() -> None:
        if os.environ.get("CI") == "true":
            raise RuntimeError(_missing_local_es_message("run"))
        pytest.skip(_missing_local_es_message("run"))

    yaml_str = get_settings().cluster_credentials_yaml
    if yaml_str is None:
        _route_failure()
        return  # pragma: no cover -- _route_failure raises/skips

    try:
        parsed = yaml.safe_load(yaml_str)
    except yaml.YAMLError:
        _route_failure()
        return  # pragma: no cover

    if not isinstance(parsed, dict) or "local-es" not in parsed:
        _route_failure()
        return  # pragma: no cover


async def seed_minimum_for_overlap_probe_real_engine() -> dict[str, str]:
    """Seed cluster + template + query_set + judgment_list for real-engine overlap probe tests.

    Pre-flight: calls :func:`_check_local_es_credentials_or_skip` BEFORE any DB
    write or HTTP call — if ``local-es`` isn't in the mounted YAML, the helper
    skips locally or raises ``RuntimeError`` in CI.

    Acquires its own DB session via :func:`get_session_factory` (matches
    ``_seed_minimum_for_post_studies()``'s pattern at
    ``test_studies_api.py:62-64`` — does NOT accept ``db`` as an argument).

    Returns exactly six keys: ``cluster_id``, ``template_id``, ``query_set_id``,
    ``judgment_list_id``, ``target_index``, ``es_base_url``. Callers MUST use
    the returned ``es_base_url`` when invoking :func:`bulk_index_overlap_probe_docs`
    so the URL the cluster row points at and the URL the helper writes to are
    byte-identical.
    """
    _check_local_es_credentials_or_skip()

    es_base_url = _es_base_url()
    if not es_base_url:
        # Defense in depth — @es_required on the test should have caught this
        # already, but a caller invoking the helper outside a decorated test
        # would otherwise produce a misleading ConnectError later. Skip cleanly.
        pytest.skip(
            "Elasticsearch not reachable on localhost:9200 or elasticsearch:9200 — "
            "see docs/03_runbooks/local-dev.md."
        )

    target_index = f"overlap-probe-test-{uuid.uuid4().hex}"

    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"overlap-probe-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url=es_base_url,
            auth_kind="es_basic",
            credentials_ref="local-es",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"overlap-probe-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            # Declare bm25_k1 so the standard _VALID_SEARCH_SPACE used by the
            # rewritten test bodies passes the POST /studies handler's
            # search_space.params validation (chore_create_study_wizard_polish
            # FR-2 + FR-3). Same minimal declared_params as
            # _seed_minimum_for_post_studies().
            declared_params={"bm25_k1": "float"},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"overlap-probe-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"overlap-probe-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target=target_index,
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()

    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": judgment_list.id,
        "target_index": target_index,
        "es_base_url": es_base_url,
    }


async def bulk_index_overlap_probe_docs(
    es_base_url: str, target_index: str, doc_ids: list[str]
) -> None:
    """DELETE+PUT+optionally /_bulk+refresh the per-test index.

    DELETE accepts 200 or 404 (idempotent — the index may not exist yet).
    PUT creates the index with a minimal ``_id_marker`` keyword mapping (any
    mapping that accepts an ``_id`` field is sufficient for the probe's
    ``ids``-query).

    When ``doc_ids`` is empty, SKIPS the ``/_bulk`` POST entirely (an empty
    NDJSON body returns ES 400 ``parse_exception: request body is required``)
    and proceeds directly to ``/<target>/_refresh``, leaving the index empty
    but searchable for the immediately-following probe. This is the path used
    by AC-1 (zero-overlap -> 422).

    When ``doc_ids`` is non-empty, builds one NDJSON body
    (``{"index": {"_index": target, "_id": doc_id}}\\n{"_id_marker": "ok"}\\n``
    per record) and POSTs to ``/_bulk`` with ``Content-Type:
    application/x-ndjson``. Raises on ``bulk_resp.json()["errors"] is True``
    so a misbehaving ES (mapping mismatch, etc.) fails the calling test loudly
    rather than appearing to succeed.

    No basic-auth — both CI and local Compose run ES with security disabled.
    """
    async with httpx.AsyncClient(base_url=es_base_url, timeout=30.0) as client:
        # DELETE — idempotent.
        delete_resp = await client.delete(f"/{target_index}")
        if delete_resp.status_code not in (200, 404):
            raise RuntimeError(
                f"bulk_index_overlap_probe_docs: DELETE /{target_index} returned "
                f"{delete_resp.status_code}: {delete_resp.text[:200]}"
            )

        # PUT — minimal mapping; the probe only needs _id, so any mapping that
        # accepts an _id field is sufficient.
        create_resp = await client.put(
            f"/{target_index}",
            json={
                "mappings": {
                    "properties": {
                        "_id_marker": {"type": "keyword"},
                    }
                }
            },
        )
        create_resp.raise_for_status()

        # Conditional /_bulk — skip the call entirely for empty doc_ids (an
        # empty NDJSON body is malformed; see D-8 in feature_spec.md).
        if doc_ids:
            body_lines: list[str] = []
            for doc_id in doc_ids:
                body_lines.append(json.dumps({"index": {"_index": target_index, "_id": doc_id}}))
                body_lines.append(json.dumps({"_id_marker": "ok"}))
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
                raise RuntimeError(
                    f"bulk_index_overlap_probe_docs: /_bulk reported errors; first: {first_error}"
                )

        # Always refresh so the immediately-following _search sees the documents
        # (or the empty index for the zero-doc path).
        refresh_resp = await client.post(f"/{target_index}/_refresh")
        refresh_resp.raise_for_status()


async def delete_overlap_probe_index(es_base_url: str, target_index: str) -> None:
    """Idempotent DELETE for ``finally:`` blocks; swallows transport errors.

    Re-raising in ``finally:`` would mask the original test failure (e.g.,
    a probe-assertion failure followed by ES going down would surface as
    ``ConnectError`` instead of ``AssertionError``). The per-test 32-hex uuid
    suffix is the isolation guarantee; cleanup is best-effort, not the line
    of defense.
    """
    try:
        async with httpx.AsyncClient(base_url=es_base_url, timeout=30.0) as client:
            resp = await client.delete(f"/{target_index}")
            if resp.status_code not in (200, 404):
                logger.warning(
                    "overlap_probe.cleanup.unexpected_status",
                    target_index=target_index,
                    status_code=resp.status_code,
                    body=resp.text[:200],
                )
    except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "overlap_probe.cleanup.transport_error",
            target_index=target_index,
            error_type=type(exc).__name__,
            error=str(exc),
        )
