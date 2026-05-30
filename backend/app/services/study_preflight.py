# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Create-time preflight overlap probe for POST /api/v1/studies.

Single bounded ids-existence probe against the study's target index to detect
"all trials will score 0" failure modes (re-indexed corpus, rotated index,
stale judgments) before any orchestrator budget is spent.

The probe runs after Tier 1's target-mismatch check (PR #184) and before the
study row is inserted. On insufficient overlap the studies POST handler
raises 422 ``INSUFFICIENT_JUDGMENT_OVERLAP``. On any of the five documented
adapter exceptions, the probe emits a WARN log and returns ``None``; the
handler then falls through silently (per FR-4 / Q2 → A — consistent with
RelyLoop's "tolerate transient adapter failures at write time" pattern).

See ``docs/00_overview/planned_features/feat_study_preflight_overlap_probe/``
for the full spec.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.adapters.protocol import NativeQuery
from backend.app.db import repo
from backend.app.db.models import Cluster
from backend.app.services.cluster import ClusterUnreachable, acquire_adapter

logger = structlog.get_logger(__name__)

MIN_OVERLAP: int = 3
"""Minimum judged-doc overlap to allow study creation (cap-aware: the handler
computes ``required = min(MIN_OVERLAP, max(judged_doc_count, 1))``)."""

PROBE_TIMEOUT_S: float = 2.0
"""Per-adapter-call timeout passed to ``search_batch``. The outer
``asyncio.wait_for`` uses ``PROBE_TIMEOUT_S + 1.0`` as a wall-clock guard."""

MAX_PROBED_DOCS: int = 200
"""Max doc_ids shipped in the ``ids`` query body. Protects against degenerate
judgment lists with thousands of judgments per qid."""


@dataclass(frozen=True)
class OverlapProbeResult:
    """Result of a successful probe (including the empty-judgments path).

    ``representative_query_id is None`` ONLY on the empty-judgments path
    (no qid in the query_set has any judgments). On that path the other
    three fields are 0.
    """

    overlap_size: int
    probed_doc_count: int
    judged_doc_count: int
    representative_query_id: str | None


async def probe_judgment_overlap(
    db: AsyncSession,
    cluster: Cluster,
    *,
    judgment_list_id: str,
    query_set_id: str,
    target: str,
) -> OverlapProbeResult | None:
    """Run the create-time overlap probe.

    Returns:
        ``OverlapProbeResult``: probe completed (including the empty-judgments
            path — see ``representative_query_id is None``).
        ``None``: probe skipped due to one of the five fall-through exceptions
            documented in FR-4. The probe emits a WARN log with the reason
            before returning.

    The caller (POST /api/v1/studies handler) interprets the result via the
    cap-aware threshold formula: reject 422 ``INSUFFICIENT_JUDGMENT_OVERLAP``
    when ``result.overlap_size < min(MIN_OVERLAP, max(result.judged_doc_count, 1))``.
    """
    # 1) Pick representative qid (or short-circuit on empty judgments).
    representative_qid = await repo.find_first_judged_query(
        db,
        query_set_id=query_set_id,
        judgment_list_id=judgment_list_id,
    )
    if representative_qid is None:
        logger.info(
            "studies.preflight.overlap_probe.empty",
            study_judgment_list_id=judgment_list_id,
            study_query_set_id=query_set_id,
        )
        return OverlapProbeResult(
            overlap_size=0,
            probed_doc_count=0,
            judged_doc_count=0,
            representative_query_id=None,
        )

    # 2) Capture total judged-doc count BEFORE applying the cap (for the error
    # message's `judged_doc_count=N` field).
    judged_doc_count = await repo.count_judgments_for_list_and_query(
        db,
        judgment_list_id,
        representative_qid,
    )

    # 3) Fetch up to MAX_PROBED_DOCS judged doc_ids, deterministically.
    judged_doc_ids = await repo.list_doc_ids_for_list_and_query(
        db,
        judgment_list_id,
        representative_qid,
        limit=MAX_PROBED_DOCS,
    )
    probed_doc_count = len(judged_doc_ids)

    # 4) Acquire adapter + issue one bounded ids-query.
    native = NativeQuery(
        query_id="overlap_probe",
        body={
            "query": {"ids": {"values": judged_doc_ids}},
            "size": probed_doc_count,
        },
    )
    try:
        async with acquire_adapter(cluster) as adapter:
            result = await asyncio.wait_for(
                adapter.search_batch(
                    target=target,
                    queries=[native],
                    top_k=probed_doc_count,
                    strict_errors=True,
                    timeout=PROBE_TIMEOUT_S,
                ),
                timeout=PROBE_TIMEOUT_S + 1.0,
            )
    except (ClusterUnreachable, ClusterUnreachableError):
        logger.warning(
            "studies.preflight.overlap_probe.skipped",
            study_judgment_list_id=judgment_list_id,
            study_query_set_id=query_set_id,
            study_target=target,
            cluster_id=cluster.id,
            cluster_name=cluster.name,
            reason="unreachable",
        )
        return None
    except (TimeoutError, QueryTimeoutError):
        logger.warning(
            "studies.preflight.overlap_probe.skipped",
            study_judgment_list_id=judgment_list_id,
            study_query_set_id=query_set_id,
            study_target=target,
            cluster_id=cluster.id,
            cluster_name=cluster.name,
            reason="timeout",
        )
        return None
    except InvalidQueryDSLError:
        logger.warning(
            "studies.preflight.overlap_probe.skipped",
            study_judgment_list_id=judgment_list_id,
            study_query_set_id=query_set_id,
            study_target=target,
            cluster_id=cluster.id,
            cluster_name=cluster.name,
            reason="invalid_query_dsl",
        )
        return None

    hits = result.get("overlap_probe", [])
    return OverlapProbeResult(
        overlap_size=len(hits),
        probed_doc_count=probed_doc_count,
        judged_doc_count=judged_doc_count,
        representative_query_id=representative_qid,
    )
