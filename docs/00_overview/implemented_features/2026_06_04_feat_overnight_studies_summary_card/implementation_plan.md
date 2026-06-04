# Implementation Plan — Overnight "Ran While You Were Away" Summary Card

**Date:** 2026-06-01
**Status:** Complete (PR #444, merged 2026-06-04)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rules, enum discipline), [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (FR-1 … FR-6).
- Read-only feature: no migration, no state mutation, no audit events.
- Reuse the shipped Phase 1 (`feat_overnight_autopilot`) domain helpers and traversal — never re-derive chain math.
- Enum discipline: the card's `stop_reason` phrasing is grounded in `CHAIN_STOP_REASONS` with a source-of-truth comment (reuse the Phase 1 map verbatim).
- Keep increments verifiable: backend endpoint + repo first (Epic 1), then frontend card + visited-state (Epic 2), then E2E (Epic 3).

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 (discovery endpoint + dedup + length≥2 + terminal-only) | Epic 1 / Stories 1.1, 1.2 | Repo helper + endpoint |
| FR-2 (`since`-window filtering + 422) | Epic 1 / Story 1.2 | Typed query param; global validation handler produces envelope |
| FR-3 (card render conditional on ≥1 chain + nullable fallback) | Epic 2 / Story 2.2 | Card component |
| FR-4 (stop-reason phrasing grounded in allowlist) | Epic 2 / Story 2.2 | Reuse Phase 1 phrase map |
| FR-5 (localStorage visited-state + dismissal `max+1ms`) | Epic 2 / Story 2.1, 2.2 | Visited-state hook + dismiss |
| FR-6 (info affordance + glossary key) | Epic 2 / Story 2.3 | New `recent_chains_card` glossary key |

**Deferred phases:** None. The spec is single-phase (§3 Phase boundaries — this IS Phase 2 of `feat_overnight_autopilot`, delivered standalone). No `phase<N>_idea.md` tracking file is required. Two deferred *follow-on* ideas surface from the spec's open questions and should be captured as separate idea files when work begins (not blocking): a `chore_` for `ix_studies_parent_study_id` / `ix_studies_completed_at` (OQ-3) and a `chore_` for keyset pagination on the discovery endpoint (OQ-2). These are explicitly out of scope here.

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Conventions (project-specific)

```
- Repo functions take `db: AsyncSession` as first arg; flush stages, caller commits. This feature is read-only (no flush/commit).
- Domain layer is pure — no DB, no async. Reuse chain_summary.py (already pure).
- Routers return typed Pydantic response models; errors via the studies router `_err()` helper (studies.py:89) → {detail:{error_code,message,retryable}}.
- Malformed typed query params auto-produce the VALIDATION_ERROR envelope via the global validation_exception_handler (errors.py:129-169,195) — do NOT add a manual parse path.
- Cursor/pagination: list endpoints emit X-Total-Count. This endpoint emits X-Total-Count = len(data) (bounded), no cursor param (OQ-2 resolved).
- Frontend: TanStack Query hooks in ui/src/lib/api/studies.ts; components in ui/src/components/studies/; glossary keys in ui/src/lib/glossary.ts; enum-grounded option maps carry a // Source-of-truth comment.
- All new repo functions exported via backend/app/db/repo/__init__.py __all__.
```

### AI Agent Execution Protocol

Standard order per template §2: load `architecture.md` + `state.md`; implement backend (repo → endpoint → schema) first; run backend tests; implement frontend; run E2E; update docs; no migration round-trip needed (no schema change); attach evidence per story.

---

## Epic 1 — Backend: recent-completed-chains discovery

### Story 1.1 — Repo helper: find recent completed chains (one row per anchor)
**Outcome:** A pure-read repo function returns, for a given `since`/`limit`, the de-duplicated set of completed overnight chains (length ≥ 2, terminal tail) as hydrated `ChainTraversalResult`s ordered by tail completion DESC.

**New files**

| File | Purpose |
|---|---|
| (none) | Logic lands in the existing `backend/app/db/repo/study.py` alongside `get_chain_for_study` |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/study.py` | Add `list_recent_completed_chains(db, *, since, limit)` → `list[ChainTraversalResult]`. Reuses the existing `get_chain_for_study` traversal per resolved anchor. |
| `backend/app/db/repo/__init__.py` | Export `list_recent_completed_chains` via `__all__` |

**Key interfaces**

```python
# db/repo/study.py
async def list_recent_completed_chains(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    limit: int = 20,
) -> list[ChainTraversalResult]:
    """Return de-duplicated completed overnight chains (length >= 2),
    newest tail-completion first, capped at `limit`.

    Algorithm (FR-1):
      1. SELECT candidate member ids: studies where parent_study_id IS NOT NULL
         (i.e. studies that ARE a follow-up child — guarantees their chain has
         length >= 2) AND completed_at IS NOT NULL AND status IN
         ('completed','cancelled','failed') AND (since IS NULL OR completed_at >= since).
         Order by completed_at DESC; cap the candidate scan generously
         (e.g. limit*6) so dedup-to-anchor can still fill `limit` distinct chains.
      2. For each candidate (newest first), resolve its anchor via
         get_chain_for_study and key into an ordered dict on anchor_id to
         DEDUPLICATE to one row per chain. Skip anchors already seen.
      3. Skip any chain whose derive_chain_stop_reason(...) == 'in_flight'
         (defensive — step 1 already excludes non-terminal tails, but a chain
         with a still-running *interior* link must also be excluded).
      4. Stop once `limit` distinct chains are collected.
      5. Return the collected ChainTraversalResults in tail-completion-DESC order.
    """
```

**Tasks**
1. Add the candidate-member query (filter `parent_study_id IS NOT NULL`, terminal status, `completed_at >= since`, order `completed_at DESC`, scan-cap `limit * _CHAIN_MAX_DESCENDANTS`).
2. Resolve each candidate to its anchor via `get_chain_for_study`; dedup on `anchor_id` using an insertion-ordered dict.
3. Apply the `in_flight` exclusion via `derive_chain_stop_reason` (import from `chain_summary.py`) and the length-≥2 guard (`len(result.links) >= 2`).
4. Cap to `limit` distinct chains; preserve tail-completion-DESC ordering.
5. Handle `get_chain_for_study` returning `None` for a candidate anchor (chain member hard-deleted between the candidate query and traversal — the concurrent-delete race): skip that anchor and continue, never raise (mirrors the Phase 1 defensive skip at `study.py:327-333`).
6. Export via `__all__`.

**Definition of Done**
- `list_recent_completed_chains` exists, is pure-read (no flush/commit), exported in `__all__`.
- Handles `get_chain_for_study() is None` by skipping the anchor (no exception).
- Integration test `test_studies_chain_recent_repo.py` covers: 3-link chain returned once (AC-12 dedup), single-study excluded (AC-2), `since` boundary (AC-3), in-flight excluded (AC-4), terminal-failed chain returned with derivations (AC-11 data path), AND a hard-deleted-member candidate is skipped without error (concurrent-delete failure mode).
- `make test-integration` subset green.

### Story 1.2 — Endpoint: `GET /api/v1/studies/chains/recent`
**Outcome:** A read-only endpoint returns the discovery rows in the documented response shape, with `X-Total-Count`, inert pagination fields, and the standard `422` envelope for a malformed `since`.

**New files**

| File | Purpose |
|---|---|
| (none) | Endpoint + schemas land in the existing studies router + schemas module |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Add `get_recent_chains` handler. **Declare it BEFORE the `/studies/{study_id}` dynamic route** so `chains` is not captured as a path param (route-order collision per spec §8.1). |
| `backend/app/api/v1/schemas.py` | Add `RecentChainSummary` + `RecentChainsResponse` schemas |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/chains/recent` | query: `since?` (ISO-8601 dt), `limit?` (int `ge=1,le=50`, default 20) | `200` `RecentChainsResponse` (+ `X-Total-Count: len(data)`) | `VALIDATION_ERROR` (422) for malformed `since`/`limit` |

**Key interfaces**

```python
# api/v1/studies.py  (declare ABOVE the /studies/{study_id} route)
@router.get("/studies/chains/recent", response_model=RecentChainsResponse, tags=["studies"])
async def get_recent_chains(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> RecentChainsResponse:
    chains = await repo.list_recent_completed_chains(db, since=since, limit=limit)
    rows = [_recent_chain_row(c) for c in chains]   # reuse chain_summary derivations
    response.headers["X-Total-Count"] = str(len(rows))
    return RecentChainsResponse(data=rows, next_cursor=None, has_more=False)
```

`_recent_chain_row(traversal)` (module-level helper in `studies.py`) builds one `RecentChainSummary` by calling `select_best_link`, `compute_cumulative_lift`, `derive_chain_stop_reason` on `traversal.links` / `traversal.anchor_trials` (the exact reuse already done by `get_study_chain` at `studies.py:786-799`), reading `anchor_name = traversal.links[0].name`, `chain_length = len(traversal.links)`, `objective_metric = traversal.links[0].objective.get("metric")`, `tail_completed_at = traversal.links[-1].completed_at`, and the best-link proposal via `traversal.proposal_id_by_link_id`.

**Pydantic schemas**

```python
# api/v1/schemas.py
class RecentChainSummary(BaseModel):
    anchor_study_id: str
    anchor_name: str
    chain_length: int
    best_metric: float | None
    objective_metric: str
    cumulative_lift: float | None
    direction: ObjectiveDirection          # reuse existing Literal
    stop_reason: ChainStopReason           # reuse existing import (schemas.py:31)
    best_link_proposal_id: str | None
    tail_completed_at: datetime

class RecentChainsResponse(BaseModel):
    data: list[RecentChainSummary]
    next_cursor: str | None = None         # always None (OQ-2)
    has_more: bool = False                 # always False (OQ-2)
```

**Tasks**
1. Add the two schemas to `schemas.py` (reuse `ObjectiveDirection`, `ChainStopReason`).
2. Add `_recent_chain_row` helper mirroring `get_study_chain`'s derivation block.
3. Add the `get_recent_chains` handler **above** the `/studies/{study_id}` route declaration.
4. Set `X-Total-Count = len(data)`; emit inert `next_cursor=None`/`has_more=False`.
5. Verify route-ordering: a request to `/studies/chains/recent` hits the new handler, not `get_study_detail` with `study_id="chains"`.

**Definition of Done**
- Endpoint returns the documented shape; `X-Total-Count` = returned-row count.
- AC-1 (chain appears), AC-5 (empty→200 `data:[]`), AC-6 (malformed `since`→422 `VALIDATION_ERROR` envelope), AC-11 (failed chain → null metric fields, 200) covered by `test_studies_chain_recent_api.py` (integration) + `test_studies_chain_recent_contract.py` (contract: shape + 422 envelope + `X-Total-Count` header).
- Route-order collision regression asserted (request to `/studies/chains/recent` does not 404 as an unknown study).
- `make test-integration` + `make test-contract` subsets green; `make lint` + `make typecheck` clean.

**Epic 1 gate (hard stop):** 1 endpoint live (`GET /api/v1/studies/chains/recent`); repo helper + 2 schemas merged; integration + contract green for AC-1/2/3/4/5/6/11/12.

---

## Epic 2 — Frontend: the "Ran while you were away" card

### Story 2.1 — Visited-state hook + `useRecentChains` query hook
**Outcome:** A localStorage-backed visited-state hook supplies `since`; a TanStack hook fetches the discovery endpoint.

**New files**

| File | Purpose |
|---|---|
| `ui/src/hooks/use-studies-visited.ts` | `useStudiesVisited()` → `{ since: string, dismiss(maxTailCompletedAt: string): void }`; reads/writes `localStorage["relyloop.last_visited_studies_at"]`; first-visit default = now − 7d |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/studies.ts` | Add `RecentChainSummary` + `RecentChainsResponse` TS types + `useRecentChains(since, opts)` hook (mirror `useStudyChain` at :212) |

**Key interfaces**

```typescript
// ui/src/lib/api/studies.ts
export interface RecentChainSummary {
  anchor_study_id: string;
  anchor_name: string;
  chain_length: number;
  best_metric: number | null;
  objective_metric: string;
  cumulative_lift: number | null;
  direction: 'maximize' | 'minimize';   // Source-of-truth: backend ObjectiveDirection
  stop_reason: StudyChainResponse['stop_reason'];   // reuse Phase 1 union
  best_link_proposal_id: string | null;
  tail_completed_at: string;
}
export interface RecentChainsResponse { data: RecentChainSummary[]; next_cursor: string | null; has_more: boolean; }
export function useRecentChains(since: string, opts?: { enabled?: boolean }):
  UseQueryResult<RecentChainsResponse, ApiError>;  // GET /api/v1/studies/chains/recent?since=&limit=20

// ui/src/hooks/use-studies-visited.ts
export function useStudiesVisited(): {
  since: string;                          // stored value OR (now - 7d) on first visit
  dismiss: (maxTailCompletedAt: string) => void;  // store maxTailCompletedAt + 1ms
};
```

**Client-side persistence:** `localStorage` (key `relyloop.last_visited_studies_at`) — persists across sessions/visits (durable visited-state). DoD matches: "persists across visits."

**Tasks**
1. Implement `useStudiesVisited` with SSR-safe guards (read `localStorage` only in effect / lazy init; Next 16 App Router client component). First-visit default `new Date(Date.now() - 7*864e5).toISOString()`.
2. `dismiss(maxTailCompletedAt)` writes `new Date(new Date(maxTailCompletedAt).getTime() + 1).toISOString()` (the `+1ms` exclusive nudge per FR-5).
3. Add `useRecentChains` mirroring `useStudyChain` (queryKey `['studies','recent-chains', since]`; no aggressive polling — `refetchOnWindowFocus: true`, default staleness).

**Definition of Done**
- `use-studies-visited.test.ts`: first visit → `since` ≈ now−7d (AC-9); `dismiss(T)` stores `T+1ms` (AC-8); subsequent read returns the stored value.
- Hook compiles under `tsc --strict`; `pnpm lint` clean.

### Story 2.2 — `RecentChainsCard` component + mount on `/studies`
**Outcome:** The dismissible card renders above the studies table when ≥1 chain is returned, with nullable-safe rows and the "Review chain" link; renders nothing on empty/pending/error.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/recent-chains-card.tsx` | The card component |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/studies/page.tsx` | Mount `<RecentChainsCard />` between the `<h1>` header block (ends line ~120) and the target-filter chip row (line ~121) — i.e. immediately after the header `<div>`, before the `{targetFromUrl && (...)}` block |

**UI element inventory**

| Element | Label/title | Data source | Interactions |
|---|---|---|---|
| Card (`<Card>`) | "Ran while you were away" (CardTitle) | `useRecentChains(since)` | Renders only when `data.length >= 1` |
| Info affordance (card) | `<InfoTooltip glossaryKey="recent_chains_card" />` next to title — explains the card | glossary | hover/focus tooltip |
| Info affordance ("overnight" term) | `<InfoTooltip glossaryKey="overnight_autopilot" />` next to the word "overnight" in the card subtitle/body — reuses the existing Phase 1 key per spec §11 + FR-6 | glossary (existing `overnight_autopilot`, `glossary.ts:917`) | hover/focus tooltip |
| Per-chain row | anchor_name (as `<Link>`), "{chain_length} studies", "Best {objective_metric}: {best_metric}", "Lift: {±cumulative_lift}", stop-reason phrase | `RecentChainSummary` | "Review chain" `<Link href={/studies/{anchor_study_id}}>` |
| Null-metric row variant | stop-reason phrase prominent (e.g. "Chain failed"), no numeric line | `best_metric === null` | same link |
| Dismiss button | "Got it" | — | `dismiss(maxTailCompletedAt)` → card hides |

**State dependency analysis:** the card owns its own query + visited-state via the two hooks; it does NOT depend on the page's `useStudies` query or `urlState`. `maxTailCompletedAt` for dismissal = `Math.max(...data.map(d => Date.parse(d.tail_completed_at)))` → ISO string. No shared-state changes to the existing page.

**Key interfaces**

```tsx
// recent-chains-card.tsx
// feat_overnight_studies_summary_card FR-4 — wire stop_reason → human phrase.
// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS
const STOP_REASON_PHRASE: Record<RecentChainSummary['stop_reason'], string> = {
  depth_exhausted: 'Reached the depth limit',
  no_lift: 'Stopped: no further improvement',
  budget: 'Stopped: daily LLM budget reached',
  parent_failed: 'Chain failed',
  cancelled: 'Chain cancelled',
  in_flight: 'Still running',   // defensive — filtered server-side
};
export function RecentChainsCard(): React.ReactNode;
```

**Tasks**
1. Build the card reusing `Card/CardHeader/CardTitle/CardContent`, `InfoTooltip` (TWO placements: `recent_chains_card` on the title, `overnight_autopilot` on the "overnight" term per FR-6), `Link`, and the `formatSignedLift` pattern (port from `auto-followup-chain-panel.tsx:48-51`).
2. Early-return `null` when `query.isPending`, `query.isError`, or `data.length === 0` (FR-3 edge flows).
3. Render the per-row metadata; when `best_metric`/`cumulative_lift` are `null`, show the stop-reason phrase in place of the numeric line (AC-11).
4. Wire "Got it" → `dismiss(maxTail)` then the query refetches with the advanced `since` (empty → card unmounts).
5. Mount in `page.tsx` at the documented insertion point.

**Legacy behavior parity:** No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated; this is purely additive.

**Definition of Done**
- `recent-chains-card.test.tsx`: renders rows from a fixture with correct anchor link target (AC-7); renders nothing on empty/error/pending (AC-7); all 6 `stop_reason` values map to a phrase, never a raw wire value (AC-10); null-metric row shows the failed phrase, not "NaN"/"—" alone (AC-11); "Got it" calls `dismiss` with the max `tail_completed_at` (AC-8); BOTH info affordances render (`recent_chains_card` + `overnight_autopilot`, FR-6) — assert both `tooltip-body-*` testids / triggers are present.
- `tsc --strict` + `pnpm lint` clean; the form-select / data-table enum-discipline guards are not tripped (the stop-reason map is a render-only inbound map, not a `<SelectItem>` wire value — no guard applies, but the source-of-truth comment is present).

### Story 2.3 — Glossary key `recent_chains_card`
**Outcome:** A new short+long glossary entry backs the card's info affordance; the existing `overnight_autopilot` key is reused for the "overnight" term.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | Add `recent_chains_card` entry (`short` ≤ 140 chars, `long`, `ariaLabel`) per the §11 tooltip inventory |

**Tasks**
1. Add the entry near the `overnight_autopilot` / `auto_followup_chain` keys (glossary.ts:917-939), matching the existing `GlossaryEntryShort & GlossaryEntryLong` shape.
2. `short`: "RelyLoop ran follow-up studies overnight. This card shows chains that finished since your last visit; 'Got it' hides it until a new one finishes." (≤140 chars — trim to fit.)

**Definition of Done**
- `glossary.test.ts` passes (length caps + key presence — the existing test enforces ≤140 `short` / ≤800 `long`).
- `<InfoTooltip glossaryKey="recent_chains_card" />` type-checks (the key is now a `ShortGlossaryKey`).

**Epic 2 gate (hard stop):** card renders conditionally on `/studies`; visited-state + dismissal behave per AC-8/AC-9; stop-reason phrasing grounded; glossary key live; all frontend vitest + `tsc` + lint green.

---

## Epic 3 — End-to-end + docs

### Story 3.1 — Real-backend Playwright E2E
**Outcome:** A real-backend E2E spec seeds a completed chain via API helpers, loads `/studies`, asserts the card is visible with the right anchor, clicks "Review chain", and asserts navigation to the anchor detail page.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/recent-chains-card.spec.ts` | Real-backend E2E (no `page.route()`) |

**Tasks**
1. Setup via `request` API helpers: create cluster/template/query-set/judgment-list, then seed a 2–3 study chain with terminal tail (reuse existing chain-seeding helpers from the Phase 1 E2E if present; otherwise seed studies with `parent_study_id` linkage + `completed_at`/`best_metric` via the test-only seed path).
2. Seed `localStorage["relyloop.last_visited_studies_at"]` to a time before the chain's tail completion via `page.addInitScript()` so the card shows.
3. `page.goto('/studies')`; assert the card title "Ran while you were away" is visible and contains the anchor name.
4. Click the "Review chain" link; assert URL is `/studies/{anchor_study_id}` and the Phase 1 chain panel renders.
5. (Optional) click "Got it"; reload; assert the card is gone.

**Definition of Done**
- Spec uses `page` for all assertions (no `page.route()` mocking of backend); `request` only for setup (CLAUDE.md E2E rule).
- Passes in the smoke E2E job against the real stack (AC-7 browser-visible behavior).

### Story 3.2 — Docs
**Outcome:** Architecture docs reflect the new endpoint + card.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/api-conventions.md` | Add `GET /api/v1/studies/chains/recent` to the studies surface notes (read-only, `X-Total-Count = len(data)`, no cursor) |
| `docs/01_architecture/ui-architecture.md` | One line on the recent-chains card placement on `/studies` |
| `state.md` / `state_history.md` | On merge: prepend the one-liner to "Last 5 merges", drop the oldest into `state_history.md` |

**Definition of Done**
- Docs consistent with shipped behavior; `state.md` snapshot refreshed on merge.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: the reused `chain_summary.py` derivations already have Phase 1 unit coverage — no duplication. No new pure helper warrants a standalone unit test (the row-shaping `_recent_chain_row` is exercised via integration).
- DoD: existing `chain_summary` unit suite stays green.

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Files: `test_studies_chain_recent_repo.py` (Story 1.1), `test_studies_chain_recent_api.py` (Story 1.2)
- Tasks: AC-1 (chain appears), AC-2 (single excluded), AC-3 (`since` boundary), AC-4 (in-flight excluded), AC-5 (empty→200), AC-11 (failed chain null fields), AC-12 (one row per anchor), plus the concurrent hard-delete skip (Story 1.1 step 5 — a candidate whose chain is gone is skipped, not raised). Seed rows directly via repo (mirror `test_studies_chain_api.py` setup pattern).
- DoD: happy path + every exclusion path covered against real DB.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- File: `test_studies_chain_recent_contract.py` (Story 1.2)
- Tasks: response-shape keys/types of `RecentChainsResponse`/`RecentChainSummary`; `422` `VALIDATION_ERROR` envelope for malformed `since` (AC-6); `X-Total-Count` header present and = `len(data)`.
- DoD: the one new endpoint has contract coverage; the only error code (`VALIDATION_ERROR`) is asserted. **Coordinate with `bug_contract_allowlists_outdated_after_mvp2_features`** — if a hand-maintained endpoint/route allowlist trips on the new route, update it in the same PR.

### 3.4 E2E tests
- Location: `ui/tests/e2e/`
- File: `recent-chains-card.spec.ts` (Story 3.1) — real backend, `page`-driven assertions, `request` for setup only.
- DoD: stable pass in the smoke job.

### Frontend vitest (component/hook)
- `ui/src/__tests__/components/studies/recent-chains-card.test.tsx` (Story 2.2)
- `ui/src/__tests__/hooks/use-studies-visited.test.ts` (Story 2.1)
- `ui/src/__tests__/lib/glossary.test.ts` (existing — extended by Story 2.3 key, enforced by the existing length-cap test)

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/...studies/page*` (if any) | `<StudiesTable>` render | n/a | No change needed — card is additive and early-returns `null` when no chains; existing table assertions unaffected. Verify the card's pending-state `null` return doesn't change initial DOM the table tests assert on. |
| `backend/tests/contract/test_studies_*` | route allowlist | n/a | Add the new route if an allowlist enumerates studies routes (coordinate with `bug_contract_allowlists_outdated_after_mvp2_features`). |

### 3.5 Migration verification
- N/A — no schema change, no migration. (Alembic head stays `0022_solr_engine_auth_check`.)

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `make lint && make typecheck`
- [ ] `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build`
- [ ] smoke E2E job

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — refresh "Last 5 merges" + Alembic head unchanged (`0022`); note feature shipped. No new debt.
- **`architecture.md`** — no new layer (endpoint added to existing studies router; card to existing studies page) — a one-line note is optional, not required.
- **`CLAUDE.md`** — no new convention; no edit.

### 4.1 Architecture docs
- [ ] `api-conventions.md`: new endpoint note (Story 3.2).
- [ ] `ui-architecture.md`: card placement note (Story 3.2).

### 4.2–4.5 Product / Runbooks / Security / Quality
- N/A — read-only feature; no new ops procedure, no security surface, test layers documented in §3.

**Documentation DoD**
- [ ] `state.md` refreshed on merge; api-conventions.md + ui-architecture.md consistent with shipped behavior.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Reuse `chain_summary.py` derivations and the `get_chain_for_study` traversal — no duplication of chain math.
- Reuse the Phase 1 stop-reason phrase map shape and `formatSignedLift` helper rather than re-inventing.

### 5.2 Planned refactor tasks
- [ ] If `_recent_chain_row` and `get_study_chain`'s inline derivation block diverge meaningfully, extract a shared `build_chain_summary(traversal) -> <dict>` helper. Bounded — only if the duplication is non-trivial; otherwise inline is fine.

### 5.3 Guardrails
- [ ] Behavioral parity proven by tests; lint/typecheck green; no scope expansion (no index migration, no cursor paging — those are deferred ideas).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_overnight_autopilot` Phase 1 (`chain_summary.py`, `get_chain_for_study`, `/chain` panel) | All stories | **implemented** (PR #343) | none — satisfied |
| `bug_contract_allowlists_outdated_after_mvp2_features` coordination | Story 1.2 contract | open | new route may trip a hand-maintained allowlist → contract failure; mitigate by updating the allowlist in this PR |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Route-order collision: `/studies/chains/recent` captured by `/studies/{study_id}` | M | H (404s) | Declare the static route BEFORE the dynamic route; add a regression assertion (Story 1.2) |
| Discovery query slow at scale (`parent_study_id` unindexed) | L (single-tenant) | L | `limit`-cap + bounded traversal; defer index to a `chore_` (OQ-3) |
| Inclusive `since` re-shows dismissed chain | M | M (UX annoyance) | `dismiss` stores `max(tail_completed_at)+1ms` (FR-5) — covered by AC-8 |
| Client-clock skew suppresses chains | L | M | dismissal cutoff is DB-sourced `tail_completed_at`, not client `now` (FR-5) |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Chain member hard-deleted between discovery query and traversal | concurrent delete (test teardown path) | `get_chain_for_study` returns `None`; endpoint skips that anchor | auto (defensive skip) |
| Endpoint errors / network down | backend down | card renders nothing (no error banner) | auto — best-effort discoverability never blocks the page |
| Empty discovery result | no chains since `since` | `200 {data:[]}`, no card | normal |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 (repo + endpoint) — unblocks the frontend contract.
2. Epic 2 (card + hooks + glossary) — depends on the endpoint shape.
3. Epic 3 (E2E + docs) — depends on both.

### Parallelization
- Story 2.3 (glossary) can run in parallel with 2.1/2.2.
- Story 3.2 (docs) can be drafted in parallel once the endpoint shape is locked (after Story 1.2).

## 8) Rollout and cutover plan
- No feature flag — additive read-only feature ships directly.
- No migration / backfill.
- Release gate: all ACs green in CI; allowlist coordination resolved; smoke E2E green.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — repo helper
- [ ] Story 1.2 — endpoint + schemas
- [ ] Story 2.1 — hooks
- [ ] Story 2.2 — card + mount
- [ ] Story 2.3 — glossary
- [ ] Story 3.1 — E2E
- [ ] Story 3.2 — docs

## 10) Story-by-Story Verification Gate (Agent Checklist)
- [ ] Files created/modified match story scope.
- [ ] Endpoint contract implemented exactly (path/query/status/error code/X-Total-Count).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Tests added across integration/contract/frontend-vitest/E2E where applicable.
- [ ] Commands passed: `make test-unit`, `make test-integration` (or subset), `make test-contract`, `cd ui && pnpm test`, smoke E2E (if UI touched).
- [ ] No migration round-trip needed (no schema change) — explicitly noted.
- [ ] Docs updated in same PR.

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** spec §8.1 = 1 endpoint (`GET /studies/chains/recent`); plan = 1 endpoint (Story 1.2). ✔ Match.
2. **Error code coverage:** spec §8.5 = `VALIDATION_ERROR` (only). Plan contract test (Story 1.2 / §3.3) asserts it. ✔
3. **FR coverage:** FR-1..FR-6 all mapped in §1 to stories. ✔
4. **Story internal consistency:** endpoint table fields match `RecentChainSummary` schema fields; DoD references `VALIDATION_ERROR`/422 and `X-Total-Count`; no new-file ownership conflict (the feature adds 4 files: `recent-chains-card.tsx`, `use-studies-visited.ts`, the E2E spec — backend logic lands in existing files); modified files all exist (verified: `studies.py`, `schemas.py`, `repo/study.py`, `repo/__init__.py`, `studies.ts`, `studies/page.tsx`, `glossary.ts`). ✔
5. **Test file count:** 2 integration + 1 contract + 2 frontend-vitest + 1 E2E + 1 existing glossary test extended — each assigned to a story (1.1, 1.2, 2.1, 2.2, 2.3, 3.1). ✔ No orphans.
6. **Gate arithmetic:** Epic 1 gate "1 endpoint live" = 1 endpoint defined. ✔
7. **Open questions resolved:** OQ-2 resolved (limit-cap only) — reflected in schema (inert pagination). OQ-1 (per-link convergence) deferred — explicitly out of scope. OQ-3 (indexes) deferred to a `chore_` idea. ✔
8. **Infra paths:** Alembic head `0022_solr_engine_auth_check` (state.md) — N/A, no migration. Router registered at `main.py:214` (`studies_router`, prefix `/api/v1`) — the new endpoint joins the existing router, no new registration. ✔
9. **Frontend data plumbing:** the card owns its own `useRecentChains` + `useStudiesVisited` — does NOT depend on the page's `useStudies`/`urlState`. No parent-prop plumbing needed. ✔
10. **Persistence scope:** `localStorage` (durable across visits) — task + DoD agree ("persists across visits"). ✔
11. **Enum contract audit:** the only enumerated field is the inbound `stop_reason` (rendered, not sent). Plan grounds the phrase map in `CHAIN_STOP_REASONS` with a `// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS` comment. All 6 wire values mapped. No outbound `<select>` → no form-select/data-table guard applies. ✔
12. **Admin/ceiling audit:** N/A (no admin model pre-MVP4). ✔
13. **Audit-event audit:** N/A — read-only feature, no state mutation; spec §6 explicitly marks audit events N/A. ✔

No unresolved findings.

## 12) Definition of plan done
- [x] Every FR (1–6) mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, Endpoints (where API-facing), Key interfaces, Tasks, DoD.
- [x] Test layers (integration/contract/frontend-vitest/e2e) explicitly scoped; unit reuse noted.
- [x] Doc updates planned (api-conventions.md, ui-architecture.md, state.md).
- [x] Lean refactor scope + guardrails explicit (bounded shared-helper extraction only).
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed — no unresolved findings.
