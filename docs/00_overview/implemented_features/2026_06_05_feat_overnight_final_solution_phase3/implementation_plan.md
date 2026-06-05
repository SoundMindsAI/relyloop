# Implementation Plan — Overnight Final Solution Phase 3 (Proposal supersession on chain rollup)

**Date:** 2026-06-05
**Status:** Complete (PR #457, merged 2026-06-05)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Source idea:** [`idea.md`](idea.md)

---

## 0) Planning principles

- Spec traceability first — every story maps to one or more FRs from `feature_spec.md` §7.
- Hard gates between epics: backend (Epic 1+2+3) merge-green before frontend (Epic 4) begins integration.
- Conditional UPDATEs vs read-check-mutate: `bulk_mark_superseded` uses conditional UPDATE (idempotency); `reinstate_from_superseded` uses read-check-mutate (404 vs 409 distinguishability — D-17).
- Post-commit structlog (D-19): the service helper returns `(count, ids)`; emission is the caller's responsibility, after `await db.commit()` succeeds.
- The chain-traversal filter widening (FR-4) is a one-line co-requisite of FR-2 — they ship in the same PR (this one); not splittable.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (schema + 5 wire-value mirrors) | Epic 1 / Story 1.1 (backend), Epic 4 / Story 4.1 (frontend) | Migration `0023_proposals_superseded_status`; ORM CHECK + repo `Literal` + API `Literal` cascade through `regen-generated-artifacts.sh` to `ui/openapi.json` + `ui/src/lib/types.ts`. Frontend half lands with the rest of Epic 4. |
| FR-2 (service helper) | Epic 2 / Story 2.1 | New `backend/app/services/chain_rollup.py` with `mark_non_winning_chain_proposals_superseded(db, *, study_id) -> tuple[int, list[str]]` (D-19 signature). |
| FR-3 (repo helpers) | Epic 1 / Story 1.2 | New `bulk_mark_superseded` (conditional UPDATE-RETURNING) + `reinstate_from_superseded` (read-check-mutate per D-17). |
| FR-4 (chain-traversal filter widening) | Epic 2 / Story 2.2 | One-line widening at [`backend/app/db/repo/study.py:341`](../../../../backend/app/db/repo/study.py#L341). Co-requisite of FR-2 — must ship in the same PR. |
| FR-5 (`_stop` wires rollup) | Epic 2 / Story 2.3 | Append rollup call inside `_stop`'s existing transaction; emit `chain_proposals_superseded` after commit (D-19). |
| FR-6 (reinstate endpoint + `?include_superseded` flag) | Epic 3 / Story 3.1 | `POST /api/v1/proposals/{id}/reinstate` + new `?include_superseded: bool = False` query param (D-15 revised — leaves `?status=` single-value contract untouched). |
| FR-7 (telemetry) | Inline with Stories 2.1, 2.3, 3.1 | Post-commit emission (D-19). Helper returns the IDs payload; caller logs after commit. |
| FR-8 (frontend) | Epic 4 / Story 4.1 | Filter toggle, badge variant, reinstate button, two new glossary keys, `PROPOSAL_STATUS_VALUES` lock test. Lands together because they share a single regen of `ui/openapi.json` + `types.ts`. |

**Spec-plan FR coverage check:** All 8 spec FRs (FR-1 through FR-8) covered above. No FRs orphaned.

**Phase coverage:** Single-phase delivery per spec D-1. No phase deferral; no `phase*_idea.md` artifacts needed.

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Conventions (RelyLoop)

- Repo functions take `db: AsyncSession` first; use `await db.flush()` (caller commits).
- Services are async; accept `db: AsyncSession` + typed kwargs; do NOT commit (caller commits).
- Domain layer is pure (no DB, no I/O, no async). N/A here — no new domain code.
- Models use `Mapped[]` + `String(36)` UUIDs.
- Routers return typed Pydantic response models; errors use `HTTPException` via the existing [`_err()`](../../../../backend/app/api/v1/proposals.py#L79-L89) helper for the structured envelope.
- All `__init__.py` exports updated via `__all__`.
- Generated artifacts: re-run `bash scripts/regen-generated-artifacts.sh` after every wire-value or response-schema change.
- Conventional Commits + DCO `Signed-off-by:` (use `git commit -s`).

### AI Agent Execution Protocol

For every story, execute in this order:
1. Read the cited files at the cited lines first; verify they still match before writing.
2. Apply the changes in the order: migration → ORM → repo → service → API → tests.
3. Run the story's DoD verification commands (lint + typecheck + the specific test files).
4. Move to the next story only after the DoD is green locally.

---

## Epic 1 — Backend schema + repo helpers

### Story 1.1 — Migration `0023_proposals_superseded_status` + ORM CHECK + repo Literal + API Literal

**Outcome:** The five backend wire-value mirrors for `proposals.status` admit `superseded` in lockstep. DB-level CHECK + ORM-level CHECK + repo `Literal` filter + API `Literal` + generated-artifacts pipeline all agree on the five-value allowlist.

**New files:**
- `migrations/versions/0023_proposals_superseded_status.py` — Alembic migration: DROP + ADD CHECK constraint with the new value list. Reversible per CLAUDE.md Absolute Rule #5; downgrade refuses if any `superseded` rows exist (D-3 locked Q4 (a) hard-guard).

**Modified files:**
- [`backend/app/db/models/proposal.py`](../../../../backend/app/db/models/proposal.py) — extend the inline `status IN (...)` literal in `__table_args__` (line 42).
- [`backend/app/db/repo/proposal.py`](../../../../backend/app/db/repo/proposal.py) — extend `ProposalStatusFilter` Literal (line 56).
- [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) — extend `ProposalStatusWire` Literal (line 1379).

**Tasks:**
1. Write migration `0023_proposals_superseded_status.py` mirroring the [`0022_solr_engine_auth_check.py`](../../../../migrations/versions/0022_solr_engine_auth_check.py) DROP+ADD pattern. Set `revision: str = "0023"` and `down_revision: str | None = "0022"` (numeric short form — codebase convention; the descriptive slug lives in the filename).
2. `upgrade()`: `op.drop_constraint("proposals_status_check", "proposals", type_="check")` then `op.create_check_constraint("proposals_status_check", "proposals", "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded')")`.
3. `downgrade()`: hard-guard SELECT `COUNT(*) FROM proposals WHERE status='superseded'`; if non-zero, raise `RuntimeError` with the message naming the count + the recommended manual UPDATE (per spec AC-2). Then DROP + re-ADD the original 4-value constraint.
4. Verify Alembic round-trips on the test DB: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`.
5. Update the ORM CHECK literal at `backend/app/db/models/proposal.py:42` to admit `'superseded'`.
6. Update `ProposalStatusFilter` Literal at `backend/app/db/repo/proposal.py:56` to admit `"superseded"`.
7. Update `ProposalStatusWire` Literal at `backend/app/api/v1/schemas.py:1379` to admit `"superseded"`.
8. Run `bash scripts/regen-generated-artifacts.sh` and confirm `ui/openapi.json` + `ui/src/lib/types.ts` pick up the new value (the `generated-artifacts-fresh` CI job will otherwise red-light the PR).

**Definition of Done:**
- `make migrate` succeeds; `alembic downgrade -1 && alembic upgrade head` round-trips cleanly.
- AC-1 and AC-2 pass in integration: a row with `status='superseded'` can be inserted after upgrade; downgrade aborts with the documented error message when such a row exists.
- `make typecheck` passes (ORM + Literal changes compile).
- `git status` shows `ui/openapi.json` + `ui/src/lib/types.ts` updated by the regen script.

### Story 1.2 — Repo helpers `bulk_mark_superseded` + `reinstate_from_superseded`

**Outcome:** Two new repo functions: one bulk conditional-UPDATE (system-driven rollup), one read-check-mutate (operator-driven reinstate with deterministic 404/409 distinguishability).

**New files:** None.

**Modified files:**
- [`backend/app/db/repo/proposal.py`](../../../../backend/app/db/repo/proposal.py) — append the two new helpers; export both via `__all__`.
- [`backend/app/db/repo/__init__.py`](../../../../backend/app/db/repo/__init__.py) — re-export `bulk_mark_superseded`, `reinstate_from_superseded`.

**Key interfaces:**
```python
# backend/app/db/repo/proposal.py — append after `record_pr_open_failure`.

async def bulk_mark_superseded(
    db: AsyncSession,
    *,
    study_ids: list[str],
) -> list[str]:
    """Conditional UPDATE: pending → superseded for proposals whose study_id ∈ study_ids.

    Idempotent. Skips already-superseded, pr_opened, pr_merged, rejected rows.
    Returns the IDs actually transitioned (empty list on no-op). Caller commits.
    """
    if not study_ids:
        return []
    stmt = (
        update(Proposal)
        .where(Proposal.study_id.in_(study_ids), Proposal.status == "pending")
        .values(status="superseded")
        .returning(Proposal.id)
    )
    result = await db.execute(stmt)
    transitioned: list[str] = [row.id for row in result]
    if transitioned:
        await db.flush()
    return transitioned


async def reinstate_from_superseded(
    db: AsyncSession,
    *,
    proposal_id: str,
) -> Proposal:
    """Transition ``superseded → pending``. Mirrors the ``reject_proposal``
    read-check-mutate precedent (D-17) so the API can distinguish 404 (id
    unknown) from 409 (wrong status).

    Raises :class:`LookupError` if the proposal id does not exist (API
    translates to HTTP 404 ``PROPOSAL_NOT_FOUND``). Raises
    :class:`InvalidStateTransition` if the proposal is not in ``superseded``
    status (API translates to HTTP 409 ``INVALID_STATE_TRANSITION``).
    Caller commits.
    """
    row = await get_proposal(db, proposal_id)
    if row is None:
        raise LookupError(f"proposal {proposal_id!r} not found")
    if row.status != "superseded":
        raise InvalidStateTransition(proposal_id, row.status)
    row.status = "pending"
    await db.flush()
    return row
```

**Tasks:**
1. Append the two functions to `backend/app/db/repo/proposal.py` after `record_pr_open_failure` (line ~330).
2. Add both names to `backend/app/db/repo/proposal.py`'s `__all__`.
3. Add both names to `backend/app/db/repo/__init__.py`'s `from .proposal import …` block and `__all__`.
4. Write integration tests at `backend/tests/integration/db/test_proposal_supersession.py` (D-20 — Postgres-specific UPDATE RETURNING + CHECK constraint behavior; SQLite would mis-represent):
   - `test_bulk_mark_superseded_transitions_pending_only` (AC-3, AC-4).
   - `test_bulk_mark_superseded_returns_ids` (AC-3).
   - `test_bulk_mark_superseded_idempotent_on_rerun` (AC-3 idempotency).
   - `test_bulk_mark_superseded_skips_pr_opened_rejected` (AC-4).
   - `test_bulk_mark_superseded_empty_study_ids_returns_empty_list` (defensive).
   - `test_reinstate_from_superseded_happy_path` (AC-5).
   - `test_reinstate_from_superseded_raises_lookup_error_on_unknown_id` (D-17 — distinguishes 404).
   - `test_reinstate_from_superseded_raises_invalid_state_transition_on_pending` (AC-13).
   - `test_reinstate_from_superseded_raises_invalid_state_transition_on_pr_opened` (defense).

**Definition of Done:**
- All 9 new integration tests pass against the real Postgres test DB.
- `make typecheck` passes.
- `make lint` passes; `repo/__init__.py` exports the new helpers.
- AC-3, AC-4, AC-5 satisfied at the repo layer.

---

## Epic 2 — Service layer + orchestrator wiring + filter widening

### Story 2.1 — Service helper `chain_rollup.py`

**Outcome:** A new service-layer module that walks a study's chain, identifies the winner, and delegates loser supersession to the repo helper. Returns `(count, ids)` so callers can emit structlog post-commit (D-19). No commit inside the service.

**New files:**
- `backend/app/services/chain_rollup.py` — single module exposing `mark_non_winning_chain_proposals_superseded`.

**Modified files:**
- `backend/app/services/__init__.py` (if it exists) — re-export the new function. Check first; many service modules are imported directly.

**Key interfaces:**
```python
# backend/app/services/chain_rollup.py

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.domain.study.chain_summary import (
    derive_chain_stop_reason,
    select_best_link,
)


async def mark_non_winning_chain_proposals_superseded(
    db: AsyncSession,
    *,
    study_id: str,
) -> tuple[int, list[str]]:
    """Walk the chain anchored at ``study_id``, identify the winning link,
    and supersede all sibling-link ``pending`` proposals.

    Returns ``(count, ids)`` so the caller can emit ``chain_proposals_superseded``
    after their commit succeeds (D-19). Does NOT commit; caller commits.

    Early-returns ``(0, [])`` when the chain is missing, single-link, in-flight,
    or has no completed link to win.
    """
    traversal = await repo.get_chain_for_study(db, study_id)
    if traversal is None:
        return (0, [])
    if len(traversal.links) < 2:
        return (0, [])
    stop_reason = derive_chain_stop_reason(traversal.links, traversal.anchor_trials)
    if stop_reason == "in_flight":
        return (0, [])
    best_link_id = select_best_link(traversal.links)
    if best_link_id is None:
        return (0, [])
    loser_ids = [link.id for link in traversal.links if link.id != best_link_id]
    transitioned = await repo.bulk_mark_superseded(db, study_ids=loser_ids)
    return (len(transitioned), transitioned)
```

**Tasks:**
1. Create `backend/app/services/chain_rollup.py` with the function above.
2. Verify the imports resolve: `app.db.repo` exports `get_chain_for_study` + `bulk_mark_superseded` (from Story 1.2); `app.domain.study.chain_summary` exports `derive_chain_stop_reason` + `select_best_link` (Phase 1).
3. Write unit tests at `backend/tests/unit/services/test_chain_rollup_service.py` — mock `repo.get_chain_for_study` + `select_best_link` + `derive_chain_stop_reason` + `repo.bulk_mark_superseded`. Cover:
   - chain not found → `(0, [])`
   - single-link chain → `(0, [])`
   - `in_flight` stop_reason → `(0, [])`
   - no best link → `(0, [])`
   - happy path with 2 losers → `(2, [loser1, loser2])`
   - happy path where `bulk_mark_superseded` returns fewer rows than candidates (race) → returned count matches len(transitioned).

**Definition of Done:**
- All 6 unit tests pass.
- `make typecheck` passes.
- Service is callable from `_stop` (Story 2.3) and can be unit-tested in isolation.

### Story 2.2 — Chain-traversal proposal-filter widening

**Outcome:** `get_chain_for_study`'s proposal lookup widens from `Proposal.status != "rejected"` to `Proposal.status.notin_(("rejected", "superseded"))`. The cascade to `list_recent_completed_chains` happens automatically (it reuses the same function).

**New files:** None.

**Modified files:**
- [`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py#L341) — line 341.

**Tasks:**
1. Replace `Proposal.status != "rejected"` with `Proposal.status.notin_(("rejected", "superseded"))` at `study.py:341`.
2. Write an integration test at `backend/tests/integration/db/test_chain_traversal_filter_widening.py`:
   - Seed a 3-link chain with proposals: anchor `pending`, child `superseded`, grandchild `pending`.
   - Call `get_chain_for_study(db, grandchild_id)`.
   - Assert `proposal_id_by_link_id` contains `{anchor_id: anchor_proposal_id, grandchild_id: grandchild_proposal_id}` — child entry is **absent** (superseded → omitted).

**Definition of Done:**
- The integration test passes.
- AC-6 partial coverage (proposal-resolution assertion).
- `make test-integration` shows no regression in existing `get_chain_for_study` tests.

### Story 2.3 — `_stop` wires the rollup + post-commit structlog (FR-5, FR-7)

**Outcome:** Every chain-link `_stop` invocation conditionally calls the rollup inside its existing transaction; on commit, emits the `chain_proposals_superseded` structlog event.

**New files:** None.

**Modified files:**
- [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py#L693) — append a conditional rollup call inside `_stop`'s `try:` block + emit structlog after the existing `await db.commit()` line; populate `chain_anchor_id` + `best_link_id` for the log payload.

**Tasks:**
1. After the existing `repo.create_proposal(... status="pending" ...)` call (around line 730) but before the existing `await db.commit()`, add a conditional rollup call:
   ```python
   superseded_count = 0
   superseded_ids: list[str] = []
   chain_anchor_id: str | None = None
   best_link_id: str | None = None
   if not (study.parent_study_id is None and (study.config or {}).get("auto_followup_depth") in (None, 0)):
       traversal = await repo.get_chain_for_study(db, study_id)
       if traversal is not None and len(traversal.links) >= 2:
           chain_anchor_id = traversal.anchor_id
           best_link_id = select_best_link(traversal.links)
       count, ids = await chain_rollup.mark_non_winning_chain_proposals_superseded(db, study_id=study_id)
       superseded_count = count
       superseded_ids = ids
   ```
   (The `chain_rollup` import + the inner `select_best_link` re-read for the log payload are intentional — the service helper returns count/ids but the log needs anchor + winner too; reading them locally in the orchestrator keeps the service's return shape minimal.)
2. After the existing `await db.commit()`, emit the structlog event if `superseded_count > 0`:
   ```python
   if superseded_count > 0:
       logger.info(
           "chain_proposals_superseded",
           extra={
               "study_id": study_id,
               "chain_anchor_id": chain_anchor_id,
               "best_link_id": best_link_id,
               "superseded_count": superseded_count,
               "superseded_proposal_ids": superseded_ids,
           },
       )
   ```
3. Import the new module: `from backend.app.services import chain_rollup` + `from backend.app.domain.study.chain_summary import select_best_link` if not already imported.
4. Write integration tests at `backend/tests/integration/workers/test_orchestrator_stop_supersedes_losers.py`:
   - `test_stop_supersedes_losers_atomic_with_commit` (AC-6, AC-7) — seed 3-link chain, complete tail via `_stop`, assert atomic supersession + winner row insert.
   - `test_stop_rolls_back_supersession_on_invalid_state` (AC-9) — monkeypatch `complete_study` to raise; assert no rows transition; `_stop` exits gracefully.
   - `test_stop_emits_structlog_after_commit` (D-19) — capture log records; assert the event fires exactly once with `superseded_count == 2` after the commit succeeds.
5. Write integration test at `backend/tests/integration/workers/test_orchestrator_stop_skips_anchor.py`:
   - `test_stop_anchor_only_skips_rollup_no_select` (AC-8) — seed a standalone study (no parent, depth=0); complete via `_stop`; assert zero `chain_rollup` log records AND that `get_chain_for_study` was never called (use a spy).
6. Write integration test at `backend/tests/integration/workers/test_orchestrator_late_link.py`:
   - `test_late_link_rerun_is_idempotent` (AC-10) — seed a chain where `_stop` already ran on link C and superseded losers; simulate a late link D completing; assert idempotent re-run (count==0 on already-superseded set; only D's losers transition if applicable).

**Definition of Done:**
- All 5 integration tests pass.
- AC-6, AC-7, AC-8, AC-9, AC-10 satisfied.
- `make typecheck` passes; `make lint` passes.
- Existing orchestrator `_stop` tests pass unmodified (verify with `make test-integration`).

---

## Epic 3 — API surface

### Story 3.1 — `?include_superseded` flag + `POST /api/v1/proposals/{id}/reinstate` (FR-6, FR-7 operator side)

**Outcome:** Two coupled API changes: (a) a new `?include_superseded=false` boolean param on the list endpoint (D-15 revised after impl-plan-gen Pass 2) so the default response excludes superseded rows; (b) a new reinstate endpoint flips `superseded → pending` with deterministic 404/409 errors. The existing single-value `?status=` contract is **unchanged** — explicit `?status=` always beats implicit `include_superseded`.

**New files:** None.

**Modified files:**
- [`backend/app/api/v1/proposals.py`](../../../../backend/app/api/v1/proposals.py) — add `include_superseded: bool = False` query param to `list_proposals_endpoint`; add `reinstate_proposal_endpoint`.
- [`backend/app/db/repo/proposal.py`](../../../../backend/app/db/repo/proposal.py) — add `include_superseded: bool = False` kwarg to `list_proposals_paginated` + `count_proposals` (and any other helper that mirrors the filter). Implicit filter logic: `if status is None and not include_superseded: stmt = stmt.where(Proposal.status != "superseded")`. Existing `Proposal.status == status` filter unchanged.

**Endpoints:**

| Method | Path | Request body | Success response | Key error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/proposals/{proposal_id}/reinstate` | `{}` (empty) | `200 OK` carrying `ProposalDetail` with `status='pending'` | `404 PROPOSAL_NOT_FOUND` (id unknown), `409 INVALID_STATE_TRANSITION` (wrong status — reused from reject endpoint per D-16) |
| `GET` | `/api/v1/proposals?include_superseded=true` | n/a | `ProposalsListResponse` (existing schema; rows now include `superseded`) | `422 VALIDATION_ERROR` (invalid bool) |

**Key interfaces:**
```python
# backend/app/api/v1/proposals.py — append after `open_pr_endpoint`.

@router.post(
    "/proposals/{proposal_id}/reinstate",
    response_model=ProposalDetail,
    tags=["proposals"],
)
async def reinstate_proposal_endpoint(
    proposal_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProposalDetail:
    """Phase 3: ``superseded → pending`` transition.

    Mirrors :func:`reject_proposal_endpoint` (D-17) so 404 (unknown id) and 409
    (wrong status) are deterministic. Reuses ``INVALID_STATE_TRANSITION`` (D-16).
    """
    proposal = await repo.get_proposal(db, proposal_id)
    if proposal is None:
        raise _err(404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} not found", False)
    try:
        await repo.reinstate_from_superseded(db, proposal_id=proposal_id)
    except InvalidStateTransition as exc:
        raise _err(
            409,
            "INVALID_STATE_TRANSITION",
            f"proposal {proposal_id} is in status {exc.current_status!r}; "
            "only 'superseded' proposals can be reinstated",
            False,
        ) from exc
    await db.commit()
    # D-19: post-commit structlog (intent is durable now).
    logger.info(
        "chain_proposal_reinstated",
        extra={
            "proposal_id": proposal_id,
            "study_id": proposal.study_id,
            "prior_status": "superseded",
        },
    )
    refreshed = await repo.get_proposal(db, proposal_id)
    if refreshed is None:
        raise _err(
            404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} disappeared mid-update", False
        )
    return await _assemble_proposal_detail(db, refreshed)
```

```python
# backend/app/api/v1/proposals.py — add include_superseded to list_proposals_endpoint.

async def list_proposals_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[ProposalStatusWire | None, Query(alias="status")] = None,
    # ...existing params unchanged (cluster_id, source, template_id, study_id,
    # is_last_merged, cursor, limit, sort)...
    include_superseded: Annotated[bool, Query()] = False,
) -> ProposalsListResponse:
    # Body unchanged except for plumbing include_superseded through to
    # list_proposals_paginated + count_proposals.
```

```python
# backend/app/db/repo/proposal.py — add include_superseded kwarg.

async def list_proposals_paginated(
    db: AsyncSession,
    *,
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    status: ProposalStatusFilter | None = None,  # UNCHANGED
    # ...rest unchanged...
    include_superseded: bool = False,  # NEW
) -> Sequence[Proposal]:
    # ...
    if status is not None:
        stmt = stmt.where(Proposal.status == status)  # UNCHANGED
    elif not include_superseded:
        # D-15 revised: implicit exclusion only when no explicit ?status= filter
        # AND include_superseded is False.
        stmt = stmt.where(Proposal.status != "superseded")
    # ...
```

**Tasks:**
1. Add an `include_superseded: bool = False` kwarg to `list_proposals_paginated`. Implement the implicit-exclusion rule per the key interface above.
2. Add the same kwarg to `count_proposals` (and any other helper that mirrors the filter) — grep for usages.
3. Add an `include_superseded: Annotated[bool, Query()] = False` query param to `list_proposals_endpoint` and plumb it through to both repo helpers.
4. Append `reinstate_proposal_endpoint` after `open_pr_endpoint`.
5. Verify the new endpoint is registered (added to the router's `__all__` if the router exports a list, otherwise just via the `@router.post` decorator).
6. Write contract tests at `backend/tests/contract/test_proposals_reinstate_contract.py`:
   - `test_reinstate_happy_path_returns_200_with_pending_status` (AC-11).
   - `test_reinstate_unknown_id_returns_404_proposal_not_found` (AC-12).
   - `test_reinstate_pending_status_returns_409_invalid_state_transition` (AC-13).
   - `test_reinstate_pr_opened_status_returns_409_invalid_state_transition` (defense).
   - `test_reinstate_emits_chain_proposal_reinstated_after_commit` (D-19, FR-7).
7. Extend `backend/tests/contract/test_proposals_filter_contract.py` (or create the file if missing):
   - `test_status_filter_accepts_superseded_explicitly` (FR-1 — `?status=superseded` returns only superseded rows).
   - `test_default_excludes_superseded_when_include_superseded_false` (D-15 revised — no `?status=`, no `?include_superseded` → superseded omitted).
   - `test_include_superseded_true_returns_all_five` (D-15 revised — `?include_superseded=true` includes superseded).
   - `test_explicit_status_pending_beats_include_superseded_true` (D-15 revised — `?status=pending&include_superseded=true` returns only pending).
   - `test_existing_status_single_value_backward_compatible` (regression — `?status=pending` still returns only pending).
   - Regression-lock the `ProposalStatusWire` Literal allowlist (asserts the 5-element tuple).

**Definition of Done:**
- All 5 reinstate contract tests + 4 filter contract tests pass.
- AC-11, AC-12, AC-13 satisfied.
- The new endpoint appears in `/openapi.json` after `scripts/regen-generated-artifacts.sh`; the `generated-artifacts-fresh` CI job stays green.
- Existing proposals contract tests pass unmodified (single-value backward compat).
- `make typecheck` passes; `make lint` passes.

---

## Epic 4 — Frontend

### Story 4.1 — Filter toggle + StatusBadge variant + Reinstate button + glossary + enums lock + regen artifacts (FR-1 frontend, FR-8)

**Outcome:** `/proposals` index defaults to omitting `superseded` (backend default behavior per Story 3.1); a "Show superseded" filter chip opts in via `?include_superseded=true` (D-15 revised — uses chip-toggle pattern matching the existing `<CurrentlyLiveFilterChip>` precedent, NOT a `<Checkbox>` — that shadcn primitive isn't installed in this project). Superseded rows render with the `outline` badge variant + a tooltip. `/proposals/[id]` shows a "Reinstate" button only when `status='superseded'`. Two new glossary keys mounted on the badge tooltip + reinstate-button tooltip.

**New files:**
- `ui/src/__tests__/lib/enums-proposal-status-discipline.test.ts` — value-lock test for `PROPOSAL_STATUS_VALUES` (mirrors the pattern in `enums-convergence-discipline.test.ts`).

**Modified files:**
- [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts#L202-L204) — append `'superseded'` to `PROPOSAL_STATUS_VALUES`.
  ```typescript
  // Values must match backend/app/api/v1/schemas.py ProposalStatusWire.
  export const PROPOSAL_STATUS_VALUES = ['pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded'] as const;
  ```
- [`ui/src/components/common/status-badge.tsx`](../../../../ui/src/components/common/status-badge.tsx#L23-L28) — append `superseded: 'outline'` to the `proposal:` block (D-12 reuses the `outline` variant).
- `ui/src/lib/glossary.ts` — add two new keys:
  - `'proposal.status.superseded'`: "Marked as a non-winning sibling of an overnight-chain proposal. The chain identified a better alternative; this proposal is preserved for audit and can be reinstated if you want to ship it instead."
  - `'proposal.reinstate'`: "Flip this superseded proposal back to pending so you can ship it. Useful when the chain's automatically-chosen winner doesn't match your judgment."
- `ui/src/lib/api/proposals.ts` — add `useReinstateProposal()` TanStack Query mutation hook that POSTs `/api/v1/proposals/{id}/reinstate` and invalidates `['proposals']` + `['proposals', id]` on success. Also: thread `include_superseded?: boolean` through `useProposals(params)` and append `&include_superseded=true` to the query string when truthy.
- `ui/src/app/proposals/page.tsx` — add a new `<ShowSupersededFilterChip>` (or inline equivalent) mirroring the existing `<CurrentlyLiveFilterChip>` (also in this directory) — both are two-state chip toggles that read/write a single URL key via `useDataTableUrlState`. The chip is active when `urlState.filters['include_superseded'] === 'true'`. The chip writes `?include_superseded=true` when activated; removes the key when deactivated.
- `ui/src/components/proposals/show-superseded-filter-chip.tsx` (new) — mirror `<CurrentlyLiveFilterChip>` shape; expose `active` + `onToggle` props and the standard chip styling.
- `ui/src/app/proposals/[id]/page.tsx` — add the "Reinstate" button rendered only when `proposal.status === 'superseded'`; placed alongside the existing "Open PR" / "Reject" affordances (D-11); on click → `useReinstateProposal().mutate(id)`.
- `ui/openapi.json` + `ui/src/lib/types.ts` — regenerated by the script.

**UI element inventory:**

For `/proposals` page:
- **Filter chip** "Show superseded" — new `<ShowSupersededFilterChip>` mirroring the existing `<CurrentlyLiveFilterChip>` two-state shape. Placed alongside the existing chips. Bound to URL key `?include_superseded` (active when `'true'`). Single source of truth: `useDataTableUrlState.filters['include_superseded']`.

For `/proposals/[id]` page:
- **Button** "Reinstate" — `variant="default"`, `size="sm"`. Visible only when `proposal.status === 'superseded'`. Disabled while the mutation is in-flight. Tooltip via `<InfoTooltip glossaryKey="proposal.reinstate">` mounted adjacent.

For `<StatusBadge>` component:
- **Badge variant** `superseded: 'outline'` — same Tailwind variant as `rejected` (per D-12). Label text "Superseded". When rendered, optional `<InfoTooltip glossaryKey="proposal.status.superseded">` adjacent (mounted by parent surfaces, not the badge itself, so the badge stays presentational).

**State dependency analysis:** The chip's active state lives in URL via `useDataTableUrlState.filters['include_superseded']` (existing hook reads `?include_superseded=true` from `useSearchParams()`). No new React state introduced at the page level. The chip's value is forwarded through `useProposals({ include_superseded: filters['include_superseded'] === 'true' })`. The reinstate button mounts on the existing proposal-detail page's existing action-row component; no new state plumbing required because `proposal.status` is already in scope.

**Tasks:**
1. Append `'superseded'` to `PROPOSAL_STATUS_VALUES` in `ui/src/lib/enums.ts`. Keep the `// Values must match backend/app/api/v1/schemas.py ProposalStatusWire.` source-of-truth comment.
2. Append `superseded: 'outline'` to the `proposal:` block in `ui/src/components/common/status-badge.tsx`. Verify the label-text mapping (if any) also accommodates "Superseded" (read the file).
3. Add the two glossary keys to `ui/src/lib/glossary.ts` with the text from FR-8.
4. Add `useReinstateProposal()` to `ui/src/lib/api/proposals.ts` — TanStack Query `useMutation` calling `POST /api/v1/proposals/{id}/reinstate`; on success invalidates `['proposals']` + `['proposals', id]`.
5. Create `ui/src/components/proposals/show-superseded-filter-chip.tsx` mirroring `<CurrentlyLiveFilterChip>` (read that file first; copy the chip shape, swap labels + glossary). Mount it on `ui/src/app/proposals/page.tsx` alongside the existing `<CurrentlyLiveFilterChip>`. Bind active state to `urlState.filters['include_superseded'] === 'true'`; on toggle, set/clear the URL key via the same hook API the live-chip uses.
6. Add the "Reinstate" button to `ui/src/app/proposals/[id]/page.tsx`. Placement: inside the existing action-button row (alongside "Open PR" / "Reject"); conditional render on `proposal.status === 'superseded'`. On click → `useReinstateProposal().mutate(id)`. Disabled during mutation. Mount `<InfoTooltip glossaryKey="proposal.reinstate">` adjacent.
7. Write the enums-discipline test at `ui/src/__tests__/lib/enums-proposal-status-discipline.test.ts` (mirror `enums-convergence-discipline.test.ts`): assert `PROPOSAL_STATUS_VALUES` exact 5-element tuple; assert the source-of-truth comment exists.
8. Extend `ui/src/__tests__/lib/glossary.test.ts` to value-lock both new keys (mirror existing keys' lock tests).
9. Extend `ui/src/__tests__/components/proposals/proposals-list-page.test.tsx`:
   - Default URL has no `?include_superseded` param (test the URL composer).
   - Activating the "Show superseded" chip appends `&include_superseded=true` to the URL and forwards `include_superseded: true` to `useProposals`.
   - Round-trip: navigating to a URL containing `?include_superseded=true` renders the chip in its active visual state on mount.
   - Existing single-value `?status=pending` regression: chip is inactive; `useProposals` receives `status='pending'` and `include_superseded=false`.
10. Extend `ui/src/__tests__/components/proposals/proposal-detail-page.test.tsx`:
    - Reinstate button NOT in DOM when `proposal.status='pending'`.
    - Reinstate button visible when `proposal.status='superseded'`.
    - Click → mutation fires; on resolve, status flips to `pending` in the UI.
11. Extend `ui/src/__tests__/components/common/status-badge.test.tsx` to render the superseded variant.
12. Write E2E spec at `ui/tests/e2e/proposals-superseded-reinstate.spec.ts`:
    - Real-backend setup via API helpers (no `page.route()` mocking per CLAUDE.md).
    - Seed: anchor study (completed) + child study (completed, `auto_followup_depth=1`); via the `_test` seed helpers if available, otherwise direct API calls.
    - After both studies complete, poll `GET /api/v1/proposals?status=superseded` until at least one row appears (proves the rollup ran).
    - Navigate to `/proposals`, check "Show superseded," click into a superseded row.
    - Assert the "Reinstate" button is visible; click it; assert the badge flips to "Pending" without page reload.
13. Run `bash scripts/regen-generated-artifacts.sh` to refresh `ui/openapi.json` + `ui/src/lib/types.ts` with the new endpoint + widened `?status=` contract.

**Definition of Done:**
- All AC-14, AC-15, AC-16, AC-17, AC-18 pass via vitest + Playwright.
- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` all green.
- The `generated-artifacts-fresh` CI job stays green.
- Existing proposals-list + proposal-detail + status-badge vitest tests pass unmodified.

---

## Epic 5 — Documentation

### Story 5.1 — Architecture + runbook + tutorial updates

**Outcome:** Three docs reflect Phase 3: api-conventions notes the `?status=` widening; data-model.md shows the new `superseded` state; new runbook explains the supersession model; tutorial mentions the `Show superseded` toggle.

**New files:**
- `docs/03_runbooks/proposal-state-management.md` — operator-facing runbook explaining the supersession lifecycle: what it means, when it fires, how to read the `chain_proposals_superseded` log event, how to reinstate.

**Modified files:**
- `docs/01_architecture/api-conventions.md` — note the additive `superseded` value on `ProposalStatusWire`; note the `?status=` query param widening from singular to list (D-15); no new error code (D-16).
- `docs/01_architecture/data-model.md` — update the proposals-status state machine section to include `superseded` + the rollup/reinstate transitions.
- `docs/03_runbooks/agent-debugging.md` — add a "Chain rollup events" subsection explaining `chain_proposals_superseded` + `chain_proposal_reinstated` event interpretation.
- `docs/08_guides/tutorial-first-study.md` — extend the overnight-chain section with a single sentence: "Non-winning proposals are automatically marked superseded; check 'Show superseded' on /proposals to inspect them."

**Tasks:** As above. Keep prose tight; reference the spec rather than restating it.

**Definition of Done:**
- Files written; `reuse lint` passes (SPDX headers on the new runbook).
- The proposals-status state machine diagram in `data-model.md` matches the spec's §9 diagram.
- `mkdocs build --strict` passes if `docs/` is mirrored to the public site (verify via the existing `build-guides-freshness` job).

---

## UI Guidance

### Reference: current proposal-detail action row

Read [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/%5Bid%5D/page.tsx) for the current action-button pattern. The existing "Open PR" + "Reject" buttons live inside a flex row near the top of the detail page; "Reinstate" joins the same row as a third sibling, conditionally rendered.

### Analogous markup patterns

**Reinstate button JSX (model after the existing Reject button):**
```tsx
{proposal.status === 'superseded' && (
  <div className="flex items-center gap-2">
    <Button
      variant="default"
      size="sm"
      disabled={reinstateMutation.isPending}
      onClick={() => reinstateMutation.mutate(proposal.id)}
      aria-label="Reinstate proposal"
    >
      {reinstateMutation.isPending ? 'Reinstating…' : 'Reinstate'}
    </Button>
    <InfoTooltip glossaryKey="proposal.reinstate" />
  </div>
)}
```

**Show-superseded filter chip (D-15 revised — model EXACTLY after [`ui/src/components/proposals/currently-live-filter-chip.tsx`](../../../../ui/src/components/proposals/currently-live-filter-chip.tsx); the project does NOT have a `<Checkbox>` shadcn primitive):**
```tsx
// ui/src/components/proposals/show-superseded-filter-chip.tsx (new)
'use client';
import type { ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { InfoTooltip } from '@/components/common/info-tooltip';

export interface ShowSupersededFilterChipProps {
  active: boolean;
  onToggle: () => void;
}

export function ShowSupersededFilterChip({ active, onToggle }: ShowSupersededFilterChipProps): ReactNode {
  return (
    <div className="flex items-center gap-1">
      <Button
        variant={active ? 'default' : 'outline'}
        size="sm"
        onClick={onToggle}
        aria-pressed={active}
      >
        Show superseded
      </Button>
      <InfoTooltip glossaryKey="proposal.status.superseded" />
    </div>
  );
}
```
Mount on `ui/src/app/proposals/page.tsx` next to `<CurrentlyLiveFilterChip>`:
```tsx
<ShowSupersededFilterChip
  active={urlState.filters['include_superseded'] === 'true'}
  onToggle={() => urlState.setFilter('include_superseded', urlState.filters['include_superseded'] === 'true' ? null : 'true')}
/>
```
(Confirm the exact `setFilter`/setter API by reading [`use-data-table-url-state.ts:63`](../../../../ui/src/hooks/use-data-table-url-state.ts#L63); match the call shape that `<CurrentlyLiveFilterChip>` uses.)

**StatusBadge variant map entry:**
```tsx
proposal: {
  pending: 'secondary',
  pr_opened: 'default',
  pr_merged: 'success',
  rejected: 'outline',
  superseded: 'outline',  // D-12: reuses outline; distinction is via the label + row context.
},
```

### Layout and structure

- The "Show superseded" toggle sits in the same horizontal control row as the existing status filter chips on `/proposals`. No new row introduced.
- The "Reinstate" button sits alongside the existing "Open PR" + "Reject" buttons in the proposal-detail action row. Render order: Open PR (when applicable) → Reject (when applicable) → Reinstate (when applicable). Only one of these is typically visible at a time because they're gated on distinct statuses.

### Visual consistency table

| New UI element | CSS class / pattern source | Source location |
|---|---|---|
| "Show superseded" checkbox + label | Existing filter-chip pattern | `ui/src/app/proposals/page.tsx` (current filter row) |
| "Reinstate" button | Same as Reject button | `ui/src/app/proposals/[id]/page.tsx` (existing action row) |
| Superseded badge | `outline` variant from `StatusBadge` variant map | `ui/src/components/common/status-badge.tsx:23-28` |
| Reinstate-button tooltip | `<InfoTooltip glossaryKey="proposal.reinstate">` | `ui/src/components/common/info-tooltip.tsx` (existing) |
| Badge tooltip mount | `<InfoTooltip glossaryKey="proposal.status.superseded">` | same |

### Component composition

- No new components. Story 4.1 modifies two existing pages + extends one variant map + adds two glossary keys + adds one TanStack mutation hook.
- No extracted shared component; the conditional Reinstate button block is inline because it only renders on one page.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Activate "Show superseded" chip on `/proposals` | URL gains `?include_superseded=true`; `useProposals` refetches with the new flag | `GET /api/v1/proposals?include_superseded=true&…` |
| Deactivate "Show superseded" chip | URL drops `?include_superseded` key; `useProposals` refetches without the flag | `GET /api/v1/proposals?…` (default — superseded excluded) |
| Click "Reinstate" on `/proposals/[id]` | Button disables; mutation fires; on success → TanStack invalidates `['proposals']` + `['proposals', id]`; badge flips to "Pending" without reload | `POST /api/v1/proposals/{id}/reinstate` |
| Click "Reinstate" on a stale page (proposal already reinstated) | Mutation returns 409 INVALID_STATE_TRANSITION; toast appears: "This proposal is no longer superseded — refreshing"; cache invalidates | same |

### Handler function patterns

```typescript
// ui/src/lib/api/proposals.ts — append.

export function useReinstateProposal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (proposalId: string): Promise<ProposalDetail> => {
      const res = await fetch(`${API_BASE}/api/v1/proposals/${proposalId}/reinstate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body?.detail?.error_code ?? 'UNKNOWN', body?.detail?.message ?? '');
      }
      return res.json();
    },
    onSuccess: (_, proposalId) => {
      queryClient.invalidateQueries({ queryKey: ['proposals'] });
      queryClient.invalidateQueries({ queryKey: ['proposals', proposalId] });
    },
    onError: (err: ApiError) => {
      if (err.errorCode === 'INVALID_STATE_TRANSITION') {
        toast('This proposal is no longer superseded — refreshing.');
        queryClient.invalidateQueries({ queryKey: ['proposals'] });
      }
    },
  });
}
```

### Information architecture placement

- **`/proposals` index:** the "Show superseded" toggle is a small UX accent on the existing filter row. It does NOT change the page's primary IA (the list view stays the top-of-page content). It's gated UX — most operators never see it.
- **`/proposals/[id]` detail:** the "Reinstate" button joins the existing action row. Discoverability is automatic when the operator lands on a superseded proposal; the button doesn't need a separate nav entry.

### Tooltips and contextual help

| UI element | Tooltip text | Glossary key | Source-of-truth comment | Trigger | Placement |
|---|---|---|---|---|---|
| `<StatusBadge value="superseded">` (when mounted with adjacent tooltip) | (from glossary) | `proposal.status.superseded` | n/a (glossary text owns it) | info icon click | adjacent to badge |
| "Reinstate" button | (from glossary) | `proposal.reinstate` | n/a | info icon click | adjacent to button |
| "Show superseded" toggle | "Show proposals that were automatically marked as non-winners by an overnight chain. Hidden by default to focus on actionable proposals." | inline helper text (no glossary entry needed — it's a discoverability nudge, not a domain concept) | n/a | hover / focus on the checkbox label | inline helper text below |

Both glossary keys are added to `ui/src/lib/glossary.ts` by Story 4.1 task 3.

### Legacy behavior parity

N/A — no user-facing component is deleted or moved. Story 4.1 only adds new UI elements + extends existing variant/value maps. The Legacy Behavior Parity table rule (template §11) does not apply.

---

## 3) Testing workstream

### 3.1 Unit tests

| File | Owns | Story |
|---|---|---|
| `backend/tests/unit/services/test_chain_rollup_service.py` | `mark_non_winning_chain_proposals_superseded` matrix with mocked repo + domain helpers | 2.1 |

### 3.2 Integration tests

| File | Owns | Story |
|---|---|---|
| `backend/tests/integration/db/test_proposal_supersession.py` | `bulk_mark_superseded` + `reinstate_from_superseded` against real Postgres (D-20) | 1.2 |
| `backend/tests/integration/db/test_chain_traversal_filter_widening.py` | `get_chain_for_study` omits superseded proposals from `proposal_id_by_link_id` | 2.2 |
| `backend/tests/integration/workers/test_orchestrator_stop_supersedes_losers.py` | `_stop` atomic supersession + post-commit structlog | 2.3 |
| `backend/tests/integration/workers/test_orchestrator_stop_skips_anchor.py` | Anchor-only completion skips rollup (no SELECT) | 2.3 |
| `backend/tests/integration/workers/test_orchestrator_late_link.py` | Late-arriving link's rerun is idempotent | 2.3 |

### 3.3 Contract tests

| File | Owns | Story |
|---|---|---|
| `backend/tests/contract/test_proposals_reinstate_contract.py` | Reinstate endpoint happy path + 404 + 409 + structlog | 3.1 |
| `backend/tests/contract/test_proposals_filter_contract.py` (new or extend) | `?status=superseded` + multi-value + single-value backward compat + `ProposalStatusWire` allowlist lock | 3.1 |

### 3.4 Vitest

| File | Owns | Story |
|---|---|---|
| `ui/src/__tests__/lib/enums-proposal-status-discipline.test.ts` (new) | `PROPOSAL_STATUS_VALUES` 5-tuple lock + source-of-truth comment lock | 4.1 |
| `ui/src/__tests__/lib/glossary.test.ts` (extend) | Both new keys value-lock | 4.1 |
| `ui/src/__tests__/components/proposals/proposals-list-page.test.tsx` (extend) | Toggle URL contract round-trip | 4.1 |
| `ui/src/__tests__/components/proposals/proposal-detail-page.test.tsx` (extend) | Reinstate button visibility + click → mutation | 4.1 |
| `ui/src/__tests__/components/common/status-badge.test.tsx` (extend) | Superseded variant renders | 4.1 |

### 3.5 E2E

| File | Owns | Story |
|---|---|---|
| `ui/tests/e2e/proposals-superseded-reinstate.spec.ts` (new) | Full chain → supersession → toggle → click → reinstate, real backend | 4.1 |

### 3.6 Existing test impact audit

- `backend/tests/contract/test_proposals_api_contract.py` (or similar existing) — verify the new `?include_superseded` flag doesn't break existing assertions. Single-value `?status=pending` URLs must still return only pending rows (D-15 revised: explicit `?status=` always beats implicit `include_superseded`).
- `backend/tests/integration/test_studies_chain_endpoint.py` — verify the FR-4 filter widening doesn't break existing chain-traversal tests. Specifically: tests that seed a chain with `rejected` proposals must still see them filtered out (FR-4 widens but doesn't change `rejected` behavior).
- `ui/src/__tests__/components/common/status-badge.test.tsx` — existing variants still render unchanged.

### 3.7 Migration verification

- Run locally before pushing: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`.
- Verify the downgrade hard-guard fires: manually `INSERT` a `superseded` row, then `uv run alembic downgrade -1`, assert `RuntimeError` with the documented message (AC-2).

### 3.8 CI gates

The PR must keep all 18 `pr.yml` checks green:
- Backend: ruff format-check, ruff lint, mypy --strict, pytest unit + integration + contract (80% coverage gate).
- Frontend: prettier check, eslint, tsc --strict, vitest, Next.js build.
- Docker: `buildx build` for `relyloop/api` (no push).
- Generated artifacts: `generated-artifacts-fresh` (regen + diff guard).
- Build-guides freshness; copy-docs freshness.
- CodeQL clean.
- DCO sign-off check.
- Conventional Commits format check.

---

## 4) Documentation update workstream

### 4.0 Core context files

- `state.md` — append the merged-PR one-liner under "Last 5 merges"; bump the "Last updated" line; note Alembic head moves to `0023`.
- `state_history.md` — append the full merge narrative entry per the state-md compression rule.

### 4.1 Architecture docs

- `docs/01_architecture/api-conventions.md` — Story 5.1.
- `docs/01_architecture/data-model.md` — Story 5.1.

### 4.3 Runbooks

- `docs/03_runbooks/agent-debugging.md` — Story 5.1.
- `docs/03_runbooks/proposal-state-management.md` (new) — Story 5.1.

### 4.6 Guides

- `docs/08_guides/tutorial-first-study.md` — Story 5.1 (one sentence).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

No structural refactors planned. Phase 3 is purely additive at the backend (one new service module, two new repo helpers, one new endpoint, one widened filter, one orchestrator wiring) and purely additive at the frontend (one toggle, one variant value, one button, two glossary keys, one mutation hook).

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

N/A.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

- **PR #440** (`feat_overnight_final_solution` Phase 1) — merged 2026-06-04. Provides `get_chain_for_study`, `CHAIN_STOP_REASONS`, `derive_chain_stop_reason`, `select_best_link`. Hard dep.
- **PR #442** (Phase 2) — merged 2026-06-04. No code coupling; Phase 3's filter widening cascades but requires no Phase 2 change.
- **PR #444** (`feat_overnight_studies_summary_card`) — merged 2026-06-04. Soft dep — `list_recent_completed_chains` reuses `get_chain_for_study`, so FR-4 cascades automatically.
- **PR #446** (`feat_proposal_full_param_space_view`) — merged 2026-06-04. Coordination only — informs the Reinstate button placement (D-11).
- **Alembic head:** `0022_solr_engine_auth_check`. New migration `0023_proposals_superseded_status`.

### Risks

1. **Race condition: operator opens PR while rollup running.** Mitigation: both helpers use `WHERE status='pending'` conditional UPDATEs; whichever transaction commits first wins. The losing transaction raises `InvalidStateTransition` and the operator sees the existing 409 error path. Covered by AC-9 (atomicity test).
2. **Late-arriving link re-rolls up after operator reinstate (D-18).** Documented expected behavior. UX mitigation: tooltip on Reinstate button mentions "Wait until chain has fully terminated before reinstating to avoid the rollup re-superseding your choice."
3. **Single-value backward compatibility on `?status=` widening (D-15).** FastAPI's `list[T] | None` query param parsing is robust against single-value URLs (parses as `["value"]`). Mitigation: Story 3.1 task 7 includes a backward-compat regression test.
4. **Structlog event drift if log format changes.** Mitigation: the post-commit emission (D-19) is the caller's responsibility; integration tests assert on the log record shape, locking the contract.

### Failure mode catalog

| Failure | Symptom | Mitigation |
|---|---|---|
| Rollup runs but commit fails | Logs claim supersession, DB unchanged | D-19: log AFTER commit, never before |
| `bulk_mark_superseded` matches more rows than expected (chain race) | Some "winners" superseded incorrectly | Mitigation: `WHERE status='pending'` + `study_id IN (losers)` — losers are explicitly enumerated; chain race cannot change the winner mid-call within a single transaction |
| `_stop` rollback doesn't undo the rollup | Inconsistent state | Same transaction; rollback undoes both. Test AC-9. |
| Late link re-supersedes operator-reinstated row | Operator confusion | D-18 documented; UI tooltip explains; future feature can add `protected` flag |
| Frontend default URL contract changes break existing bookmarks | Operator's saved URL with `?status=pending` shows nothing | FastAPI parses single-value `?status=pending` as `["pending"]`; backward-compat ensured by Story 3.1 task 7 regression test |

---

## 7) Sequencing and parallelization

### Suggested sequence

```
Story 1.1 (migration + Literals)
  └─▶ Story 1.2 (repo helpers — depends on Literals)
       ├─▶ Story 2.1 (service helper — depends on repo helpers)
       │    └─▶ Story 2.3 (_stop wiring — depends on service)
       ├─▶ Story 2.2 (chain-traversal filter widening — independent of 2.1, but ships in same PR)
       └─▶ Story 3.1 (API endpoint + filter widening — depends on repo helper)
            └─▶ Story 4.1 (frontend — depends on endpoint + wire-value mirror)
                 └─▶ Story 5.1 (docs)
```

### Parallelization opportunities

- Stories 2.1 and 2.2 can be implemented in either order (both depend on 1.2 only; 2.2 is one line, 2.1 is the service module).
- Story 3.1's `?status=` widening (the repo + endpoint change) can be done in parallel with Story 2.1 if a single engineer wants to context-switch; both depend only on Story 1.2 outputs.
- Story 5.1 docs writing can begin once Story 3.1 endpoint is stable (the docs reference the API shape).

For a single agent: execute strictly sequentially in the order above. The dependencies are real; skipping ahead requires careful state tracking.

---

## 8) Rollout and cutover plan

- **Feature flags:** None. The rollup runs unconditionally on chain termination; the frontend toggle controls visibility; no operator-facing gradual-rollout surface is needed.
- **Migration backfill:** None. The CHECK constraint extends additively; existing rows are unaffected. No backfill of pre-Phase-3 chains' losers (operators can manually `UPDATE` if desired).
- **Branch + PR cycle:**
  1. Branch: `feature/overnight-final-solution-phase3`.
  2. Implement Stories 1.1 → 1.2 → 2.1 → 2.2 → 2.3 → 3.1 → 4.1 → 5.1, verifying each story's DoD locally.
  3. Run `make test-unit && make test-integration && make test-contract` (skip integration locally if Postgres isn't running — CI catches it).
  4. Run `bash scripts/regen-generated-artifacts.sh` and commit any pending diffs.
  5. Push; open PR against `main`; monitor CI.
  6. Address Gemini Code Assist findings per the four-quadrant rubric.
  7. Squash-merge on green CI + clean review.
- **Post-merge:**
  - Update `state.md` "Last 5 merges" + bump Alembic head note.
  - Append full narrative to `state_history.md`.
  - Move feature folder from `planned_features/02_mvp2/` → `implemented_features/<YYYY_MM_DD>_<short_name>/` (date-prefixed, flat).
  - Verify the `mvp1-dashboard-regen` pre-commit hook regenerates the dashboard counters.

---

## 9) Execution tracker

| Story | Owner | Status | Notes |
|---|---|---|---|
| 1.1 Migration + Literals | — | [ ] | |
| 1.2 Repo helpers | — | [ ] | |
| 2.1 Service helper | — | [ ] | |
| 2.2 Chain-traversal filter widening | — | [ ] | |
| 2.3 `_stop` wiring + post-commit structlog | — | [ ] | |
| 3.1 Reinstate endpoint + `?status=` widening | — | [ ] | |
| 4.1 Frontend (toggle + badge + button + glossary + enums lock + E2E) | — | [ ] | |
| 5.1 Docs | — | [ ] | |

**Total: 8 stories across 5 epics.**
