# Feature Specification — Overnight final solution Phase 2 (morning summary card + strategy line)

**Date:** 2026-06-03
**Status:** Draft
**Owners:** Product: TBD · Engineering: TBD
**Related docs:**
- [`idea.md`](idea.md)
- [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)
- Shipped predecessor: [`feat_overnight_final_solution`](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md) (Phase 1 — the autonomous cross-knob exploration capability + the `selected_followup_kind` chain-payload field this spec consumes)
- Shipped sibling: [`feat_overnight_autopilot`](../../implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md) (the `/chain` endpoint + the chain panel this spec sits adjacent to)
- Shipped sibling: [`feat_study_convergence_indicator`](../../implemented_features/2026_06_01_feat_study_convergence_indicator/feature_spec.md) (the `StudyDetail.convergence.verdict` field Cap 4 consumes)
- Idea-stage sibling: [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md) (the `/studies` list "ran while away" surface — Phase 2 explicitly defers index-page work there per D-4)

---

## 1) Purpose

- **Problem:** After Phase 1 ships, an operator who picks `follow_suggestions` overnight wakes up to a chain of up to 6 studies — each with its own auto-created `pending` proposal — plus the existing chain panel mid-page on `/studies/{id}` that surfaces the rolled-up `cumulative_lift` / `best_link_id` / `stop_reason` and per-link Strategy badges. The data needed to answer *"what's the answer, what was explored, and which PR ships it?"* is all in the `/chain` payload, but it's panel-shaped and mid-page; the morning review is a scroll-and-scan, not a glance. Also unresolved from Phase 1 (OQ-2 / D-15): a "Strategy: …" cue on the study detail page so a mid-chain operator can see at a glance *"this study is running under `follow_suggestions`"* without scrolling to the chain panel's per-link badges.
- **Outcome:** When the chain that this study belongs to has terminated (`stop_reason` ≠ `in_flight`) and has at least 2 links, a top-of-page **Overnight result card** mounts above `LinkedEntitiesRow` and compresses the morning review into one glance: the headline lift, the one-line explored path, a link to the winning proposal, the stop reason in plain English, the winner's convergence verdict, and a short excerpt from the winner's digest narrative. The card is hide-on-empty for legacy `narrow` chains where every link's `selected_followup_kind` is null — they get a path-less summary, not a "→ → →" of blanks. Independently, a **read-only strategy line** mounts inside `LinkedEntitiesRow` for any study whose `config.auto_followup_strategy` is set, so mid-chain operators get the cue without waiting for chain termination.
- **Non-goal:** **Not** an index-page surface (delegated to the sibling `feat_overnight_studies_summary_card` per D-4 — the two specs will share the `/chain` summary domain helper but mount different surfaces). **Not** a new endpoint, **not** a new LLM call, **not** a chain-level narrative generator (D-2 — reuse the winning link's existing `digests.narrative`). **Not** a new schema additive — every datum the card needs is already exposed by `/chain` + per-study `/api/v1/studies/{id}` + per-study `/api/v1/studies/{id}/digest`.

## 2) Current state audit

### Existing implementations

| Component | Path | Behavior relevant to this feature |
|---|---|---|
| Study detail page | [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/[id]/page.tsx) | Renders a vertical stack: `<StudyHeader>` → `<LinkedEntitiesRow>` ([line 96](../../../../ui/src/app/studies/[id]/page.tsx#L96)) → optional proposal link → `<AutoFollowupChainPanel>` ([line 110](../../../../ui/src/app/studies/[id]/page.tsx#L110)) → `<ConfidencePanel>` → `<ConvergencePanel>` → `<TrialsCard>` → `<DigestPanel>` (gated on `study.status === 'completed'`). The new Overnight result card mounts BETWEEN `<StudyHeader>` and `<LinkedEntitiesRow>` (per D-6 / FR-1). |
| Linked entities row | [`ui/src/components/studies/linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) | Renders the four foreign-key chips for the study (cluster, query set, judgment list, template). The new Strategy read-only line mounts INSIDE this component (per D-5 / FR-2). |
| Chain panel | [`ui/src/components/studies/auto-followup-chain-panel.tsx`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx) | Already calls `useStudyChain(study.id)` and renders the ordered link list + cumulative-lift + best-config CTA + stop-reason phrase + per-link `<ChainLinkStrategyBadge>` ([line 80](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L80)). Unchanged by this spec — the new top-of-page card consumes the same `useStudyChain` data and displays a SUBSET of it for the at-a-glance compression. Both surfaces stay (the card is glance; the panel is detail). |
| `useStudyChain` hook | [`ui/src/lib/api/studies.ts:212-239`](../../../../ui/src/lib/api/studies.ts#L212-L239) | Fetches `GET /api/v1/studies/{id}/chain`, polls 15s while `stop_reason === 'in_flight'`, polls 15s within a 120s grace window after the tail completes for `no_lift`/`budget`, stops for other terminal reasons. The new card reuses this hook — no second query. |
| `useStudy` hook | [`ui/src/lib/api/studies.ts:74-87`](../../../../ui/src/lib/api/studies.ts#L74-L87) | `useStudy(id: string, options?: { refetchInterval?, enabled?: boolean })`. **Signature note (cycle-1 finding C1-A1 accept):** `id` is typed `string` (NOT `string \| undefined`), so the card cannot pass `chain.best_link_id` (a `str \| None`) directly. The card mounts a child component `<WinningLinkConvergenceChip linkId={...} />` ONLY when `chain.best_link_id !== null`, which type-narrows the id before the hook call (mirrors the `<ChainLinkStrategyBadge>` pattern at [`auto-followup-chain-panel.tsx:80`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L80)). Per D-3 the chip surfaces the winning link's `study.convergence?.verdict`. |
| `useStudyDigest` hook | [`ui/src/lib/api/digests.ts:30-50`](../../../../ui/src/lib/api/digests.ts#L30-L50) | `useStudyDigest(studyId: string \| undefined, opts?: { enabled?: boolean })`. Widened signature (per Story 1.2 of `feat_study_clone_narrow_bounds`) means the card can call `useStudyDigest(chain.best_link_id, { enabled: chain.best_link_id !== null })` directly without a child component. Returns `DigestResponse` carrying `narrative: str`. **Error contract (cycle-1 finding C1-A2 accept):** the digest endpoint returns 404 `DIGEST_NOT_READY` while the underlying study is still running; the hook suppresses that error via `meta.suppressErrorCodes: ['DIGEST_NOT_READY']` and `retry: false`, surfacing it as `isError: true` (NOT `data: null`). The card hides the narrative section in BOTH the `data === undefined` (loading) AND `isError === true` (404 or other error) cases. |
| `StudyChainResponse` | [`backend/app/api/v1/schemas.py:996-1008`](../../../../backend/app/api/v1/schemas.py#L996-L1008) | Already carries `anchor_study_id`, `best_link_id`, `best_metric`, `cumulative_lift`, `direction`, `stop_reason`, `proposal_id_for_best_link`, `links[]`. No additions needed. |
| `StudyChainLink` | [`backend/app/api/v1/schemas.py:953-994`](../../../../backend/app/api/v1/schemas.py#L953-L994) | Phase 1 added `selected_followup_kind: Literal["narrow_default","narrow","widen","swap_template"] | None = None` ([line 978](../../../../backend/app/api/v1/schemas.py#L978)) and `template_id: str` ([line 972](../../../../backend/app/api/v1/schemas.py#L972)). The card's path summary reads `link.selected_followup_kind`; the swap-template path summary resolves the target name via `useTemplate(link.template_id)` (mirrors the existing `<ChainLinkStrategyBadge>` pattern at [`auto-followup-chain-panel.tsx:80-117`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L80-L117)). |
| `StudyDetail.convergence` | [`backend/app/api/v1/schemas.py:937-950`](../../../../backend/app/api/v1/schemas.py#L937-L950) | `StudyConvergenceShape | None` carrying `verdict: "converged" | "still_improving" | "too_few_trials"`. The card surfaces `study.convergence.verdict` for the winning link only — graceful-degrade null is handled (verdict is hidden when null per D-3). |
| `useTemplate` hook | [`ui/src/lib/api/query-templates.ts:49`](../../../../ui/src/lib/api/query-templates.ts#L49) | Already used by the chain panel's per-link badge for swap-target name resolution. The new card's path-summary swap-template token uses the SAME hook + TanStack cache — zero new fetches per chain when the chain panel below has already populated the cache. |
| `StudyConfigSpec.auto_followup_strategy` | [`backend/app/api/v1/schemas.py:724`](../../../../backend/app/api/v1/schemas.py#L724) | Phase 1 added this `str | None` config key in `studies.config` JSONB. The Strategy read-only line in `<LinkedEntitiesRow>` reads `study.config?.auto_followup_strategy` (per FR-2). |
| `OVERNIGHT_STRATEGY_VALUES` | [`ui/src/lib/enums.ts:84-92`](../../../../ui/src/lib/enums.ts#L84-L92) | Phase 1's frontend mirror of the backend allowlist (`narrow`, `follow_suggestions`). The Strategy line in `<LinkedEntitiesRow>` consumes this constant for safe narrowing — no inline string literals (form-select-discipline rule, per [`CLAUDE.md` §"Enumerated Value Contract Discipline"](../../../../CLAUDE.md)). |
| `SELECTED_FOLLOWUP_KIND_VALUES` | [`ui/src/lib/enums.ts:94-110`](../../../../ui/src/lib/enums.ts#L94-L110) | Phase 1's frontend mirror of `auto_followup_strategy.py SELECTED_FOLLOWUP_KIND_VALUES`. The card's per-link path-summary token uses this constant for safe narrowing; reuses the `narrow_default`/`narrow`/`widen`/`swap_template` enumeration directly. |
| `CHAIN_STOP_REASONS` | [`backend/app/domain/study/chain_summary.py`](../../../../backend/app/domain/study/chain_summary.py) source-of-truth | Mirrored frontend-side in the existing chain panel's `CHAIN_STOP_REASON_PHRASE` map ([`auto-followup-chain-panel.tsx:34-41`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L34-L41)) — the new card REUSES that map by importing it (the map gains a named export) rather than re-deriving (per FR-1). |
| Glossary | [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Already carries Phase 1's `overnight_strategy`, plus pre-existing `overnight_autopilot`, `auto_followup_chain`, `auto_followup_depth`, `lift_gate`. Two new keys land here: `overnight_result` (the card's `InfoTooltip`) and `auto_followup_strategy_line` (the read-only line's `InfoTooltip`). |

### Navigation and link impact

No URL changes. Both new surfaces sit on the existing `/studies/{id}` page.

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (none) | (none) |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/studies/linked-entities-row.test.tsx`](../../../../ui/src/__tests__/components/studies/linked-entities-row.test.tsx) | Existing four-chip render tests | Existing | Extend with strategy-line render tests (visible / hidden by `config.auto_followup_strategy` value). Existing assertions remain unchanged. |
| [`ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`](../../../../ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx) | Chain panel rendering | Existing | No change required — the chain panel is untouched. The new card is a separate component with its own test file. |
| `ui/src/__tests__/app/studies/study-detail-page.test.tsx` (or wherever the page-level test lives) | Page-level mount order | TBD at impl-time | Add a structural assertion that the Overnight result card mounts BETWEEN `<StudyHeader>` and `<LinkedEntitiesRow>` when the chain has terminated. |
| `ui/tests/e2e/overnight-result-card.spec.ts` (new) | E2E coverage for the morning card | New file | Real-backend Playwright spec: seed a 2-link terminated chain via API helpers, navigate to `/studies/{anchor_id}`, assert card is visible at top with correct headline / path / best-config link / stop-reason phrase. |

### Existing behaviors affected by scope change

- **Study detail page vertical stack.** Current: `<StudyHeader>` → `<LinkedEntitiesRow>` → proposal link → `<AutoFollowupChainPanel>` → … New: insert `<OvernightResultCard>` between `<StudyHeader>` and `<LinkedEntitiesRow>` (rendered conditionally on chain terminal + ≥ 2 links). When the predicate is false, the card returns `null` and the layout is byte-identical to today. **Decision needed: no** — locked by D-6.
- **`<LinkedEntitiesRow>` content.** Current: four FK chips. New: append a fifth `<StrategyLine>` line item rendered conditionally on `study.config?.auto_followup_strategy in OVERNIGHT_STRATEGY_VALUES`. When the predicate is false, no line is rendered. **Decision needed: no** — locked by FR-2.
- **`useStudyChain` poll cadence.** Unchanged. The card consumes the existing hook's data; its visibility predicate (`stop_reason !== 'in_flight'` AND `links.length >= 2`) admits chains in the 120s `no_lift`/`budget` grace window where the hook still polls every 15s — the card stays visible across those refreshes; its render is data-driven and stable while terminal data settles. Polling stops entirely after the grace window or immediately for `depth_exhausted` / `parent_failed` / `cancelled` per the existing `useStudyChain` contract. The card's own renders do not issue independent fetches.
- **Auto-followup chain panel.** Unchanged. Per D-5 the card is glance / the panel is detail; both surfaces co-exist on the same page.

---

## 3) Scope

### In scope (single phase — Phase 2 is one PR)

- **FR-1**: New `<OvernightResultCard>` component mounts above `<LinkedEntitiesRow>` on `/studies/{id}` when `chain.stop_reason !== 'in_flight'` AND `chain.links.length >= 2`. Renders headline, explored-path summary, best-config link, stop-reason phrase, winning-link convergence verdict (when available), and a short excerpt from the winning link's `digests.narrative`. The path summary is hidden when every `link.selected_followup_kind` is null (legacy `narrow` chains — per D-7).
- **FR-2**: New `<StrategyLine>` element inside `<LinkedEntitiesRow>` renders a read-only "Strategy: Refine same knobs" or "Strategy: Try suggested follow-ups" line when `study.config.auto_followup_strategy` is set to a value in `OVERNIGHT_STRATEGY_VALUES`. Hidden for `None` / missing / unknown values.
- **FR-3**: Path summary token mapping (consumed by FR-1's "Explored: …" line):
  - `"narrow_default"` → `"refined"`
  - `"narrow"` → `"narrow"`
  - `"widen"` → `"widen"`
  - `"swap_template"` → `"swap to {short_template_name}"` (resolved via `useTemplate(link.template_id)`, truncated to 24 chars).
  - `null` → omit from the chain (anchor link gets no token).
  - Tokens join with `" → "`.
- **FR-4**: Winning link's convergence verdict is fetched via `useStudy(chain.best_link_id)`. The card surfaces `study.convergence?.verdict` as a small inline chip (`converged` / `still improving` / `too few trials`) next to the headline. When `chain.best_link_id` is null OR `study.convergence` is null, the chip is hidden (graceful-degrade per FR-3 of `feat_study_convergence_indicator`).
- **FR-5**: Winning link's digest narrative is fetched via `useStudyDigest(chain.best_link_id)`. The card renders the first ~240 characters (split at the nearest sentence boundary before 240 chars; fall back to a hard cut at 240 + "…" if no sentence boundary exists). A "View full digest →" link points at `/studies/{best_link_id}#digest`. When `useStudyDigest` returns null or errors, the narrative section is hidden (the card still renders headline + path + best config + stop reason).
- **FR-6**: Two new glossary keys land in `ui/src/lib/glossary.ts`: `overnight_result` (the card's title `InfoTooltip`) and `auto_followup_strategy_line` (the strategy-line `InfoTooltip`). Both follow the existing `short` (≤ 120 chars) + `long` (paragraph) shape.
- **FR-7**: Mount predicate is encoded as a pure-domain helper `shouldShowOvernightResultCard(chain: StudyChainResponse | undefined): boolean` colocated with the component, returning `chain !== undefined && chain.stop_reason !== 'in_flight' && chain.links.length >= 2`. Unit-tested independently of the React tree — keeps the component thin.
- **FR-8**: The card extracts the existing `CHAIN_STOP_REASON_PHRASE` map from `auto-followup-chain-panel.tsx` into a SHARED module `ui/src/lib/chain-stop-reason.ts` (named export `CHAIN_STOP_REASON_PHRASE`) and both surfaces import from it. Eliminates the source-of-truth drift risk that re-deriving the same enum mapping in two files would introduce.
- **FR-9**: Tutorial / runbook update — extend [`docs/08_guides/tutorial-first-study.md`](../../../../docs/08_guides/tutorial-first-study.md) Step 12 with a screenshot + description of the morning card after the chain terminates. No runbook delta (no new operator-actionable signal beyond what Phase 1 already surfaces).

### Out of scope

- **Index-page surface ("ran while away" card on `/studies`)** — delegated to sibling [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md) per D-4. That sibling has already locked its design forks: cookie-only visited-state + a new `GET /api/v1/studies/chains/recent?since=` discovery endpoint. The two specs ship as separate PRs; coordination is via the shared `CHAIN_STOP_REASON_PHRASE` module and (when both ship) the sibling's discovery endpoint, not by folding scope.
- A chain-level narrative LLM call (per D-2 — reuse the winner's existing narrative).
- A new field on `StudyChainLink` or `StudyChainResponse` (per D-3 — fetch the verdict via `useStudy(best_link_id)`, no payload change).
- Persistent dismiss state for the card (per D-8 — show every time the predicate fires; localStorage dismissal is a follow-up if operators ask).
- A proposal `superseded` status (Phase 3 territory — tracked at [`feat_overnight_final_solution_phase3/idea.md`](../feat_overnight_final_solution_phase3/idea.md)).
- Any change to `<AutoFollowupChainPanel>`'s rendering, polling, or layout. The panel continues to live mid-page; the card is additive above.
- Any change to the wizard, the worker, the chain endpoint, or the database schema.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` — confirmed against existing `studies.py` routers.
- **Router for this feature's endpoint changes:** None. Phase 2 is pure frontend on existing endpoints (`GET /api/v1/studies/{id}/chain`, `GET /api/v1/studies/{id}`, `GET /api/v1/studies/{id}/digest`, `GET /api/v1/query-templates/{id}`).
- **HTTP methods:** None new.
- **Non-auth error envelope shape:** N/A — no new endpoints emit errors.
- **Auth error shape:** N/A. MVP1–MVP3 ship no auth surface.

### Phase boundaries

Phase 2 is **single-PR**. There is no Phase 2A / Phase 2B split. Cap 1 (morning card), Cap 3 (strategy line), and Cap 4 (narrative reuse) all ship together — they share the same surface (`/studies/{id}`), the same set of existing endpoints, and the same review/test workload. Cap 2 (index-page surface) was the only original Phase 2 capability that warranted a separate spec, and per D-4 it is delegated to the sibling `feat_overnight_studies_summary_card` rather than re-scoped here.

No deferred phases beyond this spec require tracking artifacts.

---

## 4) Product principles and constraints

- **Glance, not panel.** The Overnight result card answers *"what's the answer, what was explored, which PR ships it?"* in a single horizontal scan. If a datum requires more than 3 seconds to read, it belongs in the chain panel (which still mounts below), not the card.
- **No new endpoints.** Every datum the card needs is reachable via existing endpoints already fetched by the study detail page (`/chain`, `/studies/{id}`, `/studies/{id}/digest`, `/query-templates/{id}`). TanStack Query cache deduplicates repeat fetches across components; the new card adds at most one new `useStudy(best_link_id)` and one new `useStudyDigest(best_link_id)` per page render (and zero when `best_link_id === study.id`, i.e., the operator landed on the winning link itself).
- **No new LLM call.** The winning link's digest narrative is already persisted; the card excerpts it. A chain-level summary LLM call would re-introduce capability-check + budget-gate + retry surface for marginal text-quality improvement.
- **No payload changes.** Phase 1 already added `selected_followup_kind` + `template_id` to `StudyChainLink`. Phase 2 consumes those + the existing `StudyDetail.convergence` and `DigestResponse.narrative` fields. Zero schema migration, zero backend code change beyond the doc updates.
- **Graceful degrade on every missing datum.** Each subsection of the card (headline, path, convergence chip, narrative excerpt) is independently hidable. A null `convergence`, a missing digest, an in-flight winning link, and a deleted swap-template target each remove ONLY their own subsection — the card never blanks.
- **Hide-on-empty for legacy chains.** A chain where every `link.selected_followup_kind` is null (legacy `narrow` strategy per Phase 1 D-12) gets a path-less card — the headline + best config + stop reason still render, but the "Explored: …" line is omitted entirely. Showing "Explored: → → →" would actively mislead the operator about what the chain did.
- **Source-of-truth discipline.** The `CHAIN_STOP_REASON_PHRASE` map lives in ONE module (FR-8); both the chain panel and the new card import it. The strategy values + path-summary kinds are sourced from `ui/src/lib/enums.ts` (form-select-discipline rule). No inline literals in the new component.

### Anti-patterns

- **Do not** fetch `/api/v1/studies/{id}/chain` a second time. The chain panel already polls it via `useStudyChain(study.id)`; TanStack Query's cache shares the result via the same `['studies', studyId, 'chain']` key. The card simply calls the same hook — no second query keying, no race.
- **Do not** call `useStudy(chain.best_link_id)` when `best_link_id === study.id`. The hook's own `enabled` gate skips it (we're already viewing the winner); the convergence chip reads directly from `study.convergence` in that branch.
- **Do not** generate a chain-level narrative via a new LLM call (per D-2). Operators who want a synthesized cross-link summary can still read the chain panel's per-link table; the card's narrative excerpt is a cue, not the answer.
- **Do not** add `convergence_verdict` to `StudyChainLink` as a soft-contract additive (per D-3). The per-link fetch pattern is the established precedent (Phase 1 D-11 for swap-template name; the chain panel already does this); duplicating the verdict into the chain payload would couple the payload's freshness to the per-link studies' convergence cache invalidation.
- **Do not** re-implement `CHAIN_STOP_REASON_PHRASE` inside the new component (FR-8). The map is identical across both surfaces; drift between them would silently mislabel one or the other.
- **Do not** hardcode strategy or kind string literals in the new component. Use `OVERNIGHT_STRATEGY_VALUES` for the strategy-line check and `SELECTED_FOLLOWUP_KIND_VALUES` for the path-summary token mapping. (Form-select-discipline rule per CLAUDE.md — the vitest lint guard catches violations.)
- **Do not** persist a dismiss state in localStorage (per D-8). The card is a derived view of chain state; if it should stop rendering for a given chain, the operator's signal is to ship the winning proposal, which terminates the chain's relevance. Adding a "dismiss" affordance now would create a UX commitment to a state-store that doesn't compose with multi-tab / multi-device usage.
- **Do not** truncate the narrative excerpt mid-word. The 240-char limit is **at or before** the nearest sentence boundary, with a hard fallback at the boundary + `…` if the first sentence exceeds 240 chars.
- **Do not** delete or alter `<AutoFollowupChainPanel>`. The panel remains the detail surface; the card is the glance surface. Both ship together.

## 5) Assumptions and dependencies

| Dependency | Why required | Status | Risk if missing |
|---|---|---|---|
| `feat_overnight_final_solution` (Phase 1) | `StudyChainLink.selected_followup_kind` + `StudyChainLink.template_id` + `StudyConfigSpec.auto_followup_strategy` + `OVERNIGHT_STRATEGY_VALUES` + `SELECTED_FOLLOWUP_KIND_VALUES`. | Implemented (PR #440, merged 2026-06-04) | N/A — shipped. The dependency is satisfied. |
| `feat_overnight_autopilot` | `/chain` endpoint, `useStudyChain` hook, `<AutoFollowupChainPanel>`, `CHAIN_STOP_REASON_PHRASE` map. | Implemented (PR #343, 2026-05-31) | N/A — shipped. |
| `feat_study_convergence_indicator` | `StudyDetail.convergence.verdict` field consumed by Cap 4's chip. | Implemented (PR #352, 2026-06-01) | Low — without it, the convergence chip is silently hidden (graceful-degrade per FR-4). The rest of the card still functions. |
| `feat_studies_convergence_visibility` | Not a dependency — its `convergence_verdict` field is on `StudySummary` (list shape), not `StudyDetail`. The card consumes the verdict from `StudyDetail.convergence.verdict` (a different but parallel field). Listed here only to disambiguate. | Implemented (PR #421/#422 + restored via #438, 2026-06-03) | N/A — not consumed. |
| `feat_digest_executable_followups` (the digest's `narrative` + `suggested_followups`) | The card's narrative excerpt reads `digest.narrative` from `GET /api/v1/studies/{best_link_id}/digest`. | Implemented (PR #225, 2026-05-24) | N/A — shipped. |
| Sibling: `feat_overnight_studies_summary_card` (index-page surface) | Coordinated, not blocking. Phase 2 ships without it; the sibling ships on its own schedule. Shared artifact = the `CHAIN_STOP_REASON_PHRASE` module (FR-8). | Idea-stage (planned MVP2) | N/A — coordination is the shared module; Phase 2's correctness does not depend on the sibling shipping first. |

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (operator) returning to a study detail page the morning after running an overnight chain. Wants to read the answer at a glance and ship the winning proposal.
- **Secondary actor:** Relevance Engineer mid-chain (Cap 3 / FR-2) — needs to see the strategy this study is running under without scrolling to the chain panel.
- **Role model:** N/A — RelyLoop MVP2 is single-tenant, no auth.
- **Permission boundaries:** N/A — no auth.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP3 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md). Phase 2 is a read-only frontend feature: it introduces no state mutation, no new endpoint, no new write path. The card and strategy line are derived views of existing data. No audit-event obligation.

## 7) Functional requirements

### FR-1: `<OvernightResultCard>` component

- **Requirement:**
  - The system **MUST** add a new component `ui/src/components/studies/overnight-result-card.tsx` mounted on `/studies/{id}` immediately above `<LinkedEntitiesRow>` at [`page.tsx:96`](../../../../ui/src/app/studies/[id]/page.tsx#L96).
  - The component's **hook order MUST be invariant across every render** (cycle-2 finding C2-A2 accept): call `useStudyChain(study.id)` FIRST, then `useStudyDigest(chain?.best_link_id ?? undefined, { enabled: chain?.best_link_id !== null && shouldShowOvernightResultCard(chain) })` SECOND, then derive the mount predicate. No hook may be called after the early return. (Both hooks already coexist on the page — `useStudyChain` via `<AutoFollowupChainPanel>` below, `useStudyDigest` via `page.tsx:69` — so TanStack Query deduplicates network traffic.) The child components `<PathToken>` (FR-3) and `<WinningLinkConvergenceChip>` (FR-4) are mounted in the render body AFTER the predicate check, so their own hooks are governed by their own stable mount lifecycle.
  - The component **MUST** return `null` when `shouldShowOvernightResultCard(chain)` is false (per FR-7) — placed AFTER both top-level hook calls.
  - When visible, the component **MUST** render the following sections in order:
    1. **Headline** — *"Overnight exploration complete — {N} {studies|study}, {signedLift} lift"* where `N = chain.links.length` and `signedLift` is `chain.cumulative_lift` formatted via the existing `formatSignedLift` helper at [`auto-followup-chain-panel.tsx:49-52`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L49-L52) — i.e. `+0.1234` / `-0.0567` / `—` (4-decimal precision, signed, NO percent sign). The helper is extracted into `ui/src/lib/format-lift.ts` for shared consumption (FR-8); the card and the existing chain-panel cumulative-lift line use IDENTICAL formatting so the two surfaces on the same page never display the same lift in two different formats (cycle-1 finding C1-B11 accept). When `chain.cumulative_lift` is null, the helper returns `—` and the headline renders *"Overnight exploration complete — {N} studies"* (lift fragment is omitted entirely — do NOT render a trailing `, — lift`).
    2. **Convergence chip** (per FR-4) — small inline chip next to the headline. Hidden when null.
    3. **Explored path** (per FR-3) — *"Explored: {token₁} → {token₂} → {token₃}"* — hidden when every `link.selected_followup_kind` is null (per D-7).
    4. **Best config CTA** — three-case render matrix (cycle-1 finding C1-B8 accept):
       - `chain.best_link_id === null` OR no link in `chain.links` matches → render *"Best config: —"* (no name, no link).
       - `best_link_id` matches a link AND `chain.proposal_id_for_best_link === null` → render *"Best config: {bestLink.name} (Awaiting proposal)"* (name only, no link).
       - `best_link_id` matches a link AND `proposal_id_for_best_link` is set → render *"Best config: {bestLink.name}"* as a link to `/proposals/{chain.proposal_id_for_best_link}`.
    5. **Stop reason** — *"Stop reason: {CHAIN_STOP_REASON_PHRASE[chain.stop_reason]}"* using the shared map (per FR-8).
    6. **Narrative excerpt** (per FR-5) — short paragraph with "View full digest →" link to `/studies/{best_link_id}#digest`. Hidden when null. **FR-5 also adds `id="digest"` to the existing `<DigestPanel>`** so the in-page anchor exists (today the panel carries only `data-testid="digest-narrative"`).
  - The component **MUST** mount inside a `<Card>` from `@/components/ui/card` (matching the existing chain panel's container) with `data-testid="overnight-result-card"`.
  - The component **MUST** include an `<InfoTooltip glossaryKey="overnight_result" />` next to the headline (per FR-6).
- **Notes:** The card is a pure render function over the existing chain data + at most two extra `useStudy(best_link_id)` / `useStudyDigest(best_link_id)` fetches. Mount predicate (FR-7) keeps the card invisible for in-flight or single-link cases — the page layout is byte-identical to today in those cases.

### FR-2: `<StrategyLine>` inside `<LinkedEntitiesRow>`

- **Requirement:**
  - The system **MUST** add a `<StrategyLine>` line item rendered INSIDE [`linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) after the four existing FK chips.
  - The line **MUST** render only when `study.config?.auto_followup_strategy` is one of the values in `OVERNIGHT_STRATEGY_VALUES`. For `null`, missing, or unknown values (defensive — the field is `str | None` per Phase 1 D-13, so a malformed JSONB value could in principle reach the frontend), the line is hidden.
  - The display mapping **MUST** be:
    - `"narrow"` → *"Strategy: Refine same knobs"*
    - `"follow_suggestions"` → *"Strategy: Try suggested follow-ups"*
  - The line **MUST** include an `<InfoTooltip glossaryKey="auto_followup_strategy_line" />` (per FR-6).
  - The line **MUST** ground its wire-value check via `OVERNIGHT_STRATEGY_VALUES as readonly string[]).includes(study.config.auto_followup_strategy)` — no inline string literals. The mapping object is typed `Record<typeof OVERNIGHT_STRATEGY_VALUES[number], string>` to force exhaustiveness; adding a new strategy value at Phase 1's allowlist would break the build until the mapping is extended.
  - The line **MUST** carry `data-testid="study-strategy-line"`.
- **Notes:** Read-only — no interaction, no editing affordance. The strategy is set at study creation and inherited verbatim by chain descendants (Phase 1 D-2); the line just surfaces the current value.

### FR-3: Explored-path token mapping

- **Requirement:**
  - The system **MUST** map each chain link's `selected_followup_kind` to a short token via a pure helper `pathTokenForLink(link: StudyChainLink, templateName: string | null): string | null`:
    - `null` (anchor or legacy-narrow chain link) → return `null` (caller omits from the chain).
    - `"narrow_default"` → return `"refined"`.
    - `"narrow"` → return `"narrow"`.
    - `"widen"` → return `"widen"`.
    - `"swap_template"` → return `"swap to {short_template_name}"` where `short_template_name` is the passed `templateName` truncated to 24 chars (+ `…` if longer), falling back to the first 6 chars of `link.template_id` when `templateName` is null.
  - The path is rendered as `tokens.join(' → ')`. Empty token list → omit the entire path line.
  - **Rules-of-Hooks compliance (cycle-1 finding C1-B5 accept).** The card MUST NOT call `useTemplate(link.template_id)` inside a `.map(...)` over `chain.links` — that would violate React's Rules of Hooks because the chain length varies between renders. Instead, the card MUST render a child component `<PathToken link={link} />` per chain link (mirroring the existing `<ChainLinkStrategyBadge>` precedent at [`auto-followup-chain-panel.tsx:80`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L80)). The child component calls `useTemplate(link.template_id)` exactly once per mount with the `enabled` gate `link.selected_followup_kind === 'swap_template'` so non-swap links don't issue the request, then calls the pure `pathTokenForLink` helper with the resolved name and renders the token. The parent card stitches the tokens together with `→` separators.
  - The TanStack Query cache shares per-link template fetches with the chain panel's existing per-link `useTemplate` calls — zero extra round-trips per chain when the panel below has already populated the cache.
- **Notes:** The pure-data helper `pathTokenForLink` lives in `ui/src/lib/chain-path-tokens.ts` (new module) so it can be unit-tested independently of React. The `<PathToken>` child component lives colocated in `overnight-result-card.tsx`. The helper drops `null` tokens silently — a mixed chain (e.g., legacy narrow link followed by a `follow_suggestions` link, hypothetically possible in future scenarios) gets the non-null tokens only, not blanks.

### FR-4: Convergence chip

- **Requirement:**
  - The **parent card** MUST gate the mount: only render `<WinningLinkConvergenceChip linkId={chain.best_link_id} viewedStudy={study} />` when `chain.best_link_id !== null`. This guarantees the child component's `linkId` prop is type-narrowed to `string` (not `string | null`) at every render.
  - The **child component** `<WinningLinkConvergenceChip>` MUST take `linkId: string` (non-null) and `viewedStudy: StudyDetail`, and MUST follow this hook-safe pattern (cycle-2 finding C2-A1 accept):
    1. **Always** call `useStudy(linkId, { enabled: linkId !== viewedStudy.id })` unconditionally at the top of the component — the `enabled: false` path skips the network request when the operator is viewing the winner directly, but the hook itself is still called in a stable position every render. This is the standard TanStack-Query-with-conditional-fetch idiom.
    2. **Then** in the render body, choose the verdict source: when `linkId === viewedStudy.id`, read `viewedStudy.convergence?.verdict` (the page already loaded it via [`page.tsx:60`](../../../../ui/src/app/studies/[id]/page.tsx#L60)); otherwise read the hook result's `data?.convergence?.verdict`.
    3. The child's render order is stable: hook → derive verdict → render chip-or-null. No conditional hook calls; no `if … return null` before the hook.
  - The chip **MUST** render only when the resolved `verdict` is `"converged"`, `"still_improving"`, or `"too_few_trials"`. Null / undefined → render `null`. This means the chip silently degrades during the (rare) interleave where `linkId !== viewedStudy.id` and the cross-study fetch is still in flight.
  - The chip's text mapping **MUST** be:
    - `"converged"` → *"Converged"*
    - `"still_improving"` → *"Still improving"*
    - `"too_few_trials"` → *"Too few trials"*
  - The chip **MUST** carry `data-testid="overnight-result-convergence-chip"`.
  - The chip **MUST** use the existing `<Badge>` primitive from `@/components/ui/badge` with the `variant="secondary"` per [`convergence-panel.tsx`](../../../../ui/src/components/studies/convergence-panel.tsx) precedent.
- **Notes:** No new endpoint, no new payload field. The verdict lives on `StudyDetail.convergence.verdict` per the shipped convergence indicator (`schemas.py:937-950`). The cross-study fetch (when `best_link_id !== study.id`) is one extra TanStack-cached request — same pattern as Phase 1 D-11 for swap-template name resolution.

### FR-5: Narrative excerpt

- **Requirement:**
  - The system **MUST** call the digest hook with the SAME shape as the FR-1 invariant-hook-order block: `useStudyDigest(chain?.best_link_id ?? undefined, { enabled: chain?.best_link_id !== null && shouldShowOvernightResultCard(chain) })` (cycle-3 finding C3-A1 accept). The widened hook signature accepts `string | undefined` (NOT `string | null`), so the `?? undefined` coercion is required to satisfy TypeScript. The `shouldShowOvernightResultCard(chain)` clause in `enabled` prevents fetching the winning link's digest for in-flight or single-link chains where the card will return null — keeping the no-extra-fetch promise from FR-1. No child component required (FR-4's child-component pattern is needed for `useStudy` ONLY because that hook takes `id: string`).
  - When `chain.best_link_id === study.id`, TanStack Query's cache shares the result with the page-level `useStudyDigest(studyId)` call at [`page.tsx:69`](../../../../ui/src/app/studies/[id]/page.tsx#L69) (same `['studies', id, 'digest']` queryKey) — no second request.
  - The narrative **MUST** be truncated via a pure helper `truncateNarrative(text: string, maxChars: number = 240): string` colocated with the component:
    1. If `text.length <= 240`, return `text` unchanged.
    2. Otherwise, find the last sentence terminator (`.`, `!`, `?`) at or before position 240. If found, return the prefix through that terminator.
    3. **Otherwise** (no sentence terminator in the first 240 chars), find the last whitespace at or before position 240. If found, return `text.slice(0, that_index) + "…"` (cycle-1 finding C1-B7 accept — never cut mid-word).
    4. **Otherwise** (no whitespace in the first 240 chars — pathological single-token input), return `text.slice(0, 240) + "…"` as the final fallback.
  - The card **MUST** render a *"View full digest →"* link to `/studies/{best_link_id}#digest` after the excerpt. **FR-5 MUST add `id="digest"`** to the existing `<DigestPanel>`'s outer wrapper at [`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx) — today the panel carries only `data-testid="digest-narrative"` on an inner div ([digest-panel.tsx:50](../../../../ui/src/components/studies/digest-panel.tsx#L50)), no `id` anchor. The one-line addition is in scope for this spec; the panel's existing tests are unaffected.
  - When `useStudyDigest` returns `data === undefined` (still loading), `isError === true` (per the hook contract — 404 `DIGEST_NOT_READY` from the endpoint when the winning link's study isn't completed yet, OR any other error — both surface as `isError: true`, NOT `data: null`), the narrative section is hidden. The card still renders headline + path + best config + stop reason + convergence chip.
- **Notes:** The 240-char limit is a UX guess — operators may want longer / shorter. Locked at 240 for the first cut; revisit if feedback says it crowds the page or trails off too quickly. The hook never returns `data: null` — its return shape is `DigestResponse | undefined` plus the `isError` flag.

### FR-6: Glossary keys

- **Requirement:**
  - The system **MUST** add `overnight_result` to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts). Suggested `short` (≤ 120 chars): *"The morning summary card on any chain link's detail page. Headline + explored path + winning config + stop reason at a glance."* (cycle-1 finding C1-B6 accept — the card mounts on any chain member's `/studies/{id}` page, not just the anchor's; the mount predicate FR-7 does NOT check `study.id === anchor_study_id`.)
  - The system **MUST** add `auto_followup_strategy_line`. Suggested `short`: *"This study's overnight-followup strategy. Set at study create; inherited by chain descendants. Refine = same knobs; Try suggestions = digest's top runnable item."*
  - Both entries **MUST** include a `long` paragraph following the existing glossary entry shape (the glossary value-lock test catches drift).
  - Both keys **MUST** be added to the glossary key-lock test ([`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) or equivalent — locate at impl-time and follow the Phase 1 `overnight_strategy` pattern).
- **Notes:** The existing `overnight_autopilot` + `overnight_strategy` keys cover adjacent concepts; the two new keys cover the morning surface specifically.

### FR-7: Mount predicate helper

- **Requirement:**
  - The system **MUST** add a pure function `shouldShowOvernightResultCard(chain: StudyChainResponse | undefined): boolean` in `ui/src/components/studies/overnight-result-card.tsx` (colocated, exported for testability).
  - The function **MUST** return `true` IFF `chain !== undefined && chain.stop_reason !== 'in_flight' && chain.links.length >= 2`. Returns `false` otherwise (no chain data, single-link chain, or in-flight).
  - The function **MUST** be unit-testable without rendering React (pure data → boolean).
- **Notes:** The predicate is intentionally narrow: chain MUST be terminated (so the rolled-up lift / best link / stop reason are settled) AND MUST have at least 2 links (so the card has SOMETHING to summarize beyond the anchor). The visibility predicate match the corresponding chain-panel `D-13 render predicate` (the panel shows ANY chain context; the card shows ONLY settled multi-link chains).

### FR-8: Shared `CHAIN_STOP_REASON_PHRASE` module

- **Requirement:**
  - The system **MUST** extract the existing `CHAIN_STOP_REASON_PHRASE` map (currently at [`auto-followup-chain-panel.tsx:34-41`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L34-L41)) into a new module `ui/src/lib/chain-stop-reason.ts` with a named export `CHAIN_STOP_REASON_PHRASE: Record<ChainStopReason, string>`.
  - Both `<AutoFollowupChainPanel>` and the new `<OvernightResultCard>` **MUST** import from this module — no local copy in either component.
  - The module **MUST** retain the existing source-of-truth comment: `// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS`.
  - Existing chain-panel tests **MUST** continue passing unchanged after the extraction.
- **Notes:** Mechanical refactor — the only behavioral change is the file the map lives in. The chain panel's render logic, polling, and stop-reason rendering are untouched.

### FR-9: Tutorial / runbook updates

- **Requirement:**
  - The system **MUST** extend [`docs/08_guides/tutorial-first-study.md`](../../../../docs/08_guides/tutorial-first-study.md) Step 12 ("Run the loop overnight") with a sub-section *"In the morning — read the overnight result card"* describing: card location (top of `/studies/{anchor_id}`), the headline + path + best config + stop reason fields, and how to ship the winning proposal from the card's CTA.
  - The system **MUST** include a screenshot of the card in the populated state (anchor + 2 children, follow_suggestions strategy, `no_lift` stop). Regenerated against a populated stack per the project's screenshot regen convention.
  - No runbook delta required — Phase 2 introduces no new operator-actionable signal beyond what Phase 1 already surfaces; the card is a view, not a behavior.
- **Notes:** Guide regeneration is covered by `/impl-execute`'s Step 2b guide-impact assessment — flag the tutorial guide for screenshot regen in the impl plan.

## 8) API and data contract baseline

### 8.1 Endpoint surface

No new endpoints. Phase 2 is pure-frontend on existing routes:

| Method | Path | Purpose | Existing? |
|---|---|---|---|
| `GET` | `/api/v1/studies/{id}/chain` | Already consumed by `<AutoFollowupChainPanel>`. The card calls the same `useStudyChain(study.id)` hook (shared TanStack cache). | Yes — Phase 1 + `feat_overnight_autopilot`. |
| `GET` | `/api/v1/studies/{id}` | Card calls `useStudy(best_link_id)` for the winning link's `convergence.verdict` (when `best_link_id !== study.id`). | Yes — pre-existing. |
| `GET` | `/api/v1/studies/{id}/digest` | Card calls `useStudyDigest(best_link_id)` for the winning link's narrative excerpt. | Yes — pre-existing. |
| `GET` | `/api/v1/query-templates/{id}` | Card calls `useTemplate(link.template_id)` per swap_template-kind link for the path-summary token. | Yes — Phase 1 + `feat_overnight_autopilot`. |

### 8.2 Contract rules

- The card is a derived view; it introduces no new wire contracts. All accuracy guarantees flow from the existing endpoints' contract tests.
- TanStack Query cache deduplicates fetches across components. The card MUST NOT issue a duplicate fetch for any (resource, id) pair the page is already loading.
- Graceful degrade: every subsection of the card is independently hideable (null verdict → no chip; null digest → no narrative; empty path tokens → no path line). The card never blanks; it just shrinks.

### 8.3 Response examples

N/A — no new endpoints emit responses. Phase 1's [`feat_overnight_final_solution` §8.4](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md) covers the `/chain` response shape this card consumes.

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `study.config.auto_followup_strategy` (read-only) | `narrow`, `follow_suggestions` (or absent / `null`) | `AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")` at [`backend/app/api/v1/schemas.py:724-738`](../../../../backend/app/api/v1/schemas.py#L724-L738). Mirrored as `OVERNIGHT_STRATEGY_VALUES` in [`ui/src/lib/enums.ts:84`](../../../../ui/src/lib/enums.ts#L84). | FR-2 `<StrategyLine>` check + display mapping inside `<LinkedEntitiesRow>`. |
| `StudyChainLink.selected_followup_kind` (read-only) | `narrow_default`, `narrow`, `widen`, `swap_template` (or `null`) | `SELECTED_FOLLOWUP_KIND_VALUES: tuple[str, ...]` in [`backend/app/domain/study/auto_followup_strategy.py`](../../../../backend/app/domain/study/auto_followup_strategy.py). Mirrored at [`ui/src/lib/enums.ts:94`](../../../../ui/src/lib/enums.ts#L94). | FR-3 `pathTokenForLink` mapping in `<OvernightResultCard>`. |
| `StudyChainResponse.stop_reason` (read-only) | `in_flight`, `no_lift`, `depth_exhausted`, `budget`, `parent_failed`, `cancelled` | `CHAIN_STOP_REASONS` in [`backend/app/domain/study/chain_summary.py`](../../../../backend/app/domain/study/chain_summary.py). Frontend phrase map at new `ui/src/lib/chain-stop-reason.ts` (FR-8). | FR-7 mount predicate + FR-1 stop-reason rendering (both surfaces). |
| `StudyDetail.convergence.verdict` (read-only) | `converged`, `still_improving`, `too_few_trials` (or `null` when shape is null) | `ConvergenceVerdict` Literal at [`backend/app/domain/study/convergence.py`](../../../../backend/app/domain/study/convergence.py). Mirrored in `ui/src/lib/enums.ts`. | FR-4 convergence chip text mapping. |

All four enumerations already exist and are validated against backend source-of-truth files by the `verify_enum_source_of_truth.sh` CI gate. Phase 2 introduces no new allowlist.

### 8.5 Error code catalog

N/A — Phase 2 introduces no new endpoints and no new validation paths. Existing endpoints' error codes are unaffected.

## 9) Data model and state transitions

No new tables, no new columns, no migration. Phase 2 is pure-frontend.

### Required invariants

- The card's mount predicate (FR-7) is the SINGLE source-of-truth for when the card renders. Any code path that needs to ask *"is the card showing?"* MUST call `shouldShowOvernightResultCard(chain)` — no inline duplication of `chain.stop_reason !== 'in_flight' && chain.links.length >= 2`.
- The strategy line's wire-value check (FR-2) MUST go through `OVERNIGHT_STRATEGY_VALUES` — no inline literal. The vitest lint guard ([`form-select-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/form-select-discipline.test.tsx)) is the regression gate.

### State transitions

None — the card and strategy line are derived views of existing data.

### Idempotency/replay behavior

N/A — read-only feature.

## 10) Security, privacy, and compliance

- **Threats:**
  - **Stale chain data in the cache** — TanStack Query's polling cadence is unchanged from Phase 1; the card respects the same stop-polling rules. Risk: low.
  - **Narrative excerpt leak** — `digests.narrative` may contain query / metric data the operator considers sensitive. The card surfaces a 240-char prefix of the narrative; the same data is already visible in the `<DigestPanel>` mid-page. No new exposure.
  - **Cross-study fetch leak** — `useStudy(best_link_id)` could in principle fetch a study the operator is not "supposed to" see. RelyLoop MVP2 is single-tenant; the cross-study fetch is no different from clicking the link to navigate. No new exposure.
- **Controls:** N/A — single-tenant MVP2, no auth surface.
- **Secrets/key handling:** N/A — no new secrets.
- **Auditability:** N/A — Phase 2 introduces no state mutation; nothing to audit.
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The Overnight result card mounts at the top of `/studies/{id}`, between `<StudyHeader>` and `<LinkedEntitiesRow>`. It is the FIRST surface the operator sees after the page title when they navigate to a study that is part of a settled multi-link chain. The chain panel (`<AutoFollowupChainPanel>`) remains mid-page below `<LinkedEntitiesRow>` and the proposal link — operators who want the per-link detail still get it; the card is the glance summary above. The Strategy line (FR-2) lives INSIDE `<LinkedEntitiesRow>` as a fifth row after the four existing FK chips.
- **Labeling taxonomy:**
  - Card title: *"Overnight result"* (not "Overnight summary" — "result" telegraphs that it's the answer).
  - Card title `<InfoTooltip>`: glossary key `overnight_result`.
  - Headline: *"Overnight exploration complete — N studies, ±0.NNNN lift"* (4-decimal signed via `formatSignedLift` per FR-1 / D-12; lift fragment omitted entirely when `cumulative_lift` is null — matches the existing chain-panel cumulative-lift label byte-for-byte).
  - Convergence chip text: *"Converged"* / *"Still improving"* / *"Too few trials"* (matches `feat_study_convergence_indicator` label vocabulary).
  - Path line: *"Explored: {tokens joined by → }"*.
  - Best config line: *"Best config: {name}"* with link (or *(Awaiting proposal)* when null).
  - Stop reason line: *"Stop reason: {phrase}"* using the shared `CHAIN_STOP_REASON_PHRASE`.
  - Narrative section opener: *"Summary"* (one word; the narrative excerpt follows).
  - "View full digest →" link text.
  - Strategy line: *"Strategy: Refine same knobs"* / *"Strategy: Try suggested follow-ups"* — matches the wizard's display labels for the corresponding wire values (Phase 1 FR-2).
- **Content hierarchy:** Card is primary (always visible when predicate fires); within the card: headline + chip first (the answer), then path (the exploration), then best config (the action), then stop reason (the why), then narrative (the explanation). Operators who only need the answer can stop reading after the first line.
- **Progressive disclosure:** The narrative is truncated to ~240 chars with a *"View full digest →"* affordance. Operators who want the full reasoning navigate to the winning link's digest panel. The path line shows tokens, not full template names (except the first 24 chars of swap targets); operators who want the full names use the chain panel below.
- **Relationship to existing pages:** Strictly additive. The chain panel continues to mount mid-page; the card is the new top-of-page glance. The proposal link below `<LinkedEntitiesRow>` (existing) is preserved — the card's "Best config" CTA links to the **winning chain link's proposal** (`chain.proposal_id_for_best_link`), which may or may not be the current study's own proposal.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Card title `<InfoTooltip>` | Glossary key `overnight_result` (FR-6) — *"The morning summary card on any chain link's detail page. Headline + explored path + winning config + stop reason at a glance."* (text matches FR-6's locked copy per D-14 — applies on any chain member, not just the anchor) | hover/focus on `<InfoTooltip>` icon | inline next to title |
| Strategy line `<InfoTooltip>` | Glossary key `auto_followup_strategy_line` (FR-6) — *"This study's overnight-followup strategy. Set at study create; inherited by chain descendants. Refine = same knobs; Try suggestions = digest's top runnable item."* | hover/focus | inline next to line text |
| Stop reason phrase | Reuses existing chain-panel pattern — when stop is `depth_exhausted`, glossary key `auto_followup_depth`; when stop is `budget`, glossary key `auto_followup_budget_skip` (matches [`auto-followup-chain-panel.tsx:297-307`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L297-L307)). | hover/focus on `<InfoTooltip>` icon | inline next to phrase |

No new glossary keys beyond FR-6's two. Existing tooltips (`auto_followup_chain`, `auto_followup_depth`, `lift_gate`, `overnight_strategy`, `overnight_autopilot`) are reused as-is.

### Primary flows

1. **Morning-review-and-ship flow.** Operator returns to `/studies/{anchor_id}` after an overnight `follow_suggestions` chain. Card renders at top of page: headline says *"Overnight exploration complete — 4 studies, +0.1245 lift"* (`formatSignedLift` output per FR-1 / D-12); convergence chip says *"Converged"*; path says *"Explored: widen → swap to function-score-v1 → narrow"*; best config link → `/proposals/{winning_proposal_id}`; stop reason says *"no further improvement"*; narrative excerpt summarizes the winning config. Operator clicks best config link, reviews the proposal, opens the PR.
2. **Mid-chain "what strategy is this?" flow.** Operator opens any chain link (anchor or descendant) — `<LinkedEntitiesRow>` shows the four FK chips PLUS the strategy line *"Strategy: Try suggested follow-ups"*. Operator gets the cue without scrolling to the chain panel.

### Edge/error flows

- **In-flight chain.** `chain.stop_reason === 'in_flight'` → card returns `null`. The chain panel below still renders with its polling cadence. Page layout is byte-identical to today.
- **Single-link chain.** `chain.links.length < 2` (e.g., depth=0 or the autopilot never enqueued a child) → card returns `null`. The strategy line in `<LinkedEntitiesRow>` still renders if `config.auto_followup_strategy` is set.
- **Legacy `narrow` chain.** Every `link.selected_followup_kind` is null → card renders WITHOUT the path line (per D-7). Headline + best config + stop reason + narrative still show.
- **Best link's digest still generating.** `useStudyDigest(best_link_id)` returns null → narrative section is hidden. The rest of the card still renders.
- **Best link's convergence is null.** `useStudy(best_link_id)` returns a study with `convergence === null` → convergence chip is hidden.
- **Best link's template was deleted (`swap_template` path).** `useTemplate(link.template_id)` returns null for that link → the path token falls back to `"swap to {first 6 chars of template_id}"` (matches Phase 1's existing chain-panel fallback at [`auto-followup-chain-panel.tsx:106`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L106)).
- **`chain.best_link_id` is null but chain has links.** Rare edge case where the chain endpoint returns no best link (e.g., all links failed or have null `best_metric`). Card renders headline + path + stop reason; best-config line shows *"Best config: —"*; narrative + convergence sections are hidden.
- **`chain.proposal_id_for_best_link` is null but `best_link_id` is set.** Winning link's proposal hasn't been created yet (race condition between digest worker and proposal worker). Card renders *"Best config: {bestLink.name} (Awaiting proposal)"* without the link, matching the existing chain-panel pattern at [`auto-followup-chain-panel.tsx:289-292`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L289-L292).
- **Strategy value unknown.** `study.config.auto_followup_strategy` is set to a value not in `OVERNIGHT_STRATEGY_VALUES` (defensive — the backend validator rejects this at create, but a manual DB INSERT could in principle introduce it). Strategy line is hidden silently. No log emission — the frontend is the wrong layer to surface schema corruption.

## 12) Given/When/Then acceptance criteria

### AC-1: Card renders on a terminated multi-link chain

- Given a study `A` is the anchor of a 3-link `follow_suggestions` chain (`A → B → C`), all three completed, with `chain.cumulative_lift = 0.1245`, `chain.stop_reason = "no_lift"`, `chain.best_link_id = C.id`, `chain.proposal_id_for_best_link = proposal_C.id`, and `GET /api/v1/studies/{C.id}` returns `convergence: { verdict: "converged", ... }` (the verdict lives on `StudyDetail.convergence.verdict` per [`schemas.py:937`](../../../../backend/app/api/v1/schemas.py#L937), NOT on `study.config` — cycle-1 finding C1-A3 fix).
- When the operator navigates to `/studies/{A.id}`.
- Then the page renders `<OvernightResultCard>` ABOVE `<LinkedEntitiesRow>` with:
  - headline *"Overnight exploration complete — 3 studies, +0.1245 lift"* (using `formatSignedLift(0.1245)` per FR-1 — 4-decimal signed, no percent),
  - convergence chip *"Converged"*,
  - path line *"Explored: {tokens for B then C, e.g. widen → swap to function-score-v1}"*,
  - best-config link to `/proposals/{proposal_C.id}` with text *"Best config: {C.name}"* (FR-1 three-case fallback, third case),
  - stop-reason line *"Stop reason: no further improvement"*,
  - narrative excerpt section showing the first ~240 chars of `C.digest.narrative` + *"View full digest →"* link to `/studies/{C.id}#digest`.

### AC-2: Card hidden on an in-flight chain

- Given a study `A` is the anchor of a chain with `chain.stop_reason === "in_flight"`.
- When the operator navigates to `/studies/{A.id}`.
- Then the page does NOT render `<OvernightResultCard>` (it returns `null`). The chain panel below renders normally with its polling cadence.

### AC-3: Card hidden on a single-link chain

- Given a study `A` has `auto_followup_depth = 0` and no children — `chain.links.length === 1`.
- When the operator navigates to `/studies/{A.id}`.
- Then the page does NOT render `<OvernightResultCard>`. The chain panel below renders nothing or just the anchor depending on the existing `showSummary` predicate.

### AC-4: Path line hidden for legacy `narrow` chain

- Given a study `A` is the anchor of a 3-link chain where every link's `selected_followup_kind` is null (legacy `narrow` strategy per Phase 1 D-12), `chain.stop_reason === "depth_exhausted"`, `chain.cumulative_lift = 0.05`.
- When the operator navigates to `/studies/{A.id}`.
- Then the card renders with headline *"Overnight exploration complete — 3 studies, +0.0500 lift"* (`formatSignedLift(0.05)` per FR-1 / D-12 — 4-decimal signed, no percent), best-config link, stop-reason line, and (when present) narrative excerpt — BUT the path line is omitted entirely. No *"Explored:"* text appears.

### AC-5: Narrative section hides gracefully on missing digest

- Given a terminated 2-link chain where the winning link's digest is still being generated (`useStudyDigest(best_link_id)` returns `data === undefined` or null narrative).
- When the operator navigates to the anchor.
- Then the card renders all sections EXCEPT the narrative excerpt. The "View full digest →" link is not shown. The other sections (headline / path / best config / stop reason / convergence chip) render normally.

### AC-6: Convergence chip hides gracefully on null verdict

- Given a terminated 2-link chain where `chain.best_link_id`'s `convergence === null` (e.g., the winning link has < 5 complete trials).
- When the operator navigates to the anchor.
- Then the convergence chip is not rendered. The headline renders without the chip. Other sections render normally.

### AC-7: Strategy line renders on a `follow_suggestions` study

- Given a study `A` was created with `config.auto_followup_strategy = "follow_suggestions"`.
- When the operator navigates to `/studies/{A.id}`.
- Then `<LinkedEntitiesRow>` renders the four FK chips PLUS a fifth line *"Strategy: Try suggested follow-ups"* with the `auto_followup_strategy_line` `<InfoTooltip>` icon. `data-testid="study-strategy-line"` is present.

### AC-8: Strategy line hidden on a legacy / default-narrow study

- Given a study `A` has no `auto_followup_strategy` in its `config` JSONB (legacy or explicit `"narrow"` was never set).
- When the operator navigates to `/studies/{A.id}`.
- Then `<LinkedEntitiesRow>` renders only the four FK chips. No strategy line appears. (The line ALSO appears for `"narrow"` per FR-2's display mapping — but legacy chains have the key absent, not set to `"narrow"`.)

### AC-9: Strategy line renders for `"narrow"` (explicit) AND `"follow_suggestions"`

- Given two studies — `A` with `config.auto_followup_strategy = "narrow"` (explicit), `B` with `config.auto_followup_strategy = "follow_suggestions"`.
- When the operator navigates to each in turn.
- Then `A`'s `<LinkedEntitiesRow>` renders *"Strategy: Refine same knobs"*; `B`'s renders *"Strategy: Try suggested follow-ups"*. Both lines carry the `<InfoTooltip>` icon.

### AC-10: Card on the WINNING link's own page does not double-fetch

- Given a chain `A → B → C` where `chain.best_link_id === C.id`, and the operator is viewing `/studies/{C.id}`.
- When the page renders.
- Then the card calls `useStudyChain(C.id)` (existing) but does NOT call `useStudy(C.id)` a second time — the page's existing `useStudy(C.id)` at `page.tsx:60` provides `study.convergence` directly. (Verifiable via React DevTools / vitest assertion that the network mock for `GET /api/v1/studies/{C.id}` is hit exactly once.)

### AC-11: TanStack cache deduplicates `useStudyDigest`

- Given the operator is viewing `/studies/{C.id}` AND `C.id === chain.best_link_id`.
- When the card renders.
- Then `useStudyDigest(C.id)` is called by both the page (existing, line 69) and the card — but TanStack Query's cache merges them into ONE fetch (same `['studies', C.id, 'digest']` key). (Verifiable via network mock hit count.)

### AC-12: E2E — operator opens winning proposal from the card

- Given a CI-seeded multi-link chain produced by the existing demo seed path (e.g. `make seed-demo` or `POST /api/v1/demo/seed-meaningful`) with terminal `stop_reason` and a winning link carrying a `pending` proposal. **Seeding mechanism caveat (cycle-1 finding C1-B10 accept):** if the standard demo seed does NOT reliably produce a terminated multi-link chain in CI (likely — the demo currently seeds baseline scenarios, not autopilot chains), the E2E coverage downgrades to a NARROWER real-backend assertion: navigate to ANY seeded study, assert the card is hidden (predicate negative case). The full click-through-to-proposal assertion is covered by `overnight-result-card.test.tsx` vitest (real component + mocked hook results) — see §14. The plan-stage author MUST verify which path applies at impl-time and either land the broader E2E OR document the downgrade in the implementation plan.
- When (in the seeded-chain case) the operator navigates to `/studies/{anchor.id}` and clicks the *"Best config: {winner.name}"* link.
- Then the browser navigates to `/proposals/{winner.proposal_id}` and the proposal detail page renders. (Playwright real-backend assertion; uses `page` interactions, not `page.route()` mocking — per CLAUDE.md "E2E Testing Rules".)

## 13) Non-functional requirements

- **Performance:**
  - Card render adds at most TWO extra network requests beyond what the study detail page already makes (`useStudy(best_link_id)` + `useStudyDigest(best_link_id)`) — and ZERO when `best_link_id === study.id` (the operator is already viewing the winner; existing page-level hooks serve the data).
  - `useTemplate(link.template_id)` fetches for swap_template-kind links are shared with the chain panel's existing per-link template fetches via TanStack cache — no extra round-trips per page render.
  - Total card-attributable wire load: 0–2 extra requests per page render. p99 added latency should be < 200ms on warm cache (both `/studies/{id}` and `/studies/{id}/digest` are existing fast routes).
- **Reliability:**
  - Each card subsection is independently null-safe (FR-1 / FR-4 / FR-5 graceful-degrade rules). A 500 on `useStudyDigest(best_link_id)` hides ONLY the narrative section; the rest of the card renders.
  - The mount predicate (FR-7) excludes in-flight chains, so polling-induced re-renders never cause the card to flicker in/out — once visible, the chain has settled.
- **Operability:**
  - No new structlog events (Phase 2 is frontend-only; the worker side is untouched).
  - No new metrics / alerts.
- **Accessibility:**
  - Card uses semantic `<section>` / `<header>` for the headline; convergence chip uses ARIA-appropriate badge variant; "View full digest →" link uses standard `<Link>` (next/link).
  - Strategy line is plain text inside the existing `<LinkedEntitiesRow>` semantic structure; the `<InfoTooltip>` follows the same a11y pattern as Phase 1's `auto_followup_chain` tooltip.
  - Keyboard navigation: best-config link + "View full digest" link are focusable; tooltips open on focus per the existing `<InfoTooltip>` contract.

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- **Unit tests (backend `backend/tests/unit/`):** None — Phase 2 is frontend-only.
- **Integration tests (backend `backend/tests/integration/`):** None.
- **Contract tests (backend `backend/tests/contract/`):** None — no API changes.
- **Unit tests (frontend, vitest):**
  - `ui/src/__tests__/lib/chain-stop-reason.test.ts` — assert `CHAIN_STOP_REASON_PHRASE` exports the expected six keys with non-empty values; assert source-of-truth comment present.
  - `ui/src/__tests__/lib/format-lift.test.ts` — assert `formatSignedLift(null)` returns `"—"`, `formatSignedLift(0.1245)` returns `"+0.1245"`, `formatSignedLift(-0.05)` returns `"-0.0500"` (4-decimal precision, signed, NO percent — matches the existing chain-panel helper after FR-8's extraction).
  - `ui/src/__tests__/lib/chain-path-tokens.test.ts` — assert `pathTokenForLink` returns expected tokens for each of the five `selected_followup_kind` cases (`null` / `narrow_default` / `narrow` / `widen` / `swap_template`); assert swap_template truncation at 24 chars; assert null-template-name fallback to first 6 chars of `template_id`.
  - `ui/src/__tests__/components/studies/overnight-result-card.test.tsx` — assert mount-predicate behavior (visible / hidden) for each AC scenario (AC-1 through AC-6, AC-10, AC-11); assert path-line hidden when all kinds are null (AC-4); assert narrative excerpt truncation (boundary + hard cut + no-truncate cases); assert "Awaiting proposal" fallback when `proposal_id_for_best_link` is null.
  - `ui/src/__tests__/components/studies/linked-entities-row.test.tsx` — extend with strategy-line render tests (AC-7, AC-8, AC-9): visible for `"narrow"` and `"follow_suggestions"`; hidden for null / missing / unknown.
  - Glossary key-lock test extension — assert `overnight_result` and `auto_followup_strategy_line` exist with `short` and `long` fields, per existing pattern.
- **E2E tests (`ui/tests/e2e/`):**
  - New spec `ui/tests/e2e/overnight-result-card.spec.ts` — real-backend Playwright spec. **Required coverage** (cycle-2 finding C2-B4 accept): a NEGATIVE mount-predicate assertion against a seeded non-chain or in-flight study (card is hidden, `data-testid="overnight-result-card"` is not present). **Best-effort coverage**: if the impl-plan author confirms at impl-time that the CI demo seed (`make seed-demo` / `POST /api/v1/demo/seed-meaningful`) reliably produces a terminated multi-link chain with a pending proposal, the spec ALSO covers AC-12's click-through to the winning proposal. If the demo seed does NOT produce that state, AC-12's click-through is covered by vitest only (real component + mocked hook results) and the Playwright spec ships with only the negative assertion. Either way, NO `page.route()` mocking — backend is real (per CLAUDE.md E2E rules). Seed via API helpers; navigate via `page.goto`; assert via `page.locator`.

The frontend test count is ~20–30 new test cases distributed across the test files above. Backend coverage is unchanged (no backend code touched).

## 15) Documentation update requirements

- **`docs/01_architecture/ui-architecture.md`:** Add a one-paragraph note under the existing "Study detail page" section describing the morning card's mount point + visibility predicate. Note that `CHAIN_STOP_REASON_PHRASE` is now a shared module (FR-8) to anchor future cross-surface consumers.
- **`docs/08_guides/tutorial-first-study.md`:** Per FR-9, extend Step 12 with the *"In the morning — read the overnight result card"* sub-section + screenshot.
- **`docs/03_runbooks/`:** No update required — Phase 2 introduces no new operator-actionable signal.
- **`docs/05_quality/testing.md`:** No update — existing test-layer conventions cover Phase 2's coverage; no new layer added.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The card is gated entirely by the runtime predicate (`shouldShowOvernightResultCard`); legacy studies / in-flight chains / single-link chains see no change. No flag needed.
- **Migration/backfill expectations:** N/A — no schema change.
- **Operational readiness gates:** None new.
- **Release gate:** All ACs (AC-1 through AC-12) green in CI — AC-1 through AC-11 in vitest; AC-12 in vitest + (best-effort) Playwright per D-17. `make lint && make typecheck` clean; guide regen succeeded with populated stack screenshot.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-3, AC-5, AC-10, AC-11, AC-12 | Story 2 (`<OvernightResultCard>` shell + headline + stop reason + best config) | `overnight-result-card.test.tsx` (vitest), `overnight-result-card.spec.ts` (e2e) | `ui-architecture.md`, `tutorial-first-study.md` |
| FR-2 | AC-7, AC-8, AC-9 | Story 4 (`<StrategyLine>` inside `<LinkedEntitiesRow>`) | `linked-entities-row.test.tsx` (vitest extension) | `ui-architecture.md` |
| FR-3 | AC-1, AC-4 | Story 3 (`pathTokenForLink` helper + path-line render) | `chain-path-tokens.test.ts` (vitest), covered transitively in `overnight-result-card.test.tsx` | — |
| FR-4 | AC-1, AC-6, AC-10 | Story 2 (convergence chip inside the card) | `overnight-result-card.test.tsx` | — |
| FR-5 | AC-1, AC-5, AC-11 | Story 2 (narrative excerpt rendering) + `truncateNarrative` helper | `overnight-result-card.test.tsx` (helper covered by colocated tests) | — |
| FR-6 | (glossary lock test) | Story 5 (glossary keys + lock test extension) | `glossary.test.ts` extension | — |
| FR-7 | AC-2, AC-3 | Story 2 (predicate helper colocated with component) | `overnight-result-card.test.tsx` | — |
| FR-8 | (refactor; existing chain-panel tests must continue passing) | Story 1 (extract `CHAIN_STOP_REASON_PHRASE` + `formatSignedLift`) | `chain-stop-reason.test.ts`, `format-lift.test.ts`, existing `auto-followup-chain-panel.test.tsx` (unchanged assertions) | `ui-architecture.md` |
| FR-9 | (manual review of guide screenshot) | Story 6 (guide update + screenshot regen) | (manual) | `tutorial-first-study.md` |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-12) pass in CI.
- [ ] Vitest unit tests for `chain-stop-reason`, `format-lift`, `chain-path-tokens`, `overnight-result-card`, and `linked-entities-row` extension are green.
- [ ] Glossary key-lock test passes with the two new keys (`overnight_result`, `auto_followup_strategy_line`).
- [ ] Playwright E2E `overnight-result-card.spec.ts` passes against the real backend — at minimum the negative predicate assertion (card hidden when no chain); click-through coverage is best-effort against the demo seed per D-17.
- [ ] `make lint && make typecheck` clean.
- [ ] `docs/01_architecture/ui-architecture.md` updated.
- [ ] `docs/08_guides/tutorial-first-study.md` Step 12 updated with sub-section + regenerated screenshot.
- [ ] `<AutoFollowupChainPanel>`'s tests pass unchanged after the FR-8 extraction (proves the refactor is mechanical-only).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

_None — all forks locked at preflight or below in the decision log._

### Decision log

- **D-1 (2026-06-03)** — Phase 2 mounts the morning card ABOVE `<LinkedEntitiesRow>`, not as a separate tab or modal (idea OQ-1: locked). Rationale: tabs hide information; a modal would force a click before the operator sees the answer. The top-of-page banner card is the lowest-friction surface for the morning-glance scenario. The position above `<LinkedEntitiesRow>` puts it AHEAD of any other panel — the answer should be visible before any context.
- **D-2 (2026-06-03)** — Cap 4 (the narrative section) reuses the WINNING link's existing `digests.narrative`, not a new chain-level LLM call (idea OQ-5: locked recommended default). Rationale: zero new LLM cost, zero new capability-check / budget-gate surface, fastest path to a polished UX. The winning link's narrative already explains why that config won; cross-link synthesis is a marginal text-quality improvement, not a new capability. Revisit if operators say the per-link narrative misses chain-level context.
- **D-3 (2026-06-03)** — Cap 4 fetches the winning link's convergence verdict via `useStudy(best_link_id)` rather than adding `convergence_verdict` to `StudyChainLink` (idea OQ-6: locked recommended default). Rationale: per-link fetch is at most one extra TanStack-cached request, mirrors the Phase 1 D-11 pattern for swap-template name resolution, and keeps `/chain`'s response shape stable. Adding `convergence_verdict` to the chain payload would couple `/chain`'s freshness to per-link `studies` row cache invalidation — a worse abstraction for a one-field benefit. Cycle-2 reviewer note: when `best_link_id === study.id` (operator is on the winner), the page's existing `useStudy(study.id)` provides the verdict directly — no extra fetch.
- **D-4 (2026-06-03)** — Cap 2 (index-page surface) is DELEGATED to sibling `feat_overnight_studies_summary_card`, not folded into Phase 2 (idea OQ-4: locked). Rationale: the sibling has already locked its design forks (cookie-only visited-state + a new `GET /api/v1/studies/chains/recent?since=` discovery endpoint). Folding Cap 2 into Phase 2 would either (a) re-litigate those forks here or (b) ship them in two specs simultaneously and coordinate the merge order. Cleaner to ship Phase 2 on its own (study-detail-only) and let the sibling ship the index-page surface separately — coordination via the shared `CHAIN_STOP_REASON_PHRASE` module (FR-8) and (when both ship) the sibling's discovery endpoint. The two surfaces serve different operator moments: card = answers "what happened?" when the operator already clicked a study; sibling card = answers "where did anything happen?" on the index.
- **D-5 (2026-06-03)** — Cap 1 (morning card) and Cap 3 (strategy line) ship as SEPARATE surfaces, not folded (idea OQ-3: locked recommended default). Rationale: Cap 1 fires only on terminated multi-link chains (the morning-after moment); Cap 3 helps mid-chain operators who are reviewing a still-running chain. Different mount predicates, different visibility windows, different operator moments. The strategy line lives inside `<LinkedEntitiesRow>` (always visible when the strategy is set); the card is conditional. Folding would conflate the predicates.
- **D-6 (2026-06-03)** — The card mounts BETWEEN `<StudyHeader>` and `<LinkedEntitiesRow>`, not above `<StudyHeader>` (locked). Rationale: `<StudyHeader>` carries the study's own name + status + cluster context — that's the FIRST thing the operator needs to confirm ("am I on the right page?"). The card then comes second ("here's the chain answer"). Above-header positioning would push the page identity below the chain answer, confusing operators who navigated from a search.
- **D-7 (2026-06-03)** — The explored-path line is HIDDEN entirely when every `link.selected_followup_kind` is null (legacy `narrow` chains per Phase 1 D-12; locked). Rationale: showing *"Explored: → → →"* with all nulls would actively mislead the operator about what the chain explored. Legacy chains are predictable narrowing loops — they should look like the chain panel does today, just compressed. The card's other sections (headline, best config, stop reason, narrative) carry the rest of the morning-glance value.
- **D-8 (2026-06-03)** — No persistent dismiss state for the card; show every time the predicate fires (locked). Rationale: the card is a derived view of chain state, not a "notification" with a lifecycle. Operators dismiss the morning review by shipping the winning proposal (which closes the chain's actionable relevance). Adding a localStorage / cookie dismiss state would create a UX commitment to multi-tab / multi-device sync questions that don't compose cleanly until the auth/users surface lands (backlog). Revisit only if operators specifically request a "I already shipped this" affordance.
- **D-9 (2026-06-03)** — The card's narrative excerpt is truncated at 240 chars, prefer-sentence-boundary, hard-fallback-at-240 + `…` (locked). Rationale: 240 chars ≈ 2–3 sentences ≈ ~4 lines on the card; long enough to convey the winning config's rationale, short enough not to dominate the surface. Splitting at a sentence boundary avoids mid-word truncation. Revisit if feedback says the excerpt is too short or too long.
- **D-10 (2026-06-03)** — The card REUSES the existing `<AutoFollowupChainPanel>` rather than replacing it (locked). Rationale: the panel is the detail view; the card is the glance view. Removing the panel would force operators who want the per-link table to navigate elsewhere — a regression. Both surfaces shipping together is the right answer; the operator reads top-down through whichever they need.
- **D-11 (2026-06-03, GPT-5.5 cycle-1 findings C1-A1 + C1-B5 accept)** — Per-link `useTemplate` calls + `useStudy(best_link_id)` use the CHILD-COMPONENT pattern, not inline hooks in a `.map(...)` or top-level conditional invocation. Rationale: Rules of Hooks forbid both patterns; the existing `<ChainLinkStrategyBadge>` precedent at [`auto-followup-chain-panel.tsx:80`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L80) is the established solution in this codebase. The card spawns `<PathToken>` per chain link (FR-3) and `<WinningLinkConvergenceChip>` when `chain.best_link_id !== null` (FR-4); both encapsulate the hook call cleanly.
- **D-12 (2026-06-03, GPT-5.5 cycle-1 finding C1-B11 accept)** — The card's headline lift format **reuses the existing `formatSignedLift` helper** (`+0.1234` / `-0.0567` / `—`, 4-decimal precision, signed, NO percent sign), matching the existing chain panel's cumulative-lift line byte-for-byte. Rationale: showing two different formats for the same lift number on the same page (e.g. `+12.45%` in the card and `+0.1245` in the panel below) would confuse operators about which is canonical. Helper consolidation into `ui/src/lib/format-lift.ts` (FR-8) is the source-of-truth move.
- **D-13 (2026-06-03, GPT-5.5 cycle-1 finding C1-B8 accept)** — Best-config CTA has a three-case render matrix in FR-1 (no `best_link_id` → `—`; `best_link_id` set but no proposal → `Awaiting proposal`; both set → link). Rationale: a single "fallback" rule conflated the two missing-data conditions and produced inconsistent prose between FR-1 and the edge-flow list. The matrix names each case explicitly so tests can assert each independently.
- **D-14 (2026-06-03, GPT-5.5 cycle-1 finding C1-B6 accept)** — The card mounts on **any chain member's `/studies/{id}` page**, not just the anchor's. Rationale: `useStudyChain(study.id)` returns the same chain regardless of which member is viewed; surfacing the card only on the anchor would require an extra mount predicate (`study.id === chain.anchor_study_id`) and would punish operators who navigated from a child's link. The glossary copy is reworded accordingly; AC-10 validates the descendant-page render path.
- **D-15 (2026-06-03, GPT-5.5 cycle-1 finding C1-B7 accept)** — `truncateNarrative`'s hard fallback walks back to the nearest whitespace before 240 chars (FR-5 step 3) before slicing, so a 240-char single-word-mid-narrative pathological case is the ONLY mid-word truncation. Rationale: the anti-pattern *"Do not truncate the narrative excerpt mid-word"* requires it, and the cost is one extra `lastIndexOf(' ', 240)` per render.
- **D-16 (2026-06-03, GPT-5.5 cycle-1 finding C1-A2 accept)** — The card's narrative section hides on BOTH `data === undefined` (loading) AND `isError === true` (404 `DIGEST_NOT_READY` or other error). Rationale: `useStudyDigest` never returns `data: null` per its current contract (`retry: false` + `meta.suppressErrorCodes`); the hook surfaces missing digests as `isError`. The card's render predicate must match the actual hook state shape, not the `data: null` model an earlier draft of this spec assumed.
- **D-17 (2026-06-03, GPT-5.5 cycle-1 finding C1-B10 accept)** — AC-12's E2E coverage is BEST-EFFORT against the CI demo seed; if no terminated multi-link chain is produced by `make seed-demo` in CI, the spec downgrades AC-12 to a narrower negative-predicate assertion (card hidden when no chain exists) and shifts full click-through coverage to vitest. Rationale: real-backend seeding of a TERMINATED chain requires worker execution + LLM calls (digest), which the demo seed may not exercise. The plan-stage author verifies at impl-time; downgrade is acknowledged here so reviewers know not to demand the full E2E if the seed doesn't produce the precondition.
- **D-18 (2026-06-03, GPT-5.5 cycle-2 finding C2-A1 accept)** — `<WinningLinkConvergenceChip>` uses the **parent-gates-mount + always-call-hook** pattern (FR-4). The parent gates `chain.best_link_id !== null` BEFORE mounting the child; the child takes `linkId: string` (non-null) and calls `useStudy(linkId, { enabled: linkId !== viewedStudy.id })` unconditionally at the top of every render. Rationale: the earlier draft's "branch then conditionally call useStudy" pattern was a Rules-of-Hooks violation that ESLint's `react-hooks/rules-of-hooks` rule would flag at lint-time AND would break in production if `best_link_id` ever changed between renders. The parent-gate pattern is byte-identical-render across the (rare) `best_link_id` transition because the entire chip is unmounted/remounted.
- **D-19 (2026-06-03, GPT-5.5 cycle-2 finding C2-A2 accept)** — The card's hook ordering is **invariant across every render**: `useStudyChain` first, `useStudyDigest` second, predicate derivation third, early return fourth. Both hooks are called unconditionally at the top of the component; the early return after the predicate doesn't affect hook count because both hooks ran before it. Rationale: an earlier draft would have placed the digest hook AFTER the early-return guard, producing a hook-count mismatch between the "predicate-false → returned null with 1 hook" and "predicate-true → rendered card with 2 hooks" render branches — a classic Rules-of-Hooks bug.
- **D-20 (2026-06-03, GPT-5.5 cycle-2 finding C2-B3 accept)** — All lift-format references in the spec are normalized to `formatSignedLift`'s output (`+0.NNNN` / `-0.NNNN` / `—`, 4-decimal signed, no percent). Cycle-1 D-12 locked the helper choice but the cycle-1 patch missed three downstream prose references (§11 Labeling taxonomy, §11 Primary flow example, AC-4 expected headline); cycle-2 closes those. Rationale: any percent-formatted example in the spec becomes a contract-test target that contradicts the helper's actual output, producing test/spec drift at impl-time.
- **D-21 (2026-06-03, GPT-5.5 cycle-2 finding C2-B5 accept)** — §11 Tooltips text "on a chain anchor" is corrected to match D-14's "on any chain link's detail page" framing. Rationale: cycle-1 D-14 locked the broader scope; cycle-2 catches the orphan reference in the §11 tooltip table that the cycle-1 patch missed.
- **D-22 (2026-06-03, GPT-5.5 cycle-3 finding C3-A1 accept)** — FR-5's `useStudyDigest` call shape is normalized to match FR-1's invariant-hook-order block: `useStudyDigest(chain?.best_link_id ?? undefined, { enabled: chain?.best_link_id !== null && shouldShowOvernightResultCard(chain) })`. Rationale: the hook's typed param is `string | undefined` (not `string | null`), so `?? undefined` is required for TypeScript; the `shouldShowOvernightResultCard` clause in `enabled` ensures the digest fetch only fires when the card will be rendered, honoring FR-1's "no extra fetch when card is hidden" promise. The cycle-3 patch converges spec internal consistency on the digest-hook call shape.
