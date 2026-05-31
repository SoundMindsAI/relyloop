# Implementation Plan — Overnight autopilot (surface the autonomous study chain)

**Date:** 2026-05-31
**Status:** Approved
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy sources:** [`CLAUDE.md`](../../../../../CLAUDE.md) · [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) · [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Every story traces to one or more FRs from the spec.
- Phase 1 only (Phase 2 deferred to [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md)).
- The shipped chaining engine (`enqueue_followup_study`, `evaluate_chain_gate`, narrowing primitive, cancel cascade) is read-only ground truth — no story modifies it.
- Read-only feature: no migration, no schema change, no new write paths, no new error codes beyond reused `STUDY_NOT_FOUND` (404).
- Cross-model review (GPT-5.5) deliberately skipped per operator decision — spec already converged across 3 cross-model cycles. Opus-only internal passes only.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Spec ACs covered | Notes |
|---|---|---|---|
| FR-1 (wizard relabel `🌙 Run overnight (compound automatically)`) | Epic 3 / Story 3.1 | AC-1 | UI text change in `create-study-modal.tsx`; new glossary key used (FR-6). |
| FR-2 (Deep-preset inline hint) | Epic 3 / Story 3.1 | AC-2 | Non-coupling hint; same step as overnight toggle. |
| FR-3 (`GET /api/v1/studies/{id}/chain` endpoint + derivation domain logic) | Epic 1 / Stories 1.1–1.3 | AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10 | 1.1 = pure-domain helpers, 1.2 = repo traversal, 1.3 = router + schemas. |
| FR-4 (`AutoFollowupChainPanel` rolled-up summary) | Epic 2 / Story 2.1 | AC-11, AC-12, AC-12a | Extend existing panel + add `useStudyChain` hook with D-10 refetch contract. |
| FR-5 (tutorial section "Run the loop overnight") | Epic 4 / Story 4.1 | AC-13 | New H2 in `tutorial-first-study.md`. |
| FR-6 (`overnight_autopilot` glossary key) | Epic 3 / Story 3.1 | AC-14 | Lands in same PR as wizard relabel; value-lock vitest. |

All four phase-1 FRs are covered. Phase 2 (`/studies` list "ran while away" card) is tracked at [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md); no other deferred work.

## 2) Delivery structure

This plan uses **Epic → Story → Tasks → DoD**. Four epics in dependency order:

1. **Epic 1 — Backend chain aggregation** (FR-3). Domain helpers → repo traversal → router. No other story depends on UI.
2. **Epic 2 — Frontend chain-summary panel** (FR-4). Depends on Epic 1's endpoint.
3. **Epic 3 — Wizard relabel + hint + glossary** (FR-1, FR-2, FR-6). Independent of Epics 1–2 (purely UI/copy).
4. **Epic 4 — Tutorial + docs** (FR-5 + §15 doc updates). Lands last with the user-facing copy.

### Conventions (project-specific)

- Repo functions take `db: AsyncSession` first; use `db.flush()` (caller commits). Reads use `(await db.execute(stmt)).scalars()`. New chain-traversal helper is pure read, no flush.
- Services are async. This feature has no service layer (the endpoint reads through repo + domain only — no orchestration or job_run lifecycle).
- Domain functions are pure (no DB, no I/O, no async). `derive_chain_stop_reason`, `compute_cumulative_lift`, `select_best_link` accept hydrated row + dict inputs and return scalars / IDs.
- All routers expose typed Pydantic response models; errors use `_err(status_code, code, message, retryable)` helper at `backend/app/api/v1/studies.py:80-84`.
- All repo `__all__` exports updated in `backend/app/db/repo/__init__.py`.
- Glossary entries follow the shape at `ui/src/lib/glossary.ts:866-899` (`short` + `long` + `ariaLabel`).
- TanStack Query hooks live in `ui/src/lib/api/studies.ts` (one file per resource); query keys follow the `['studies', studyId, '<subresource>']` pattern.

### AI Agent Execution Protocol

0. Load context: read `architecture.md`, `state.md`, `feature_spec.md` (this folder), `idea.md`. Confirm Alembic head is `0022_solr_engine_auth_check` (no migration this feature).
1. Read each story's outcome + DoD + endpoint contract before writing code.
2. Backend first (Epic 1): domain → repo → router → schemas. `make test-unit` after Story 1.1, full `make test` after Story 1.3.
3. Frontend (Epic 2 + Epic 3) after the endpoint is green in integration tests. `cd ui && pnpm test && pnpm typecheck && pnpm lint`.
4. Docs (Epic 4) last.
5. Run the E2E spec against a real backend (no `page.route()` mocking — per CLAUDE.md).
6. Update `state.md` "Last 5 merges" + Active branch as the final commit on the branch.
7. No schema change — no migration round-trip step.

---

## Epic 1 — Backend: chain aggregation endpoint (FR-3)

### Story 1.1 — Pure-domain chain summary helpers

**Outcome:** A new pure-Python module `backend/app/domain/study/chain_summary.py` exposes `derive_chain_stop_reason`, `compute_cumulative_lift`, `select_best_link`, and the `CHAIN_STOP_REASONS` frozenset. No DB, no I/O, no async. Reuses `compute_first_decile_max` and the direction-aware lift semantics from `backend/app/domain/study/auto_followup.py` rather than duplicating them.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/chain_summary.py` | `CHAIN_STOP_REASONS` frozenset + `ChainStopReason` Literal + `derive_chain_stop_reason` (§9 decision matrix) + `compute_cumulative_lift` (universal `best_of_completed - anchor_baseline` w/ first-decile fallback) + `select_best_link` (argmax/argmin over completed-link subset with `created_at ASC` tie-break) + `_direction_normalized_delta_from_prev` helper. All pure functions. |
| `backend/tests/unit/domain/study/test_chain_summary.py` | Unit tests for every public symbol; covers AC-5, AC-6, AC-7, AC-8, AC-9, AC-10 + the maximize/minimize direction flip + the single-link aggregation case + the empty-completed-subset case + the `baseline_metric IS NULL` first-decile fallback. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/__init__.py` | Re-export `derive_chain_stop_reason`, `compute_cumulative_lift`, `select_best_link`, `CHAIN_STOP_REASONS`, `ChainStopReason`. |

**Key interfaces**

```python
# backend/app/domain/study/chain_summary.py
from typing import Any, Literal

ChainStopReason = Literal[
    "depth_exhausted", "no_lift", "budget", "parent_failed", "cancelled", "in_flight",
]
CHAIN_STOP_REASONS: frozenset[ChainStopReason] = frozenset({
    "depth_exhausted", "no_lift", "budget", "parent_failed", "cancelled", "in_flight",
})

CHAIN_LIFT_EPSILON: float = 0.005  # matches evaluate_chain_gate default

def derive_chain_stop_reason(
    links: list[Any],
    anchor_trials: list[Any] | None = None,
) -> ChainStopReason: ...
# Evaluates §9 conditions 1-8 in order. `links` ordered created_at ASC.
# `anchor_trials` only consulted when tail.baseline_metric IS NULL (FR-3
# fallback). Tail = links[-1]. Direction from tail.objective["direction"]
# (default "maximize").

def compute_cumulative_lift(
    links: list[Any],
    anchor_trials: list[Any] | None = None,
) -> float | None: ...
# Returns best_of_completed.best_metric - anchor_baseline, direction-flipped
# for minimize. anchor_baseline = anchor.baseline_metric when non-null else
# compute_first_decile_max(anchor_trials, direction) else None. Returns None
# when completed-link subset empty OR no comparison baseline derivable.

def select_best_link(links: list[Any]) -> str | None: ...
# argmax(best_metric) over status='completed' AND best_metric IS NOT NULL
# (argmin under minimize). Tie-break by created_at ASC, id ASC. None when
# subset empty.

def _direction_normalized_delta_from_prev(
    this_metric: float | None,
    prev_metric: float | None,
    direction: Literal["maximize", "minimize"],
) -> float | None: ...
# Returns this - prev (sign-flipped for minimize). None when either side is
# None. Used by the router to populate per-link `delta_from_prev`.
```

**Tasks**

1. Create `backend/app/domain/study/chain_summary.py` with the five public symbols above + `CHAIN_LIFT_EPSILON`. Import `compute_first_decile_max` and `_direction_normalized_lift` from `backend/app/domain/study/auto_followup.py` (no duplication).
2. `derive_chain_stop_reason` walks §9 conditions 1–8 in order, returning the first match. Condition 8 returns `"budget"` (D-6 documented approximation).
3. `compute_cumulative_lift` MUST use the universal formula (D-9) — never short-circuit single-link chains to 0.
4. `select_best_link` filters to `status='completed' AND best_metric IS NOT NULL` (D-8). Tie-break deterministic.
5. Update `backend/app/domain/study/__init__.py` to re-export the five symbols.
6. Write `backend/tests/unit/domain/study/test_chain_summary.py` covering every AC in the spec §12 that maps to FR-3 (AC-5 through AC-10), plus: maximize+minimize direction flip on `compute_cumulative_lift`; `baseline_metric IS NULL` triggering first-decile fallback; first-decile fallback returning `None` triggering `cumulative_lift = None`; single-link completed chain (`AC-5` shape); completed subset empty (in-flight tail) → `best_link_id = None`; tie-break on `select_best_link` (two links with identical `best_metric` → earlier `created_at`).

**Definition of Done**

- [ ] `backend/app/domain/study/chain_summary.py` exists and exports the five public symbols listed above.
- [ ] `backend/app/domain/study/__init__.py` re-exports all five.
- [ ] `backend/tests/unit/domain/study/test_chain_summary.py` passes with at least 14 distinct test cases (one per AC-5/6/7/8/9/10 + maximize/minimize direction flip + baseline-null first-decile path + first-decile-None edge + single-link completed + completed-subset-empty + tie-break + delta_from_prev minimize sign-flip).
- [ ] No DB or I/O imports anywhere in the module (`grep -E "AsyncSession|select|httpx|asyncio" backend/app/domain/study/chain_summary.py` returns nothing).
- [ ] `make test-unit` green.

---

### Story 1.2 — Chain traversal repo helper

**Outcome:** `backend/app/db/repo/study.py` gains `get_chain_for_study(db, study_id)` — performs the bounded upward `parent_study_id` walk + linear downward `LIMIT 1` walk + hydration `SELECT … WHERE id IN (…)` + per-link proposal lookup (rejected-excluded, deterministic). Pure repo function — no domain logic.

**New files**

_None._ All code lands in existing files.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/study.py` | Add `get_chain_for_study(db, study_id) -> ChainTraversalResult \| None` returning hydrated `Study` rows ordered `created_at ASC, id ASC` plus `anchor_id`, `proposal_id_by_link_id` dict, and the optional `anchor_trials` list (only populated when `anchor.baseline_metric IS NULL`). Includes the 10-hop upward defensive cap (degrade-and-WARN-log) + linear-`LIMIT 1` downward walk per D-12 + WARN-log on truncated siblings. |
| `backend/app/db/repo/__init__.py` | Export `get_chain_for_study` and the `ChainTraversalResult` dataclass under the `feat_study_lifecycle Phase 2 Story 1.4 extensions` bucket. |
| `backend/tests/integration/test_studies_chain_repo.py` (NEW under integration/) | Integration tests for `get_chain_for_study`: linear 3-link happy path, anchor-only (single-link, no parent, no children), descendant-side walk visits all 5 children up to the cap, upward walk cap at 10 hops with cyclic seeded data, `LIMIT 1` downward truncation when a parent has 2 children (manually inserted), proposal lookup ordering (multiple non-rejected proposals → newest wins, all-rejected → `None`). |

**Key interfaces**

```python
# backend/app/db/repo/study.py — added near list_children_of_study (line 182 area)
from dataclasses import dataclass
from backend.app.db.models import Study, Proposal, Trial

@dataclass(frozen=True)
class ChainTraversalResult:
    anchor_id: str
    links: list[Study]  # ordered created_at ASC, id ASC; length 1..6
    proposal_id_by_link_id: dict[str, str]  # missing key → no proposal for that link
    anchor_trials: list[Trial] | None  # populated ONLY when anchor.baseline_metric IS NULL

async def get_chain_for_study(
    db: AsyncSession,
    study_id: str,
) -> ChainTraversalResult | None: ...
# Returns None when study_id does not exist. Otherwise:
#   1. Upward walk from study_id following parent_study_id, capped at 10
#      hops; visited-set guards against cycles; log WARN on cap-stop.
#   2. Downward walk from anchor: at each step,
#      SELECT id, created_at FROM studies WHERE parent_study_id = :cur
#      ORDER BY created_at ASC, id ASC LIMIT 1. Stop when no child or
#      after 5 descendants (anchor + 5 = 6 rows max). Log WARN if a
#      second sibling exists (fan-out invariant violated).
#   3. Hydrate: SELECT * FROM studies WHERE id IN (:link_ids) and
#      reorder client-side by (created_at, id).
#   4. Proposal lookup: SELECT DISTINCT ON (study_id) id, study_id
#      FROM proposals WHERE study_id = ANY(:link_ids) AND status != 'rejected'
#      ORDER BY study_id, created_at DESC, id DESC. Build dict.
#   5. Anchor-trials lookup: ONLY when anchor.baseline_metric IS NULL,
#      SELECT * FROM trials WHERE study_id = :anchor_id AND status = 'complete'.
#      Used by domain layer for the first-decile fallback in cumulative_lift.
```

**Tasks**

1. Add `ChainTraversalResult` dataclass + `get_chain_for_study` to `backend/app/db/repo/study.py` directly after `list_children_of_study` (insertion around current line 208).
2. Upward walk: loop `WHILE parent_study_id IS NOT NULL AND hops < 10`, fetching `(id, parent_study_id, baseline_metric)` via `select(Study.id, Study.parent_study_id, Study.baseline_metric).where(Study.id == cur)`. Use a visited-set guard. Log WARN with `study_id`, `hop_count` if the cap fires.
3. Downward walk: iterative; at each step `select(Study.id).where(Study.parent_study_id == cur).order_by(Study.created_at.asc(), Study.id.asc()).limit(2)` — selecting 2 lets us detect a fan-out without extra round-trips. Take `[0]` and log WARN if `len(result) == 2`. Stop after 5 descendants.
4. Hydrate all link IDs in a single `select(Study).where(Study.id.in_(link_ids))` and reorder by `(created_at, id)`.
5. Proposal lookup uses `DISTINCT ON (Proposal.study_id)` with `status != 'rejected'` — SQLAlchemy syntax: `select(Proposal.id, Proposal.study_id).where(Proposal.study_id.in_(link_ids), Proposal.status != 'rejected').order_by(Proposal.study_id, Proposal.created_at.desc(), Proposal.id.desc()).distinct(Proposal.study_id)`.
6. Anchor-trials lookup is conditional — execute ONLY when `anchor.baseline_metric IS NULL`.
7. Export from `backend/app/db/repo/__init__.py` under the `feat_study_lifecycle Phase 2 Story 1.4 extensions` bucket (alongside `list_children_of_study`).
8. Write integration tests as listed in "Modified files."

**Definition of Done**

- [ ] `get_chain_for_study` returns `None` (not raises) when `study_id` missing; tested.
- [ ] Linear 3-link chain returns `links` ordered `S1 → S2 → S3`; tested.
- [ ] Cyclic `parent_study_id` (seeded by direct DB update bypassing the model invariant) terminates at 10 hops, logs WARN, returns a payload anchored at the cap-stop point; tested.
- [ ] Downward walk picks `[0]` when a parent has 2 children (seeded outside the engine path) AND logs WARN; tested via `caplog`.
- [ ] Proposal lookup returns the newest non-rejected proposal per study; all-rejected gives no key in the dict; tested.
- [ ] Anchor-trials lookup only fires when `anchor.baseline_metric IS NULL` (assert via query counter or `caplog` debug).
- [ ] `repo.__all__` includes `get_chain_for_study` and `ChainTraversalResult`.
- [ ] `make test-integration` green; new tests run under `backend/tests/integration/test_studies_chain_repo.py`.

---

### Story 1.3 — `GET /api/v1/studies/{study_id}/chain` router

**Outcome:** `backend/app/api/v1/studies.py` gains a new `GET /studies/{study_id}/chain` endpoint returning the `StudyChainResponse` per spec §8.3. Wires the repo traversal (Story 1.2) into the domain aggregation (Story 1.1). Reuses the existing `_err` helper for 404.

**New files**

_None._

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Add `GET /studies/{study_id}/chain` handler `get_study_chain(study_id, db)`. Builds the `StudyChainResponse` from `repo.get_chain_for_study(db, study_id)` + the three domain helpers from Story 1.1. Returns 404 `STUDY_NOT_FOUND` when repo returns `None`. Mounted at the end of the studies router (after `list_study_trials`). |
| `backend/app/api/v1/schemas.py` | Add `StudyChainLink` (12 fields per spec §8.3) + `StudyChainResponse` (8 fields per spec §8.3) Pydantic models. |
| `backend/tests/integration/test_studies_chain_api.py` (NEW) | DB-backed happy-path tests: AC-3 (3-link chain), AC-4 (404 unknown), AC-5 (non-chained single-study), AC-8 (in-flight stop_reason), AC-9 (cancelled), AC-10 (failed), proposal-rejected exclusion. |
| `backend/tests/contract/test_studies_chain_contract.py` (NEW) | Response shape (top-level keys), `links[]` item keys, `stop_reason` enum values match `CHAIN_STOP_REASONS` frozenset, `direction` enum values, `STUDY_NOT_FOUND` 404 envelope shape. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}/chain` | — (no body, no query params, no headers beyond defaults) | `200 OK` `StudyChainResponse` per spec §8.3 (top-level `anchor_study_id, best_link_id, best_metric, cumulative_lift, direction, stop_reason, proposal_id_for_best_link, links[]`; per-link 12 fields) | `404 STUDY_NOT_FOUND` (`{ "detail": { "error_code": "STUDY_NOT_FOUND", "message": "study {id} not found", "retryable": false } }`) |

Auth dependency: none (single-tenant, no auth surface in MVP1–MVP3).

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py — added near StudyDetail
from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from backend.app.domain.study.chain_summary import ChainStopReason

class StudyChainLink(BaseModel):
    id: str
    name: str
    status: Literal["queued", "running", "completed", "cancelled", "failed"]
    best_metric: float | None
    baseline_metric: float | None
    direction: Literal["maximize", "minimize"]
    delta_from_prev: float | None
    proposal_id: str | None
    auto_followup_depth_remaining: int | None
    failed_reason: str | None
    created_at: datetime
    completed_at: datetime | None

class StudyChainResponse(BaseModel):
    anchor_study_id: str
    best_link_id: str | None
    best_metric: float | None
    cumulative_lift: float | None
    direction: Literal["maximize", "minimize"]
    stop_reason: ChainStopReason  # reuses Literal from chain_summary.py
    proposal_id_for_best_link: str | None
    links: list[StudyChainLink]
```

**Key interfaces**

```python
# backend/app/api/v1/studies.py — added after list_study_trials (line ~750)
@router.get(
    "/studies/{study_id}/chain",
    response_model=StudyChainResponse,
    tags=["studies"],
)
async def get_study_chain(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudyChainResponse:
    """Return the rolled-up chain summary for the study and its lineage (FR-3)."""
    traversal = await repo.get_chain_for_study(db, study_id)
    if traversal is None:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)

    anchor = traversal.links[0]
    direction = anchor.objective.get("direction", "maximize")  # FR-3 + studies.py:165 pattern
    stop_reason = derive_chain_stop_reason(traversal.links, traversal.anchor_trials)
    cumulative_lift = compute_cumulative_lift(traversal.links, traversal.anchor_trials)
    best_link_id = select_best_link(traversal.links)
    # Map best metric + best link's proposal selection from the traversal result.
    best_metric = next((lk.best_metric for lk in traversal.links if lk.id == best_link_id), None)
    proposal_id_for_best_link = (
        traversal.proposal_id_by_link_id.get(best_link_id) if best_link_id else None
    )

    # Build per-link entries with delta_from_prev computed pairwise.
    link_entries: list[StudyChainLink] = []
    prev_metric: float | None = None
    for lk in traversal.links:
        link_direction = lk.objective.get("direction", "maximize")
        delta = _direction_normalized_delta_from_prev(lk.best_metric, prev_metric, link_direction) if prev_metric is not None or link_entries else None
        # Anchor MUST emit delta_from_prev = None per spec §8.3.
        if not link_entries:
            delta = None
        link_entries.append(StudyChainLink(
            id=lk.id,
            name=lk.name,
            status=lk.status,
            best_metric=lk.best_metric,
            baseline_metric=lk.baseline_metric,
            direction=link_direction,
            delta_from_prev=delta,
            proposal_id=traversal.proposal_id_by_link_id.get(lk.id),
            auto_followup_depth_remaining=lk.config.get("auto_followup_depth"),
            failed_reason=lk.failed_reason,
            created_at=lk.created_at,
            completed_at=lk.completed_at,
        ))
        prev_metric = lk.best_metric

    return StudyChainResponse(
        anchor_study_id=traversal.anchor_id,
        best_link_id=best_link_id,
        best_metric=best_metric,
        cumulative_lift=cumulative_lift,
        direction=direction,
        stop_reason=stop_reason,
        proposal_id_for_best_link=proposal_id_for_best_link,
        links=link_entries,
    )
```

**Tasks**

1. Add `StudyChainLink` and `StudyChainResponse` to `backend/app/api/v1/schemas.py`. Import `ChainStopReason` from `backend.app.domain.study.chain_summary` to share the Literal.
2. Add the handler to `backend/app/api/v1/studies.py` per the signature above; import `derive_chain_stop_reason`, `compute_cumulative_lift`, `select_best_link`, `_direction_normalized_delta_from_prev` from the domain module.
3. Anchor's `delta_from_prev` MUST be `None` regardless of computation (spec §8.3); the loop guards this with `not link_entries`.
4. No pagination, no query params, no auth (single-tenant MVP1-MVP3 per spec §6).
5. Integration tests: build the AC scenarios via the existing `seed*` test helpers in `backend/tests/integration/` (study row insertion happens through the model directly when the chaining engine isn't invoked); seed proposals via `repo.create_proposal`; verify the full response shape against AC-3, then assert error envelope on AC-4.
6. Contract tests: assert top-level keys = `{anchor_study_id, best_link_id, best_metric, cumulative_lift, direction, stop_reason, proposal_id_for_best_link, links}`; assert `links[]` item keys exactly match the 12-field set; assert `stop_reason` values are members of `CHAIN_STOP_REASONS` (import the frozenset and use it in the assertion); assert 404 error envelope on missing id.

**Definition of Done**

- [ ] `GET /api/v1/studies/{id}/chain` is mounted on the studies router and visible in `openapi.json` (verify in contract test via `app.openapi()`).
- [ ] AC-3 happy path passes in integration: 3-link chain, `best_link_id = S3`, `cumulative_lift = 0.14` (within 1e-9), `delta_from_prev = [null, 0.07, 0.02]`, `proposal_id_for_best_link = null` because S3 has no proposal.
- [ ] AC-4 returns `404 STUDY_NOT_FOUND` with the canonical envelope; tested at contract layer.
- [ ] AC-5 single-link non-chained study returns `links.length = 1`, `cumulative_lift = 0.09` for completed+best>baseline shape, `stop_reason = "depth_exhausted"`; tested at integration.
- [ ] AC-8 (in_flight), AC-9 (cancelled), AC-10 (parent_failed) stop_reason derivations covered by integration assertions.
- [ ] Proposal-rejected exclusion (D-11): when all proposals on the best link are `status='rejected'`, `proposal_id_for_best_link = null`; tested at integration.
- [ ] `make test-integration` + `make test-contract` green; coverage gate ≥ 80% holds.
- [ ] No new error codes added.

---

## Epic 2 — Frontend: chain-summary panel (FR-4)

### Story 2.1 — Extend `AutoFollowupChainPanel` with the rolled-up chain summary + `useStudyChain` hook

**Outcome:** `ui/src/components/studies/auto-followup-chain-panel.tsx` calls a new `useStudyChain(studyId)` hook (added to `ui/src/lib/api/studies.ts`) and renders the chain header, ordered link list with deltas, cumulative-lift row, best-config row (3-branch per D-11), and stop-reason row when the new render predicate (D-13) holds. Existing render rules for parent link + remaining-depth + direct-children table are preserved.

**Insertion point:** the existing panel at `ui/src/components/studies/auto-followup-chain-panel.tsx` is 120 lines today. New summary block lands inside `<CardContent>` after the existing `{hasChildren && …}` block (closing `)}` at line 116, before `</CardContent>` at line 117 — verified 2026-05-31). Header `<CardTitle>` keeps the existing "Auto-followup chain" label and `auto_followup_chain` glossary key for back-compat — the new summary block has its own `<h3>` header "Overnight chain — {N} studies" under the rolled-up section.

**New files**

_None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/studies.ts` | Add `useStudyChain(studyId)` hook returning `UseQueryResult<StudyChainResponse, ApiError>` with the D-10 refetch contract (window focus + post-cancel invalidation + status-transition invalidation + `refetchInterval` while `stop_reason === 'in_flight'` OR while bounded grace condition holds for `no_lift`/`budget`). Add `StudyChainResponse` + `StudyChainLink` type re-exports from `components['schemas']`. Wire `useCancelStudy` `onSuccess` to also `qc.invalidateQueries({ queryKey: ['studies', id, 'chain'] })`. |
| `ui/src/components/studies/auto-followup-chain-panel.tsx` | Read the panel's existing `study` + `chainChildren` props. Add `const chainQ = useStudyChain(study.id)`. Compute the D-13 predicate: `const showSummary = (chainQ.data?.links.length ?? 0) >= 2 || hasParent || chainQ.data?.links[0]?.auto_followup_depth_remaining != null`. Hide the panel entirely only when no chain context AND `!showSummary`. Render the new summary block when `showSummary && chainQ.data`. Implement the stop-reason wire→phrase mapping table. Implement the 3-branch `Best config` row per D-11. Add `data-testid="chain-summary"`. |
| `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` | Extend with AC-11 (rolled-up summary renders + cumulative-lift formatted `+0.0834` + stop-reason "no further improvement" + best-config link branch), AC-12a (single-link with opt-in), proposal-rejected → "Awaiting proposal", best_link_id null → "Best config: —". Preserve existing 7 test cases unchanged (they hit the `null` early-return AND the parent/depth/children rows that the new code keeps). Mock `useStudyChain` via `vi.mock('@/lib/api/studies')` returning each test scenario. |

