# Feature Specification — Proposal Full-Parameter-Space View

**Date:** 2026-06-04
**Status:** Draft
**Owners:** Relevance-Engineering PM (product), RelyLoop maintainer (engineering)
**Related docs:**
- [`idea.md`](idea.md) (preflight-refreshed 2026-06-04)
- [`feat_digest_executable_followups_swap_template` (shipped — declared-params-diff pattern)](../../implemented_features/2026_05_29_feat_digest_executable_followups_swap_template/feature_spec.md)
- [`feat_digest_proposal` (shipped — proposal model + `config_diff` shape)](../../implemented_features/2026_05_11_feat_digest_proposal/feature_spec.md)
- [`feat_overnight_final_solution` Phase 1 (PR #440, shipped — autonomous cross-knob tuning)](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)
- [`implementation_plan.md`](implementation_plan.md) (generated next)

---

## 1) Purpose

- **Problem:** The proposal detail page surfaces `<ConfigDiffPanel>` — a table of the parameters the study **tuned** and their from→to values. What it does not surface is which other parameters *exist on the same template* that the study **did not** tune. The operator is left to guess whether the optimizer considered description-boost, fuzziness, function-score decay, etc. and rejected them, or whether those knobs were simply absent from the study's search space. That gap matters because the proposal's own suggested follow-ups (`narrow` / `widen` / `swap_template`) frequently reference parameters that *weren't* in this study's search space — "Try varying `description_boost` next" reads disconnectedly without a visible reference list of "all knobs this template supports."
- **Outcome:** A new `<FullParamSpacePanel>` renders below `<ConfigDiffPanel>` on `/proposals/[id]`. It lists **every parameter the proposal's template declares**, partitioned into three visually distinct groups: (1) **Tuned and changed** — value moved from baseline; (2) **Tuned but unchanged** — was in the study's search space but the optimizer landed back at the baseline value; (3) **Not in search space** — declared on the template but absent from this study's tuning surface. The operator can see in one glance "the optimizer had K options, tuned M, found N worth changing." Now that `feat_overnight_final_solution` chains swap templates and tune different knobs automatically, the proposal page IS the morning artifact operators read; this panel makes that artifact self-explanatory.
- **Non-goal:** This feature does not change any backend data, schema, endpoint shape, or worker. It is a pure UI surface that derives its three-state partition from data **already on the proposal detail page** (proposal, source study, source-study template). It does not introduce param-name links from the panel back into the follow-up cards (the idea's Cap 2; deferred to the open-questions section per Q3 resolution). It does not mount the same view on the study detail page (the idea's Cap 3; explicitly deferred — see §3 Out of scope).

## 2) Current state audit

### Existing implementations

| File:line | What it does | Notes |
|---|---|---|
| [`ui/src/app/proposals/[id]/page.tsx:319`](../../../../ui/src/app/proposals/[id]/page.tsx#L319) | Mounts `<ConfigDiffPanel diff={proposal.config_diff} />` directly under `<ProposalHeader>` | This is where the new panel mounts — immediately below `<ConfigDiffPanel>`, above the metric-delta card. |
| [`ui/src/app/proposals/[id]/page.tsx:176-183`](../../../../ui/src/app/proposals/[id]/page.tsx#L176-L183) | `useStudy(parentStudyId)` + `useTemplate(parentStudy.data?.template_id)` | **Gated on `hasActionableFollowup`** — fires only when the digest has ≥1 narrow/widen/swap_template item. **For manual proposals (`study_id === null`) and study proposals with text-only or empty digests, the existing fetch is disabled**, so the new panel needs the data via a different path. See §4 anti-pattern A1 and FR-3 below. |
| [`ui/src/components/proposals/config-diff-panel.tsx:38-56`](../../../../ui/src/components/proposals/config-diff-panel.tsx#L38-L56) | `extractFromTo(raw)` handles two `config_diff` shapes: canonical `{from, to}` object form (digest-worker output at `backend/workers/digest.py:1158-1174`) and legacy `[before, after]` 2-tuple form (manual proposals + agent tool). The new panel must use the same helper to read tuned values — duplicating the logic risks drift. | Exported nothing today (only `ConfigDiffPanel` and `ConfigDiffPanelProps` are exported); the helper is module-private. **Decision needed (locked here):** promote `extractFromTo` to a named export (or move it to `ui/src/lib/config-diff.ts`) so the new panel reuses it. The implementation plan promotes it via the latter route. |
| [`ui/src/components/proposals/suggested-followups-panel.tsx:346-388`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L346-L388) | `<DeclaredParamsColumn>` renders the parent-vs-swap-target declared-params diff under the `swap_template` card. **Visual pattern to reuse**: shared keys bold + `text-gray-900`, non-shared `text-gray-700`, monospace param name + `": " + type` annotation. | The new panel adopts the same typography (monospace name, `:` type annotation, font-weight modulating membership) so operators don't have to re-learn the grouping. |
| [`backend/app/db/models/proposal.py:36-89`](../../../../backend/app/db/models/proposal.py#L36-L89) | `Proposal.config_diff` is non-null JSONB. Hand-crafted proposals (`study_id IS NULL`) still have `config_diff` populated by the agent tool / manual create-proposal endpoint. | The new panel renders correctly for both source kinds (study-born and hand-crafted) — see FR-3. |
| [`backend/app/db/models/study.py:71-72`](../../../../backend/app/db/models/study.py#L71-L72) | `Study.search_space` is non-null JSONB with shape `{params: {<name>: <bounds>}, ...}` per the search-space Pydantic schema. | The new panel reads `parentStudy.search_space.params` to derive the "in search space" set. |
| [`backend/app/db/models/query_template.py:38-39`](../../../../backend/app/db/models/query_template.py#L38-L39) | `QueryTemplate.declared_params` is non-null JSONB with shape `Record<str, str>` (param name → type tag — `"float"` / `"int"` / `"categorical"`). | Confirmed shape: [`ui/src/lib/types.ts:2884-2887`](../../../../ui/src/lib/types.ts#L2884-L2887) types it as `{ [key: string]: string }` on `QueryTemplateDetail`. |
| [`backend/app/api/v1/schemas.py:1507-1532`](../../../../backend/app/api/v1/schemas.py#L1507-L1532) | `ProposalDetail.template: _TemplateEmbed` carries `id`, `name`, `version`, `engine_type`. **It does NOT carry `declared_params`**. | The new panel sources `declared_params` via `useTemplate(proposal.template.id)`, not via the embed. This is unchanged from the existing page — the existing `<SuggestedFollowupsPanel>` mount also depends on a separate `useTemplate(...)` fetch. |

### Navigation and link impact

No existing routes change. The new panel mounts inline on `/proposals/[id]`; no new routes added.

| Source file | Current link target | New link target |
|---|---|---|
| _(none)_ | _(no link changes)_ | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/proposals/config-diff-panel.test.tsx`](../../../../ui/src/__tests__/components/proposals/config-diff-panel.test.tsx) | `<ConfigDiffPanel>` render assertions | 6 | **None.** `<ConfigDiffPanel>` is unchanged; its tests are unaffected. |
| [`ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx`](../../../../ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx) | `<SuggestedFollowupsPanel>` render assertions | ~30 | **Probably none.** If the `parentTemplateQuery` lift (FR-3) changes the prop shape passed to `<SuggestedFollowupsPanel>`, the existing tests already mock that prop directly and continue to pass. |
| [`ui/tests/e2e/proposals.spec.ts`](../../../../ui/tests/e2e/proposals.spec.ts) | Asserts `config-diff-row-title.boost` + `config-diff-row-description.boost` visible on the detail page | 1 test | **None.** The seeded manual proposal's `config_diff` still renders in `<ConfigDiffPanel>` exactly as before; the new panel is additive. |

### Existing behaviors affected by scope change

- **`/proposals/[id]` initial render:** Current: header → config-diff → metric-delta → PR / Reject row → suggested-followups (when present). New: header → config-diff → **full-param-space (when `parentTemplate.data` available)** → metric-delta → PR / Reject row → suggested-followups (when present). Decision needed: **No** — additive, conditional on `parentTemplate.data`.
- **`useTemplate(...)` fetch timing on `/proposals/[id]`:** Current: fetch is gated on `parentStudyId !== null && hasActionableFollowup` (i.e., disabled for manual proposals and study proposals without actionable followups). New: fetch fires for **every proposal that loaded successfully** (gated only on `proposal.template.id`'s truthiness). Decision needed: **Yes — locked here.** See FR-3 and §19 D-1 below for the rationale and impact (the cost is one extra `GET /api/v1/query-templates/{id}` by primary key for the previously-disabled cases — sub-ms).

---

## 3) Scope

### In scope

- A new client component `<FullParamSpacePanel>` (planned location: `ui/src/components/proposals/full-param-space-panel.tsx`) that renders the three-state partition (tuned-and-changed / tuned-but-unchanged / not-in-search-space) for the proposal's template.
- A new pure helper `partitionTemplateParams({declaredParams, configDiff, searchSpaceParams})` in `ui/src/lib/proposal-param-space.ts` that produces the three-state partition and is unit-testable without DOM (the partition algorithm is the spec's domain rule — pulling it into a pure module makes it the natural test target).
- Promotion of `extractFromTo` from `config-diff-panel.tsx` to a shared module `ui/src/lib/config-diff.ts` so the new panel reuses the same `{from, to}`-vs-2-tuple normalization without duplicating the helper. The existing `<ConfigDiffPanel>` re-imports from the new location (no behavior change).
- A **two-call refactor** of `ui/src/app/proposals/[id]/page.tsx` (FR-3, D-13): (a) change the input to `useTemplate(...)` from `parentStudy.data?.template_id` to `proposal.template.id`; (b) drop `&& hasActionableFollowup` from the `useStudy(...)`'s `enabled` gate so it fires for every study-backed proposal. Both fetches become always-on for any successfully-loaded proposal. `<SuggestedFollowupsPanel>` continues to receive `parentTemplate` via the same prop; the value it receives is unchanged for the existing actionable-followup case (the two `template_id`s are equal — both resolve to the same template row).
- A new glossary key `proposal.full_param_space` (info affordance on the panel header). The panel uses the existing `<InfoTooltip glossaryKey="..." />` primitive ([`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx)) with the same hover-trigger semantics as every other proposal-page tooltip.
- **Race-aware conditional mount** (FR-4): the panel mounts only when `parentTemplate.data` is available AND, for study-backed proposals, when `parentStudy` query has settled (success or error — `parentStudy.isPending === false`). For manual proposals (`study_id === null`), the study fetch is short-circuited, so only the template gate applies. For the brief loading window, the panel does not render — there is no skeleton, no "loading" affordance, no flicker — the page continues to be functional via the other panels and the new one appears once the data lands.

### Out of scope

- **Cap 2 of the idea (param-name linking between the new panel and the follow-up cards).** Deferred per Q3 below — the visible grouping in the new panel already gives the operator the "what did this study not tune" answer; cross-panel hover linking is a polish item that compounds value if both panels are co-visible but doesn't change the headline lens. **No `phase*_idea.md` artifact will be created** (locked in D-8 + D-13 below) — Cap 2 will be reopened only if specific operator feedback surfaces.
- **Cap 3 of the idea (mount the same view on the study detail page).** Explicitly deferred — same data, different mount point; defer until the proposal-page version proves out. **No `phase*_idea.md` artifact will be created** (locked in D-8 + D-13 below) — Cap 3 will be reopened only if specific operator feedback surfaces.
- **Inline rendering of bounds for un-tuned params** (params declared on the template but never in any study's search space). The template only stores `Record<str, type-tag>` — no bounds, no defaults. Showing "type only" for that group is the locked answer (see Q2 below).
- **Schema or migration changes.** This feature consumes existing data only: `ProposalDetail.config_diff`, `ProposalDetail.template.id`, `StudyDetail.search_space.params` (via the existing `useStudy(proposal.study_id)` fetch), and `QueryTemplateDetail.declared_params` (via `useTemplate(proposal.template.id)`). No new endpoints, no new fields, no new DB columns.
- **Server-side aggregation.** All three-state partitioning happens client-side from the four payloads above. No `GET /api/v1/proposals/{id}/param-space` endpoint; the cost is one `Object.keys(...)`-shaped pure function.
- **A guide / runbook entry.** This is a small UI affordance; the existing tutorial-first-study guide and the inline tooltip cover the discoverability and explanation. (The implementation plan will assess guide-screenshot regeneration impact post-merge.)

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix convention:** N/A — no new endpoints. The feature consumes three existing endpoints: `GET /api/v1/proposals/{id}`, `GET /api/v1/studies/{id}`, `GET /api/v1/query-templates/{id}`. All three live under `/api/v1/` and follow the project's standard cursor-paginated / single-resource shapes.
- **Router namespace for this feature's endpoints:** N/A.
- **HTTP methods for CRUD:** N/A — read-only.
- **Non-auth error envelope shape:** N/A — no new error paths. Existing 404 envelopes from `GET /api/v1/query-templates/{id}` (the actual `error_code` is `TEMPLATE_NOT_FOUND` per [`backend/app/api/v1/query_templates.py:242`](../../../../backend/app/api/v1/query_templates.py#L242)) cause the panel to simply not mount — no panel-level error UI, no envelope inspection. See FR-7 edge case B for the locked behavior.
- **Auth error shape:** N/A — single-tenant, no auth surface through GA v1.
- **Pagination / headers:** N/A — no list endpoints.

### Phase boundaries (if multi-phase)

**Single-phase feature.** All three rendering states + the always-on template fetch land together — partitioning the work into "tuned states first, un-tuned state second" would ship a panel that doesn't yet answer the headline question ("what did the optimizer leave on the table"), so the bisection is value-destructive. No `phaseN_idea.md` files are required.

The two explicitly-deferred capabilities (the idea's Cap 2 and Cap 3) are out-of-scope of this spec — captured under §3 Out of scope and §19 D-2 / D-3, not as phases.

## 4) Product principles and constraints

- **Read-only over the existing schema.** No mutation of any table. No new endpoint. No new field on the wire. The panel is a pure derivation from data already on the page.
- **Three-state partition is the headline.** The panel's mental model is "the template has K knobs; the optimizer tuned M (subset of K); within M, N changed and (M − N) landed at baseline." Visual grouping must make all three groups distinguishable at a glance — no hidden-under-toggle, no "show more."
- **Reuse, don't re-derive.** `extractFromTo` is the canonical `config_diff` reader — promote it once, reuse twice. The declared-params typography comes from `<SuggestedFollowupsPanel>`'s `<DeclaredParamsColumn>` — don't invent a parallel style.
- **Degraded gracefully on edge cases.** Manual proposals (no source study), proposals whose source study has been soft-deleted, proposals whose template was soft-deleted, proposals with an empty `config_diff`: every case must render *something* sensible (empty state, partial render, or skip the panel) — no error boundary, no white screen, no console exception.
- **Enum discipline (CLAUDE.md).** The three rendering states are spec-defined labels (`Tuned (changed by this proposal)`, `Tuned (unchanged)`, `Not in search space`); they don't correspond to a backend allowlist. The panel-internal `ParamSpaceState` discriminator (`'tuned_changed' | 'tuned_unchanged' | 'untuned'`) is the spec's wire-equivalent — it does NOT travel over the wire (no JSON), it only exists between the pure-helper output and the rendering component. The discriminator IS exhaustively used in the rendering switch with a `never`-typed default branch so a future fourth state is a compile error.

### Anti-patterns

- **Do not** inline `extractFromTo` into the new panel — because the canonical `config_diff` shape is owned by `backend/workers/digest.py` and the helper is the line of defense against drift. Duplicate-and-modify would silently desync from `<ConfigDiffPanel>`.
- **Do not** add `declared_params` to `_TemplateEmbed` — because the existing `useTemplate(proposal.template.id)` fetch already loads it, and changing the embed shape is a wire-contract change that the idea explicitly ruled out ("no backend, no payload change"). The single-line input-swap on `useTemplate(...)` (FR-3) achieves the same coverage without touching the backend.
- **Do not** branch on `parentStudy` being null inside the panel itself — because the panel's only job is rendering. The branching belongs in the **pure helper** `partitionTemplateParams`, which takes `searchSpaceParams: Record<string, unknown> | undefined` and returns the three-state partition. When `searchSpaceParams` is undefined, the "tuned-but-unchanged" group is empty (we can't know which params were in the search space if we don't have the search space) and every declared param that isn't in `configDiff` falls into the "not in search space" group.
- **Do not** treat the panel as "extending `<ConfigDiffPanel>`" — because the existing panel has a stable contract (`diff: Record<string, unknown>`) and a test suite (config-diff-panel.test.tsx) that exercises only the diff-rendering responsibility. The new panel is a sibling, not a wrapper. Co-locate them visually; do not co-locate them in code.
- **Do not** render any of the three groups as a hidden `<details>`/`<summary>` toggle — because the headline value is the visible partition. A hidden group erases the lens. (The follow-up cards' "Show search space" expander is the *correct* place for that pattern because the follow-up has its own headline rationale and the search-space JSON is supplementary detail; the param-space panel's content IS the rationale.)
- **Do not** rebuild this panel's state in a TanStack Query cache. The `useTemplate` and `useStudy` fetches are already TanStack-cached; the partition is a derived value computed in render. A separate query for "the partitioned param state" is over-engineering and a stale-cache risk.

## 5) Assumptions and dependencies

- **Dependency: `feat_digest_proposal` (shipped 2026-05-11, PR #41).**
  - Why required: defines the `Proposal.config_diff` JSONB column + the canonical `{from, to}` shape in `backend/workers/digest.py:1158-1174`.
  - Status: **implemented**.
  - Risk if missing: none — the dependency is satisfied.
- **Dependency: `feat_digest_executable_followups_swap_template` (shipped 2026-05-29).**
  - Why required: defines `<DeclaredParamsColumn>` — the typography pattern this panel reuses for visual consistency.
  - Status: **implemented**.
  - Risk if missing: none.
- **Dependency: `feat_study_lifecycle` Phase 1 (shipped 2026-05-10, PR #18).**
  - Why required: defines `Study.search_space` JSONB shape (`{params: {<name>: <bounds>}}`).
  - Status: **implemented**.
  - Risk if missing: none.
- **Soft dependency: `feat_overnight_final_solution` (PR #440, shipped 2026-06-04) + `feat_overnight_final_solution_phase2` (PR #442) + `feat_overnight_studies_summary_card` (PR #444).**
  - Why related (not blocking): with the overnight autopilot live, the proposal page IS the morning artifact operators read. This panel compounds value with that flow but works equivalently for manual studies and non-chain proposals.
  - Status: **implemented**.
  - Risk if missing: none — only the *value* compounds; the feature itself works in isolation.
- **No external service dependency.** No LLM call, no engine call, no Git call. All three data sources (`/proposals/{id}`, `/studies/{id}`, `/query-templates/{id}`) are RelyLoop's own API.

## 6) Actors and roles

- **Primary actor:** Relevance engineer reviewing a proposal — either a study-born proposal generated by a completed study's digest, or (less common) a manually-created proposal via `feat_chat_agent`'s tool or the `POST /api/v1/proposals` endpoint.
- **Role model:** N/A — single-tenant install, no auth surface (MVP1–GA v1 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** Same as the rest of `/proposals/[id]` — anyone with HTTP access to the API can load the page. No role gating in MVP2.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — read-only UI; no state mutations. The feature does not add any endpoint, service, or worker that writes to the database. The `audit_log` table (scheduled to land in a future release per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — the canonical target release is recorded there; CLAUDE.md's release matrix lists it under MVP3 while data-model.md:27 places it in MVP2, a non-blocking cross-doc drift that does not affect this read-only feature) is irrelevant here — there is nothing to audit.

## 7) Functional requirements

### FR-1: Three-state partition derived client-side

- Requirement:
  - The system **MUST** expose a pure helper `partitionTemplateParams({declaredParams, configDiff, searchSpaceParams})` that returns `{tunedChanged: ParamRow[], tunedUnchanged: ParamRow[], untuned: ParamRow[]}` where:
    - **Partition universe is `Object.keys(declaredParams) ∪ Object.keys(configDiff)`.** Keys present in `searchSpaceParams` but not in either of the other two (template-evolution drift: a study's `search_space.params` references a param no longer declared on the current template) are **silently dropped** — they cannot be sensibly typed (no entry in `declared_params` to read a type-tag from) and the operator's mental model "this proposal's template" excludes them by construction. This is the locked partition-universe rule; see D-9 below.
    - `tunedChanged` contains every key in `configDiff` (the canonical `{from, to}` form OR the legacy 2-tuple `[before, after]` form OR the unknown-shape fallback, all normalized via `extractFromTo`). Each row carries `{name, type, from, to}`. **A `configDiff` key whose `from` and `to` are deeply equal (rare anomaly — manual `[1, 1]` 2-tuples, or a digest where the optimizer's winning value matched the baseline exactly) still classifies as `tunedChanged` because membership in `config_diff` is the spec's operational definition of "tuned by this proposal" — see D-10**. For drift case (`configDiff` key not in `declaredParams`), the row's `type` is the literal string `'(unknown)'`.
    - `tunedUnchanged` contains every key in `declaredParams ∩ searchSpaceParams` that is NOT in `configDiff`. Each row carries `{name, type}` and renders with a "(no change)" annotation. If `searchSpaceParams` is undefined (manual proposals; or study-backed proposals where the study fetch hasn't settled — see FR-4 mount-gating), this group is empty.
    - `untuned` contains every key in `declaredParams` that appears in NEITHER `configDiff` NOR `searchSpaceParams`. Each row carries `{name, type}` and renders greyed/italic.
    - Each output array is sorted alphabetically by `name`.
  - The helper **MUST** be pure (no side effects, no `apiClient`, no `Date.now()`, no globals).
  - The helper **MUST** be a named export from `ui/src/lib/proposal-param-space.ts` so the implementation plan can co-locate unit tests in `ui/src/__tests__/lib/proposal-param-space.test.ts`.
- Notes: The headline business rule is the partition. Pulling it into a pure module makes "the spec defines a tri-partition" testable independent of DOM, hydration, and React render cycles. The "`config_diff` membership = tuned" operational definition matches `<ConfigDiffPanel>`'s existing semantics (it renders every `config_diff` entry regardless of whether `from === to`) so operators see the same key treated consistently across the two panels.

### FR-2: `<FullParamSpacePanel>` renders the partition

- Requirement:
  - The system **MUST** render a `<Card>` titled "Full parameter space" with an `<InfoTooltip glossaryKey="proposal.full_param_space" />` adjacent to the title.
  - The card body **MUST** contain three visually distinct groups, in this exact order: **Tuned (changed by this proposal)** first, **Tuned (unchanged)** second, **Not in search space** third. Each group **MUST** have a small group header (text label, e.g. "Tuned (changed by this proposal) — N parameters") and the rows beneath it.
  - The **Tuned (changed by this proposal)** rows **MUST** render the param name (monospace), the type (subtle annotation), and the `from → to` delta in the same visual treatment as `<ConfigDiffPanel>`'s `From` / `To` columns (the cell-level typography in [`config-diff-panel.tsx:102-104`](../../../../ui/src/components/proposals/config-diff-panel.tsx#L102-L104) is the reference).
  - The **Tuned (unchanged)** rows **MUST** render the param name + type + a "(no change)" annotation in muted text.
  - The **Not in search space** rows **MUST** render the param name + type in `text-gray-700` (matching `<DeclaredParamsColumn>`'s non-shared treatment at [`suggested-followups-panel.tsx:377`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L377)), italicized to reinforce the "absent" framing.
  - Each row **MUST** carry `data-testid={`param-space-row-${state}-${name}`}` (e.g., `param-space-row-tuned_changed-title_boost`) for E2E + vitest assertions. Group headers **MUST** carry `data-testid={`param-space-group-${state}`}`.
  - When any group is empty, the system **SHOULD** omit the group header and rows entirely (no "0 parameters" placeholder) rather than render an empty heading.
  - When the **full partition universe** is empty — i.e., `Object.keys(declaredParams).length === 0` **AND** `Object.keys(configDiff).length === 0` (both must hold, since FR-1 includes `configDiff` drift keys in the universe even when `declaredParams` is empty — AC-6) — the system **MUST** render the panel's `data-testid="param-space-empty"` and the message "Template declares no parameters." — and the implementation **MUST NOT** unmount the panel entirely (so the test surface stays observable). When `declaredParams` is empty but `configDiff` has keys, the AC-6 drift-key path applies and the empty state does NOT render.
- Notes: The visual fidelity to existing panels is the user-experience win — operators learn one typography system across the proposal page, not three.

### FR-3: Both `useTemplate(...)` AND `useStudy(...)` fire for every loaded proposal (lifted gating)

- Requirement:
  - The system **MUST** change the input to `useTemplate(...)` at [`ui/src/app/proposals/[id]/page.tsx:183`](../../../../ui/src/app/proposals/[id]/page.tsx#L183) from `parentStudy.data?.template_id` to `proposal.template.id`. The `useTemplate` hook itself (`enabled: Boolean(id)` at [`ui/src/lib/api/query-templates.ts:58`](../../../../ui/src/lib/api/query-templates.ts#L58)) is unchanged.
  - The system **MUST also** lift the `useStudy(...)` `enabled` gate at [`ui/src/app/proposals/[id]/page.tsx:176-178`](../../../../ui/src/app/proposals/[id]/page.tsx#L176-L178) from `parentStudyId !== null && hasActionableFollowup` to `parentStudyId !== null` (drop the `hasActionableFollowup` condition). Without this lift, study proposals with text-only digests or empty digests would mount the panel with `parentStudy.data === undefined`, `searchSpaceParams === undefined`, and **every search-space-but-not-`config_diff` param incorrectly classified as `untuned`** (instead of `tunedUnchanged`). The `hasActionableFollowup` gate was a no-cost-when-unused optimization for the swap-target diff path; lifting it for the new panel's correctness costs one additional `GET /api/v1/studies/{id}` (single-row PK fetch) for study proposals with non-actionable digests — sub-ms on a warm DB connection.
  - The system **MUST** preserve the existing prop passed to `<SuggestedFollowupsPanel parentTemplate={...}>`. The value is unchanged for the existing actionable-followup case — `proposal.template_id == source_study.template_id` by construction in [`backend/workers/digest.py:488-494`](../../../../backend/workers/digest.py#L488-L494) where `repo.create_proposal(..., template_id=study.template_id, ...)`.
  - The system **SHOULD NOT** introduce a second `useTemplate(...)` call. One fetch, one source of truth, both panels consume it. Same posture for `useStudy(...)`.
  - The system **MUST** handle the four proposal shapes that the lifted fetches now cover:
    1. Study proposal with actionable followups (existing case — both fetches were already firing; works unchanged).
    2. Study proposal with text-only or empty digest (previously both fetches disabled; now both fire — this is the case F1 from GPT-5.5 cycle 3 surfaced; without lifting `useStudy`, `tunedUnchanged` would be empty even when `parentStudy.search_space.params` is non-empty).
    3. Manual proposal (`study_id IS NULL`; `useStudy` short-circuits via `enabled: parentStudyId !== null`; `useTemplate` fires; `searchSpaceParams` is undefined; `tunedUnchanged` is empty — see FR-7 edge case D).
    4. Proposal whose template fetch fails (404, transient network) — the fetch returns error → `parentTemplateQuery.error` populated → see FR-7 edge case B.
- Notes: This is the minimum-touch refactor that unlocks the new panel for all proposal shapes. The cost is one additional `GET /api/v1/query-templates/{id}` for case 3 and one additional `GET /api/v1/studies/{id}` + one additional `GET /api/v1/query-templates/{id}` for case 2 — all single-row primary-key fetches, sub-ms each. The alternative (adding `declared_params` + `search_space.params` to `_TemplateEmbed` / `_StudySummary`) is rejected as a backend-shape change for a UI-only feature.

### FR-4: Panel mounts conditionally with race-aware gating

- Requirement:
  - The system **MUST** render `<FullParamSpacePanel>` directly below `<ConfigDiffPanel>` and directly above the metric-delta `<Card>` on `/proposals/[id]`.
  - The system **MUST NOT** mount the panel when `parentTemplateQuery.data` is undefined (still loading, or 404 errored, or fetch disabled because `proposal.template.id` is somehow falsy — the last case should never happen since `template_id` is non-null in the DB and required on `_TemplateEmbed`, but the guard is defensive).
  - **Race-aware gating for study-backed proposals.** When `proposal.study_id !== null` (the proposal is study-born), the panel **MUST** additionally wait for `parentStudy` query to be **settled** (success OR error — TanStack's `parentStudy.isPending === false` is the gate) before mounting. This prevents the brief reclassification window where `parentTemplate.data` arrives before `parentStudy.data` and every non-`config_diff` declared param transiently classifies as `untuned`, then visibly migrates to `tunedUnchanged` once the study fetch lands. For manual proposals (`study_id === null`), there is no study fetch, so this clause is vacuously satisfied and the panel mounts as soon as `parentTemplate.data` arrives.
  - The system **MUST** allow the panel to disappear-and-reappear cleanly if the page remounts (e.g., navigating away and back); the `useTemplate` + `useStudy` caches hydrate immediately on remount, so the race-gating typically resolves in a single tick on warm cache.
  - The system **MUST NOT** introduce a loading skeleton, spinner, or "Loading param space…" placeholder. The brief loading window (the first 50–200ms on cold cache; ~0ms on warm cache) is preferable to an animated placeholder that flashes once and is gone.
- Notes: Same lazy-fetch posture as the existing `<SwapTemplateCard>` per-card fetches in `<SuggestedFollowupsPanel>` ([suggested-followups-panel.tsx:243-247](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L243-L247)). The race-gating differs from `<SwapTemplateCard>`'s posture because that component renders the diff against the swap target only — it has no equivalent of `parentStudy.search_space` whose absence would mis-classify params.

### FR-5: `extractFromTo` is promoted to a shared module

- Requirement:
  - The system **MUST** move `extractFromTo` from `ui/src/components/proposals/config-diff-panel.tsx` (lines 38–56) to `ui/src/lib/config-diff.ts` as a named export, with the JSDoc unchanged.
  - `<ConfigDiffPanel>` **MUST** import from the new location; its rendering and test assertions remain byte-identical.
  - `<FullParamSpacePanel>` **MUST** use the same import for its `tunedChanged` row rendering.
  - The system **MUST** add a unit test file `ui/src/__tests__/lib/config-diff.test.ts` that covers the three branches (canonical `{from, to}`, legacy 2-tuple, unknown shape) — duplicating the in-component coverage that the existing `config-diff-panel.test.tsx` provides, but at the helper level rather than via DOM. The duplication is intentional: it locks the helper's contract for the second consumer.
- Notes: Promoting now (rather than in a follow-up cleanup PR) keeps the diff coherent and removes the duplicate-extraction temptation that would otherwise hit the implementation plan.

### FR-6: New glossary key `proposal.full_param_space`

- Requirement:
  - The system **MUST** add a new glossary entry at the same conventional location as the other proposal entries in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) (the "Phase 2 — Proposals" block, line 558).
  - The entry **MUST** be a `short`-form glossary item with:
    - `short`: a one-sentence explanation under 120 characters. Recommended: `"Every parameter the template declares — grouped by whether the study tuned it and whether tuning changed the value."`.
    - `ariaLabel`: `"More information about the full parameter space"`.
  - The entry **MUST NOT** reference backend file paths, symbol names, or implementation jargon in the user-visible copy (per the glossary's source-of-truth policy at [`ui/src/lib/glossary.ts:5-15`](../../../../ui/src/lib/glossary.ts#L5-L15)).
  - The `glossary.test.ts` AC-12 audience-language check **MUST** pass.
- Notes: The "Why this matters" rationale for the source-of-truth policy is preserved by keeping the key engine-agnostic — the panel works identically for ES / OpenSearch / Solr proposals.

### FR-7: Defensive empty states for the four edge cases

- Requirement:
  - **Edge case A — Source study fetch fails.** When `proposal.study_id` is set but `useStudy(...)` returns 404 (study hard-deleted via maintenance — `studies` has no `deleted_at` today, so this is rare) or settles with any error, the panel **MUST** render with the `tunedUnchanged` group empty. Every declared param not in `config_diff` falls into the `untuned` group. The panel mount is gated on `parentStudy` query being **settled** (success or error), not just "data present" — see FR-4 race-mitigation.
  - **Edge case B — Template fetch fails.** When `useTemplate(proposal.template.id)` returns 404 (no `deleted_at` on `query_templates` today, but the FK doesn't cascade-delete the proposal so a manual hard-delete via raw SQL could orphan the reference; or any future soft-delete column; or transient network failure), the panel **MUST NOT** mount (per FR-4). The page's other panels (config-diff, metric-delta, PR panel) continue to render unaffected. The `<ConfigDiffPanel>` still shows tuned values from `proposal.config_diff` even though the declared-params context is gone. **The §3 API convention check above is the authoritative wording — the "panel-level template-details-unavailable empty state" phrasing is incorrect and superseded by this requirement.**
  - **Edge case C — Empty `config_diff` with non-empty search space.** When `proposal.config_diff` is `{}` but `parentStudy.search_space.params` has keys, the `tunedChanged` group is empty and every search-space key (intersected with `declared_params` per the FR-1 universe rule) falls into `tunedUnchanged`. The panel renders normally.
  - **Edge case D — Manual proposal with no source study.** When `proposal.study_id` is null, `parentStudy` is never fetched (its `useStudy(..., {enabled: parentStudyId !== null})` short-circuits) and `searchSpaceParams` is undefined. `tunedUnchanged` is empty by FR-1; `tunedChanged` shows the `config_diff` keys; `untuned` shows every other declared param.
- Notes: The pure helper + the conditional mount together cover all four. No edge case triggers an error boundary or a console exception.

### FR-8: `<FullParamSpacePanel>` has a defined prop contract

- Requirement:
  - The system **MUST** export `FullParamSpacePanelProps` with shape:
    ```ts
    export interface FullParamSpacePanelProps {
      configDiff: Record<string, unknown>;
      declaredParams: Record<string, string>;
      searchSpaceParams?: Record<string, unknown> | undefined;
    }
    ```
  - The page passes `configDiff={proposal.config_diff}`, `declaredParams={parentTemplateQuery.data.declared_params}`, and `searchSpaceParams={(parentStudy.data?.search_space as { params?: Record<string, unknown> } | undefined)?.params}` (with the same `as` casting pattern the page already uses at lines 226–241).
- Notes: The prop contract makes the panel directly unit-testable with vitest — no `useTemplate` mocking, no React Query setup, just synchronous data in / DOM out.

## 8) API and data contract baseline

### 8.1 Endpoint surface (if applicable)

**N/A — no new endpoints.** The feature consumes three existing endpoints:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/proposals/{id}` | Source of `config_diff`, `template.id` | `PROPOSAL_NOT_FOUND` (404) |
| `GET` | `/api/v1/studies/{id}` | Source of `search_space.params` (when `proposal.study_id` is non-null) | `STUDY_NOT_FOUND` (404) |
| `GET` | `/api/v1/query-templates/{id}` | Source of `declared_params` | `TEMPLATE_NOT_FOUND` (404) — [`backend/app/api/v1/query_templates.py:242`](../../../../backend/app/api/v1/query_templates.py#L242) |

All three are read-only and already exist; no router file changes.

### 8.2 Contract rules

- No new contract — the feature is a pure consumer of three existing contracts.
- The existing error envelope remains the standard `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `api-conventions.md`; the panel handles 404 from `/query-templates/{id}` by simply not mounting (FR-7 edge case B) — no envelope inspection, no user-facing error string.

### 8.3 Response examples

N/A — no new endpoints.

### 8.4 Enumerated value contracts

**No backend-validated enumerations are introduced or consumed.** The panel uses three internal-only **group labels** (`'tuned_changed' | 'tuned_unchanged' | 'untuned'`) as a TypeScript `Literal` type representing the group an output array belongs to. These never travel over the wire and are NOT a field on individual rows — they identify which of the three arrays returned by `partitionTemplateParams` a row came from:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `ParamSpaceGroup` (group identity) | `'tuned_changed'`, `'tuned_unchanged'`, `'untuned'` | **None — internal-only.** Defined in `ui/src/lib/proposal-param-space.ts` as `type ParamSpaceGroup = 'tuned_changed' \| 'tuned_unchanged' \| 'untuned'`. Used to (a) key the three output arrays in `PartitionResult`, (b) generate `data-testid` markers like `param-space-group-${group}` and `param-space-row-${group}-${name}`, and (c) drive the exhaustive group-rendering function in `<FullParamSpacePanel>` with a `never`-typed default branch so a future variant is a compile error. | `<FullParamSpacePanel>` group-rendering function; helper return shape |
| `ParamRow` (row shape, group-typed via container) | Two row shapes — `TunedChangedRow = { name: string; type: string; from: unknown; to: unknown }` for the `tunedChanged` array, `DeclaredRow = { name: string; type: string }` for the `tunedUnchanged` AND `untuned` arrays | **None — internal-only.** Defined in `ui/src/lib/proposal-param-space.ts`. Rows do NOT carry a `state` discriminator field — the group identity is the containing array. | `<FullParamSpacePanel>` per-group row renderer |

The CLAUDE.md "Enumerated Value Contract Discipline" rule applies to values the frontend sends to the backend; this group identity does the opposite direction (frontend-defined, never serialized), so the rule does not apply. The discriminant is still typed via `Literal` (not a free string) so future drift is caught at compile time. **The three-arrays-with-group-identity design is the locked answer (D-12 below) — rows are NOT discriminated unions with an on-row `state` field.**

### 8.5 Error code catalog (if API-heavy)

N/A — no new error codes.

## 9) Data model and state transitions

### New/changed entities

**None.** The feature introduces no new tables, no new columns, no migrations.

### Required invariants

- The pure helper `partitionTemplateParams` **MUST** produce three disjoint output arrays — no key appears in more than one. (Implementation: a key is checked against `configDiff` first, then `searchSpaceParams`, then falls through to `untuned`; the three checks are mutually exclusive.)
- Every key in `declaredParams` **MUST** appear in exactly one of the three groups. (Implementation: the helper iterates `Object.keys(declaredParams)` and assigns each to one group.) Edge: if `configDiff` contains a key NOT in `declaredParams` (drift case — declared_params evolved but old proposals still reference removed keys), that key **MUST** still appear in `tunedChanged` (the proposal's own data takes precedence over the template's current declarations — the spec's truthfulness rule). This is a "best-effort defensive" behavior; the AC includes a unit test for it.

### State transitions

N/A — pure render-time derivation, no persisted state.

### Idempotency/replay behavior (if event-driven)

N/A — not event-driven.

## 10) Security, privacy, and compliance

- **Threats:** None new. The feature reads existing API responses that the operator is already authorized to load (single-tenant, no auth gating). No PII, no credentials, no token surfaces touched.
- **Controls:** N/A — no new attack surface.
- **Secrets/key handling:** N/A.
- **Auditability:** N/A — read-only, no audit_log emission (per §6 above).
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The new panel mounts on the existing `/proposals/[id]` route, immediately below `<ConfigDiffPanel>` and immediately above the metric-delta `<Card>`. No new route. No new sidebar entry. No new tab.
- **Labeling taxonomy:**
  - Card title: **"Full parameter space"** (matches the existing pattern of sentence-case noun-phrase panel titles: "Config diff", "Metric delta", "Suggested follow-ups").
  - Group headers (in render order):
    1. **"Tuned (changed by this proposal)"** — annotated `"— N parameters"` (where N is `tunedChanged.length`).
    2. **"Tuned (unchanged)"** — annotated `"— N parameters"`.
    3. **"Not in search space"** — annotated `"— N parameters"`.
  - Per-row labels: param name (monospace), type tag (subtle), value treatment per group (see FR-2).
- **Content hierarchy:** Card header + tooltip → three grouped sections in the locked order above. **Tuned (changed by this proposal)** is visually heaviest (full from→to columns); **Tuned (unchanged)** is medium (name + "(no change)"); **Not in search space** is lightest (name + type, muted).
- **Progressive disclosure:** None. The panel shows everything inline. No `<details>` toggles, no "Show all" buttons.
- **Relationship to existing pages:** The panel sits alongside `<ConfigDiffPanel>` and `<SuggestedFollowupsPanel>` as a third lens on the same proposal — config-diff shows "what changed," full-param-space shows "what could have changed," suggested-followups shows "what to try next." The three lenses are intentionally complementary, not redundant.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| `<FullParamSpacePanel>` card title | `"Every parameter the template declares — grouped by whether the study tuned it and whether tuning changed the value."` | `hover` / `focus` | adjacent to title (inline-flex, same as existing panels) |

The single new tooltip is grounded in the new glossary key `proposal.full_param_space` (FR-6). Per-row hover tooltips for type explanations (e.g., "float = continuous numeric parameter") are deferred — operators already understand the three declared-param types from the wizard and the swap-template card.

### Primary flows

1. **Operator reviews a study-born proposal with chain-aware tuning.** Operator opens `/proposals/<id>` for an overnight chain's winning link. `<ConfigDiffPanel>` shows the 2–3 knobs that changed; `<FullParamSpacePanel>` shows those 2–3 plus the 5–8 other declared params (the ones the study had in its search space but didn't move, plus the ones outside the search space entirely). Operator can now answer "did the optimizer consider description-boost?" by checking which group it's in.
2. **Operator reviews a manual proposal.** Opens `/proposals/<id>` for an agent-tool-created proposal (`study_id IS NULL`). `<ConfigDiffPanel>` shows the manually-specified diff; `<FullParamSpacePanel>` mounts (FR-3 ensures the template fetch fires), shows the diff keys under "Tuned (changed by this proposal)," and every other declared param under "Not in search space" (the `tunedUnchanged` group is empty because there's no source study). Visual integrity preserved; degraded gracefully per FR-7 edge case D.
3. **Operator reviews a chain link's proposal where the swap target tunes a disjoint param set.** Phase 1 of the spec (the chain-link proposal's panel) shows declared_params of the *winning link's template* — which, for a swap-template chain link, is the swap target. The operator can compare against the chain's earlier proposals (each showing its own template's declared_params) to see the cross-knob exploration the autopilot ran.

### Edge/error flows

- **Template soft-deleted between proposal creation and review.** `useTemplate` 404s; the panel does not mount; the rest of the page renders normally. (FR-7 edge case B.)
- **Source study soft-deleted.** `useStudy` 404s; `parentStudy.data` is undefined; `searchSpaceParams` is undefined; the `tunedUnchanged` group is empty; everything else renders. (FR-7 edge case A.)
- **Empty `config_diff` (rare — possible when the optimizer's best trial matched the baseline exactly on every param, or for manually-created proposals that specified `config_diff: {}`).** `tunedChanged` is empty; `tunedUnchanged` shows every search-space key (or empty if no source study). (FR-7 edge case C.)
- **`config_diff` references a param no longer declared on the template.** Edge case from template-evolution. The drift key still shows under `tunedChanged` (proposal's data is authoritative for what was actually tuned). The drift is silent from the operator's perspective — the panel doesn't flag the orphan. (Decision locked here per D-5 below.)
- **Page load races: template fetch resolves before study fetch.** For study-backed proposals (`proposal.study_id !== null`), the panel does NOT mount until both `parentTemplateQuery.data` is truthy AND `parentStudy.isPending === false` (the study query has settled — success OR error). This is the race-aware gating from FR-4. The operator never sees a transient classification: the panel either is absent (data still loading) or is correctly populated. For manual proposals (`study_id === null`), there is no study fetch to wait for, so the panel mounts as soon as `parentTemplateQuery.data` is truthy.

## 12) Given/When/Then acceptance criteria

### AC-1: Tuned-and-changed group renders with from→to deltas

- Given a proposal with `config_diff = { title_boost: { from: 1.0, to: 2.5 }, description_boost: { from: 1.0, to: 0.5 } }`, a source study with `search_space.params = { title_boost: {...}, description_boost: {...}, fuzziness: {...} }`, and a template with `declared_params = { title_boost: "float", description_boost: "float", fuzziness: "int", function_score_decay: "categorical" }`
- When the operator navigates to `/proposals/<id>` and the page renders
- Then `<FullParamSpacePanel>` mounts with three groups, **each group's rows sorted alphabetically by param name per FR-1**:
  - **Tuned (changed by this proposal) — 2 parameters**: `description_boost (float)  1 → 0.5`, then `title_boost (float)  1 → 2.5` (alphabetical: `description_boost` < `title_boost`)
  - **Tuned (unchanged) — 1 parameter**: `fuzziness (int) (no change)`
  - **Not in search space — 1 parameter**: `function_score_decay (categorical)` (greyed, italic)
- Example values:
  - Input: see `Given` above
  - Expected `data-testid` markers visible **in DOM order** (alphabetical within each group):
    - `param-space-group-tuned_changed`, then `param-space-row-tuned_changed-description_boost`, then `param-space-row-tuned_changed-title_boost`
    - `param-space-group-tuned_unchanged`, then `param-space-row-tuned_unchanged-fuzziness`
    - `param-space-group-untuned`, then `param-space-row-untuned-function_score_decay`

### AC-2: Legacy 2-tuple `config_diff` shape renders correctly

- Given a manual proposal with `config_diff = { boost: [1.0, 1.5] }` (the legacy 2-tuple shape from agent-tool / manual create-proposal callers — see [`config-diff-panel.test.tsx:43-55`](../../../../ui/src/__tests__/components/proposals/config-diff-panel.test.tsx#L43-L55)), `study_id = null`, and a template with `declared_params = { boost: "float", title_weight: "float" }`
- When the page renders
- Then `<FullParamSpacePanel>` shows:
  - **Tuned (changed by this proposal) — 1 parameter**: `boost (float)  1 → 1.5` (the 2-tuple is normalized via the promoted `extractFromTo`)
  - **Not in search space — 1 parameter**: `title_weight (float)`
  - **Tuned (unchanged)** group **NOT** rendered (empty; `searchSpaceParams` is undefined for manual proposals)

### AC-3: Manual proposal (no source study) renders without errors

- Given `proposal.study_id === null` (manual proposal)
- When the page renders
- Then `<FullParamSpacePanel>` mounts as soon as `useTemplate(proposal.template.id)` resolves
- And the `tunedUnchanged` group is absent (zero rows; group header not rendered)
- And no console error or React error boundary fires

### AC-4: Template soft-deleted between proposal creation and review

- Given a proposal whose `template.id` is for a soft-deleted template; `GET /api/v1/query-templates/{id}` returns 404
- When the page renders
- Then `<ConfigDiffPanel>` continues to render `proposal.config_diff` as usual
- And `<FullParamSpacePanel>` does NOT mount (`parentTemplateQuery.data` is undefined)
- And the rest of the page (metric-delta, PR / Reject row, suggested-followups) renders unaffected

### AC-5: Empty `config_diff` shows full Tuned (unchanged) group

- Given `proposal.config_diff = {}` and `parentStudy.search_space.params = { foo: {...}, bar: {...} }` and `declaredParams = { foo: "float", bar: "int", baz: "categorical" }`
- When the page renders
- Then `<FullParamSpacePanel>` shows (alphabetical within each group per FR-1):
  - **Tuned (changed by this proposal)** group **NOT** rendered (empty)
  - **Tuned (unchanged) — 2 parameters**: `bar (int) (no change)`, then `foo (float) (no change)`
  - **Not in search space — 1 parameter**: `baz (categorical)`

### AC-6: `config_diff` drift key (declared on proposal but not in current template) still surfaces

- Given `config_diff = { removed_param: { from: 1, to: 2 } }` and `declaredParams = {}` (the template's declared params were edited after the proposal was generated, removing `removed_param`)
- When the page renders
- Then **Tuned (changed by this proposal) — 1 parameter** group contains `removed_param  1 → 2`
- And the absence from `declaredParams` is silent (no warning, no error — the proposal's own truth wins per D-5)

### AC-7: Three rendering states are visually distinguishable

- Given AC-1's inputs
- When the page renders
- Then the **Tuned (changed by this proposal)** rows visually carry the from→to value treatment matching `<ConfigDiffPanel>`'s `From`/`To` columns
- And the **Tuned (unchanged)** rows visually carry a "(no change)" annotation in muted text
- And the **Not in search space** rows visually carry `text-gray-700 italic` styling matching `<DeclaredParamsColumn>`'s non-shared treatment

### AC-8: Glossary key `proposal.full_param_space` resolves and the tooltip renders

- Given the card mounted
- When the operator hovers (or keyboard-focuses) the info icon next to the card title
- Then the tooltip body shows the FR-6 short-form copy
- And the `tooltip-trigger-proposal.full_param_space` and `tooltip-body-proposal.full_param_space` `data-testid` markers are present

### AC-9: `extractFromTo` is shared and `<ConfigDiffPanel>` tests stay green

- Given the FR-5 refactor (helper moved to `ui/src/lib/config-diff.ts`)
- When the test suite runs
- Then `ui/src/__tests__/components/proposals/config-diff-panel.test.tsx` passes byte-identically
- And `ui/src/__tests__/lib/config-diff.test.ts` (new) passes with the same three-branch coverage at the helper level

### AC-10: Lifted `useTemplate(...)` does not regress `<SuggestedFollowupsPanel>` rendering

- Given a study proposal with a `swap_template` followup
- When the page renders (with FR-3's lifted `useTemplate(proposal.template.id)` instead of the previous `useTemplate(parentStudy.data?.template_id)`)
- Then `<SuggestedFollowupsPanel>` receives the same `parentTemplate.declared_params` value it received before the refactor
- And the swap-template card's `<DeclaredParamsColumn>` (parent vs swap target) renders byte-identically

### AC-11: Race-aware mount gating for study-backed proposals

- Given a study-backed proposal (`proposal.study_id !== null`) loading on a cold cache
- When the template fetch (`useTemplate(proposal.template.id)`) resolves before the study fetch (`useStudy(proposal.study_id)`) — i.e., `parentTemplateQuery.data` is truthy and `parentStudy.isPending === true`
- Then `<FullParamSpacePanel>` MUST NOT be in the DOM yet
- And once `parentStudy.isPending === false` (the study query has settled, success or error), the panel mounts and renders the correct three-state partition derived from the now-known `searchSpaceParams`
- And the operator sees no transient classification — the panel is either absent (data still loading) or correctly populated (never visibly reclassified)
- Example assertions (page-level vitest, race-gating regression test):
  - With `useTemplate` mocked to resolve immediately and `useStudy` mocked to remain pending: `screen.queryByTestId('param-space-group-tuned_changed')` returns `null`
  - After `useStudy` settles to its success value: the same query returns the group element

## 13) Non-functional requirements

- **Performance:** The panel's render cost is `O(declared_params.length)` for the partition pass plus `O(declaredParams.length * log(declaredParams.length))` for the per-group alphabetical sort — both negligible for the realistic upper bound (~25 declared params per template). The additional `GET /api/v1/query-templates/{id}` for cases the old gating skipped is a single-row primary-key fetch (sub-ms on a warm DB connection). No backend cost change.
- **Reliability:** The conditional mount (FR-4) ensures any single fetch failure degrades to a missing panel, never to a page crash. The unit-tested pure helper (FR-1) is the regression-test surface; the integration cost of a TanStack-cached fetch is the same as the existing `<SwapTemplateCard>` pattern.
- **Operability:** No new logs, no new metrics, no new alerts. The feature does not change observability.
- **Accessibility:** Group headers are semantic `<h3>` (or equivalent `<div>` with appropriate aria role) so screen readers narrate the partition. Each row's icon affordance (if any — currently the spec keeps rows pure text) is decorative. The single `<InfoTooltip>` is keyboard-focusable per the existing primitive's Radix Tooltip implementation.

## 14) Test strategy requirements (spec-level)

- **Unit tests (`ui/src/__tests__/lib/`):**
  - `proposal-param-space.test.ts` — exercises `partitionTemplateParams` across:
    1. AC-1 fixture (three non-empty groups).
    2. Empty `config_diff` (AC-5).
    3. Undefined `searchSpaceParams` (AC-3, AC-2 manual-proposal shape).
    4. `config_diff` drift case — key not in `declaredParams` (AC-6) — `type` resolves to `'(unknown)'`.
    5. `searchSpace` drift case — key in `searchSpaceParams` but not in `declaredParams` and not in `configDiff` — silently dropped per the FR-1 partition universe rule (D-9).
    6. Legacy 2-tuple `config_diff` shape (AC-2).
    7. `from === to` anomaly — `config_diff` entry with deeply-equal values still classifies as `tunedChanged` per D-10.
    8. Sort stability — alphabetical ordering within each group.
  - `config-diff.test.ts` — three-branch coverage of the promoted `extractFromTo` (canonical `{from, to}`, legacy 2-tuple, unknown shape).
- **Component tests (`ui/src/__tests__/components/proposals/`):**
  - `full-param-space-panel.test.tsx` — renders the panel with synthetic props for each AC-1..AC-7 + AC-8 scenario. Wraps `<TooltipProvider>` per the existing `config-diff-panel.test.tsx` pattern.
- **Page-level tests (`ui/src/__tests__/app/proposals/[id]/page.test.tsx` — extends the existing file):**
  - **Study proposal without actionable followups (FR-3 cycle-3 F1 regression guard)** — assert that BOTH `useTemplate(proposal.template.id)` AND `useStudy(proposal.study_id)` fire (FR-3 lifted gating dropped `hasActionableFollowup` from both). Seed a fixture with `proposal.study_id` set, `proposal.digest.suggested_followups = []` (empty) or text-only, and `parentStudy.search_space.params = { foo: {...} }` (search space non-empty) that is absent from `config_diff`. After both fetches settle, assert that `<FullParamSpacePanel>` mounts AND that `param-space-row-tuned_unchanged-foo` is in the DOM — NOT `param-space-row-untuned-foo`. This is the bug GPT-5.5 cycle-3 F1 surfaced; without it, `foo` would mis-classify as `untuned` and the test would catch the regression.
  - **Manual proposal (`study_id === null`)** — assert that the panel mounts as soon as `useTemplate(proposal.template.id)` resolves (no `useStudy` to wait for), per FR-7 edge case D.
  - **Template fetch 404** — mock the `useTemplate` query to settle with a 404 error; assert that `<FullParamSpacePanel>` does NOT render while `<ConfigDiffPanel>`, the metric-delta card, and the PR/Reject row remain visible. Covers FR-7 edge case B and AC-4.
  - **Race-gating regression** — for a study-backed proposal, simulate `parentTemplate.data` resolving before `parentStudy` settles; assert that `<FullParamSpacePanel>` is NOT yet in the DOM (FR-4 race-aware gating). Once `parentStudy` settles, assert the panel mounts with the correctly-classified `tunedUnchanged` group.
- **Integration / contract tests:** N/A — no backend changes.
- **E2E (`ui/tests/e2e/`):**
  - Extend [`ui/tests/e2e/proposals.spec.ts`](../../../../ui/tests/e2e/proposals.spec.ts) with one new test: navigate to a seeded manual proposal's `/proposals/<id>` page and assert `data-testid="param-space-group-tuned_changed"` and `data-testid="param-space-group-untuned"` are visible. The seeded helper at [`ui/tests/e2e/helpers/seed.ts:300`](../../../../ui/tests/e2e/helpers/seed.ts#L300) (`seedTemplate`) already creates a template with `declared_params = { boost: 'float' }` and `seedProposal` writes a `config_diff` that includes `title.boost` (drift case AC-6 in miniature, since `title.boost` ≠ `boost`). The test verifies the panel renders without React errors and shows the expected groups.
  - Real-backend test (not `page.route()` mocked) — same posture as the existing `proposals.spec.ts` cases.

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` — no update required; the new panel follows the established `<Card>` + `<InfoTooltip>` patterns this doc already describes.
- `docs/02_product/` — no operator-facing user-story changes; the proposal page already exists and this is a polish addition.
- `docs/03_runbooks/` — no new runbook needed; the panel has no operational footprint.
- `docs/04_security/` — no update; no new security surface.
- `docs/05_quality/testing.md` — no update; tests follow the existing layer convention.
- `docs/08_guides/` — **possible regen impact**: the proposal-detail screenshot in any guide that walks through `/proposals/<id>` will gain the new panel below `<ConfigDiffPanel>`. The implementation plan's post-implementation guide-impact assessment (per `/impl-execute` Step 2b) determines whether a regeneration is warranted.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The change is additive client-side; no new backend behavior to flag.
- **Migration/backfill expectations:** None — no schema changes.
- **Operational readiness gates:** None — read-only UI.
- **Release gate:** Standard MVP2 gates: backend tests + UI vitest + tsc + ESLint + Next build + Playwright (real-backend) all green; the dashboard regen pre-commit hook lands the dashboards in lockstep; the cross-model GPT-5.5 review converges with no High-severity findings; Gemini Code Assist findings adjudicated; PR #-of-record merged via the merge-skew check (`pr.yml` against current `main`).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (pure partition helper) | AC-1, AC-2, AC-3, AC-5, AC-6 | Story 1.1 — pure helper + unit tests | `ui/src/__tests__/lib/proposal-param-space.test.ts` | none |
| FR-2 (panel renders three groups) | AC-1, AC-2, AC-5, AC-7 | Story 1.3 — `<FullParamSpacePanel>` component + tests | `ui/src/__tests__/components/proposals/full-param-space-panel.test.tsx` | none |
| FR-3 (lifted `useTemplate` input) | AC-3, AC-4, AC-10, AC-11 | Story 1.4 — page-level refactor + page test | page-level vitest in `ui/src/__tests__/app/proposals/[id]/page.test.tsx` (FR-3 lifted-gating tests); component test verifies `<SuggestedFollowupsPanel>` parity; tsc + lint catch the input swap | none |
| FR-4 (conditional mount + race-aware gating) | AC-4, AC-11 | Story 1.4 — page-level mount logic | page-level vitest in `ui/src/__tests__/app/proposals/[id]/page.test.tsx` (race-gating regression test) | none |
| FR-5 (extractFromTo promotion) | AC-9 | Story 1.2 — helper move + unit tests | `ui/src/__tests__/lib/config-diff.test.ts` | none |
| FR-6 (glossary key) | AC-8 | Story 1.3 — glossary entry added alongside panel | covered by Story 1.3 tooltip render assertion + the existing `glossary.test.ts` AC-12 audience-language check | none |
| FR-7 (defensive empty states) | AC-3, AC-4, AC-5, AC-6 | Stories 1.1 (helper edges) + 1.4 (mount guard) | covered by Story 1.1 + Story 1.4 tests | none |
| FR-8 (prop contract) | AC-1..AC-7 | Story 1.3 — exported `FullParamSpacePanelProps` | tsc enforces the contract; unit tests instantiate per the prop shape | none |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-11 — every AC listed in §12) pass in CI.
- [ ] All test layers (unit / component / E2E) are green. No backend test changes required.
- [ ] No documentation updates required outside the spec + plan + implementation tracker (per §15).
- [ ] Rollout gates from §16 are satisfied (lint / typecheck / tests / build / cross-model review converge / Gemini adjudicated / merge-skew checked / PR merged).
- [ ] No open questions remain in §19.
- [ ] The dashboard regen pre-commit hook has updated `MVP2_DASHBOARD.md` to reflect the new shipped feature.
- [ ] The feature folder has been moved from `docs/00_overview/planned_features/02_mvp2/feat_proposal_full_param_space_view/` to `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_proposal_full_param_space_view/`.

## 19) Open questions and decision log

### Open questions

_None._ Q1, Q2, Q3 from the idea are all resolved in this spec (locked as D-2, D-3, D-4 below).

### Decision log

- **2026-06-04 — D-1: Lift `useTemplate(...)` input from `parentStudy.data?.template_id` to `proposal.template.id`.** Locked because the existing input was gated on `hasActionableFollowup` (the proposal had to have ≥1 narrow/widen/swap_template followup) AND on a successful `useStudy` fetch — both gates fail for manual proposals and study proposals without actionable followups. The lifted input fires the template fetch for **every** loaded proposal at the cost of one extra `GET /api/v1/query-templates/{id}` (single-row PK fetch, sub-ms). Alternatives considered: (A) add `declared_params` to `_TemplateEmbed` (rejected — backend shape change for a UI feature; idea explicitly ruled out); (B) second `useTemplate(proposal.template.id)` alongside the existing one (rejected — two fetches for the same data, duplicate TanStack cache entries, slight runtime overhead). The lift is the smallest and cleanest path.
- **2026-06-04 — D-2 (resolves idea Q1): One panel with visual grouping, not two stacked panels.** Locked because two panels would visually fragment a single mental model ("the template's parameter space, partitioned by what this study did with it"). One card with three labeled groups is the established pattern (`<ConfigDiffPanel>` is one card with one table; the new panel is one card with three group-labeled tables).
- **2026-06-04 — D-3 (resolves idea Q2): Show param name + type-tag for un-tuned params; do NOT show bounds.** Locked because the template's `declared_params` JSONB stores `Record<str, type-tag>` only — bounds live on each study's `search_space`. The "Not in search space" group has no study-scoped bounds by definition; showing the type-tag (the only thing the template tracks) is the truthful representation.
- **2026-06-04 — D-4 (resolves idea Q3): Scope the new panel to THIS proposal's template only.** Locked because `<SuggestedFollowupsPanel>` already renders a parent-vs-swap-target declared_params diff for `swap_template` cards ([suggested-followups-panel.tsx:280-298](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L280-L298)). Adding a swap-target column to the new panel would duplicate that surface and break the "this is what THIS proposal had to work with" mental model. The new panel scopes to one template; the swap-template card scopes to two.
- **2026-06-04 — D-5: `config_diff` drift keys (declared on proposal but no longer in `declared_params`) silently surface under `tunedChanged`.** Locked because the proposal's own data is authoritative for what was actually tuned at the time the proposal was created. Surfacing the drift with a warning would require introducing a new visual treatment for a rare condition; silent surfacing keeps the renderer simple and the operator's view truthful. AC-6 locks the test.
- **2026-06-04 — D-6: Promote `extractFromTo` from `config-diff-panel.tsx` to `ui/src/lib/config-diff.ts` in this PR (not a follow-up).** Locked because deferring the promotion would temptingly let the implementation duplicate the helper into the new panel — exactly the drift risk anti-pattern #1 warns against. Doing it in-PR (FR-5) costs ~10 LOC of additional diff and yields a unit-testable shared utility.
- **2026-06-04 — D-7: No loading skeleton; panel appears once `parentTemplate.data` resolves.** Locked because the loading window is short (~50-200ms), an animated placeholder would flash once and disappear, and the same posture is already established by `<SwapTemplateCard>`'s per-card template fetches.
- **2026-06-04 — D-8: Cap 2 (param-name hover linking between this panel and the follow-up cards) and Cap 3 (mount on study detail page) are deferred — explicitly NOT phases, NOT idea files.** Locked because neither survives the pre-defer diagnostic (CLAUDE.md "Pre-defer diagnostic"): both are surface enhancements that compound value only after the headline three-state lens proves out with operator usage. Capture as `phaseN_idea.md` only if operator pull surfaces.
- **2026-06-04 — D-9 (cycle-1 F1, accepted): Partition universe is `declaredParams ∪ configDiff`; `searchSpace`-only drift keys are silently dropped.** Locked because (a) the operator's mental model "this proposal's template" is anchored on `declared_params`, (b) `searchSpace` keys not in `declared_params` cannot be sensibly typed (no type-tag to display), and (c) the case is rare (it requires a template edit to remove a param between study creation and proposal review — and the study itself would have failed validation if `search_space` referenced an undeclared param at create time, so the drift requires a post-create template mutation). The pure helper documents and tests this; an explicit drift-key case is in FR-1.
- **2026-06-04 — D-10 (cycle-1 F5, accepted minimally): A `config_diff` entry with `from === to` classifies as `tunedChanged` per the spec's operational definition "appears in `config_diff` ⇒ tuned by this proposal."** Locked because (a) `<ConfigDiffPanel>` already renders every `config_diff` entry regardless of value comparison (lines 98–107 of `config-diff-panel.tsx`), and the new panel maintains visual fidelity with it; (b) the spec relabels the group "Tuned (changed by this proposal)" to make the membership definition explicit rather than implying value comparison; (c) for canonical digest-worker output, the `from === to` case is rare because `recommended_config` typically only contains values different from the baseline. Adding a value-comparison filter would either desync the two panels (operator sees the same key in two visual groups) or change `<ConfigDiffPanel>` semantics (out of scope). FR-1 test #7 locks the contract.
- **2026-06-04 — D-11 (cycle-1 F8, rejected): The lifted `useTemplate(proposal.template.id)` does NOT risk regressing `<SuggestedFollowupsPanel>` rendering for previously-disabled cases.** Rejected with counter-evidence: `<SuggestedFollowupsPanel>` only consumes `parentTemplate` inside `<SwapTemplateCard>` (per `SHOWS_DECLARED_PARAMS_DIFF` lookup at [`suggested-followups-panel.tsx:90-95`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L90-L95) and the per-kind branch at [lines 119-130](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L119-L130)). For narrow/widen/text cards (and for empty digests / no digest at all), the `parentTemplate` prop is structurally ignored — passing a now-populated value where the prop is unused is a no-op. The lifted fetch covers the same swap-template case as before (no behavior change there) plus three new cases that are structurally indifferent to the prop. No regression risk; no additional swap-target test needed.
- **2026-06-04 — D-12 (cycle-3 F2, accepted): Three-arrays-with-group-identity, NOT discriminated-union rows.** Locked because the helper's natural shape `{tunedChanged, tunedUnchanged, untuned}` is three separate arrays — adding a redundant `state` field to every row would duplicate information already encoded by the containing array. The group identity drives `data-testid` markers (`param-space-group-${group}` / `param-space-row-${group}-${name}`) and the exhaustive group-rendering switch with a `never`-typed default branch — that's where compile-time exhaustiveness lives, not on the rows themselves. The earlier §8.4 wording implied `ParamRow.state` and was corrected in this cycle.
- **2026-06-04 — D-13 (cycle-3 F1, accepted — high-severity correctness fix): Lift BOTH `useTemplate(...)` AND `useStudy(...)` gates, not just `useTemplate`.** Locked because the cycle-1/2 FR-3 only changed `useTemplate(...)`'s input, but `useStudy(...)` was independently gated on `parentStudyId !== null && hasActionableFollowup`. Study proposals with text-only or empty digests would mount the panel with `parentStudy.data === undefined`, `searchSpaceParams === undefined`, and **every search-space-but-not-`config_diff` param mis-classifying as `untuned`** instead of `tunedUnchanged`. Dropping `hasActionableFollowup` from the `useStudy` gate restores correct classification. Cost: one additional `GET /api/v1/studies/{id}` for the previously-disabled cases — sub-ms PK fetch.
- **2026-06-04 — D-14 (cycle-3 F6, accepted): No `phase*_idea.md` artifacts for Cap 2 / Cap 3 deferrals.** Locked because both capabilities are surface enhancements whose value emerges only after operator usage of the headline three-state lens. Capturing them as idea files now would create defer-and-never-fix artifacts (the failure mode CLAUDE.md's "tangential discoveries" rule warns against — most deferred-idea files become invisible debt). If operator feedback explicitly requests either capability, a fresh idea file can be authored then; capturing speculatively now is the wrong default. This supersedes the earlier §3 Out of scope wording that mentioned `phase2_idea.md` capture.
