# Feature Specification — Overnight "Ran While You Were Away" Summary Card

**Date:** 2026-06-01
**Status:** Draft
**Owners:** Relevance-Engineering PM (product), RelyLoop maintainer (engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`feat_overnight_autopilot` (Phase 1, shipped PR #343)](../../implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md)
- [`feat_study_convergence_indicator` (shipped PR #352)](../../implemented_features/2026_06_01_feat_study_convergence_indicator/feature_spec.md)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)
- [`implementation_plan.md`](implementation_plan.md) (generated next)

---

## 1) Purpose

- **Problem:** Phase 1 (`feat_overnight_autopilot`) made an overnight study chain *reviewable* from any study's detail page (`GET /api/v1/studies/{id}/chain` + `AutoFollowupChainPanel`). But it solved reviewability, not **discoverability**. When the operator wakes up and loads `/studies`, the list looks identical to the night before — studies sorted `created_at DESC`, with no callout that three of them ran automatically while they slept and a chain finished. The operator has to already know to click into *some* member of the chain.
- **Outcome:** A "ran while you were away" card surfaces at the top of `/studies` when at least one overnight chain has completed since the operator's last visit. Each completed chain is listed with its anchor name, chain length, best metric, cumulative lift, and a one-click "Review chain" link to the anchor's detail page. The card is dismissible ("Got it") and re-appears only when a *new* chain completes. The result: the operator's first glance at `/studies` answers "what finished while I was away?" without hunting.
- **Non-goal:** This feature does not change the chaining engine, does not add an outgoing webhook / email / push notification (a backlog alternative), and does not introduce auth or a server-side per-user visited-state model. It is a read-only discoverability layer on top of the already-shipped Phase 1 surfaces.

## 2) Current state audit

### Existing implementations

- **`backend/app/api/v1/studies.py:771` — `GET /api/v1/studies/{study_id}/chain`** (Phase 1, `feat_overnight_autopilot`). Returns `StudyChainResponse` for **one** study's chain (the chain its `study_id` belongs to). It does NOT answer "which chains completed recently" — there is no list-of-chains endpoint. This is the single most important gap this feature must close.
- **`backend/app/db/repo/study.py:250` — `get_chain_for_study(db, study_id)`** returns a `ChainTraversalResult` (anchor id, ordered `links[]`, proposal map, optional anchor trials). Per-study traversal only.
- **`backend/app/domain/study/chain_summary.py`** — pure-domain derivations reused by the chain endpoint: `derive_chain_stop_reason(links, anchor_trials)`, `compute_cumulative_lift(links, anchor_trials)`, `select_best_link(links)`. These are reused unchanged by this feature's new endpoint.
- **`backend/app/api/v1/studies.py:466` — `GET /api/v1/studies` (`list_studies`)** — cursor-paginated study list. Its response shape `StudySummary` (`backend/app/api/v1/schemas.py:879`) carries `id, name, cluster_id, status, best_metric, direction, created_at, completed_at` — **it does NOT carry `parent_study_id`**. This is why pure client-side anchor/leaf detection is impossible without N+1 round-trips, and why a server-side discovery endpoint is required.
- **`ui/src/app/studies/page.tsx`** — the `/studies` page. Renders an `<h1>Studies</h1>` header, an optional target-filter chip row, then a `<Card>` wrapping `<StudiesTable>`, then the `<CreateStudyModal>`. The new card mounts between the header block and the existing filter-chip/table `<Card>`.
- **`ui/src/lib/api/studies.ts:212` — `useStudyChain(studyId)`** — TanStack hook for the per-study chain. The new `useRecentChains` hook follows the same `apiClient.get` + `useQuery` pattern in this file.
- **`ui/src/lib/glossary.ts:917` — `overnight_autopilot` glossary key** (and `:929` `auto_followup_chain`). The card reuses `overnight_autopilot` for its info affordance; a new `recent_chains_card` key is added for the card itself.

### Navigation and link impact

No existing links change. The card adds a new outbound link per row to `/studies/{anchor_study_id}` (an existing route — `ui/src/app/studies/[id]/page.tsx`).

| Source file | Current link target | New link target |
|---|---|---|
| (new) `ui/src/components/studies/recent-chains-card.tsx` | — | `/studies/{anchor_study_id}` (existing detail route) |

### Existing test impact

No existing test changes meaning. New tests are added (see §14). The `/studies` page currently has frontend vitest coverage for the clone-from deep link and target-filter chip; the new card is additive and must not break the existing `StudiesTable` render assertions.

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/...studies/page*.test.tsx` (if present) | `<StudiesTable>` render | n/a | None — card is additive; new tests cover the card separately |

### Existing behaviors affected by scope change

- **`/studies` initial render:** Current: header + filter chips + table. New: header + **(conditional) recent-chains card** + filter chips + table. Decision needed: **No** — additive, conditional on having ≥1 unseen completed chain.

---

## 3) Scope

### In scope

- A new **read-only** endpoint `GET /api/v1/studies/chains/recent?since=<ts>&limit=<n>` that returns one summary row per **completed anchor-rooted overnight chain** whose newest link completed at/after `since`. Reuses the Phase 1 `chain_summary.py` derivations per chain.
- A new repo helper to find candidate anchors (chains of length ≥ 2 — i.e., the chaining engine actually ran a follow-up) whose tail completed at/after `since`, then hydrate each chain via the existing `get_chain_for_study` traversal logic.
- A frontend **"ran while you were away" card** on `/studies`, conditional on ≥1 returned chain, listing per chain: anchor name, chain length, best metric, cumulative lift, stop-reason phrase, and a "Review chain" link to the anchor detail page.
- A **localStorage-backed visited-state hook** that stores `last_visited_studies_at` (ISO-8601 UTC) and supplies it as the `since` query param. A "Got it" dismiss action advances the stored timestamp to "now," hiding the card until a newer chain completes.
- A new glossary key `recent_chains_card` plus reuse of the existing `overnight_autopilot` key for the card's info affordance.

### Out of scope

- Any change to the chaining engine (`backend/app/domain/study/auto_followup.py`, the auto-followup worker). This feature is read-side + UI only — identical posture to Phase 1.
- Server-side per-operator visited state (a `studies_visits` table or `users.last_visited_at`). Locked to localStorage for MVP2 (no auth). Revisit when multi-tenant lands.
- Outgoing webhook / email / push notification for chain-complete events (backlog idea per Phase 1 spec §3).
- Per-link convergence verdict inlined into the card. `feat_study_convergence_indicator` shipped, so this is *possible* as a follow-on enhancement, but it is explicitly deferred to keep this feature's surface bounded (see §19 open question OQ-1).
- Any new migration. The feature reads existing `studies` columns only.

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) and the existing `backend/app/api/v1/studies.py` router:

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints. The new endpoint lives under the existing studies router prefix: `/api/v1/studies/chains/recent`. (Confirmed: the router uses `/studies/...` paths; the chain endpoint is `/studies/{study_id}/chain`.)
- **Router namespace for this feature's endpoints:** `backend/app/api/v1/studies.py` (the existing studies router — no new router file).
- **HTTP methods:** `GET` only (read-only).
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — verified at `backend/app/api/v1/studies.py:89` (`_err()` helper builds exactly this). Malformed **typed query params** (e.g. a bad `since` datetime) are translated into this same envelope automatically by the global `validation_exception_handler` registered at `backend/app/api/errors.py:129-169,195` (it emits `error_code=VALIDATION_ERROR`, `retryable=false`). The endpoint MUST therefore declare `since`/`limit` as typed FastAPI query params and rely on this handler — it MUST NOT add a redundant manual parse-and-`_err` path for the same case.
- **Auth error shape:** N/A — single-tenant, no auth surface through GA v1.
- **Pagination / headers:** list endpoints emit `X-Total-Count` and use cursor pagination (`next_cursor` + `has_more`) per `list_studies` at `studies.py:536-552`. This endpoint follows the same shape (see §8).

### Phase boundaries (if multi-phase)

Single-phase feature. This IS "Phase 2" of `feat_overnight_autopilot`, now delivered as its own standalone feature. There are no further deferred phases — no `phase<N>_idea.md` tracking files are required.

## 4) Product principles and constraints

- **Read-only over the shipped engine.** No mutation of `studies`, `trials`, or `proposals`. The card and endpoint are pure reads — consistent with RelyLoop's "the tool's role ends at the PR" posture.
- **Discoverability, not nagging.** The card is dismissible and only re-appears when a *newer* chain completes. It must never block, modal, or interrupt.
- **Single-tenant reality.** No auth, no per-user server state. Visited-state is client-local (localStorage). This is correct for MVP2 and is explicitly revisited when multi-tenant lands.
- **Enum discipline (CLAUDE.md).** The card's stop-reason phrasing maps from the backend `CHAIN_STOP_REASONS` frozenset — the mapping table must be grounded with a `// Values must match backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS` source-of-truth comment (the Phase 1 `AutoFollowupChainPanel` already establishes this pattern at `ui/src/components/studies/auto-followup-chain-panel.tsx:32`).

### Anti-patterns

- **Do not** add `parent_study_id` to `StudySummary` and fan out N `/chain` calls client-side — because that is both a wire-contract change AND N+1 latency. One server-side aggregation endpoint is strictly better. (This is the locked rejection from idea-preflight.)
- **Do not** store visited-state server-side via an "anonymous operator" row — because it is pure overhead until auth lands and delivers zero multi-device benefit in a single-tenant install.
- **Do not** treat a single-link "chain" (a study with no follow-up child) as a chain — the card is specifically about *overnight chains that ran follow-ups*. Filter to chains of length ≥ 2 so a normal manual study never appears in the card.
- **Do not** re-derive cumulative lift / stop reason in the new endpoint — because `chain_summary.py` already owns those semantics and re-deriving risks drift. Reuse the existing functions.
- **Do not** make the card a blocking modal or auto-redirect — because it is a passive discoverability affordance, not an interrupt.

## 5) Assumptions and dependencies

- **Dependency: `feat_overnight_autopilot` (Phase 1).**
  - Why required: this feature reuses the Phase 1 `chain_summary.py` derivations and the `/studies/{id}/chain` panel that "Review chain" links into.
  - Status: **implemented** — merged as PR #343 on 2026-05-31 (`implemented_features/2026_05_31_feat_overnight_autopilot/`).
  - Risk if missing: none — the dependency is satisfied.
- **Dependency: `feat_study_convergence_indicator`.**
  - Why required: only for the optional per-link convergence one-liner (deferred — see OQ-1). Not required for the core feature.
  - Status: implemented (PR #352).
  - Risk if missing: n/a (optional enhancement only).
- **Assumption:** study counts on a single-tenant laptop are modest (hundreds, not millions), so a `WHERE parent_study_id IS NOT NULL` discovery query without a dedicated index is acceptable for MVP2 (see §13 Performance).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (the single operator).
- **Role model:** N/A — single-tenant install, no auth surface.
- **Permission boundaries:** N/A — single-tenant.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A for this feature. Both new surfaces are **non-mutating**: the `GET /api/v1/studies/chains/recent` endpoint is a pure read, and the visited-state write is client-only localStorage (no tenant-visible state change reaches the backend). No `audit_log` emission is required even once `audit_log` lands at MVP3, because there is no state mutation to record.

## 7) Functional requirements

### FR-1: Recent-completed-chains discovery endpoint
- Requirement:
  - The system **MUST** expose `GET /api/v1/studies/chains/recent` returning one summary row per completed, anchor-rooted overnight chain (chain length ≥ 2) whose **tail (newest link) `completed_at` is at/after the `since` query param** (when `since` is omitted, return the most-recent completed chains up to `limit`).
  - The system **MUST** derive each row's `best_metric`, `cumulative_lift`, `stop_reason`, and `best_link_proposal_id` by reusing the Phase 1 `chain_summary.py` functions (`compute_cumulative_lift`, `derive_chain_stop_reason`, `select_best_link`) — never re-deriving inline.
  - The system **MUST** include the anchor's display `name`, `anchor_study_id`, and `chain_length` (= number of links) per row.
  - The system **MUST** exclude single-link "chains" (a study with no follow-up child) so normal manual studies never appear.
  - The system **MUST** emit exactly **one row per anchor** — a chain has multiple non-anchor members, so the discovery query MUST resolve each candidate member to its anchor and de-duplicate to a single row per `anchor_study_id` **before** applying `limit` and computing `X-Total-Count`. Two members of the same chain must never produce two card rows.
  - The system **SHOULD** order rows by tail `completed_at` DESC (newest-finished chain first) and cap at `limit` (default 20, max 50).
- Notes: A "completed chain" means the chain's tail link is in a terminal state (`completed`, `cancelled`, or `failed`). A chain with any `queued`/`running` link is in-flight and MUST be excluded (it hasn't "finished while you were away"). The `stop_reason` derivation already returns `in_flight` for such chains via `derive_chain_stop_reason`; the endpoint filters those out before returning.

### FR-2: `since`-window filtering
- Requirement:
  - The system **MUST** accept an optional `since` query param (ISO-8601 datetime) and filter to chains whose tail `completed_at >= since`.
  - The system **MUST** treat an absent `since` as "no lower bound" (return the newest completed chains up to `limit`).
  - The system **MUST** return `422 VALIDATION_ERROR` (the standard envelope) for a malformed `since` value (FastAPI datetime coercion handles this).
- Notes: mirrors the existing `?since=` semantics on `list_studies` (`studies.py:476`).

### FR-3: "Ran while you were away" card
- Requirement:
  - The frontend **MUST** render a dismissible card at the top of `/studies` (between the page header and the existing filter/table card) **only when** the discovery endpoint returns ≥ 1 chain for the stored `since`.
  - The card **MUST** list each returned chain with: anchor `name`, `chain_length` ("3 studies"), `best_metric`, `cumulative_lift` (rendered as a signed delta), a human stop-reason phrase, and a "Review chain" link to `/studies/{anchor_study_id}`.
  - The card **MUST** render nothing (no empty shell) when zero chains are returned or while the query is pending/errored.
- Notes: visual priority — the card sits above the table because it is the "what's new" summary; it collapses to nothing when there's nothing new.

### FR-4: Stop-reason phrasing grounded in the backend allowlist
- Requirement:
  - The frontend stop-reason → phrase mapping **MUST** be grounded in `backend/app/domain/study/chain_summary.py` `CHAIN_STOP_REASONS` with a source-of-truth comment, covering every wire value: `depth_exhausted`, `no_lift`, `budget`, `parent_failed`, `cancelled`, `in_flight`.
  - Although `in_flight` chains are filtered out server-side (FR-1), the mapping **MUST** still include a phrase for it as a defensive fallback (never render a raw wire value).
- Notes: reuse the Phase 1 `AutoFollowupChainPanel` stop-reason map verbatim where phrasing already exists.

### FR-5: localStorage visited-state + dismissal
- Requirement:
  - The frontend **MUST** persist the visited-state timestamp (ISO-8601 UTC string) in `localStorage` under the namespaced key `relyloop.last_visited_studies_at` (the `relyloop.` prefix avoids collisions with other app keys) and pass it as the endpoint's `since` param.
  - On first ever visit (no stored value), the frontend **MUST** default `since` to "now minus a bounded lookback window" (default 7 days) so a brand-new operator sees recently-finished chains rather than the entire history — but never sees an unbounded backfill.
  - The "Got it" dismiss action **MUST** advance the stored `relyloop.last_visited_studies_at` to the **maximum `tail_completed_at` among the currently-displayed chains, plus 1 millisecond** (a server-derived timestamp nudged just past the newest displayed chain), NOT the browser's local `now`. The `+1ms` nudge is **required** because the endpoint's `since` filter is **inclusive** (`tail_completed_at >= since`, matching `list_studies` `?since=` semantics — FR-2); storing the bare maximum would re-surface the just-dismissed chain on the next load. Nudging past it makes the next query exclude exactly the chains the operator already saw, while staying immune to client-clock skew. If `data` is empty when "Got it" is somehow triggered, fall back to the existing stored value (no-op).
  - The visited-state write **MUST NOT** reach the backend (client-only).
- Notes: the bounded first-visit lookback prevents a months-old install from dumping every historical chain into the card on first load. 7 days is the default; revisit if operators report it's too short/long. Using the max returned `tail_completed_at` (a DB-sourced UTC timestamp) as the dismissal cutoff avoids the clock-skew failure mode where `Date.now()` on a fast client clock would skip chains.

### FR-6: Info affordance / glossary
- Requirement:
  - The card **MUST** carry an info affordance (`<InfoHint>` / glossary popover, matching the established contextual-help pattern) explaining what an overnight chain is, reusing the existing `overnight_autopilot` glossary key.
  - A new glossary key `recent_chains_card` **MUST** be added describing the card itself (what "ran while away" means, that dismissing hides it until a new chain finishes).
- Notes: keeps contextual-help drift-free per `feat_contextual_help`.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/chains/recent` | List completed overnight chains (length ≥ 2) whose tail finished at/after `since` | `422 VALIDATION_ERROR` (bad `since`/`limit`) |

**Route placement note:** the static path segment `chains/recent` must be registered so it does **not** collide with the existing dynamic `GET /api/v1/studies/{study_id}` route. FastAPI matches routes in declaration order, and `chains` would otherwise be captured as a `{study_id}` path value. The new route MUST be declared **before** the `/studies/{study_id}` route in `studies.py` (or use a sufficiently specific path) so `chains` is never swallowed by the dynamic segment. This is a verification item for the implementation plan.

Query params:
- `since` (optional, ISO-8601 datetime) — lower bound on tail `completed_at`.
- `limit` (optional, int, default 20, `ge=1, le=50`) — max rows.

**Pagination (OQ-2 resolved → `limit`-cap only):** the endpoint does **not** accept a `cursor` query param in this feature. The response still includes `next_cursor` and `has_more` fields for **shape-parity** with `StudyListResponse`, but they are always emitted as inert `null` / `false` respectively. Keyset paging over `(tail_completed_at DESC, anchor_id DESC)` is a deferred follow-on (captured as a `chore_` idea) to be picked up only if an operator hits the `limit` cap in practice. The card realistically shows a handful of chains, so the cap is sufficient for MVP2.

### 8.2 Contract rules
- Error body MUST include machine-readable `error_code` (per the `_err` envelope).
- Status codes MUST be deterministic: `200` with `data: []` when no chains match; `422` only for malformed query params.
- An empty result (no chains since `since`) is **not** an error — it returns `200` with `data: []`. The frontend renders no card in that case.

### 8.3 Response examples

Success (one completed 3-study chain since `since`):
```json
{
  "data": [
    {
      "anchor_study_id": "018f...a1",
      "anchor_name": "ACME KB relevance — overnight",
      "chain_length": 3,
      "best_metric": 0.8123,
      "objective_metric": "ndcg",
      "cumulative_lift": 0.0461,
      "direction": "maximize",
      "stop_reason": "no_lift",
      "best_link_proposal_id": "018f...c7",
      "tail_completed_at": "2026-06-01T06:14:22Z"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

**Nullable-field contract (failed / cancelled / no-metric chains):** because the endpoint includes chains whose tail is terminal-but-not-`completed` (`failed`, `cancelled`) and chains where no link produced a usable metric, the following row fields are **nullable** and the card MUST render a fallback rather than assume a value:
- `best_metric: float | null` — `null` when no link in the completed subset has a metric (`select_best_link` returned `None`).
- `cumulative_lift: float | null` — `null` when `best_metric` is `null` OR no anchor baseline is derivable (mirrors `compute_cumulative_lift` returning `None`).
- `best_link_proposal_id: string | null` — `null` when the best link has no surfaceable proposal, or when there is no best link.
- `objective_metric: string` — the objective's `metric` key (e.g. `"ndcg"`), read from the anchor's `objective` JSONB so the card can render an accurate "Best {metric}: …" label. Non-null (objective is a required, non-null column); defaults to the anchor's `objective["metric"]`.

The card's fallback for a `null` `best_metric`/`cumulative_lift` is to show the stop-reason phrase prominently (e.g. "Chain failed" / "No usable result") instead of a numeric metric line (see §11 + AC-11).

Empty (no chains finished since `since`) — HTTP 200:
```json
{ "data": [], "next_cursor": null, "has_more": false }
```

Failure — malformed `since` — HTTP 422 (standard envelope from `_err`):
```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "invalid since: <detail>",
    "retryable": false
  }
}
```

The `X-Total-Count` header is emitted as the count of **returned** rows (`len(data)`), NOT a full count of all matching chains. Rationale: an exact total would require resolving every candidate anchor (defeating the `limit`-bounded traversal and the §13 resource-exhaustion mitigation). Since this endpoint is `limit`-capped with no cursor (OQ-2), `X-Total-Count == len(data)` is the honest, bounded value. (This intentionally differs from `list_studies`, which can cheaply `COUNT(*)` a single-table filter; here the count would require the per-chain traversal fan-out.)

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `stop_reason` (response) | `depth_exhausted`, `no_lift`, `budget`, `parent_failed`, `cancelled`, `in_flight` | `backend/app/domain/study/chain_summary.py` (`CHAIN_STOP_REASONS` frozenset / `ChainStopReason` `Literal[...]`) | stop-reason phrase map in `ui/src/components/studies/recent-chains-card.tsx` |
| `direction` (response) | `maximize`, `minimize` | `backend/app/api/v1/schemas.py` (`ObjectiveDirection` Literal — already used by `StudyChainResponse`) | metric/lift sign rendering in the card |

The card emits **no** wire values to the backend (no filters/sorts the user controls), so there is no inbound enum-drift risk; the only enum contract is the inbound `stop_reason`/`direction` rendering, locked above.

### 8.5 Error code catalog

No new error codes. The endpoint reuses `VALIDATION_ERROR` (422) from the shared `_err` envelope for malformed query params.

## 9) Data model and state transitions

### New/changed entities

**None.** No new table, no new column, no migration. The feature reads existing `studies` columns:
- `studies.parent_study_id` (`String(36)`, nullable, self-FK — `backend/app/db/models/study.py:82`) — chain linkage.
- `studies.completed_at` (`timestamptz`, nullable — `:121`) — tail-completion window filter.
- `studies.status`, `studies.best_metric`, `studies.baseline_metric`, `studies.objective`, `studies.config`, `studies.name`, `studies.created_at` — consumed by the reused `chain_summary.py` derivations and the row shape.

### Required invariants

- Linear-chain invariant (D-7 from Phase 1): a chain is a linear `parent_study_id` lineage of length 1..6. The discovery endpoint reuses the Phase 1 traversal's defensive caps (10-hop upward, 5-descendant downward, cycle guards) by calling `get_chain_for_study` per candidate anchor.
- "Chain" = length ≥ 2. A study with no follow-up child is excluded (FR-1).

### State transitions

None — read-only feature.

### Idempotency/replay behavior

N/A — `GET` is naturally idempotent. The localStorage visited-state is last-write-wins per browser; multi-tab behavior is benign (each tab reads/writes the same key; the worst case is the card briefly re-appearing in another tab until it refetches, which is acceptable).

## 10) Security, privacy, and compliance

- **Threats:** (1) information disclosure via the new endpoint — mitigated: single-tenant, no cross-tenant boundary, returns only study metadata the operator already owns. (2) Resource exhaustion via an unbounded discovery query — mitigated: `limit` cap (≤ 50) + bounded per-chain traversal caps inherited from Phase 1 + bounded first-visit lookback window (FR-5). (3) localStorage tampering — benign: the worst an attacker-with-local-access can do is change which chains show in their own card; no privilege boundary crossed.
- **Controls:** input validation on `since`/`limit` via FastAPI typed query params; reuse of the hardened Phase 1 traversal.
- **Secrets/key handling:** none — no secrets touched.
- **Auditability:** N/A — no state mutation (see §6 Audit events).
- **Data retention/deletion/export impact:** none.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** top of the `/studies` page, between the `<h1>Studies</h1>` header block and the existing target-filter-chip row + `<Card><StudiesTable></Card>`. It is page content, not a global nav element.
- **Labeling taxonomy:**
  - Card title: **"Ran while you were away"**.
  - Per-row primary: the anchor study name (clickable link).
  - Per-row metadata: "{N} studies", "Best {objective_metric}: {best_metric}" (label sourced from the response's `objective_metric` field — e.g. "Best ndcg: 0.812"), "Lift: {+/-cumulative_lift}", stop-reason phrase. When `best_metric`/`cumulative_lift` are `null` (failed/no-metric chain), the numeric lines are replaced by the stop-reason phrase (per §8.3 nullable-field contract + AC-11).
  - Primary action per row: **"Review chain"** → anchor detail page.
  - Dismiss action: **"Got it"**.
- **Content hierarchy:** card title + dismiss button on the top row; then a compact list of chain rows (newest-finished first). Each row is a single line on desktop, wrapping on mobile.
- **Progressive disclosure:** the card shows the rolled-up summary only; the full per-link breakdown lives on the anchor's detail page (the existing `AutoFollowupChainPanel`). "Review chain" is the bridge. An info affordance (glossary popover) explains what an overnight chain is.
- **Relationship to existing pages:** extends `/studies` (sits alongside the existing table). Links into the existing `/studies/[id]` detail page where the Phase 1 panel already lives.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| Card title info icon | "RelyLoop ran follow-up studies overnight, each narrowing on the previous winner. This card shows chains that finished since your last visit." | info-icon click | top | new `recent_chains_card` |
| "Overnight" term in card body | reuse existing `overnight_autopilot` short text ("Run additional studies overnight, each narrowing in on the previous winner. Stops on its own; you still open every PR.") | hover/focus | top | existing `overnight_autopilot` (`glossary.ts:917`) |
| "Lift" label | "How much better the chain's best study scored vs. the anchor study's baseline." | hover/focus | top | reuse/extend convergence/lift glossary phrasing |

All tooltip text traces to a glossary key (existing `overnight_autopilot`; new `recent_chains_card` added in the glossary story). No free-floating tooltip text.

### Primary flows

1. **Wake-up review.** Operator opens `/studies` in the morning → the card shows "2 chains finished while you were away" → they click "Review chain" on the top one → land on the anchor detail page with the Phase 1 `AutoFollowupChainPanel` → review and open a PR if warranted.
2. **Dismiss.** Operator reads the card, decides nothing needs action → clicks "Got it" → `last_visited_studies_at` advances to the max displayed `tail_completed_at` + 1ms (FR-5) → card disappears → stays hidden until a chain *newer than the newest one just shown* completes.

### Edge/error flows

- **No chains since last visit:** endpoint returns `data: []` → no card renders.
- **First ever visit (no stored timestamp):** `since` defaults to now − 7 days → only recently-finished chains show (no full-history dump).
- **Endpoint error / pending:** card renders nothing (no error banner — discoverability is best-effort and must never block the page).
- **Chain still in-flight:** excluded server-side (FR-1) — only fully-finished chains appear.
- **A chain member hard-deleted between discovery and traversal:** the reused Phase 1 traversal returns `None` for that anchor → the endpoint skips it (defensive; matches the Phase 1 concurrent-delete handling at `study.py:327-333`).

## 12) Given/When/Then acceptance criteria

### AC-1: Completed chain appears in the discovery endpoint
- Given a 3-study chain where the tail completed at `2026-06-01T06:00:00Z`
- When `GET /api/v1/studies/chains/recent?since=2026-06-01T00:00:00Z`
- Then the response `data` contains exactly one row with `anchor_study_id` = the anchor, `chain_length` = 3, a non-null `cumulative_lift`, a `stop_reason` ∈ `CHAIN_STOP_REASONS`, and `tail_completed_at` = `2026-06-01T06:00:00Z`.

### AC-2: Single-study (no follow-up) is excluded
- Given a study with `parent_study_id IS NULL` and no children, completed within the window
- When `GET /api/v1/studies/chains/recent?since=<earlier>`
- Then that study does NOT appear in `data` (chains require length ≥ 2).

### AC-3: `since` filters by tail completion
- Given two completed chains — chain A's tail completed at `T-2h`, chain B's at `T+2h` (relative to `since=T`)
- When `GET /api/v1/studies/chains/recent?since=T`
- Then only chain B appears.

### AC-4: In-flight chain excluded
- Given a 2-study chain whose tail link is still `running`
- When `GET /api/v1/studies/chains/recent` (no `since`)
- Then the chain does NOT appear (only fully-finished chains).

### AC-5: Empty result is 200, not error
- Given no chains completed since `since`
- When `GET /api/v1/studies/chains/recent?since=<future>`
- Then HTTP `200` with body `{"data": [], "next_cursor": null, "has_more": false}` and `X-Total-Count: 0`.

### AC-6: Malformed `since` returns 422 envelope
- Given `since=not-a-date`
- When the endpoint is called
- Then HTTP `422` with `detail.error_code == "VALIDATION_ERROR"`.
- Example: `GET /api/v1/studies/chains/recent?since=not-a-date` → `{"detail":{"error_code":"VALIDATION_ERROR","message":"...","retryable":false}}`.

### AC-7: Card renders only when chains exist
- Given the endpoint returns ≥ 1 chain
- When the operator loads `/studies`
- Then the "Ran while you were away" card renders above the studies table with one row per chain and a "Review chain" link to `/studies/{anchor_study_id}`.
- And Given the endpoint returns `data: []`, Then no card renders.

### AC-8: "Got it" dismiss hides the card
- Given the card is visible showing chains whose newest `tail_completed_at` is `T_max`
- When the operator clicks "Got it"
- Then `relyloop.last_visited_studies_at` in localStorage is set to `T_max + 1ms` (NOT client `now`) AND the card disappears AND a reload (with no chain finished strictly after `T_max`) shows no card.
- And Given a new chain completes at `T_max + 1h` after dismissal, When the page reloads, Then the card re-appears showing only that newer chain (the inclusive `>=` filter against `T_max + 1ms` excludes the previously-dismissed chains).

### AC-9: First-visit bounded lookback
- Given no `last_visited_studies_at` in localStorage and a chain that completed 30 days ago
- When the operator loads `/studies` for the first time
- Then that 30-day-old chain does NOT appear (first-visit lookback is bounded to 7 days), but a chain completed 2 days ago DOES appear.

### AC-10: Stop-reason phrase never shows a raw wire value
- Given a chain with `stop_reason == "no_lift"`
- When the card renders
- Then the row shows a human phrase (e.g., "Stopped: no further improvement"), never the literal `no_lift`.

### AC-11: Failed / no-metric chain renders a fallback, not a crash
- Given a 2-study chain whose tail link `failed` (so `best_metric`, `cumulative_lift`, and `best_link_proposal_id` are all `null`)
- When the chain is returned by the endpoint and the card renders the row
- Then the endpoint returns those three fields as `null` (200, valid shape), AND the card row shows the stop-reason phrase prominently (e.g. "Chain failed") instead of a numeric metric/lift line, AND "Review chain" still links to the anchor detail page.

### AC-12: One row per chain regardless of which member matched
- Given a 3-study chain (anchor + 2 children) whose tail completed in the window
- When `GET /api/v1/studies/chains/recent?since=<earlier>`
- Then `data` contains exactly ONE row for that chain (keyed on `anchor_study_id`), not three — and `X-Total-Count` reflects one chain.

## 13) Non-functional requirements

- **Performance:** The discovery query scans `studies` for candidate anchors (`parent_study_id IS NOT NULL` to find chained members, then resolves anchors) and runs the bounded Phase 1 traversal per candidate chain (≤ `limit` chains × ≤ 6 links). `studies.parent_study_id` has **no dedicated index** today (only `parent_proposal_id` is indexed, per migration 0018). For MVP2 single-tenant scale (hundreds of studies) a sequential scan is acceptable; the `limit` cap (≤ 50) bounds the traversal fan-out. If a future install reports slowness, add `ix_studies_parent_study_id` + `ix_studies_completed_at` in a follow-on chore (captured as OQ-3 / a deferred idea, not in this feature's scope).
- **Reliability:** the card is best-effort — endpoint failure or pending state renders no card and never blocks the page (FR-3 edge flow).
- **Operability:** the endpoint reuses the Phase 1 traversal's existing WARN logs (fan-out, cycle, cap). No new metrics required for MVP2.
- **Accessibility:** the card is keyboard-navigable; the dismiss button has an `aria-label`; the info affordance follows the existing `<InfoHint>` a11y pattern; stop-reason phrases are screen-reader-friendly text, not icons.

## 14) Test strategy requirements (spec-level)

- **Unit (`backend/tests/unit/`):** the new repo helper's anchor-discovery + length-≥2 filtering logic is exercised through the integration layer (DB-backed); any pure helper added (e.g., a row-shaping function) gets a unit test. The reused `chain_summary.py` functions already have unit coverage from Phase 1 — no duplication.
- **Integration (`backend/tests/integration/`):** new tests in the spirit of `test_studies_chain_api.py` / `test_studies_chain_repo.py` covering AC-1 through AC-5 and AC-9's window logic against a real DB: completed 3-chain appears; single-study excluded; `since` boundary; in-flight excluded; empty → `data: []`; hard-deleted-link skip.
- **Contract (`backend/tests/contract/`):** new assertions in the spirit of `test_studies_chain_contract.py` covering the response shape (keys, types), the `422` envelope for malformed `since` (AC-6), and the `X-Total-Count` header. Update the hand-maintained contract allowlists if the new endpoint trips them (note: `bug_contract_allowlists_outdated_after_mvp2_features` is open — coordinate).
- **E2E / frontend (`ui/src/__tests__/` + `ui/tests/e2e/`):** vitest component tests for the card (renders rows from a fixture, dismiss advances localStorage, renders nothing on empty/error, stop-reason phrase mapping covers all 6 values — AC-7/8/10). A real-backend Playwright spec (no `page.route()` mocking) that seeds a completed chain via API helpers, loads `/studies`, asserts the card is visible with the right anchor name, clicks "Review chain", and asserts navigation to the anchor detail page — anchored to the real-backend E2E posture (CLAUDE.md forbids `page.route()` mocking of backend endpoints).

## 15) Documentation update requirements

- `docs/01_architecture`: add the new endpoint to the studies surface notes in [`api-conventions.md`](../../../01_architecture/api-conventions.md) (or the studies section it cross-references) and a one-line note in [`ui-architecture.md`](../../../01_architecture/ui-architecture.md) about the recent-chains card placement.
- `docs/02_product`: N/A (no new user story doc required; covered by the autopilot story).
- `docs/03_runbooks`: N/A — no new ops procedure (read-only feature).
- `docs/04_security`: N/A.
- `docs/05_quality`: N/A (test layers documented in §14).
- `docs/08_guides`: optional — the autopilot tutorial step (Phase 1 added Tutorial Step 12) MAY get a one-line mention that the `/studies` card surfaces finished chains. Not required for completion.
- `state.md`: refresh "Last 5 merges" + drop oldest into `state_history.md` on merge.
- `CLAUDE.md`: no new convention; no edit required.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none — additive read-only feature, ships behind no flag.
- **Migration/backfill expectations:** none — no schema change.
- **Operational readiness gates:** standard CI (lint, typecheck, backend tests + 80% coverage, frontend vitest + tsc + ESLint + build, smoke E2E).
- **Release gate:** all ACs green in CI; frontend card behind no flag; `bug_contract_allowlists_outdated_after_mvp2_features` coordination resolved if the new endpoint trips the allowlists.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-4, AC-12 | Repo helper + endpoint stories | `test_studies_chain_recent_repo.py`, `test_studies_chain_recent_api.py` | api-conventions.md |
| FR-2 | AC-3, AC-5, AC-6 | Endpoint story | `test_studies_chain_recent_api.py`, `test_studies_chain_recent_contract.py` | api-conventions.md |
| FR-3 | AC-7, AC-11 | Card component story | `recent-chains-card.test.tsx`, Playwright spec | ui-architecture.md |
| FR-4 | AC-10 | Card component story | `recent-chains-card.test.tsx` | — |
| FR-5 | AC-8, AC-9 | Visited-state hook story | `recent-chains-card.test.tsx`, `use-recent-chains-visited.test.ts` | ui-architecture.md |
| FR-6 | (covered via FR-3 render) | Glossary story | `glossary.test.ts` | — |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 … AC-12) pass in CI.
- [ ] All test layers (integration / contract / frontend vitest / real-backend E2E) are green; reused domain logic retains Phase 1 unit coverage.
- [ ] Documentation updates (api-conventions.md, ui-architecture.md) merged.
- [ ] Rollout gates from §16 satisfied.
- [ ] No open questions remain in §19 (OQ-1/OQ-2/OQ-3 resolved or explicitly deferred with an idea file).

## 19) Open questions and decision log

### Open questions

- **OQ-1 — Per-link convergence one-liner in the card?** `feat_study_convergence_indicator` shipped, so the card *could* include "Link 2 still climbing — budget may have been short." **Recommended default: DEFER** — keep the card to the rolled-up summary for MVP2; the per-link verdict lives on the detail page. If pulled in, it adds a per-link convergence fetch/derivation to the endpoint. Owner: PM — Due: before implementation plan (default = defer; capture as a follow-on idea if desired).
- ~~**OQ-2 — Cursor pagination on the discovery endpoint, or `limit`-cap only?**~~ **RESOLVED (2026-06-01) → `limit`-cap only.** No `cursor` query param this feature; `next_cursor`/`has_more` ship as inert `null`/`false` for shape-parity. Keyset paging is a deferred `chore_` follow-on. See §8.1 + decision log.
- **OQ-3 — Add `ix_studies_parent_study_id` (+ `ix_studies_completed_at`) now or defer?** **Recommended default: DEFER** — single-tenant scale doesn't need it; adding an index would pull a migration into an otherwise migration-free feature. Capture as a `chore_` idea to add the index if a large install reports slowness. Owner: engineering — Due: before implementation plan (default = defer).

### Decision log
- **2026-06-01** — Visited-state model locked to **cookie/localStorage** (not server-side). Rationale: single-tenant + no auth makes server-side per-user state pure overhead until the backlog auth layer lands.
- **2026-06-01** — Chain-discovery locked to a **server-side `GET /api/v1/studies/chains/recent` endpoint**, rejecting client-side fan-out. Rationale: `StudySummary` lacks `parent_study_id`, so client-side anchor detection would require both a wire-contract change and N+1 `/chain` round-trips; one server aggregation is strictly better.
- **2026-06-01** — "Chain" defined as **length ≥ 2** for card purposes. Rationale: the card is specifically about overnight chains that ran follow-ups; a lone manual study is not a chain.
- **2026-06-01** — Feature is **single-phase** (this IS Phase 2 of `feat_overnight_autopilot`, delivered standalone). No further deferred phases; no `phase<N>_idea.md` tracking files required.
- **2026-06-01** (GPT-5.5 cycle 1) — **OQ-2 resolved → `limit`-cap only**, no `cursor` param; `next_cursor`/`has_more` inert for shape-parity. Removed the contradiction between §8.1 and OQ-2.
- **2026-06-01** (GPT-5.5 cycle 1) — `best_metric`, `cumulative_lift`, `best_link_proposal_id` declared **nullable** in the response; card renders the stop-reason phrase as a fallback for failed/no-metric chains (AC-11). Rationale: the endpoint includes terminal `failed`/`cancelled` tails, which may have no usable metric.
- **2026-06-01** (GPT-5.5 cycle 1) — Added `objective_metric` (objective's `metric` key) to the response row so the card's "Best {metric}: …" label is accurate rather than generic.
- **2026-06-01** (GPT-5.5 cycle 1) — Dismissal cutoff is the **max returned `tail_completed_at`** (DB-sourced), not client `Date.now()`, to avoid clock-skew suppression.
- **2026-06-01** (GPT-5.5 cycle 1) — `X-Total-Count` = count of **returned** rows, not all-matching, to preserve the `limit`-bounded traversal (§13 resource bound). Documented the intentional divergence from `list_studies`.
- **2026-06-01** (GPT-5.5 cycle 1) — Added an explicit **one-row-per-anchor de-duplication** invariant (FR-1 + AC-12): multiple members of one chain must collapse to a single row before `limit`/count.
- **2026-06-01** (GPT-5.5 cycle 1) — Cited the global `validation_exception_handler` (`errors.py:129-169,195`) so the malformed-`since` → `VALIDATION_ERROR` envelope is automatic; forbade a redundant manual parse path. (GPT-5.5's premise that no handler exists was rejected with this counter-evidence; the citation was added to prevent a redundant implementation.)