**Endpoints consumed**

| Method | Path | Consumer | Notes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}/chain` | `useStudyChain` hook | New hook. Refetch contract per D-10. |

**Key interfaces**

```typescript
// ui/src/lib/api/studies.ts
export type StudyChainResponse = components['schemas']['StudyChainResponse'];
export type StudyChainLink = components['schemas']['StudyChainLink'];

export interface UseStudyChainOptions {
  /** Override default refetch contract — primarily for tests. */
  refetchInterval?: number | false;
}

export function useStudyChain(
  studyId: string,
  options: UseStudyChainOptions = {},
): UseQueryResult<StudyChainResponse, ApiError> {
  return useQuery<StudyChainResponse, ApiError>({
    queryKey: ['studies', studyId, 'chain'],
    queryFn: async () => {
      const { data } = await apiClient.get<StudyChainResponse>(
        `/api/v1/studies/${studyId}/chain`,
      );
      return data;
    },
    // D-10 grace + in-flight polling.
    refetchInterval: options.refetchInterval ?? ((query) => {
      const data = query.state.data;
      if (!data) return false;
      if (data.stop_reason === 'in_flight') return 15_000;
      if (data.stop_reason === 'no_lift' || data.stop_reason === 'budget') {
        const tail = data.links[data.links.length - 1];
        if (!tail?.completed_at) return false;
        const ageMs = Date.now() - new Date(tail.completed_at).getTime();
        return ageMs < 120_000 ? 15_000 : false;
      }
      return false;
    }),
    // refetchOnWindowFocus is TanStack's default — explicit for documentation.
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
}
```

**UI element inventory (added in this story)**

| Element | Type | Label/title | Data source | Interaction |
|---|---|---|---|---|
| Summary container | `<div data-testid="chain-summary">` | — | `chainQ.data` | rendered when D-13 predicate holds |
| Summary header | `<h3>` | `Overnight chain — {N} studies` (N = `links.length`) | `chainQ.data.links.length` | — |
| Header tooltip | `<InfoTooltip glossaryKey="auto_followup_chain" />` | — | existing key | hover/focus |
| Ordered link list | `<ol>` of `<li>` | each `{link.name} — {status} — best: {best_metric}{delta_from_prev formatted as ±0.0000}` | `chainQ.data.links[]` | each link's name is a `<Link>` to `/studies/{link.id}` |
| Cumulative-lift row | `<p data-testid="chain-summary-cumulative-lift">` | `Cumulative lift: {±0.0000}` or `—` when null | `chainQ.data.cumulative_lift` + `chainQ.data.direction` | tooltip with `glossaryKey="lift_gate"` |
| Best-config row (3-branch, D-11) | `<p data-testid="chain-summary-best-config">` | branch A: `<Link href="/proposals/{proposal_id_for_best_link}">{best_link.name}</Link>` · branch B: `Best config: {best_link.name} (Awaiting proposal)` plain text · branch C: `Best config: —` plain text | `chainQ.data.proposal_id_for_best_link` + `chainQ.data.best_link_id` | branch A is a link; branches B and C are not |
| Stop-reason row | `<p data-testid="chain-summary-stop-reason">` | `Stop reason: {phrase}` from mapping table | `chainQ.data.stop_reason` | tooltip: `auto_followup_depth` when `depth_exhausted`, `auto_followup_budget_skip` when `budget`, none otherwise |

**Stop-reason → phrase mapping table (FR-4)**

```typescript
// ui/src/components/studies/auto-followup-chain-panel.tsx
// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS
const CHAIN_STOP_REASON_PHRASE: Record<NonNullable<StudyChainResponse['stop_reason']>, string> = {
  depth_exhausted: 'depth budget exhausted',
  no_lift: 'no further improvement',
  budget: 'daily LLM budget reached',
  parent_failed: 'parent study failed or was cancelled',
  cancelled: 'operator cancelled the chain',
  in_flight: 'chain still running',
};
```

**State dependency analysis**

| State | Owned by | Read by | Action |
|---|---|---|---|
| `useStudyChain` query data | `useStudyChain` hook (per studyId) | `<AutoFollowupChainPanel>` | new — no existing reference |
| Existing `useStudyChildren` query data | `useStudyChildren` hook | `<AutoFollowupChainPanel>` parent in `/studies/[id]/page.tsx` | unchanged — still drives the direct-children table |
| `study.parent_study_id` prop | `<AutoFollowupChainPanel>` props | parent-link row | unchanged |
| Cross-component: `useCancelStudy.onSuccess` | `ui/src/lib/api/studies.ts:160` | study-detail page | extend to invalidate `['studies', id, 'chain']` |

**Tasks**

1. Regenerate TypeScript types (or hand-add to `components['schemas']` typing layer) so `StudyChainResponse` + `StudyChainLink` resolve from the OpenAPI schema. If the project uses `openapi-typescript`, run the generator; otherwise add hand-rolled type exports mirroring the Pydantic shapes from Story 1.3 (the project already has a `ui/src/lib/types.ts` shim for this).
2. Add `useStudyChain` to `ui/src/lib/api/studies.ts` per the snippet above. Add `qc.invalidateQueries({ queryKey: ['studies', id, 'chain'] })` to the existing `useCancelStudy.onSuccess` callback at line 160 area.
3. Add the status-transition invalidation: in `useStudy` consumers on `/studies/[id]/page.tsx`, when the existing `useStudy` query observes a transition from `running` to a terminal status, invalidate `['studies', id, 'chain']`. Implement via a small `useEffect` in `auto-followup-chain-panel.tsx` keyed on `study.status` — when status flips from `running` to `{completed, cancelled, failed}`, call `queryClient.invalidateQueries({ queryKey: ['studies', study.id, 'chain'] })`. (Avoids fanning the dependency back to `page.tsx`.)
4. Extend `auto-followup-chain-panel.tsx`: compute `showSummary` predicate (D-13). Render the new summary container after the existing `{hasChildren && …}` block.
5. Implement the `delta_from_prev` formatter: `delta == null ? '' : (delta >= 0 ? '+' : '') + delta.toFixed(4)`. Same formatter for `cumulative_lift`.
6. Implement the 3-branch `Best config` row per D-11.
7. Implement the stop-reason mapping table with the `// Source-of-truth:` comment cited above.
8. Update `null` early-return to also account for `chain.links[0]?.auto_followup_depth_remaining == null` (D-13 — render the summary even when no children spawned yet, as long as the operator opted in).
9. Extend the vitest spec with the new AC cases. Use `vi.mock('@/lib/api/studies', async (importOriginal) => { const mod = await importOriginal(); return { ...mod, useStudyChain: vi.fn() }; })` and per-test set the mock return.

**Legacy behavior parity**

No legacy behavior parity table — the existing panel is 120 LOC (under the 100-LOC delete/replace threshold's intent — see [implementation-plan-template.md L304](../../feature_templates/implementation-plan-template.md)) AND we are extending it in place, not deleting or migrating it. Every existing test case at `auto-followup-chain-panel.test.tsx:81-141` continues to pass unchanged — explicitly required by AC-12 and called out in DoD.

**Definition of Done**

- [ ] `useStudyChain` hook exists in `ui/src/lib/api/studies.ts` with the D-10 refetch contract; `useCancelStudy.onSuccess` invalidates the chain query.
- [ ] Panel renders `data-testid="chain-summary"` when D-13 predicate holds; rendering hidden for true non-chained studies.
- [ ] AC-11: rolled-up summary renders for the AC-3 payload — ordered link list, `Cumulative lift: +0.1400`, best-config row shows `"Best config: <S3.name> (Awaiting proposal)"` as plain text (not link) since S3 has no proposal; tested at vitest.
- [ ] AC-12a: single-link opt-in renders summary with `Cumulative lift: +0.0100`, `Stop reason: no further improvement`; tested.
- [ ] AC-12: panel returns `null` when no chain context AND no opt-in; existing test case at `auto-followup-chain-panel.test.tsx:80-83` passes unchanged.
- [ ] Proposal-rejected (D-11) branch B copy `(Awaiting proposal)`; tested.
- [ ] Best-link-id null (completed subset empty) branch C copy `Best config: —`; tested.
- [ ] Stop-reason mapping table is grounded by `// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS` comment; verified via grep.
- [ ] `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build` all green.
- [ ] E2E spec at `ui/tests/e2e/overnight-chain.spec.ts` (added in Story 4.2) passes against a real backend (no `page.route()`).

---

## Epic 3 — Wizard relabel + hint + glossary (FR-1, FR-2, FR-6)

### Story 3.1 — Relabel wizard control + add Deep-preset hint + new glossary key

**Outcome:** Wizard Step 5 in `create-study-modal.tsx` carries the `"🌙 Run overnight (compound automatically)"` label + the human-merge-boundary helper text + the new `overnight_autopilot` glossary key on the `<InfoTooltip>`. The Deep-preset hint appears when both gate conditions hold (D-13 of the spec re: hint gating in FR-2). `ui/src/lib/glossary.ts` carries the new `overnight_autopilot` entry. None of this changes the wire contract — the underlying `<Select>` still emits `undefined` for "Off" and `1..5` for the depth values.

**Insertion point:** `create-study-modal.tsx` line 1422 (`<Label htmlFor="cs-auto-followup">Auto-followup chain</Label>`) and line 1423 (`<InfoTooltip glossaryKey="auto_followup_depth" />`). Helper-text replacement at line 1447-1450. The Deep-preset hint inserts between the preset selector and the numeric inputs grid (around line 1300-1320 in the same file — locate the `presetLabel(deep)` mention and the `max_trials`/`time_budget_min` inputs to anchor the insertion).

**New files**

_None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | Add `overnight_autopilot` entry under the `feat_auto_followup_studies Story 3.1 — chain-panel + wizard entries` section (after the existing `auto_followup_depth` entry around line 877). |
| `ui/src/components/studies/create-study-modal.tsx` | (1) Replace line 1422 `<Label>` text from `"Auto-followup chain"` to `"🌙 Run overnight (compound automatically)"`. (2) Replace line 1423 `glossaryKey` from `"auto_followup_depth"` to `"overnight_autopilot"`. (3) Replace helper paragraph at line 1447-1450 with the exact FR-1 string. (4) Add the new Deep-preset hint conditional rendering: `{preset === 'deep' && (values.auto_followup_depth === undefined || values.auto_followup_depth === 0) && (<p role="note" data-testid="cs-overnight-hint" className="text-xs text-muted-foreground">💡 Tip — this is a long study. Enable '🌙 Run overnight (compound automatically)' below to chain follow-up runs while you're away.</p>)}`. Insertion point: between the `<Select>` preset block and the `<div>` that contains the numeric input grid (anchor by grepping for `presetLabel(deep)` and the `max_trials` input). Keep `data-testid="cs-auto-followup"` on the existing `<SelectTrigger>` (line 1436) for back-compat. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` (existing — verify and extend) | Extend (or add a focused new file `create-study-modal-overnight.test.tsx`) with AC-1: label string equals `"🌙 Run overnight (compound automatically)"` verbatim; AC-2 (hint show): pick Deep preset, leave depth Off, assert `data-testid="cs-overnight-hint"` renders with the exact copy; AC-2 (hint hide): set depth to 1, assert hint is gone. Audit any existing label assertion in the file that referenced `"Auto-followup chain"` and update to the new label. |
| `ui/src/__tests__/lib/glossary.test.ts` (existing — extend) | AC-14: assert `glossary.overnight_autopilot.short` is a string, length ≤ 120, contains verbatim `"you still open every PR"`; assert `glossary.overnight_autopilot.long` is a non-empty string. |

**UI element inventory (this story)**

| Element | Type | Label/title | Data source | Interaction |
|---|---|---|---|---|
| Wizard label | `<Label htmlFor="cs-auto-followup">` | `🌙 Run overnight (compound automatically)` | hardcoded | clicking focuses the SelectTrigger |
| Info tooltip on label | `<InfoTooltip glossaryKey="overnight_autopilot" />` | from glossary | hover/focus | shows `short` text |
| Helper paragraph | `<p className="text-xs text-muted-foreground">` | the exact FR-1 paragraph | hardcoded | none |
| Wizard `<Select>` (UNCHANGED) | existing | wire values `0..5` from `AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES` | `values.auto_followup_depth` | unchanged — `data-testid="cs-auto-followup"` retained |
| Deep-preset hint | `<p role="note" data-testid="cs-overnight-hint">` | the exact FR-2 paragraph | hardcoded | none |

**Enumerated value contract (FR-1)**

Wire values are unchanged: `AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES = [0, 1, 2, 3, 4, 5]` at `ui/src/lib/enums.ts:111` — the existing `// Values must match …` source-of-truth comment stays in place. Backend allowlist: `StudyConfigSpec.auto_followup_depth` validator at `backend/app/api/v1/schemas.py:710-723` enforces `0 ≤ n ≤ 5`. No story patches this contract.

**Glossary entry shape (FR-6)**

```typescript
// ui/src/lib/glossary.ts — added after the existing auto_followup_depth entry.
overnight_autopilot: {
  short:
    'Run additional studies overnight, each narrowing in on the previous winner. Stops on its own; you still open every PR.',
  long: [
    'When you enable this, RelyLoop runs follow-up studies automatically after each study completes — every follow-up narrows the search space around the previous winner and runs deterministically while you sleep.',
    '',
    'The chain stops on its own: when there is no further improvement, when the daily LLM budget caps out, when a study fails, or when the depth counter hits zero.',
    '',
    'RelyLoop never opens a pull request automatically. The chain ends with a proposal you review — you still open every PR.',
  ].join('\n'),
  ariaLabel: 'More information about the overnight autopilot',
},
```

**Tasks**

1. Edit `ui/src/lib/glossary.ts`: add the `overnight_autopilot` entry as above. Verify no key collision with `grep '"overnight_autopilot"' ui/src/lib/glossary.ts` returning exactly 1 hit.
2. Edit `ui/src/components/studies/create-study-modal.tsx`:
   - Line 1422: replace `Auto-followup chain` → `🌙 Run overnight (compound automatically)`.
   - Line 1423: replace `glossaryKey="auto_followup_depth"` → `glossaryKey="overnight_autopilot"`.
   - Lines 1447-1450: replace helper paragraph with the exact FR-1 text.
   - Add the hint block above the numeric inputs grid in Step 5 (anchored by grepping for the `Deep (1000)` selector block + the `max_trials` numeric input).
3. Update or add `create-study-modal.test.tsx` cases for AC-1 and AC-2 (both show + hide).
4. Update `glossary.test.ts` for AC-14.
5. Run `cd ui && pnpm test --filter create-study-modal --filter glossary` until both new specs pass.
6. Run `cd ui && pnpm typecheck && pnpm lint`. The `ShortGlossaryKey`/`LongGlossaryKey` derived types at `ui/src/lib/glossary.ts:906-916` will pick up the new key automatically.

**Tooltips and contextual help (this story)**

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment target | JSX pattern |
|---|---|---|---|---|---|---|
| Wizard label | `glossary.overnight_autopilot.short` (from key) | hover/focus on info icon | right of label | `overnight_autopilot` (NEW) | `// added in ui/src/lib/glossary.ts under feat_overnight_autopilot FR-6` | `<InfoTooltip glossaryKey="overnight_autopilot" />` (matches the pattern at `ui/src/components/common/info-tooltip.tsx` and existing usage at `create-study-modal.tsx:1423`) |
| Wizard hint | (none — the hint IS the help text) | — | inline | — | — | `<p role="note" data-testid="cs-overnight-hint" className="text-xs text-muted-foreground">…</p>` |

**Definition of Done**

- [ ] `ui/src/lib/glossary.ts` carries `overnight_autopilot` with `short` ≤ 120 chars and the verbatim phrase `"you still open every PR"`; `long` is a non-empty string.
- [ ] `glossary.test.ts` value-lock case passes (AC-14).
- [ ] Wizard label text equals `"🌙 Run overnight (compound automatically)"` verbatim; tested.
- [ ] Wizard `<InfoTooltip>` carries `glossaryKey="overnight_autopilot"`; tested via `data-testid` on the icon container OR by asserting `byText` of the new short string in the tooltip body.
- [ ] Helper text equals the FR-1 paragraph verbatim; tested.
- [ ] Deep-preset hint renders only when `preset === 'deep' && (auto_followup_depth ∈ {undefined, 0})`; depth = 1 hides the hint within the same render cycle; tested for both AC-2 directions.
- [ ] Hint carries `data-testid="cs-overnight-hint"` and `role="note"`.
- [ ] No change to `AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES` or any submit-payload assertion in the wizard test suite; verified by green vitest run on the wizard tests not touched by this story.
- [ ] `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build` all green.

---

## Epic 4 — Tutorial + docs (FR-5 + §15 doc updates)

### Story 4.1 — Tutorial: add "Run the loop overnight" + ship the four §15 doc updates

**Outcome:** `docs/08_guides/tutorial-first-study.md` gets the new H2 step + the explicit human-merge boundary language. The three §15 doc files (`api-conventions.md`, `data-model.md`, `ui-architecture.md`) get the small text additions called out in the spec.

**New files**

_None._

**Modified files**

| File | Change |
|---|---|
| `docs/08_guides/tutorial-first-study.md` | Add new H2 `## Step 12 — Run the loop overnight` after the existing `## Step 11 — (Optional) Upgrade your judgment list to UBI` and before `## Where to next`. Content walks the 5 steps from FR-5 (pick `Deep (1000)`, enable `🌙 Run overnight (compound automatically)` at depth 3, start before logging off, review the chain-summary panel in the morning, open the winning PR), names the human-merge boundary verbatim, and references the cancel cascade affordance (`POST /studies/{id}/cancel?cascade=true` default). |
| `docs/01_architecture/api-conventions.md` | Add a row for `GET /api/v1/studies/{id}/chain` in the studies sub-resource list (mirrors the format of the existing `GET /studies/{id}/children` row). |
| `docs/01_architecture/data-model.md` | Add a one-line note under the studies-table description: "Chain lineage is the linear walk through `parent_study_id`; rolled-up summaries computed on-read at `GET /api/v1/studies/{id}/chain` (no schema change)." |
| `docs/01_architecture/ui-architecture.md` | Add a paragraph noting the chain-summary surface on the study detail page (mirrors the UBI-panel paragraph). One-paragraph addition; cites D-10 for the refetch contract and D-11/D-13 for the panel render predicate. |
| `state.md` | After merge, prepend the one-line entry for this feature to "Last 5 merges (newest first)" and drop the oldest row. Update "Active feature" if applicable. |

**Tutorial section skeleton (FR-5 / AC-13)**

```markdown
## Step 12 — Run the loop overnight

You picked a `Deep (1000)` budget in Step 5 because the search space is wide
enough that one study can only sample a sliver. Overnight autopilot makes
each next study start where the last one left off — every follow-up
narrows around the previous winner, runs deterministically, and stops on
its own when the lift plateaus.

1. Open the **Create study** wizard. Pick the **Deep (1000)** preset.
2. Set **🌙 Run overnight (compound automatically)** to **depth 3**.
3. Click **Create study** before logging off.
4. In the morning, open the study detail page. The **Overnight chain**
   panel summarises what ran, the cumulative lift across the chain, which
   link won, and the stop reason.
5. The summary points at a proposal — click it, review the diff, open the
   PR. (You can also use the cancel button on any mid-chain study with
   `?cascade=true` (the default) to halt pending children.)

**RelyLoop runs the exploration overnight unattended, but it never opens
a PR on your behalf. The chain ends with a proposal you review and merge
— your one decision.**
```

**Tasks**

1. Edit `docs/08_guides/tutorial-first-study.md`. Insert the new H2 section between Step 11 and `## Where to next` per the skeleton above.
2. Edit `docs/01_architecture/api-conventions.md`: locate the studies sub-resource list (grep for `/studies/{id}/children`) and add the new row for `/chain`.
3. Edit `docs/01_architecture/data-model.md`: locate the studies-table description (grep for `parent_study_id`) and add the one-line note.
4. Edit `docs/01_architecture/ui-architecture.md`: add the chain-summary paragraph adjacent to the UBI-panel paragraph.
5. After Stories 1.1–3.1 + E2E land and CI is green, prepend the merge one-liner to `state.md` "Last 5 merges" and drop the oldest row.

**Definition of Done**

- [ ] `tutorial-first-study.md` contains the new H2 with all 5 numbered steps + the verbatim human-merge boundary paragraph; rendered Markdown is well-formed (no broken inline code, no orphan links).
- [ ] `api-conventions.md` lists the new endpoint row.
- [ ] `data-model.md` notes the on-read derivation.
- [ ] `ui-architecture.md` describes the chain-summary panel + cites D-10/D-11/D-13.
- [ ] AC-13 covered.
- [ ] `state.md` updated at the end of the feature branch.
- [ ] No new runbook (per spec §15 — existing study/auto-followup runbooks cover the engine).

---

### Story 4.2 — E2E spec for the chain-summary panel

**Outcome:** A new Playwright spec at `ui/tests/e2e/overnight-chain.spec.ts` seeds a 3-link chain via API helpers, attaches a proposal to the middle link, navigates to the anchor's detail page, and asserts the chain-summary surface renders with the expected content.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/overnight-chain.spec.ts` | E2E coverage: seed via `seedAutoFollowupChain` (existing helper at `ui/tests/e2e/helpers/seed.ts`); attach a proposal to the middle link via `POST /api/v1/proposals` (existing endpoint); navigate to `/studies/{anchorId}`; assert `data-testid="chain-summary"` is visible with the 3 link names, cumulative-lift formatted as `±0.0NNN`, stop-reason phrase, and best-config link/plain-text branch. Real-backend interaction per CLAUDE.md E2E rules — no `page.route()` mocking. |

**Modified files**

_None_ (helpers reused as-is).

**Tasks**

1. Author `overnight-chain.spec.ts`. Anchor to the existing `auto-followup.spec.ts` patterns (real-backend `seedAutoFollowupChain` + `seedFullChain` from `helpers/seed.ts`).
2. Setup via API helpers only (cluster + queryset + judgment list + chain seed + proposal creation). Use the existing `seedAutoFollowupChain(N)` helper at `ui/tests/e2e/helpers/seed.ts` — verify that it can return enough metadata to attach a proposal (best-link id is exposed); if not, add a small `seedChainProposal(linkId)` helper inline in the spec calling `POST /api/v1/proposals` directly.
3. Use `page.goto(`/studies/${anchorId}`)` + `page.getByTestId('chain-summary')` + `expect(...).toBeVisible()` and subsequent `getByText` assertions for the cumulative-lift line, stop-reason phrase, and best-config CTA. Do not mock backend requests with `page.route()`.
4. Skip-gate (deferred): if the existing chaining engine requires depth-3 children to complete before the worker enqueues the next link, and the E2E flow can't reasonably wait for that, the spec MAY accept the post-seed in-flight stop_reason (assert `Stop reason: chain still running` instead of `no further improvement`). Choose the path that completes deterministically in <30s; document the choice in a comment block at the top of the spec.

**Definition of Done**

- [ ] `ui/tests/e2e/overnight-chain.spec.ts` exists and passes against a real backend (`make up` + worker running).
- [ ] Spec asserts: panel visible by `data-testid`, expected link names visible, cumulative-lift line rendered with the `±0.0NNN` format, stop-reason phrase visible, best-config branch verified (link target OR `(Awaiting proposal)` plain text).
- [ ] No `page.route()` calls anywhere in the spec.
- [ ] Spec runs under the `pnpm test:e2e:stable` job (no new flake patterns).

---

## UI Guidance (frontend-facing work)

### Reference: current component structure

**`ui/src/components/studies/auto-followup-chain-panel.tsx`** — 120 LOC.

| Section | Lines | Description |
|---|---|---|
| Imports + props interface | 1-22 | `Link`, `InfoTooltip`, `Card`/`CardContent`/`CardHeader`/`CardTitle`, `StudyDetail`/`StudySummary`. Props: `study: StudyDetail`, `chainChildren: StudySummary[]`. |
| Derivation locals | 41-46 | `parentId`, `depth`, `hasParent`, `hasDepth`, `hasChildren` |
| Null early-return | 48-51 | when `!hasParent && !hasDepth && !hasChildren` |
| `<Card data-testid="auto-followup-chain-panel">` | 53-119 | parent-link row (62-72) + remaining-depth row (73-80) + children table (81-116) |

State variables today: none — pure render from props.

**Insertion point for the new summary block:** inside `<CardContent>` after the closing `)}` of the children-table block at line 116, before the `</CardContent>` at line 117.

**`ui/src/components/studies/create-study-modal.tsx`** — large (~1500 LOC).

| Section | Anchor (grep target) | Description |
|---|---|---|
| Preset selector block | `presetLabel(deep)` near line 105 + the `<Select>` rendering the four preset values | The four-option preset select that drives `max_trials`/`time_budget_min` writes |
| Numeric inputs grid | `Max trials` input around line 1300 area | the `max_trials` + `time_budget_min` + `seed` inputs |
| Auto-followup row | line 1420-1451 | the row we're relabeling |

**Insertion point for the Deep-preset hint:** between the preset selector block and the numeric inputs grid. Anchor by grepping for the `presetLabel(deep)` mention OR the `Provide either max trials or a time budget` helper paragraph at line 1411-1413 — the hint goes ABOVE that helper, immediately after the preset selector's closing tag.

### Analogous markup patterns

The new summary block models on the existing `<CardContent>` rows in `auto-followup-chain-panel.tsx`:

```tsx
{/* Pattern: row with InfoTooltip — from auto-followup-chain-panel.tsx:73-80 */}
<p data-testid="auto-followup-remaining-depth">
  Remaining auto-follow-ups: <span className="font-medium">{depth}</span>
  <span className="ml-2 inline-flex">
    <InfoTooltip glossaryKey="auto_followup_depth" />
  </span>
</p>
```

Apply the same pattern to `Cumulative lift`, `Stop reason`. For the link-list (per-link `<Link>` to `/studies/{id}`), reuse the existing children-table pattern at line 96-102:

```tsx
{/* Pattern: link to study detail — from auto-followup-chain-panel.tsx:96-102 */}
<Link
  href={`/studies/${child.id}`}
  className="text-blue-600 underline-offset-4 hover:underline"
>
  {child.name}
</Link>
```

For the best-config branch-A link to `/proposals/{id}`, mirror the existing proposal link at `ui/src/app/studies/[id]/page.tsx:99-106`:

```tsx
{/* Pattern: link to proposal — from page.tsx:99-106 */}
<Link
  href={`/proposals/${proposalId}`}
  className="text-blue-600 underline-offset-4 hover:underline"
>
  view proposal
</Link>
```

The wizard hint mirrors the existing wizard helper-paragraph pattern at `create-study-modal.tsx:1447-1450`:

```tsx
{/* Pattern: muted helper text — from create-study-modal.tsx:1447-1450 */}
<p className="text-xs text-muted-foreground">
  Run additional studies overnight, each narrowing around the previous winner. Halts
  on no lift, exhausted budget, or failed parent.
</p>
```

(The new hint adds `role="note"` + `data-testid="cs-overnight-hint"`.)

### Layout and structure

- Chain-summary block sits at the bottom of `<CardContent>`, after the existing children-table block. Visual hierarchy: header (h3) → ordered list → summary metric rows (cumulative-lift / best-config / stop-reason).
- Numeric formatting: cumulative-lift and per-link `delta_from_prev` use `±0.0000` (4 decimal places). Negative values are rendered with a leading `-`; positive with a leading `+`.
- The new block does NOT introduce any new card or modal — it lives inside the existing `<Card>`.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Operator navigates to `/studies/{id}` | `useStudyChain(studyId)` fires automatically (TanStack `enabled: true` default) | `GET /api/v1/studies/{id}/chain` |
| Window focuses (returns from background tab) | TanStack default `refetchOnWindowFocus` triggers refetch | `GET /api/v1/studies/{id}/chain` |
| Operator clicks Cancel on the study | `useCancelStudy.onSuccess` invalidates `['studies', id, 'chain']` → refetch | `POST /studies/{id}/cancel`; then `GET /chain` |
| Study transitions `running → terminal` (observed via `useStudy`) | `useEffect` in the panel invalidates `['studies', id, 'chain']` | `GET /chain` |
| Stop reason is `in_flight` | Hook keeps polling every 15s | `GET /chain` every 15s |
| Stop reason is `no_lift` or `budget` AND tail.completed_at < 120s old | Hook polls 15s (D-10 grace window) | `GET /chain` every 15s for ≤ 4 ticks |
| Stop reason is `depth_exhausted` / `parent_failed` / `cancelled` | Hook stops polling | — |
| Operator clicks the best-link `<Link>` (branch A) | client-side route to `/proposals/{id}` | none |

### Component composition

- The new summary block stays inline in `auto-followup-chain-panel.tsx`. No new extracted component — the conditional rendering and the stop-reason mapping are simple enough to keep co-located. (When the convergence-indicator sibling feature lands, that may extract a `ChainSummaryRows` subcomponent; out of scope here.)

### Information architecture placement

- **Wizard control (FR-1):** stays in Step 5 of the create-study modal — same row as the existing auto-followup `<Select>`. No new step, no navigation move.
- **Chain summary (FR-4):** stays inside the existing `AutoFollowupChainPanel` mounted at `ui/src/app/studies/[id]/page.tsx:109`, between `LinkedEntitiesRow` and `ConfidencePanel`. No new page, no new card outside the existing one.
- **Discovery:** operators discover the chain surface by visiting any study detail page; no new sidebar entry, no new tab.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment target | JSX pattern |
|---|---|---|---|---|---|---|
| Wizard label | `glossary.overnight_autopilot.short` | hover/focus on info icon | right of label | `overnight_autopilot` (NEW — added in `ui/src/lib/glossary.ts` under FR-6) | `// from FR-6 — added to ui/src/lib/glossary.ts` | `<InfoTooltip glossaryKey="overnight_autopilot" />` (pattern at `info-tooltip.tsx`) |
| Wizard inline hint | (none — hint IS the text) | — | inline beneath preset row | — | — | `<p role="note" data-testid="cs-overnight-hint" …>` |
| Panel header (existing) | `glossary.auto_followup_chain.short` | hover/focus | right of `<CardTitle>` | `auto_followup_chain` (existing, reused) | already cited in `glossary.ts:878` | unchanged |
| Remaining-depth row (existing) | `glossary.auto_followup_depth.short` | hover/focus | right of value | `auto_followup_depth` (existing, reused) | already cited | unchanged |
| Cumulative-lift row (NEW) | `glossary.lift_gate.short` | hover/focus | right of label | `lift_gate` (existing, reused) | already cited | `<InfoTooltip glossaryKey="lift_gate" />` |
| Stop-reason mapping `depth_exhausted` (NEW) | `glossary.auto_followup_depth.short` | hover/focus on info icon | right of mapped phrase | `auto_followup_depth` (existing, reused) | already cited | `<InfoTooltip glossaryKey="auto_followup_depth" />` |
| Stop-reason mapping `budget` (NEW) | `glossary.auto_followup_budget_skip.short` | hover/focus on info icon | right of mapped phrase | `auto_followup_budget_skip` (existing, reused) | already cited | `<InfoTooltip glossaryKey="auto_followup_budget_skip" />` |

### Visual consistency

- The new rows use the same `text-sm` typography as the existing `<CardContent className="space-y-3 text-sm">` rules at `auto-followup-chain-panel.tsx:61`.
- The cumulative-lift formatter shares the `(n) => n.toFixed(4)` pattern from the children-table `best_metric` cell at line 108.
- Links inside the summary block use the existing `text-blue-600 underline-offset-4 hover:underline` class chain.

### Legacy behavior parity

No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. `AutoFollowupChainPanel` is being extended in place (lines 1-120 remain; new block appended after line 116). The existing 7 vitest cases at `auto-followup-chain-panel.test.tsx:80-141` continue to pass unchanged; this is captured in Story 2.1 DoD.

### Client-side persistence

N/A — this feature uses no `localStorage` / `sessionStorage` / cookies.

---

## 3) Testing workstream

### 3.1 Unit tests
- **Location:** `backend/tests/unit/domain/study/test_chain_summary.py`
- **Scope:** pure-function coverage of `derive_chain_stop_reason`, `compute_cumulative_lift`, `select_best_link`, `_direction_normalized_delta_from_prev`.
- **Tasks:**
  - [ ] AC-6 (no_lift via baseline) + minimize companion
  - [ ] AC-7 (depth_exhausted)
  - [ ] AC-8 (in_flight)
  - [ ] AC-9 (cancelled)
  - [ ] AC-10 (parent_failed)
  - [ ] AC-5 single-link non-chained study (cumulative_lift + best_link_id + stop_reason)
  - [ ] cumulative_lift maximize + minimize direction flip
  - [ ] cumulative_lift baseline-null first-decile fallback + first-decile-None edge
  - [ ] select_best_link tie-break on created_at
  - [ ] select_best_link completed-subset-empty → None
  - [ ] delta_from_prev minimize sign-flip + null-on-either-side
- **DoD:** all branches covered; tests deterministic; no fixtures touch DB.

### 3.2 Integration tests
- **Locations:** `backend/tests/integration/test_studies_chain_repo.py` (Story 1.2) + `backend/tests/integration/test_studies_chain_api.py` (Story 1.3)
- **Scope:** DB-backed traversal + endpoint behavior.
- **Tasks:**
  - [ ] linear 3-link chain happy path (AC-3 shape)
  - [ ] anchor-only single-link payload (AC-5)
  - [ ] AC-4 404 STUDY_NOT_FOUND
  - [ ] AC-8 in_flight stop_reason (queued/running link present)
  - [ ] AC-9 cancelled tail
  - [ ] AC-10 failed tail
  - [ ] proposal selection: multiple non-rejected proposals → newest wins; all-rejected → null
  - [ ] anchor-trials fetched ONLY when `anchor.baseline_metric IS NULL`
  - [ ] upward walk 10-hop cap with seeded cyclic data (degraded-anchor log via `caplog`)
  - [ ] downward `LIMIT 1` truncation with seeded fan-out + WARN log
- **DoD:** happy + every documented stop_reason + 404 + edge cases (rejected proposals, fan-out detection, cap) green.

### 3.3 Contract tests
- **Location:** `backend/tests/contract/test_studies_chain_contract.py` (new)
- **Scope:** endpoint shape, status codes, error envelope, enum coverage.
- **Tasks:**
  - [ ] response top-level keys = `{anchor_study_id, best_link_id, best_metric, cumulative_lift, direction, stop_reason, proposal_id_for_best_link, links}`
  - [ ] `links[]` item keys = the 12-field set
  - [ ] `stop_reason` values are members of `CHAIN_STOP_REASONS` frozenset (import & assert)
  - [ ] `direction` values are `"maximize"` or `"minimize"`
  - [ ] `STUDY_NOT_FOUND` 404 envelope shape `{ "detail": { "error_code", "message", "retryable": false } }`
- **DoD:** every documented error code (`STUDY_NOT_FOUND` is the only one) covered; OpenAPI surface includes the new endpoint (verify via `app.openapi()`).

### 3.4 Vitest (UI unit/component)
- **Locations:**
  - `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` (extended)
  - `ui/src/__tests__/components/studies/create-study-modal.test.tsx` (extended) OR `ui/src/__tests__/components/studies/create-study-modal-overnight.test.tsx` (new focused file)
  - `ui/src/__tests__/lib/glossary.test.ts` (extended)
- **Tasks:**
  - [ ] AC-1 wizard label string verbatim
  - [ ] AC-2 hint show (Deep + Off)
  - [ ] AC-2 hint hide (Deep + depth≥1)
  - [ ] AC-11 rolled-up summary renders, cumulative-lift formatted `+0.1400`, best-config Awaiting-proposal branch
  - [ ] AC-12 hide-when-no-chain-context still passes (existing case unchanged)
  - [ ] AC-12a single-link with opt-in renders summary
  - [ ] D-11 branch B `(Awaiting proposal)` rendered as plain text when all proposals rejected
  - [ ] D-11 branch C `Best config: —` when `best_link_id = null`
  - [ ] Stop-reason mapping table renders the expected phrase for each of the 6 wire values
  - [ ] AC-14 `glossary.overnight_autopilot` value-lock (short ≤ 120 + verbatim phrase)
- **DoD:** all of the above pass; existing 7 panel test cases unchanged.

### 3.5 E2E tests
- **Location:** `ui/tests/e2e/overnight-chain.spec.ts` (new — Story 4.2)
- **Rule:** real backend, no `page.route()` mocking, real browser interactions via `page` object.
- **Tasks:**
  - [ ] seed chain via API + attach proposal to middle link
  - [ ] navigate to anchor's `/studies/{id}` page
  - [ ] assert `data-testid="chain-summary"` visible
  - [ ] assert link names + cumulative-lift line + stop-reason phrase visible
  - [ ] assert best-config branch (link OR `(Awaiting proposal)` per seeded state)
- **DoD:** spec passes on `pnpm test:e2e:stable`; no new flake patterns.

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` | renders parent link + depth + children table; `auto-followup-chain-panel` testid | ~7 cases (lines 77-142) | Extend with new cases AC-11/AC-12a/D-11 branches/stop-reason mapping. Existing 7 cases stay unchanged (panel header text + render-null path + children-table rendering all preserve). |
| `ui/src/__tests__/components/studies/create-study-modal.*.test.tsx` | `"Auto-followup chain"` label string | TBD — `grep` at impl time | Update any case that asserts on the verbatim string `"Auto-followup chain"` to the new `"🌙 Run overnight (compound automatically)"`. Wire values 0..5 and submit-payload shape unchanged, so any payload-asserting cases stay green. |
| `backend/tests/contract/test_studies_*.py` | `/children` contract | unchanged | No change — `/children` semantics unchanged; only NEW `/chain` is added. |
| `backend/tests/integration/test_studies_api.py` | studies CRUD | unchanged | No change. |
| `backend/tests/integration/test_auto_followup.py` | chain engine behavior | unchanged | No change — engine is read-only for this feature. |
| `ui/tests/e2e/auto-followup.spec.ts` | wizard depth selector + remaining-depth indicator | unchanged | No change — wire contract unchanged, `data-testid="cs-auto-followup"` preserved. The spec's label assertions (if any) must be reviewed at impl time and updated to the new wizard label. |
| `ui/src/__tests__/lib/glossary.test.ts` | glossary value locks | extended | Extend with AC-14 case. |

### 3.7 Migration verification

**N/A — no schema change in this feature.** Alembic head remains `0022_solr_engine_auth_check`. No `make migrate` needed for any story.

### 3.8 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`
- [ ] `pnpm test:e2e:stable` (or whichever target wraps the project's Playwright stable profile)

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update on final merge:
- [ ] "Last 5 merges (newest first)" — prepend one-line entry; drop the oldest
- [ ] "Active feature" — clear to none (or to the next MVP2 feature in the queue)
- [ ] No Alembic head movement (no migration this feature)

**`architecture.md`** — no update needed (no new top-level layer, no new topical doc, no new critical flow). The chain endpoint slots into the existing `backend/app/api/v1/studies.py` router that `architecture.md` already lists.

**`CLAUDE.md`** — no update needed (no new conventions, no new env vars, no new build commands).

### 4.1 Architecture docs
- [ ] `docs/01_architecture/api-conventions.md` — add `/chain` row (Story 4.1)
- [ ] `docs/01_architecture/data-model.md` — one-line note re chain summary derivation (Story 4.1)
- [ ] `docs/01_architecture/ui-architecture.md` — note the chain-summary surface (Story 4.1)

### 4.2 Product docs
- [ ] No `docs/02_product/` change

### 4.3 Runbooks
- [ ] No new runbook (per spec §15)

### 4.4 Security docs
- [ ] No change

### 4.5 Quality docs
- [ ] No change

### Documentation DoD
- [ ] `state.md` reflects the merge.
- [ ] Three `docs/01_architecture/` files updated and merged.
- [ ] Tutorial section live at `docs/08_guides/tutorial-first-study.md`.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Avoid duplicating `compute_first_decile_max` / `_direction_normalized_lift` from `backend/app/domain/study/auto_followup.py` — `chain_summary.py` imports and reuses them.
- Avoid duplicating the stop-reason wire→phrase mapping — keep it in one place (the panel module) with a `// Source-of-truth:` comment back to the backend frozenset.

### 5.2 Planned refactor tasks
- [ ] Reuse `compute_first_decile_max` from `auto_followup.py` (do not copy).
- [ ] Reuse `_direction_normalized_lift` from `auto_followup.py` (do not copy).
- [ ] Keep stop-reason phrase mapping in exactly one frontend module; source-of-truth comment cites `chain_summary.py CHAIN_STOP_REASONS`.

### 5.3 Refactor guardrails
- [ ] No change to `auto_followup.py` itself — it stays untouched (CLAUDE.md "engine read-only" invariant for this feature per spec §4 anti-patterns).
- [ ] No new shared util layer — the domain reuse is direct cross-module import.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_auto_followup_studies` (chaining engine) | All stories | Shipped (PR #223, 2026-05-24) | N/A |
| `feat_study_baseline_trial` (`baseline_metric` column) | Story 1.1 (cumulative_lift) | Shipped (2026-05-25) | N/A — graceful fallback to first-decile |
| `feat_study_sub_warmup_guard` (warmup floor) | Story 4.1 (tutorial cross-reference only) | Shipped (PR #316, 2026-05-29) | N/A |
| `feat_ubi_judgments` | Story 4.1 (tutorial cross-reference only — Step 11 anchor) | Shipped (PR #317, 2026-05-29) | N/A |
| `feat_study_convergence_indicator` (idea-stage sibling) | None for this plan — sibling will extend `links[]` later | Idea-stage | Low — response shape is extensible |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Downward walk's seq-scan on `studies.parent_study_id` (no index) regresses at scale | Low | Low (deployments are tens to low-hundreds of studies — spec §13) | Documented in spec §13. If a future deployment exceeds ~10k studies, add `ix_studies_parent_study_id` migration as a separate spec. |
| Hint copy might cause noise for operators who chose Deep without wanting overnight | Low | Low | Hint is `role="note"` muted text and disappears the moment the operator opts in or picks a different preset. |
| `useStudyChain` poll interval (15s during grace) might race with the tail's `completed_at` mutation | Low | Low | Grace window is bounded at 120s (4 polls); after that the hook stops. The race resolves naturally as the chain transitions to a terminal state. |
| OpenAPI typegen for the new schemas misses fields, causing TS errors | Low | Medium | Verify by running `pnpm typecheck` against the regenerated `components['schemas']` after backend lands. If the project's typegen is manual, hand-add `StudyChainResponse` + `StudyChainLink` to `ui/src/lib/types.ts`. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cyclic `parent_study_id` graph (defensive) | Manual DB write outside the engine path | Upward walk stops at 10 hops, log WARN, treat stop-point as anchor; client sees a valid payload (no `INTERNAL_ERROR`) | Manual — investigate the rogue write |
| Fan-out (>1 child per parent) | Manual DB write outside the engine path | Downward walk takes the `created_at ASC` first child, logs WARN, ignores additional siblings | Manual |
| Proposal table has multiple non-rejected proposals per link | Digest re-run or admin re-issue | `DISTINCT ON (study_id)` picks newest by `created_at DESC, id DESC` | Automatic — by design |
| Anchor with `baseline_metric IS NULL` AND zero complete trials | Anchor failed early | `cumulative_lift = null`; panel renders `Cumulative lift: —` | None needed — degrades gracefully |
| Tail `completed_at` clock skew (older than 120s but stop_reason flips) | Hosted clock drift | Poll stops; next window-focus refetch picks up the new state | Automatic — operator focuses the window |
| `useStudyChain` query errors (network) | Backend down or 5xx | Panel shows whatever it has (TanStack `data` retained); existing parent-link / depth / children rows still render from `study` prop + `chainChildren` prop | Automatic — TanStack retries |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 (backend) — Stories 1.1 → 1.2 → 1.3.** Endpoint must be green before any frontend work can be tested.
2. **Epic 3 (wizard relabel + glossary) — Story 3.1.** Independent of Epic 1; can run in parallel.
3. **Epic 2 (panel) — Story 2.1.** After Epic 1.
4. **Epic 4 — Stories 4.1 (docs) + 4.2 (E2E).** After Epics 2 + 3.

### Parallelization opportunities
- Epic 3 (Story 3.1) is independent of Epic 1 and can land in parallel with Story 1.1.
- Story 4.1 (docs) can be drafted while Stories 1.x and 2.1 are in code review.
- Story 4.2 (E2E) requires both Epics 1 + 2 green.

---

## 8) Rollout and cutover plan

- **Rollout stages:** none — internal-only behavior change.
- **Feature flag:** none.
- **Migration / cutover:** none — no schema change.
- **Reconciliation:** none — no external system involved.

---

## 9) Execution tracker

### Current sprint
- [x] Story 1.1 — Pure-domain chain summary helpers
- [x] Story 1.2 — Chain traversal repo helper
- [x] Story 1.3 — `GET /api/v1/studies/{id}/chain` router
- [ ] Story 2.1 — Extend `AutoFollowupChainPanel` + `useStudyChain` hook
- [ ] Story 3.1 — Wizard relabel + Deep hint + glossary key
- [ ] Story 4.1 — Tutorial + 3 docs/01_architecture updates + state.md
- [ ] Story 4.2 — E2E spec `overnight-chain.spec.ts`

### Blocked items
- None.

### Done this sprint
- (filled by `/impl-execute`)

---

## 10) Story-by-Story Verification Gate

For every story, attach evidence:

- [ ] Files created/modified match the story's `New files` / `Modified files` tables
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code) — Story 1.3
- [ ] Key interfaces implemented with the documented signatures — Stories 1.1, 1.2, 1.3, 2.1
- [ ] Tests added/updated at every layer the story touches
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration`
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build`
  - [ ] `pnpm test:e2e:stable` (Story 4.2)
- [ ] No migration round-trip — feature has no schema change.
- [ ] Related docs updated in same branch when behavior/contract changed.

---

## 11) Plan consistency review

### Spec ↔ plan endpoint count
- Spec §8.1: 1 endpoint (`GET /api/v1/studies/{study_id}/chain`).
- Plan: 1 endpoint (Story 1.3). ✅ Match.

### Spec ↔ plan error code coverage
- Spec §8.6: 1 error code (`STUDY_NOT_FOUND` 404 — reused, not new).
- Plan: covered by Story 1.3 integration test (AC-4) + contract test §3.3 envelope assertion. ✅ Match.

### Spec ↔ plan FR coverage
- 6 FRs in spec; 6 rows in §1 traceability table. Every FR assigned to ≥ 1 story. ✅ Match.

### Story internal consistency
- Story 1.3's endpoint table fields match `StudyChainResponse` + `StudyChainLink` Pydantic schemas (field names + types).
- DoD assertions reference `STUDY_NOT_FOUND` + 404 status; no other error codes referenced.
- `chain_summary.py` is owned by Story 1.1 alone; `get_chain_for_study` is owned by Story 1.2 alone; the router handler by Story 1.3 alone. No ownership conflicts.
- Every modified file path verified to exist (`backend/app/db/repo/study.py`, `backend/app/api/v1/studies.py`, `backend/app/api/v1/schemas.py`, `ui/src/components/studies/auto-followup-chain-panel.tsx`, `ui/src/components/studies/create-study-modal.tsx`, `ui/src/lib/glossary.ts`, `ui/src/lib/api/studies.ts`, etc.).

### Test file count and assignment
- 4 new backend test files (`test_chain_summary.py`, `test_studies_chain_repo.py`, `test_studies_chain_api.py`, `test_studies_chain_contract.py`) — 1 per Epic-1 story + 1 for the contract layer (added under Story 1.3 DoD).
- 3 frontend test files touched (`auto-followup-chain-panel.test.tsx` extended, `create-study-modal*.test.tsx` extended, `glossary.test.ts` extended).
- 1 new E2E spec (`overnight-chain.spec.ts`, Story 4.2).
- Every test file in §3 is owned by exactly one story; no orphans.

### Gate arithmetic
- Epic 1 gate: "1 endpoint live + 14+ unit cases green + integration AC-3/4/5/8/9/10 green + contract shape + error envelope green." Matches Story 1.1/1.2/1.3 DoD aggregate.
- Epic 2 gate: "panel renders summary for opted-in chains + branches A/B/C of best-config + existing 7 cases still pass + E2E covers the surface (when Story 4.2 lands)."
- No gate references a count that doesn't match story scope.

### Open questions resolved
- Spec §19: OQ-1 through OQ-5 all resolved before spec finalize. D-1 through D-13 logged. No open questions remain.

### Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| Alembic head = `0022_solr_engine_auth_check` | `ls migrations/versions/ \| sort \| tail` | Verified |
| `backend/app/api/v1/studies.py:80-84` defines `_err(...)` helper | Read studies.py:80-84 | Verified |
| `backend/app/api/v1/studies.py:165` reads `objective.get("direction", "maximize")` | Read studies.py:161-175 | Verified |
| `backend/app/db/repo/study.py:182-208` is `list_children_of_study` | Read repo/study.py:182-208 | Verified |
| `repo.__all__` exports `list_children_of_study` | Read repo/__init__.py | Verified |
| `backend/app/domain/study/auto_followup.py` exports `compute_first_decile_max` + `_direction_normalized_lift` | Read auto_followup.py:77-227 | Verified |
| `ui/src/components/studies/auto-followup-chain-panel.tsx` is 120 LOC, mount at `/studies/[id]/page.tsx:109` | Read both files | Verified (120 LOC; insertion anchors line 116/117 confirmed) |
| `ui/src/lib/glossary.ts:866-899` carries `auto_followup_depth`, `auto_followup_chain`, `lift_gate`, `auto_followup_budget_skip` | Read glossary.ts:855-900 | Verified |
| `AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES = [0, 1, 2, 3, 4, 5]` at `ui/src/lib/enums.ts:111` | grep | Verified |
| `useStudy`, `useStudyChildren`, `useCancelStudy` patterns at `ui/src/lib/api/studies.ts` | Read | Verified |
| `create-study-modal.tsx:1422` is the wizard label `"Auto-followup chain"` | Read 1400-1455 | Verified |
| `presetLabel('deep')` = `"Deep (1000)"`; preset wire values = `['focused','standard','deep','custom']` | Read 95-114 | Verified |
| `Proposal.status` allowed values include `'rejected'` | Read models/proposal.py:42 | Verified |
| Existing 7 vitest cases in `auto-followup-chain-panel.test.tsx` at lines 77-142 | Read | Verified |
| `InfoTooltip` accepts `glossaryKey` typed as `ShortGlossaryKey` (auto-narrowed by `glossary` const-satisfies) | Read info-tooltip.tsx | Verified |

### Infrastructure path verification
- Migrations dir: `/Users/ericstarr/relyloop/migrations/versions/` (matches CLAUDE.md). No migration this feature.
- Router registration: `backend/app/main.py:214` registers `studies_router` at prefix `/api/v1`. New endpoint inherits this prefix automatically. ✅
- Domain dir: `backend/app/domain/study/` exists with 11 files; `chain_summary.py` is new and unique.
- Test dirs: `backend/tests/unit/domain/study/` exists; `backend/tests/integration/` exists (flat — `test_studies_*.py` siblings); `backend/tests/contract/` exists. Plan paths match.

### Frontend data plumbing verification
- `useStudyChain(studyId)` is keyed only by `study.id` — already available as a prop on `<AutoFollowupChainPanel>`. ✅
- `study.parent_study_id`, `study.config.auto_followup_depth`, `chainChildren[]` are already in props. ✅
- `useCancelStudy` already lives in `ui/src/lib/api/studies.ts:143-163`; adding the chain-key invalidation is a 1-line addition. ✅
- `useStudy` polling reaches `study.status`; the `useEffect` in the panel can read `study.status` from props (the parent page passes the full `StudyDetail`). ✅

### Persistence scope consistency
- No `localStorage` / `sessionStorage` usage in any story. ✅

### Enumerated value contract audit

| Field | Backend source | Spec §8.5 | Plan frontend | Match? |
|---|---|---|---|---|
| `stop_reason` | `CHAIN_STOP_REASONS` frozenset in `backend/app/domain/study/chain_summary.py` (new in Story 1.1) | `depth_exhausted, no_lift, budget, parent_failed, cancelled, in_flight` | Plan §"Stop-reason → phrase mapping table" with source-of-truth comment | ✅ |
| `direction` | `Study.objective['direction']` default `"maximize"` (existing pattern) | `maximize, minimize` | Plan reads from `link.direction` field on the response | ✅ |
| `status` (per-link) | `Study.status` CHECK constraint | `queued, running, completed, cancelled, failed` | Plan renders from `link.status`; no new frontend dropdown introduced | ✅ |
| `AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES` | `0..5`, see `enums.ts:111` and backend `_validate_auto_followup_depth` | unchanged | unchanged | ✅ |

All four enumerated fields cite a backend source-of-truth and match character-for-character.

### Audit-event coverage audit

Per spec §6: `N/A — audit_log lands at MVP3`. RelyLoop is MVP2 today. This feature ships NO new state mutations:
- FR-1, FR-2: pure UI text changes.
- FR-3: read-only `GET` endpoint.
- FR-4: UI rendering of a read-only response.
- FR-5: docs.
- FR-6: glossary entry (text only).

No mutation sites → no audit-event obligation → no audit-row contract test needed. ✅

### Findings classification

**Major findings (this Opus-only review pass):** none. All scope decisions are locked by the spec's D-1 through D-13 decisions. Endpoint contract, schemas, traversal algorithm, derivation matrix, render predicate, refetch contract — every load-bearing piece is grounded in cited spec content + verified codebase paths.

**Minor findings (applied without gating):**
- F1 (style): plan-level UI Guidance section consolidated rather than per-story to avoid duplication. Applied — section appears once below Epic 4.
- F2 (test plumbing): wizard test file may be split into a focused `create-study-modal-overnight.test.tsx` to avoid bloating the existing modal spec. Applied as DoD-level option, defer to executor's judgment.

**Cross-model review:** skipped per operator instruction. Logged here for the review log.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces (where applicable), Tasks, and DoD.
- [x] Test layers (unit/integration/contract/vitest/e2e) are explicitly scoped.
- [x] Documentation updates across docs/01–05 + docs/08 are planned and owned.
- [x] Lean refactor scope and guardrails are explicit.
- [x] Epic gates are measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed; no unresolved findings.

---

## Review log

- **Mode:** Generate.
- **Source spec:** [`feature_spec.md`](feature_spec.md) (Approved 2026-05-31; spec-gen ran 3 GPT-5.5 convergence cycles).
- **Review passes:** 1 Opus internal pass (Pass 1: spec-plan-FR cross-reference; Pass 2: codebase verification). No additional internal passes needed — no changes flagged at the structural/contract level after Pass 1.
- **Cross-model review:** **skipped per operator instruction** — operator note: spec already received 3-cycle GPT-5.5 convergence treatment in spec-gen; this plan is Opus-only.
- **Verification ledger:** see §11 table — 17 material claims verified against the codebase, all `Verified`.
- **Spec-plan alignment:** all 6 FRs covered, 1 endpoint matched, all decisions D-1 through D-13 applied verbatim (D-6 stop-reason wire-value set, D-7 linear-chain invariant, D-8 completed-link subset, D-9 universal cumulative-lift formula, D-10 refetch contract, D-11 rejected-proposal exclusion, D-12 iterative LIMIT-1 traversal, D-13 panel render predicate).
- **Open questions:** none — all spec OQs resolved before finalize.
- **Doc updates:** `state.md` updated on final merge (Story 4.1 DoD). `architecture.md` + `CLAUDE.md` unchanged.
- **Deferred phases:** Phase 2 (`/studies` list "ran while away" card) tracked at [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md) — pre-existing, no action.
