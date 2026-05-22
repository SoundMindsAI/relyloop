# Implementation Plan — feat_study_preflight_overlap_probe

**Date:** 2026-05-22
**Status:** Complete (PR #193, squash-merged `ca835e0` on 2026-05-22)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [api-conventions.md](../../../01_architecture/api-conventions.md), [CLAUDE.md](../../../../CLAUDE.md), [adapters.md](../../../01_architecture/adapters.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from the spec.
- One epic, three stories — the feature is bounded enough that a single epic gate is sufficient.
- Backend-only feature: no schema migration, no Pydantic schema changes, no frontend code change (the create-study modal's existing target+cluster filter already prevents the most common path to this 422).
- Single PR: all three stories land in one branch + one PR. Scope is ~120 LOC of production code + ~180 LOC of tests; tightly coupled (service module + repo functions + handler integration + tests).
- Use the existing `_err(...)` envelope helper, `acquire_adapter()` context manager, and `infra_structlog_test_helpers` log assertion helpers — no new infrastructure.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (probe runs in handler, ordering after Tier 1) | Epic 1 / Story 1.3 | Insert probe call in `studies.py` POST handler between `JUDGMENT_TARGET_MISMATCH` and config-serialize block. |
| FR-2 (probe shape: ids-query) | Epic 1 / Story 1.2 | New `probe_judgment_overlap()` in `backend/app/services/study_preflight.py`; depends on repo functions from Story 1.1. |
| FR-3 (2-tier cap-aware threshold + empty-judgments path + error message contract) | Epic 1 / Story 1.3 | Conditional `if result.overlap_size < min(MIN_OVERLAP, max(result.judged_doc_count, 1)): raise _err(422, ...)` in handler + INFO log on `representative_query_id=None`. |
| FR-4 (5-exception fall-through matrix + WARN log) | Epic 1 / Story 1.2 | Exception handlers inside the probe function: emit WARN log + return `None`; handler treats `None` as silent fall-through. |
| FR-5 (new error code in api-conventions.md) | Epic 1 / Story 1.3 | Add `INSUFFICIENT_JUDGMENT_OVERLAP` row to the studies-endpoint error-code table. |

All 5 FRs covered. No phase boundary (single-phase ship per spec §3). No tracking file for deferred phases needed.

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Conventions (project-specific)

Honors all RelyLoop conventions from `CLAUDE.md`:
- All repo functions take `db: AsyncSession` as first arg; use `db.flush()` (caller commits).
- Services are async and accept `db: AsyncSession` + typed arguments.
- Pure-domain functions don't exist here (no new domain layer code) — the probe is service-layer because it composes repo + adapter.
- Routers return typed Pydantic response models; errors use the `_err(...)` helper at `studies.py:74-78` which raises `HTTPException` with the canonical `{detail: {error_code, message, retryable}}` envelope.
- structlog via `logger = structlog.get_logger(__name__)` at module top.
- Conventional Commits format for every commit (`feat(...)`, `test(...)`, `docs(...)`).
- Update `backend/app/db/repo/__init__.py` `__all__` for any new exported repo function.

### AI Agent Execution Protocol

0. Load context: `architecture.md`, `state.md`, this plan, the spec.
1. **Implement Story 1.1 first** (repo functions). Story 1.2 service depends on the repo functions existing.
2. **Implement Story 1.2** (probe service helper). Story 1.3 handler depends on this function existing.
3. **Implement Story 1.3** (handler integration + api-conventions.md row).
4. Run backend tests (unit + integration + contract subset for touched endpoints) after each story.
5. Update `docs/01_architecture/api-conventions.md` and `state.md` (recent changes) in the same PR.
6. Run `make lint`, `make typecheck`, `make test-unit`, `make test-integration`, `make test-contract`.
7. Attach evidence in the PR description.

---

## Epic 1 — Preflight overlap probe at POST /api/v1/studies

### Story 1.1 — Repo functions: find_first_judged_query + list_doc_ids_for_list_and_query

**Outcome:** Two new repo functions are added that the probe service helper composes. Both are read-only single-statement SELECTs against existing tables (no schema change).

**Traces to:** FR-2 (probe data fetch).

**New files**

None. All edits are additive to existing repo modules.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/query.py` | Add `find_first_judged_query(db, *, query_set_id, judgment_list_id) -> str \| None`. Single SELECT with an `EXISTS` subquery + `ORDER BY q.id ASC LIMIT 1`. Returns the `queries.id` (UUIDv7-as-text). |
| `backend/app/db/repo/judgment.py` | Add `list_doc_ids_for_list_and_query(db, judgment_list_id, query_id, *, limit) -> list[str]`. Single `SELECT doc_id FROM judgments WHERE judgment_list_id = :list AND query_id = :qid ORDER BY doc_id ASC LIMIT :limit`. `limit` is a REQUIRED keyword arg (no default) so callers cannot accidentally fetch an unbounded list. |
| `backend/app/db/repo/__init__.py` | Add `find_first_judged_query` to the existing `from backend.app.db.repo.query import (...)` block and to `__all__`. Add `list_doc_ids_for_list_and_query` to the `from backend.app.db.repo.judgment import (...)` block (at line 43-56) and to `__all__`. |

**Endpoints**

None.

**Key interfaces**

```python
# backend/app/db/repo/query.py — new imports required at module top:
#   from backend.app.db.models import Judgment, Query  (extend existing Query-only import)

async def find_first_judged_query(
    db: AsyncSession,
    *,
    query_set_id: str,
    judgment_list_id: str,
) -> str | None:
    """First queries.id (by id ASC) in query_set that has ≥1 judgment in list, or None.

    Used by the preflight overlap probe to pick a representative qid without
    fetching query_text (privacy: query strings stay out of logs per spec §10
    Threat 2). Single SELECT with a correlated EXISTS subquery; backed by
    judgments_list_query_idx on (judgment_list_id, query_id).
    """
    stmt = (
        select(Query.id)
        .where(Query.query_set_id == query_set_id)
        .where(
            select(Judgment.id)
            .where(Judgment.query_id == Query.id)
            .where(Judgment.judgment_list_id == judgment_list_id)
            .exists()
        )
        .order_by(Query.id.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# backend/app/db/repo/judgment.py
async def list_doc_ids_for_list_and_query(
    db: AsyncSession,
    judgment_list_id: str,
    query_id: str,
    *,
    limit: int,
) -> list[str]:
    """Up to ``limit`` judged doc_ids for (judgment_list_id, query_id), doc_id ASC.

    Required keyword ``limit`` — there is no default. Callers must pass an
    explicit cap (the preflight probe passes ``limit=MAX_PROBED_DOCS=200``).
    Deterministic ordering keeps the probe replayable. The
    UniqueConstraint("judgment_list_id", "query_id", "doc_id") at
    judgment.py:49-54 guarantees rows are already distinct per (list, qid).
    """
    stmt = (
        select(Judgment.doc_id)
        .where(Judgment.judgment_list_id == judgment_list_id)
        .where(Judgment.query_id == query_id)
        .order_by(Judgment.doc_id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
```

**Pydantic schemas**

None.

**Tasks**

1. Add `find_first_judged_query` to `backend/app/db/repo/query.py`. Extend the existing `from backend.app.db.models import Query` line at query.py:31 to `from backend.app.db.models import Judgment, Query`. Use a correlated `select(Judgment.id).where(...).exists()` subquery — equivalent in PostgreSQL to `EXISTS (SELECT 1 FROM judgments WHERE ...)` because PG discards the SELECT-list inside EXISTS. No new `sqlalchemy` imports needed beyond the existing `select`.
2. Add `list_doc_ids_for_list_and_query` to `backend/app/db/repo/judgment.py` next to `count_judgments_for_list_and_query` at lines 228-245 (sibling functions; keep them grouped).
3. Update `backend/app/db/repo/__init__.py`:
   - In the `from backend.app.db.repo.query import (...)` block (lines 86-95): add `find_first_judged_query` (alphabetical).
   - In the `from backend.app.db.repo.judgment import (...)` block (lines 43-56): add `list_doc_ids_for_list_and_query` (alphabetical).
   - Append both names to `__all__` in the appropriate sections (lines 175-188 + 222-233).

**Definition of Done**

- [ ] Both functions importable via `from backend.app.db.repo import find_first_judged_query, list_doc_ids_for_list_and_query` (covered by `__all__` update).
- [ ] Behavior coverage is provided downstream — Story 1.2's unit tests exercise both functions via mocks AND Story 1.3's real-engine integration tests exercise both against a live Postgres + ES (AC-1, AC-2, AC-10). Story 1.1 does not introduce dedicated repo-layer integration tests because the functions are short single-statement SELECTs whose semantics are 100% exercised through the probe path. If a future change adds independent semantics (e.g., a second caller), add dedicated tests in `backend/tests/integration/test_study_preflight_repo.py` at that point.
- [ ] `make lint` + `make typecheck` green.

---

### Story 1.2 — Service helper: probe_judgment_overlap

**Outcome:** A new service module `backend/app/services/study_preflight.py` exports a single async public function `probe_judgment_overlap(...)` that composes the repo functions from Story 1.1 with one bounded `adapter.search_batch` call, returning an `OverlapProbeResult` or `None` per the FR-2/FR-3/FR-4 contracts. All 5 fall-through exceptions are caught internally.

**Traces to:** FR-2 (probe shape), FR-4 (5-exception fall-through).

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/study_preflight.py` | New service module. Exports the `OverlapProbeResult` dataclass + `probe_judgment_overlap` coroutine + the three module-level constants (`MIN_OVERLAP = 3`, `PROBE_TIMEOUT_S = 2.0`, `MAX_PROBED_DOCS = 200`). ~80 LOC. |

**Modified files**

None.

**Endpoints**

None — service module, not router.

**Key interfaces**

```python
# backend/app/services/study_preflight.py
"""Create-time preflight overlap probe for POST /api/v1/studies.

Single bounded ids-existence probe against the study's target index to detect
"all trials will score 0" failure modes (re-indexed corpus, rotated index,
stale judgments) before any orchestrator budget is spent. Per spec §1.

The probe runs after Tier 1's target-mismatch check (PR #184) and before the
study row is inserted. On insufficient overlap → 422 INSUFFICIENT_JUDGMENT_OVERLAP
at the handler. On any of the 5 documented adapter exceptions → WARN log +
return None → handler falls through (per FR-4 / Q2 → A).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.adapters.protocol import NativeQuery
from backend.app.db import repo
from backend.app.db.models import Cluster
from backend.app.services.cluster import ClusterUnreachable, acquire_adapter
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

MIN_OVERLAP: int = 3
"""Minimum overlap to allow study creation (cap-aware: see handler in studies.py)."""

PROBE_TIMEOUT_S: float = 2.0
"""Per-adapter-call timeout passed to ``search_batch``. Outer asyncio.wait_for
uses ``PROBE_TIMEOUT_S + 1.0`` as the wall-clock guard."""

MAX_PROBED_DOCS: int = 200
"""Max doc_ids shipped in the ids-query body. Protects against degenerate
judgment lists with thousands of judgments per qid."""


@dataclass(frozen=True)
class OverlapProbeResult:
    """Result of a successful probe (including the empty-judgments path).

    ``representative_query_id is None`` ONLY on the empty-judgments path
    (no qid in the query_set has any judgments). On that path the other three
    fields are 0.
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
        OverlapProbeResult: probe completed (or the empty-judgments path was
            taken — see ``representative_query_id is None``).
        None: probe skipped due to one of the 5 fall-through exceptions
            (per FR-4). The probe logged the reason at WARNING level.

    The caller (POST /api/v1/studies handler) interprets the result via the
    cap-aware threshold formula: reject 422 if
    ``result.overlap_size < min(MIN_OVERLAP, max(result.judged_doc_count, 1))``.
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

    # 2) Capture total judged-doc count BEFORE applying the cap.
    judged_doc_count = await repo.count_judgments_for_list_and_query(
        db,
        judgment_list_id,
        representative_qid,
    )

    # 3) Fetch up to MAX_PROBED_DOCS judged doc_ids deterministically.
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
        body={"query": {"ids": {"values": judged_doc_ids}}, "size": probed_doc_count},
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
    except (asyncio.TimeoutError, QueryTimeoutError):
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
```

**Pydantic schemas**

None — `OverlapProbeResult` is a frozen dataclass (not a wire model).

**Tasks**

1. Create `backend/app/services/study_preflight.py` with the full module body shown above (imports, constants, dataclass, function).
2. Verify imports resolve: `acquire_adapter` from `backend.app.services.cluster`, `ClusterUnreachable` from same module, `ClusterUnreachableError`/`InvalidQueryDSLError`/`QueryTimeoutError` from `backend.app.adapters.errors`, `NativeQuery` from `backend.app.adapters.protocol`, `Cluster` from `backend.app.db.models`, `repo` from `backend.app.db`, structlog at module top.
3. Verify `acquire_adapter` is exported from `backend.app.services.cluster` `__all__` (verified at `cluster.py:294-307` — yes).
4. Use `structlog.get_logger(__name__)` per convention.

**Definition of Done**

- [ ] Module exists at `backend/app/services/study_preflight.py` with the three module-level constants, `OverlapProbeResult` dataclass, and `probe_judgment_overlap` coroutine.
- [ ] Unit test in `backend/tests/unit/services/test_study_preflight.py` covering the happy path with mocked adapter returning 3 ScoredHits → `OverlapProbeResult.overlap_size == 3`.
- [ ] Unit test for the empty-judgments path: `find_first_judged_query` mocked to return `None` → returns `OverlapProbeResult(0, 0, 0, None)` + emits the `studies.preflight.overlap_probe.empty` INFO log. Adapter is NOT invoked (assert via mock).
- [ ] Unit test for the unreachable path: adapter raises `ClusterUnreachableError` → returns `None` + emits `studies.preflight.overlap_probe.skipped` WARN log with `reason="unreachable"`.
- [ ] `make lint` + `make typecheck` green.

---

### Story 1.3 — POST /studies handler integration + api-conventions.md + error envelope

**Outcome:** `POST /api/v1/studies` invokes `probe_judgment_overlap(...)` after the Tier 1 `JUDGMENT_TARGET_MISMATCH` check and before the config-serialize block. On insufficient overlap (cap-aware threshold) returns 422 `INSUFFICIENT_JUDGMENT_OVERLAP`. On `None` (probe skipped) falls through silently. `api-conventions.md` carries the new error code row.

**Traces to:** FR-1 (probe runs in handler, ordering), FR-3 (cap-aware threshold + error message), FR-5 (api-conventions.md row).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Add import for `probe_judgment_overlap` + `MIN_OVERLAP` from `backend.app.services.study_preflight`. Insert probe call between the existing `JUDGMENT_TARGET_MISMATCH` block (lines 271-283) and the config-serialize block (line 286). On `result is not None and result.overlap_size < required`, raise `_err(422, "INSUFFICIENT_JUDGMENT_OVERLAP", <message>, False)`. `required = min(MIN_OVERLAP, max(result.judged_doc_count, 1))`. No surrounding try/except — the probe function handles its own exceptions per FR-4. |
| `backend/tests/contract/test_studies_api_contract.py` | Add `test_studies_router_declares_insufficient_judgment_overlap()` source-presence test — asserts the literal `"INSUFFICIENT_JUDGMENT_OVERLAP"` appears in `studies.py` AND its source position is strictly AFTER `"JUDGMENT_TARGET_MISMATCH"` AND strictly BEFORE the line `config_payload = body.config.model_dump`. Mirrors the existing FR-1b/FR-1 ordering lock at lines 182-213. |
| `docs/01_architecture/api-conventions.md` | Add one new row to the studies-endpoint error-code table (after the `JUDGMENT_TARGET_MISMATCH` row at line 79): `INSUFFICIENT_JUDGMENT_OVERLAP` (422, retryable=false) with the recovery copy from spec §7.5. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | `CreateStudyRequest` (unchanged shape from `schemas.py:589`) | `201` `StudyDetail` (unchanged) | **`INSUFFICIENT_JUDGMENT_OVERLAP` (422 — new)**, plus existing: `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `INVALID_SEARCH_SPACE` (400), `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400), `VALIDATION_ERROR` (422), `JUDGMENT_CLUSTER_MISMATCH` (422 from Tier 1), `JUDGMENT_TARGET_MISMATCH` (422 from Tier 1). |

**Pydantic schemas**

No new schemas. The 422 uses the canonical `_err(...)` envelope; no new request/response models.

**Key interfaces**

No new top-level functions. Inline integration in the existing `create_study` handler:

```python
# backend/app/api/v1/studies.py — between the existing JUDGMENT_TARGET_MISMATCH
# block (lines 271-283) and the config-serialize block (line 286).

# 3c. Preflight overlap probe (feat_study_preflight_overlap_probe FR-1).
# Single ids-existence search against the study's target. On <required overlap,
# reject 422 INSUFFICIENT_JUDGMENT_OVERLAP. On probe-skip (cluster unreachable,
# timeout, invalid DSL), fall through silently — the probe function already
# emitted a WARN log per FR-4.
probe_result = await probe_judgment_overlap(
    db,
    cluster,
    judgment_list_id=body.judgment_list_id,
    query_set_id=body.query_set_id,
    target=body.target,
)
if probe_result is not None:
    required = min(MIN_OVERLAP, max(probe_result.judged_doc_count, 1))
    if probe_result.overlap_size < required:
        raise _err(
            422,
            "INSUFFICIENT_JUDGMENT_OVERLAP",
            (
                f"judgment_list {judgment_list.name!r}: representative "
                f"query_id={probe_result.representative_query_id!r} has "
                f"{probe_result.overlap_size} of {probe_result.probed_doc_count} "
                f"probed doc IDs present in cluster {cluster.name!r} "
                f"target {body.target!r} "
                f"(judged_doc_count={probe_result.judged_doc_count}). "
                f"This is a strong signal of corpus/judgment mismatch "
                f"(e.g., the target index was re-indexed or rotated since "
                f"the judgments were authored) — pytrec_eval will likely "
                f"score 0 on every trial. Regenerate judgments against the "
                f"current index, or rebuild the index from the snapshot "
                f"the judgments were authored on."
            ),
            False,
        )
```

**Tasks**

1. Add the import to `backend/app/api/v1/studies.py`:
   ```python
   from backend.app.services.study_preflight import MIN_OVERLAP, probe_judgment_overlap
   ```
   Place it next to the existing `from backend.app.services import study_state` line at studies.py:65.
2. Insert the probe-call block between lines 283 and 286 of `studies.py`. Exact JSX shown in "Key interfaces" above.
3. Add `INSUFFICIENT_JUDGMENT_OVERLAP` row to `docs/01_architecture/api-conventions.md` after the `JUDGMENT_TARGET_MISMATCH` row at line 79. Use the description from spec §7.5.
4. Add the new source-presence test to `backend/tests/contract/test_studies_api_contract.py`. The test asserts BOTH the probe call site AND the error-code literal sit between the target check and the config-serialize line (so a refactor that moves either the call or the raise still trips CI):
   ```python
   def test_studies_router_declares_insufficient_judgment_overlap() -> None:
       """FR-1 + FR-5 — source-presence guard that the new code appears
       in studies.py AFTER JUDGMENT_TARGET_MISMATCH AND BEFORE the
       config-serialize line. Locks both the call site and the literal.
       """
       from pathlib import Path
       source = Path("backend/app/api/v1/studies.py").read_text(encoding="utf-8")
       assert '"INSUFFICIENT_JUDGMENT_OVERLAP"' in source
       assert "probe_judgment_overlap(" in source
       target_pos = source.index('"JUDGMENT_TARGET_MISMATCH"')
       probe_pos = source.index("probe_result = await probe_judgment_overlap(")
       overlap_pos = source.index('"INSUFFICIENT_JUDGMENT_OVERLAP"')
       config_pos = source.index("config_payload = body.config.model_dump")
       assert target_pos < probe_pos < overlap_pos < config_pos, (
           f"Ordering: JUDGMENT_TARGET_MISMATCH ({target_pos}) < "
           f"probe call ({probe_pos}) < INSUFFICIENT_JUDGMENT_OVERLAP literal "
           f"({overlap_pos}) < config_payload assignment ({config_pos}) — "
           f"got ordering violation."
       )
   ```

**Definition of Done**

- [ ] `POST /api/v1/studies` with insufficient overlap returns 422 `INSUFFICIENT_JUDGMENT_OVERLAP` AND no `studies` row is inserted AND no Arq job is enqueued (integration AC-1; assertion uses `SELECT COUNT(*) FROM studies` before/after + Arq spy).
- [ ] Boundary-inclusive case (overlap == MIN_OVERLAP=3) returns 201 (integration AC-3).
- [ ] Boundary-exclusive case (overlap == 2) returns 422 when judged_doc_count >= 3 (integration AC-4).
- [ ] Cap-aware case (judged_doc_count == 2, overlap == 2) returns 201 (required = min(3, 2) = 2). Add as AC-4b.
- [ ] Empty-judgments path: judgment_list has 0 rows for any qid in the query_set → 422 + `studies.preflight.overlap_probe.empty` INFO log (integration AC-9).
- [ ] FK-404 paths (judgment_list_id not in DB, etc.) return 404 with their specific code; the probe is NOT called (integration AC-5; mock `probe_judgment_overlap` and assert it was not awaited).
- [ ] Tier 1 ordering: target mismatch returns `JUDGMENT_TARGET_MISMATCH` (NOT `INSUFFICIENT_JUDGMENT_OVERLAP`); the probe is NOT called (integration AC-6).
- [ ] Source-presence ordering test passes: target check → overlap check → config-serialize.
- [ ] `GET /api/v1/studies/{id}` for a pre-existing fixture row with insufficient overlap returns 200 (integration AC-12 read-path negative).
- [ ] `api-conventions.md` carries the new row in firing order.
- [ ] `make lint` + `make typecheck` + `make test-unit` + `make test-integration` + `make test-contract` all green.

---

## UI Guidance

**No UI work in this feature.** The create-study modal's existing target+cluster filter (shipped by Tier 1 PR #184) already prevents the most common path to this 422. Chat-agent and direct-API callers exercise the 422 path via the existing 422-handler in the orchestrator (no new client branching needed).

Per the spec §11 information-architecture section: no new routes, no new tabs, no new components.

**No legacy behavior parity table** — no user-facing component >100 LOC is being deleted or migrated in this plan. The feature is purely backend.

**No client-side persistence** — no localStorage/sessionStorage.

**No enumerated value contract** — the new error code is a backend literal, not a frontend allowlist.

---

## 3) Testing workstream

### 3.1 Unit tests

- **Location:** `backend/tests/unit/services/test_study_preflight.py` (new file; sibling to the existing `test_agent_judgments_dispatch.py`, `test_dispatch_run_query.py`, `test_study_state.py` at `backend/tests/unit/services/`).
- **Scope:** `probe_judgment_overlap` orchestration with mocked adapter and mocked repo functions.
- **Tasks:**
  - [ ] `test_probe_returns_overlap_size_on_happy_path()` — mocked adapter returns `{"overlap_probe": [ScoredHit(doc_id="d1", score=1.0), ScoredHit(doc_id="d2", score=1.0), ScoredHit(doc_id="d3", score=1.0)]}`; mocked repos return `representative_qid="q1"`, `judged_doc_count=5`, `judged_doc_ids=["d1","d2","d3","d4","d5"]`. Assert `OverlapProbeResult(overlap_size=3, probed_doc_count=5, judged_doc_count=5, representative_query_id="q1")`. (Covers the AC-11 dict-key-unpacking semantic — `result.get("overlap_probe", [])` resolves correctly to the per-query hits list.)
  - [ ] `test_probe_handles_unexpected_dict_key()` — mocked adapter returns `{"different_key": [...]}` (defensive sanity case). Assert `OverlapProbeResult.overlap_size == 0` because `result.get("overlap_probe", [])` defaults to `[]`. Locks the `.get()` fallback so a future refactor that uses `result["overlap_probe"]` (KeyError) is caught by this test.
  - [ ] `test_probe_returns_empty_result_when_no_judgments()` — mock `find_first_judged_query` to return `None`. Assert `OverlapProbeResult(0, 0, 0, None)` returned + `studies.preflight.overlap_probe.empty` INFO log emitted (via `RecordingLogger` per `_log_helpers.py`) + `acquire_adapter`/`search_batch` NOT called (assert via Mock).
  - [ ] `test_probe_returns_none_on_cluster_unreachable()` — mocked adapter raises `ClusterUnreachableError`. Assert returns `None` + WARN log with `reason="unreachable"`.
  - [ ] (Cycle-2 expansion if any added — see exception matrix in §3.2 AC-13)
- **DoD:**
  - [ ] Four unit cases pass deterministically; mock-based, no DB needed.

### 3.2 Integration tests

- **Location:** `backend/tests/integration/test_studies_api.py` (existing file; extend with new cases).
- **Scope:** DB-backed real-engine integration against the ES service-container; mocked adapter for the FR-4 exception matrix.
- **Tasks (real engine):**
  - [ ] AC-1 — `test_post_study_insufficient_overlap_returns_422()` — seeds a cluster + judgment list with 50 doc_ids that don't exist in the cluster's index. Assert 422 + `INSUFFICIENT_JUDGMENT_OVERLAP` + message contains `"0 of 50 probed"` + `"judged_doc_count=50"` + no `studies` row inserted + no Arq job enqueued.
  - [ ] AC-2 — `test_post_study_sufficient_overlap_returns_201()` — same setup but seed the cluster's index with all 50 judged doc_ids (overlap=50, ≥3). Assert 201 + `studies` row inserted + Arq enqueued.
  - [ ] AC-3 — `test_post_study_overlap_at_threshold_returns_201()` — exactly 3 judged doc_ids present in the index, judged_doc_count=5 → required=3, overlap=3 → 201 (boundary-inclusive lock).
  - [ ] AC-4 — `test_post_study_overlap_one_below_threshold_returns_422()` — judged_doc_count=5, overlap=2 → required=3, 2<3 → 422.
  - [ ] AC-4b — `test_post_study_cap_aware_threshold_allows_small_judgment_lists()` — judged_doc_count=2, overlap=2 → required=min(3, 2)=2, allow → 201. Locks the `min()` formula.
  - [ ] AC-9 — `test_post_study_empty_judgments_returns_422_with_info_log()` — judgment_list exists but has 0 judgment rows. Assert 422 + `INSUFFICIENT_JUDGMENT_OVERLAP` + INFO log `studies.preflight.overlap_probe.empty` (via `capture_logs()` per `_log_helpers.py`).
  - [ ] AC-12 — `test_get_study_does_not_validate_pre_existing_insufficient_overlap()` — seed a study row with insufficient overlap via direct DB write; assert `GET /api/v1/studies/{id}` returns 200 (read path is unaffected).
- **Tasks (adapter-call-shape via `monkeypatch` on `ElasticAdapter.search_batch`):**
  - [ ] AC-5 — `test_post_study_404_fk_path_does_not_invoke_probe()` — non-existent `judgment_list_id`. Assert 404 + `JUDGMENT_LIST_NOT_FOUND` AND `probe_judgment_overlap` was not invoked (monkeypatch a spy on the module-level reference).
  - [ ] AC-6 — `test_post_study_target_mismatch_does_not_invoke_probe()` — mismatched target. Assert 422 + `JUDGMENT_TARGET_MISMATCH` AND `probe_judgment_overlap` was not invoked.
  - [ ] AC-7 — `test_post_study_cluster_unreachable_during_probe_returns_201_with_warn()` — `monkeypatch` `ElasticAdapter.search_batch` to raise `ClusterUnreachableError`. Assert 201 + `studies` row inserted + Arq enqueued + WARN log with `reason="unreachable"` (via `capture_logs()`).
  - [ ] AC-8 — `test_post_study_probe_timeout_returns_201_with_warn()` — `monkeypatch` `search_batch` to `await asyncio.sleep(PROBE_TIMEOUT_S + 2.0)`. Assert 201 + WARN log with `reason="timeout"`.
  - [ ] AC-10 — `test_post_study_max_probed_docs_cap_honored()` — seed 500 judgments for the rep qid; index contains only `doc_499`, `doc_500` (lex-last two). Assert 422 (overlap=0; cap fetches `doc_001..doc_200`) AND `adapter.search_batch` was called with `len(NativeQuery.body["query"]["ids"]["values"]) == 200` (not 500) AND error message contains `"0 of 200 probed"` + `"judged_doc_count=500"`.
  - [ ] AC-11 — `test_post_study_probe_call_shape_locked()` — spy on `search_batch` and assert it was called with `target=<study.target>`, exactly one `NativeQuery` with `query_id="overlap_probe"`, `body=={"query":{"ids":{"values": ...}}, "size": 3}` (for judged_doc_ids of length 3), `top_k=3`, `strict_errors=True`, `timeout=PROBE_TIMEOUT_S`. **Observability lock for dict-key unpacking:** seed `judged_doc_count=3` and have the spy return `{"overlap_probe": [ScoredHit(doc_id="d1", score=1.0), ScoredHit(doc_id="d2", score=1.0)]}` (2 hits). Required = `min(3, max(3, 1)) = 3`; overlap = 2 < 3 → 422. Assert the response message contains `"2 of 3 probed"` (not `"0 of 3 probed"`). This observably proves the probe read hits from the `"overlap_probe"` key — if the handler/probe used the wrong key or fell back to `[]` defensively, the message would say `"0 of 3"`. The unit-test layer (§3.1 `test_probe_handles_unexpected_dict_key`) locks the `.get()` fallback semantics; this integration case locks the happy-key read.
  - [ ] AC-13 — `test_post_study_fr4_exception_matrix()` — `pytest.mark.parametrize` over `[(ClusterUnreachable, "unreachable"), (ClusterUnreachableError, "unreachable"), (asyncio.TimeoutError, "timeout"), (QueryTimeoutError, "timeout"), (InvalidQueryDSLError, "invalid_query_dsl")]`. For each, monkeypatch the adapter to raise that exception; assert 201 + `studies` insert + Arq enqueue + WARN log with the matching `reason` field. **Monkeypatch paths:** the `ClusterUnreachable` (service-layer) case must patch the symbol bound inside the probe module: `monkeypatch.setattr("backend.app.services.study_preflight.acquire_adapter", <fake_async_cm>)` where `<fake_async_cm>` is an async context-manager-shaped callable whose `__aenter__` raises `ClusterUnreachable`. The four adapter-layer cases (`ClusterUnreachableError`, `QueryTimeoutError`, `InvalidQueryDSLError`, `asyncio.TimeoutError`) patch `backend.app.adapters.elastic.ElasticAdapter.search_batch` directly (the real `acquire_adapter` constructs an `ElasticAdapter` and the patched `search_batch` raises on call). The `asyncio.TimeoutError` case uses `monkeypatch.setattr(..., async lambda *args, **kw: await asyncio.sleep(PROBE_TIMEOUT_S + 2.0))` — the outer `asyncio.wait_for(PROBE_TIMEOUT_S + 1.0)` fires before the sleep returns.
- **DoD:**
  - [ ] All real-engine cases pass against the ES service container.
  - [ ] All adapter-call-shape cases pass against the mocked adapter.
  - [ ] WARN logs asserted via the existing `_log_helpers.py` helpers (`capture_logs()` + `find_log_events()` + `assert_log_level()`).

### 3.3 Contract tests

- **Location:** `backend/tests/contract/`
- **Scope:** Envelope shape + source-presence ordering lock + envelope literal in the route.
- **Tasks:**
  - [ ] In `test_studies_error_codes.py`: add `test_insufficient_judgment_overlap_envelope_shape()` — set up valid FK rows that pass all earlier checks (cluster + template + query_set + judgment_list with matching cluster_id + target + query_set_id), then `monkeypatch` `backend.app.api.v1.studies.probe_judgment_overlap` (the symbol the handler imports) to return `OverlapProbeResult(overlap_size=0, probed_doc_count=3, judged_doc_count=3, representative_query_id="01990000-0000-7000-8000-000000000099")`. POST to `/api/v1/studies` and assert the response body matches the canonical envelope shape: `detail.error_code == "INSUFFICIENT_JUDGMENT_OVERLAP"`, `detail.retryable == False`, `detail.message` contains `"0 of 3 probed"` AND `"judged_doc_count=3"`. Hermetic — no real cluster involved.
  - [ ] In `test_studies_api_contract.py`: add `test_studies_router_declares_insufficient_judgment_overlap()` — source-presence ordering lock per Story 1.3 Task #4. Pattern mirrors the existing `test_studies_router_declares_judgment_mismatch_error_codes()` at lines 182-213.
- **DoD:**
  - [ ] The new code's envelope is locked at the contract layer.
  - [ ] The handler's source-position ordering is locked against refactor.

### 3.4 E2E tests

- **Location:** `ui/tests/e2e/`
- **Scope:** None new. The create-study modal's target+cluster filter prevents the modal path to this 422 in practice; chat-agent path is exercised by the integration tests above.
- **Tasks:**
  - [ ] Audit: run `grep -rn "judgment.*list\|judgmentList" ui/tests/e2e/` and confirm no existing E2E seed creates a study where the cluster's seeded index doesn't contain the judged doc IDs. The existing seed helper at [`ui/tests/e2e/helpers/seed.ts:400-413`](../../../../ui/tests/e2e/helpers/seed.ts#L400-L413) seeds judgments with doc IDs that ARE present in the cluster's `products` index (verified — same pattern Tier 1 confirmed).
- **DoD:**
  - [ ] Existing Playwright suite still passes (no new spec).

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | Existing happy-path test `test_post_study_happy_path_excludes_unset_config_keys` at line 96; existing `test_post_study_judgment_query_set_mismatch_returns_422` at line 153; existing Tier 1 tests at lines 207-430 | (existing) | **Audit each setup fixture** — does the seeded judgment list have any doc_ids present in the cluster's seeded index? The happy-path test currently passes through Tier 1's checks and reaches the new probe. If the seed `target='stub-index'` (per line 73 mention in Tier 1 spec) is empty of any docs, the new probe will return overlap=0 and the existing happy-path test will break. **Action:** read the existing setup fixtures in `test_studies_api.py` (and `conftest.py`) and either (a) seed the cluster's index with the judged doc_ids before the POST, or (b) seed the test cluster's `ElasticAdapter` to be unreachable so the probe falls through (returns None, study creates 201). Prefer (a) — exercises the real-engine happy path. |
| `backend/tests/integration/conftest.py` | Existing fixtures that build `Study` rows + seed `Judgment` rows | (existing) | If a fixture seeds judgments without seeding matching index docs, extend it. The cleanest seam: a new conftest fixture `seed_index_docs_matching_judgments(cluster, target, judgments)` that bulk-indexes the doc IDs into the cluster's test index. Reuse across the new AC-1..AC-12 tests. |
| `ui/tests/e2e/helpers/seed.ts` | Existing E2E seed | (existing — line 400-413 per Tier 1 audit) | No change. The seed already creates judgments with doc IDs matching the seeded index (`products`); the existing E2E happy path passes the new probe. |
| `backend/tests/contract/test_openapi_surface.py` | OpenAPI snapshot | (existing) | No change — no schema changes; no new OpenAPI surface. |
| `backend/tests/integration/test_judgments_api.py` | Existing tests | (existing) | No change — the probe is invoked on study POST only; judgments endpoints unaffected. |

### 3.6 Migration verification

N/A — no schema changes. (Alembic head stays at `0015_trials_per_query_metrics`.)

### 3.7 CI gates

- [ ] `make lint` (ruff)
- [ ] `make typecheck` (mypy --strict)
- [ ] `make test-unit` (incl. the 4 new unit cases in `unit/services/test_study_preflight.py`)
- [ ] `make test-integration` (incl. 14 new integration test functions / ~18 parametrized cases — 7 real-engine + 7 mocked; AC-13 alone contributes 5 parametrized sub-cases)
- [ ] `make test-contract` (incl. 2 new contract cases)
- [ ] Existing Playwright suite via `make test-e2e` (if available) or `cd ui && pnpm e2e` — no new spec, must still pass.

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — update to:
  - Move feature into the "Most recent meaningful changes" section after PR merge.
  - Note: no Alembic head change (stays at `0015_trials_per_query_metrics`).
- **`architecture.md`** — no change. Pure service-layer + handler addition; the new `backend/app/services/study_preflight.py` is a new module but doesn't introduce a new top-level layer.
- **`CLAUDE.md`** — no change. No new convention, env var, or absolute rule.

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `api-conventions.md` — add the `INSUFFICIENT_JUDGMENT_OVERLAP` row to the studies-endpoint error-code table (after `JUDGMENT_TARGET_MISMATCH` at line 79). Assigned to Story 1.3.

### 4.2 Product docs (`docs/02_product`)

- This feature is the canonical doc. No other product doc changes.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] Extend `docs/03_runbooks/study-lifecycle-debugging.md` with one paragraph on `INSUFFICIENT_JUDGMENT_OVERLAP` recovery (per spec §15). Content: how to inspect the WARN log fields when the probe is skipped, how to re-run the probe by re-POSTing, and the two recovery paths (regenerate judgments OR rebuild the index). Assigned to Story 1.3.

### 4.4 Security docs (`docs/04_security`)

- No change — no new attack surface, no new secret. The probe is read-only; uses the existing `acquire_adapter` credentials path.

### 4.5 Quality docs (`docs/05_quality`)

- No change — existing test layers cover the feature.

**Documentation DoD**

- [ ] `state.md` reflects the merged PR.
- [ ] `api-conventions.md` carries the new error-code row in firing order (after `JUDGMENT_TARGET_MISMATCH`).
- [ ] `docs/03_runbooks/study-lifecycle-debugging.md` extended with the `INSUFFICIENT_JUDGMENT_OVERLAP` recovery paragraph per §4.3 task.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None. The feature is purely additive — 1 new service module + 2 new repo functions + 1 handler insertion + 1 doc row. No refactor opportunity worth the scope expansion.

### 5.2 Planned refactor tasks

- None.

### 5.3 Refactor guardrails

- N/A.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Story 1.1 repo functions | Story 1.2 service helper | In-PR (same branch) | Story 1.2 cannot compose its probe without `find_first_judged_query` + `list_doc_ids_for_list_and_query`. Order Stories 1.1 → 1.2 within the branch. |
| Story 1.2 service helper | Story 1.3 handler integration | In-PR (same branch) | Story 1.3 cannot call `probe_judgment_overlap` without the module existing. Order Stories 1.2 → 1.3 within the branch. |
| Tier 1 (`feat_study_target_judgment_mismatch_guard`) | All stories | **Shipped (PR #184, merged 2026-05-21)** | The new probe runs AFTER Tier 1's `JUDGMENT_TARGET_MISMATCH` block; without Tier 1, the cluster + target preconditions wouldn't hold for the probe's `acquire_adapter(cluster)` + `target=body.target` call. Verified satisfied via state.md. |
| GPT-5.5 cross-model review on the implementation | Final PR review | Configured per `.env` | If unavailable, fall back to Opus-only review with explicit log entry per `impl-execute` skill protocol. |
| Existing `_log_helpers.py` (from PR #114) | Unit + integration log assertions | Shipped (`backend/tests/_log_helpers.py`) | None — file exists and is documented. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing `test_studies_api.py` integration fixtures seed judgment lists with doc_ids that don't exist in the seeded ES index, so the existing happy-path tests break when the new probe runs | M | M | Audit listed in §3.5. Likely fix: extend the existing setup fixture to bulk-index the judged doc_ids before the POST, OR (if the fixture's cluster fixture is intentionally minimal) override to return 0 doc count and gate the existing test on a probe-skip path. Prefer the bulk-index fix — exercises the real path. |
| Probe timeout fires under heavy ES load in CI | L | L | `PROBE_TIMEOUT_S = 2.0` + outer `asyncio.wait_for(3.0)` is generous for the CI's local Docker ES. AC-8 explicitly tests the timeout-skip path; CI timeout-induced flake would land on the skip-path, study still creates 201. |
| `acquire_adapter` raises a NEW exception class not in FR-4's list (e.g., adapter author adds a `CertificateExpiredError` in a future release) | L | M | The probe catches 5 explicit exception classes per FR-4. Any other exception propagates up and the POST returns 500 INTERNAL_ERROR — operator-visible failure that is the correct signal to widen FR-4. AC-13 parametrizes the matrix to lock the current 5 classes. |
| GPT-5.5 cycle-1 re-surfaces findings already resolved in the spec | L | L | The plan carries the spec's locked decisions (cap-aware threshold formula, dataclass return type, `strict_errors=True`, ids-existence probe shape, etc.) — cycle-1 should converge fast. |
| Integration test for cluster-unreachable accidentally exercises the real adapter (instead of the mock) and produces a false 503 | L | L | The AC-7/AC-13 tests use `monkeypatch` on `ElasticAdapter.search_batch` (or `acquire_adapter` for the service-layer `ClusterUnreachable`). The monkeypatch is targeted at the symbol the probe imports. Use `monkeypatch.setattr("backend.app.adapters.elastic.ElasticAdapter.search_batch", ...)`. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Re-indexed corpus, all doc_ids changed | Operator runs `_reindex` with new doc IDs while keeping the index name | Probe returns overlap=0 → 422 `INSUFFICIENT_JUDGMENT_OVERLAP` | Manual — operator regenerates judgments OR restores from snapshot |
| Judgments authored against a rotated index | Index was deleted and recreated between judgment generation and study creation | Same as above — probe catches at create time | Manual — same recovery |
| Cluster offline at probe time | Network blip, ES restart, credentials file deleted | Probe catches `ClusterUnreachable*` → WARN log + return None → study creates (201) | Orchestrator's per-trial failure handling surfaces the issue at trial 1 |
| Probe wall-clock exceeds 2.0s | Slow ES, large `ids` query (200 doc IDs is a small payload but pathological cluster) | Probe catches `asyncio.TimeoutError` → WARN log + return None → study creates | Same — orchestrator surfaces |
| Adapter rejects ids body as malformed | Adapter defect or ES version skew | Probe catches `InvalidQueryDSLError` → WARN log + return None → study creates | Manual — investigate adapter defect from WARN log |
| Empty judgment list (zero judgment rows total) | Operator created the list but worker hasn't written rows yet, OR imported an empty CSV | `find_first_judged_query` returns `None` → `OverlapProbeResult(0,0,0,None)` → required=1, overlap=0 → 422 + INFO log | Manual — wait for worker OR re-import |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — repo functions (~30 LOC of production code; no dedicated repo-layer tests — coverage flows through Story 1.2 unit tests and Story 1.3 integration tests, per Story 1.1 DoD). Backend types must exist before Story 1.2 can compose them.
2. **Story 1.2** — service helper (~80 LOC + 4 unit test cases). Depends on Story 1.1.
3. **Story 1.3** — handler integration + api-conventions.md + runbook paragraph + 14 integration test functions (18 parametrized cases) + 2 contract cases. Depends on Story 1.2.

### Parallelization opportunities

- Stories 1.1 → 1.2 → 1.3 are sequential within the branch. No parallelizable work.
- The audit task in §3.5 (existing integration fixture compatibility) can run in parallel with Story 1.1 to surface fixture-fix scope early.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single — merge to `main` triggers nothing for MVP1 (no remote staging). Operators pull on next `make up`.
- **Feature flag strategy:** None. Validation is a hard-gate at the API boundary; staged rollout would mean half the operators get the 422 and half don't.
- **Migration/cutover steps:** None — no schema changes.
- **Reconciliation/repair strategy:** None — no external systems involved.
- **Backwards compatibility:** Pre-existing queued/running studies with insufficient overlap are NOT retroactively rejected (forward-only fix, matches Tier 1's precedent).

---

## 9) Execution tracker

### Current sprint

- [x] Story 1.1 — Repo functions
- [x] Story 1.2 — Service helper
- [x] Story 1.3 — Handler integration + api-conventions.md row + contract tests

### Blocked items

- None.

### Done this sprint

- [x] Story 1.1 (commit `2d1727e`) — `find_first_judged_query` + `list_doc_ids_for_list_and_query` + `__init__.py` exports
- [x] Story 1.2 (commit `2d1727e`) — `backend/app/services/study_preflight.py` (`OverlapProbeResult` + `probe_judgment_overlap` + module-level constants)
- [x] Story 1.3 (commit `2d1727e`) — `studies.py` handler integration + `api-conventions.md` row + `study-lifecycle-debugging.md` paragraph + source-presence contract test
- [x] Tests (commits `2d1727e`, `0602927`) — 4 unit + 14 integration test functions (18 parametrized cases) + 2 contract

---

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created/modified match story scope (New files / Modified files tables).
- [ ] Endpoint contract implemented exactly as documented (status codes + envelope shapes — Story 1.3).
- [ ] Key interfaces implemented with compatible signatures (Story 1.1 + 1.2).
- [ ] Required tests added/updated for all applicable layers.
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (subset for touched endpoints)
    - [ ] `make test-contract`
- [ ] Migration round-trip evidence: N/A (no schema changes).
- [ ] `docs/01_architecture/api-conventions.md` updated when Story 1.3 lands.

---

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:**
   - Spec §7.1 lists 1 endpoint (POST /studies).
   - Plan covers it (Story 1.3). ✅ Match.

2. **Spec ↔ plan error code coverage:**
   - Spec §7.5 lists 1 new code (`INSUFFICIENT_JUDGMENT_OVERLAP`).
   - Plan §3.3 has 1 envelope-shape contract test + 1 source-presence ordering contract test. ✅ Match.

3. **Spec ↔ plan FR coverage:**
   - FR-1: Story 1.3 ✅
   - FR-2: Story 1.2 ✅
   - FR-3: Story 1.3 ✅
   - FR-4: Story 1.2 ✅
   - FR-5: Story 1.3 ✅
   - All 5 FRs covered.

4. **Story internal consistency:**
   - Story 1.1: Modified files exist (verified: `backend/app/db/repo/query.py`, `backend/app/db/repo/judgment.py`, `backend/app/db/repo/__init__.py`). Key interfaces use `AsyncSession` first arg per convention. ✅
   - Story 1.2: New module path matches the `backend/app/services/<name>.py` convention. All imports resolve against verified module paths. ✅
   - Story 1.3: Modified files exist (verified: `studies.py`, `test_studies_api_contract.py`, `api-conventions.md`). The `_err(...)` helper at studies.py:74 matches the envelope shape. ✅
   - No file ownership conflicts across stories.

5. **Test file count and assignment:**
   - Unit: 4 cases in 1 new file (`unit/services/test_study_preflight.py`). All assigned to Story 1.2.
   - Integration: 14 test functions across 1 existing file (`integration/test_studies_api.py`) — 7 real-engine (AC-1, AC-2, AC-3, AC-4, AC-4b, AC-9, AC-12) + 7 mocked (AC-5, AC-6, AC-7, AC-8, AC-10, AC-11, AC-13). AC-13 alone is `pytest.mark.parametrize` over 5 exception tuples (5 sub-cases). All assigned to Story 1.3.
   - Contract: 2 cases across 2 existing files (`contract/test_studies_error_codes.py`, `contract/test_studies_api_contract.py`). All assigned to Story 1.3.
   - No orphaned test files.

6. **Gate arithmetic:** Single epic, no sub-phase gates beyond per-story DoD. N/A.

7. **Open questions resolved:**
   - Spec §19 lists no open questions. All decisions locked. ✅

8. **Plan ↔ codebase verification:**
   - `backend/app/api/v1/studies.py:271-283` `JUDGMENT_TARGET_MISMATCH` block verified — handler insertion point at line 283/286 is correct. ✅
   - `backend/app/api/v1/studies.py:74-78` `_err(...)` helper verified. ✅
   - `backend/app/services/cluster.py:227-253` `acquire_adapter` async context manager verified. ✅
   - `backend/app/services/cluster.py:294-307` exports `acquire_adapter` in `__all__`. ✅
   - `backend/app/adapters/protocol.py:74-80` `NativeQuery` Pydantic model verified (has `query_id: str` + `body: dict[str, Any]`). ✅
   - `backend/app/adapters/protocol.py:174-196` `search_batch` returns `dict[str, list[ScoredHit]]` verified. ✅
   - `backend/app/adapters/errors.py` exports `ClusterUnreachableError`, `InvalidQueryDSLError`, `QueryTimeoutError` verified. ✅
   - `backend/app/db/models/judgment.py:49-54` `UniqueConstraint("judgment_list_id","query_id","doc_id")` verified — `SELECT doc_id` is implicitly distinct per (list, qid). ✅
   - `backend/app/db/models/judgment.py:55` index `judgments_list_query_idx` on `(judgment_list_id, query_id)` verified. ✅
   - `backend/app/db/repo/judgment.py:228-245` `count_judgments_for_list_and_query` exists; the new `list_doc_ids_for_list_and_query` sibling is grouped at the same location. ✅
   - `backend/app/db/repo/__init__.py:43-56` judgment-repo import block verified — append site for new function. ✅
   - `backend/app/db/repo/__init__.py:86-95` query-repo import block verified — append site for new function. ✅
   - `backend/tests/_log_helpers.py` exists (from PR #114) — exports `assert_log_level`, `find_log_events`, `RecordingLogger`. ✅
   - `backend/tests/contract/test_studies_api_contract.py:182-213` existing source-presence ordering test verified — new test follows the same pattern. ✅
   - `backend/tests/unit/services/` subdir exists with siblings `test_agent_judgments_dispatch.py`, `test_dispatch_run_query.py`, `test_study_state.py`. ✅
   - `backend/tests/integration/test_studies_api.py` exists with 19 existing test functions (verified at lines 96, 125, 153, 207, 237, 305, 364, 398, 431, 460, 469, 493, 503, 517, 538, 559, 580, 601). ✅
   - `docs/01_architecture/api-conventions.md:79` `JUDGMENT_TARGET_MISMATCH` row verified — new row inserts after. ✅
   - Alembic head: `migrations/versions/0015_trials_per_query_metrics.py` confirmed as latest. ✅

9. **Infrastructure path verification:**
   - Migration directory: N/A (no migration).
   - Router registration: N/A (no new router; extending existing handler at `backend/app/api/v1/studies.py`).
   - Service module location: `backend/app/services/study_preflight.py` matches the existing `backend/app/services/<name>.py` pattern (verified by `study_state.py`, `study_confidence.py`, `cluster.py`, etc.). ✅

10. **Frontend data plumbing verification:** N/A — no frontend work.

11. **Persistence scope consistency:** N/A — no localStorage/sessionStorage.

12. **Enumerated value contract audit:** N/A — no new `<select>` allowlists. The probe's `reason` field is an internal log value, not a wire enum.

13. **Audit-event coverage audit:** N/A — pre-MVP2 (audit_log not yet active).

---

## 12) Definition of plan done

- [ ] Every FR is mapped to stories/tasks/tests/docs updates. ✅
- [ ] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD. ✅
- [ ] Test layers (unit/integration/contract) are explicitly scoped (no E2E in this plan). ✅
- [ ] Documentation updates across docs/01-05 are planned and owned. ✅
- [ ] Lean refactor scope is "none" with stated reason. ✅
- [ ] Epic gates are measurable. ✅
- [ ] Story-by-Story Verification Gate is included. ✅
- [ ] Plan consistency review (§11) performed with no unresolved findings. ✅
