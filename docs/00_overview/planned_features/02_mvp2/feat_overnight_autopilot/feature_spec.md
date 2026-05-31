# Feature Specification — Overnight autopilot (surface the autonomous study chain)

**Date:** 2026-05-31
**Status:** Draft
**Owners:** Product: TBD · Engineering: TBD
**Related docs:**
- [`idea.md`](idea.md)
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)
- Shipped sibling: [`feat_auto_followup_studies`](../../../implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) (the chaining engine this feature surfaces)
- Shipped sibling: [`feat_study_sub_warmup_guard`](../../../implemented_features/2026_05_29_feat_study_sub_warmup_guard/feature_spec.md) (the warm-up floor; same "overnight ergonomics" theme)
- Idea-stage sibling: [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) (queued for the same study-detail panel area)

---

## 1) Purpose

- **Problem:** the autonomous-chaining capability (`auto_followup_depth`) is fully implemented, gated, idempotent, and budget-aware — but it is hidden behind a wizard control labeled "Auto-followup chain" with no trust framing, and the post-run surface is a minimal panel that shows the parent link + remaining depth + a children table with no cumulative lift, no stop reason, and no "best-of-chain" pointer. The live database shows zero studies have ever used the feature.
- **Outcome:** an operator can (a) discover the overnight path while creating a study because the wizard control is reframed as a labeled "🌙 Run overnight (compound automatically)" toggle with explicit copy about the human-merge boundary, and (b) wake up to a single chain-summary panel on the study detail page that rolls the chain into "what ran, what's the cumulative lift, which link won, here is the proposal to ship" — reviewable in minutes, one click from a PR.
- **Non-goal:** **no change to the chaining engine itself.** The narrowing primitive, lift gate, budget gate, cancel cascade, depth decrement, idempotency layers, and telemetry events ship unchanged. This feature is read-side aggregation + UI relabeling + tutorial copy. **No new notification path** (chain-complete webhook stays out-of-scope per idea Q3 default).

## 2) Current state audit

### Existing implementations

| Component | Path | Behavior |
|---|---|---|
| Wizard depth selector | [`ui/src/components/studies/create-study-modal.tsx:1420-1451`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1420-L1451) | Step-5 `<Select>` labeled **"Auto-followup chain"** with options `Off / 1 follow-up / 2 follow-ups / 3 follow-ups / 4 follow-ups / 5 follow-ups`. Wizard-0 maps to `undefined` (sentinel); wire values 1..5 map to `config.auto_followup_depth`. Helper text: "Run additional studies overnight, each narrowing around the previous winner. Halts on no lift, exhausted budget, or failed parent." Reuses `auto_followup_depth` glossary key. |
| Chain panel (existing) | [`ui/src/components/studies/auto-followup-chain-panel.tsx`](../../../../../ui/src/components/studies/auto-followup-chain-panel.tsx) | Mounted at [`ui/src/app/studies/[id]/page.tsx:109`](../../../../../ui/src/app/studies/[id]/page.tsx#L109). Renders parent-study link (when `parent_study_id` is set) + remaining-depth indicator + direct-children table (`name`, `status`, `best_metric`). Hidden when `!hasParent && !hasDepth && !hasChildren`. Reuses `auto_followup_chain` glossary key for the card title tooltip. |
| Children endpoint | [`backend/app/api/v1/studies.py:630-659`](../../../../../backend/app/api/v1/studies.py#L630-L659) | `GET /api/v1/studies/{study_id}/children` returns `StudyListResponse` of direct children only (D-13 from the chaining-engine spec). Empty list, not 404, for childless rows. |
| Children repo | [`backend/app/db/repo/study.py:182-208`](../../../../../backend/app/db/repo/study.py#L182-L208) | `list_children_of_study(db, parent_study_id)` filters by `Study.parent_study_id == parent_study_id`, ordered by `created_at ASC, id ASC`. No `deleted_at` filter (Study has no soft-delete in MVP1). |
| Chaining engine | [`backend/workers/auto_followup.py`](../../../../../backend/workers/auto_followup.py) + [`backend/app/domain/study/auto_followup.py`](../../../../../backend/app/domain/study/auto_followup.py) | `enqueue_followup_study` evaluates the chain gate, runs the budget peek, narrows the search space ±50% around the winner, creates the child row, enqueues `start_study`. Decision matrix in `evaluate_chain_gate`: SKIP_PARENT_FAILED → SKIP_DEPTH_EXHAUSTED (depth missing OR depth==0) → SKIP_NO_LIFT (best_metric None OR lift ≤ epsilon) → ENQUEUE. Direction-aware lift since `feat_study_baseline_trial` FR-5. |
| Schema validator | [`backend/app/api/v1/schemas.py:690-723`](../../../../../backend/app/api/v1/schemas.py#L690-L723) | `StudyConfigSpec.auto_followup_depth: int \| None` (default `None`), `_validate_auto_followup_depth` checks `0 ≤ depth ≤ 5`, raises `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE:` prefix that `api/errors.py` unwraps to the canonical envelope (`error_code: AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`, 422). |
| Cancel cascade | [`backend/app/services/study_state.py:250-347`](../../../../../backend/app/services/study_state.py#L250-L347) | `cancel_study_with_chain_cascade` (called by `POST /studies/{id}/cancel?cascade=true`, default) walks descendants and cancels in-flight chain children. Emits `auto_followup_cancelled_with_parent` per descendant (log-only). |
| Telemetry events | `backend/workers/auto_followup.py` lines 14-22 | Eight `event_type` log lines — `auto_followup_enqueued`, `auto_followup_skipped_no_lift`, `auto_followup_skipped_parent_failed`, `auto_followup_skipped_parent_missing`, `auto_followup_skipped_budget`, `auto_followup_depth_exhausted`, `auto_followup_enqueued_duplicate_dropped`, `auto_followup_cancelled_with_parent`. **Log-only** — no `audit_log` table exists in MVP2; events are not queryable from the API. Stop reason for the chain summary must be derived from DB state, not from these events. |
| Glossary keys (reusable) | [`ui/src/lib/glossary.ts:866-899`](../../../../../ui/src/lib/glossary.ts#L866-L899) | `auto_followup_depth`, `auto_followup_chain`, `lift_gate`, `auto_followup_budget_skip` — all four ship with `short` text matching the chain semantics this feature surfaces. |
| Stop-condition presets | [`ui/src/components/studies/create-study-modal.tsx:95-114`](../../../../../ui/src/components/studies/create-study-modal.tsx#L95-L114) | Four wire values: `focused` (`max_trials=50`), `standard` (`max_trials=200`), `deep` (`max_trials=1000, time_budget_min=480`), `custom`. **No "Thorough (overnight)" preset exists** — `Deep (1000 + 8h cap)` is the closest analog; the idea's reference to a "Thorough (overnight)" preset is a leftover from an earlier draft and must be corrected to `Deep (1000)` everywhere it appears. |

### Navigation and link impact

No URL changes. The chain panel stays at `/studies/{id}` between the existing `LinkedEntitiesRow` and `AutoFollowupChainPanel` mount site; the wizard relabeling does not move any control.

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (none) | (none) |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`](../../../../../ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx) | Renders parent link + depth + children table | ~4 cases | Extend to cover new fields (cumulative-lift line, stop-reason line, best-of-chain link). The existing "hide when no chain context" case still passes — the new fields are surfaced only when the new `/chain` endpoint returns non-empty data. |
| `ui/src/__tests__/components/studies/create-study-modal.*` (if a wizard test exercises the depth selector label / helper text exactly) | Label string `"Auto-followup chain"` | TBD — `grep` at impl time | Update to the new label `"🌙 Run overnight (compound automatically)"` once the relabel lands. Wire values (`undefined`, `1..5`) do not change, so any submit-payload assertions stay green. |
| `backend/tests/contract/test_studies_*.py` | Existing `/children` contract tests | TBD | No change — this feature adds a NEW `/chain` endpoint; the existing `/children` contract is unchanged. |

### Existing behaviors affected by scope change

- **Wizard control labeling.** Current: `<Label>` reads "Auto-followup chain" with helper text "Run additional studies overnight…". New: `<Label>` reads "🌙 Run overnight (compound automatically)" with helper text rewritten to make the human-merge boundary explicit (see FR-1). Decision needed: no (idea preflight locked the copy; final wording in FR-1).
- **Chain panel content.** Current: shows parent link + remaining-depth + direct-children table only. New: same three when the local study is mid-chain, PLUS — when the local study is the chain's anchor (`parent_study_id IS NULL` AND at least one descendant exists) OR is itself a descendant — a rolled-up chain summary (ordered list, cumulative lift, best-of-chain config, stop reason, proposal link). Decision needed: no (idea preflight locked the canonical surface as the study-detail panel).
- **"Ran while away" card on `/studies` list.** Stretch capability per idea Q1 default. Decision needed: yes — but the recommended default in the idea is "defer to a follow-on idea unless story-shaped work allows it." This spec defers it to a Phase 2 `phase2_idea.md` (see §3 Phase boundaries) so MVP2 ships the trust-restoring panel without the discoverability magic.

---

## 3) Scope

### In scope (Phase 1 — the only phase shipped under this spec)

- **FR-1**: Relabel the wizard's `auto_followup_depth` control with the canonical "🌙 Run overnight (compound automatically)" framing + the human-merge boundary copy.
- **FR-2**: Add a non-coupling hint inline beneath the `Deep (1000)` preset selector that nudges the operator toward enabling the chain when `Deep` is selected and `auto_followup_depth` is still unset.
- **FR-3**: Add `GET /api/v1/studies/{study_id}/chain` — a new dedicated endpoint that walks the chain (parent + all descendants reachable through `parent_study_id`) and rolls up `links[]`, `cumulative_lift`, `best_link_id`, `best_metric`, `stop_reason`, `proposal_id_for_best_link`.
- **FR-4**: Extend the existing `AutoFollowupChainPanel` to render the rolled-up summary when the new `/chain` endpoint returns a non-empty chain — adding cumulative-lift, stop-reason, best-of-chain link, and a one-click path to the proposal that carries the best config.
- **FR-5**: Add a tutorial section ("Run the loop overnight") to [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) covering the canonical path: pick `Deep (1000)` → enable overnight compounding depth 3 → start before logging off → review the chain summary in the morning → open the winning PR. Tutorial must name the human-merge boundary explicitly.
- **FR-6**: New glossary key `overnight_autopilot` for the wizard control's `InfoTooltip` (replaces the reused `auto_followup_depth` key in the new wizard placement; the old key stays available for the in-chain remaining-depth tooltip).

### Out of scope

- Any change to `enqueue_followup_study`, `evaluate_chain_gate`, the budget gate, the narrowing primitive, the depth decrement, or the cancel cascade.
- Any change to `auto_followup_depth` validation bounds (`0..5` per `_validate_auto_followup_depth`).
- New telemetry events. The existing 8 log events are sufficient — stop reason on the new `/chain` endpoint is derived from study state, not from event lookups.
- Chain-complete webhook (idea Q3 default — defer to the existing "outgoing webhooks for resource lifecycle events" backlog item).
- `/studies` list "ran while away" card (idea Q1 default — `phase2_idea.md`).
- Auto-coupling of `Deep (1000)` and `auto_followup_depth` (idea Q2 default — keep independent; FR-2 is a hint, not a coupling).
- Any change to the cascade cancellation contract (`?cascade=true|false`, `INVALID_CASCADE_PARAM`).
- Any migration. The `/chain` endpoint reads existing `parent_study_id` links + existing `studies.config.auto_followup_depth` + existing `best_metric` / `best_trial_id` / `status` / `failed_reason` columns.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` — confirmed by inspection of [`backend/app/api/v1/studies.py:199-723`](../../../../../backend/app/api/v1/studies.py#L199-L723). All study endpoints use that prefix.
- **Router for this feature's endpoint:** [`backend/app/api/v1/studies.py`](../../../../../backend/app/api/v1/studies.py).
- **HTTP methods:** `GET` for the new read-only chain endpoint.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — confirmed against `_err` helper at [`studies.py:80-84`](../../../../../backend/app/api/v1/studies.py#L80-L84) and against [`docs/01_architecture/api-conventions.md` §"Error envelope"](../../../../01_architecture/api-conventions.md).
- **Auth error shape:** N/A. MVP1–MVP3 ship no auth surface.

### Phase boundaries

- **Phase 1 (this spec, MVP2):** FR-1 through FR-6 — the wizard relabel + the `/chain` aggregation endpoint + the chain-panel extension + the tutorial. Ships the trust-restoring chain-summary surface.
- **Phase 2 (deferred to [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md)):** the `/studies` list "ran while away" card that calls out chain-complete studies the operator hasn't visited yet. Rationale for deferral: requires a "last visited at" persistence model (no existing column) or a transient `unread_at` cookie; carries product/UX surface area (visited-state model, dismissal, badge counts) that's a separate scoped decision. Phase 1 ships the panel that makes the chain reviewable; Phase 2 makes it discoverable from the index page.

---

## 4) Product principles and constraints

- The chaining engine is shipped, tested, and trusted — this feature MUST NOT modify it. All FR-* changes are additive on the read side or are pure relabeling on the write side.
- The chain-summary endpoint MUST reflect the human-merge boundary in its response shape — `proposal_id_for_best_link` is `null` when no proposal exists yet; the UI surfaces "Awaiting review" rather than a fake CTA.
- Tooltip copy for the wizard control MUST source from the glossary, per the "Enumerated Value Contract Discipline" pattern: every tooltip cites either an existing key or names a new key to be added in a specific story (FR-6).
- Stop reason MUST be derived from DB state, not from log events — events are not queryable and the audit_log table doesn't exist until MVP3.
- Cumulative lift MUST be defined as direction-normalized `best_of_completed.best_metric − anchor.baseline_metric` (preferred), falling back to `best_of_completed.best_metric − first_decile_max(anchor)` ONLY when `anchor.baseline_metric IS NULL`. Never use `anchor.best_metric` as the comparison baseline. Per-link `delta_from_prev` is the link's `best_metric` minus the prior link's `best_metric` (direction-normalized for `minimize`).
- The `Deep (1000)` hint (FR-2) MUST NOT auto-toggle `auto_followup_depth`; it is a textual nudge only (idea Q2 locked default — preserves operator agency).

### Anti-patterns

- **Do not** modify `enqueue_followup_study` or `evaluate_chain_gate` to persist stop reasons in a new column — derive from existing state (`status`, `failed_reason`, `best_metric`, `auto_followup_depth` remaining, child rows present). New persistence breaks the "no migration" scope guarantee and reopens a shipped feature's surface.
- **Do not** couple `Deep (1000)` preset selection with `auto_followup_depth`. The idea preflight locked the recommendation as a hint, not a coupling — invisible magic erodes operator trust the feature is trying to build.
- **Do not** add a chain-complete webhook in this feature. Roll into the broader outgoing-webhooks backlog idea.
- **Do not** rename or repurpose the existing `/studies/{id}/children` endpoint. The new `/chain` endpoint is additive; `/children` retains its single-hop semantics per D-13 of the chaining-engine spec.
- **Do not** invent a new tooltip glossary key without listing it in §11's tooltip inventory with the story that adds it. The Story 2.13 lint guard (`form-select-discipline.test.tsx`, `data-table-column-discipline.test.tsx`) enforces glossary citation for `<DataTable>` columns; the new `overnight_autopilot` key MUST land in `ui/src/lib/glossary.ts` in the same PR.
- **Do not** wire the chain endpoint unconditionally into the existing `useStudy` 3-second poll. Refetch contract for the chain panel is defined under FR-4 (post-cancel, on window-focus, plus a modest chain-poll while `stop_reason === 'in_flight'`).
- **Do not** broaden scope to support chain fan-out (a parent with multiple direct children). The shipped chaining engine enforces single-child per parent (per `feat_auto_followup_studies` D-13 + the layer-2 idempotency backstop at [`backend/workers/auto_followup.py:91-99`](../../../../../backend/workers/auto_followup.py#L91-L99)); this spec carries the same linear-chain invariant. If a future feature relaxes the single-child rule, the response shape will need `parent_study_id` per link, branch-level stop reasons, and pagination — all out of scope here.

## 5) Assumptions and dependencies

| Dependency | Why required | Status | Risk if missing |
|---|---|---|---|
| `feat_auto_followup_studies` (chaining engine) | This entire feature is a read-side surfacing layer on top of it. | Implemented (PR #223, 2026-05-24) | N/A — already shipped. |
| `feat_study_baseline_trial` (`baseline_metric` column) | Cumulative-lift computation prefers the anchor's `baseline_metric` over the first-decile fallback. | Implemented (2026-05-25) | N/A — already shipped. Spec gracefully degrades to first-decile fallback (per `evaluate_chain_gate` FR-2a) when `baseline_metric IS NULL`. |
| `feat_study_sub_warmup_guard` (sub-warmup threshold) | Tutorial copy cross-references the `STUDIES_TPE_WARMUP_FLOOR = 50` so the recommended "depth 3 + Deep preset" path is internally consistent (Deep is 1000 trials, well over 50). | Implemented (PR #316, 2026-05-29) | N/A — already shipped. |
| `feat_study_convergence_indicator` (idea-stage sibling) | Will land alongside this on the same study-detail panel area. Coordination flag: the convergence indicator may add a per-link convergence verdict to the chain summary later; this spec leaves the response shape extensible (new fields under `links[]` are non-breaking additions). | Idea-stage — queued behind this feature in the same `/pipeline` batch. | Low — the sibling can extend `links[]` items without breaking this contract. |
| `feat_ubi_judgments` | Tutorial section references that overnight compounding against a fresh UBI judgment list is meaningfully more valuable than against a static LLM snapshot. | Implemented (PR #317, 2026-05-29) | N/A — already shipped. |

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (operator) creating studies through the wizard and reviewing chain results the next morning.
- **Role model:** N/A — RelyLoop MVP1–MVP3 is single-tenant, no auth surface (per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** N/A — no auth.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP3 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md). This feature ships no new state mutations: FR-1 + FR-2 are UI text changes, FR-3 is a read-only GET endpoint, FR-4 is UI rendering, FR-5 is docs. The chaining engine itself (which IS state-mutating) is out of scope and already shipped — its audit-event obligations are tracked under `feat_auto_followup_studies` (currently also N/A pre-MVP3).

## 7) Functional requirements

### FR-1: Reframe the wizard `auto_followup_depth` control as "🌙 Run overnight (compound automatically)"

- **Requirement:**
  - The system **MUST** replace the wizard Step-5 `<Label>` text from `"Auto-followup chain"` to the exact string `"🌙 Run overnight (compound automatically)"` (leading moon emoji + ASCII space + remainder) at [`ui/src/components/studies/create-study-modal.tsx:1422`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1422).
  - The system **MUST** replace the helper-text paragraph beneath the selector with: *"When this study finishes, automatically start a follow-up that narrows in on the best result, then repeat. Stops on its own when it stops improving, hits the daily budget, or runs out of depth. No production changes happen without your review — you still open every PR by hand."*
  - The system **MUST** replace the `InfoTooltip glossaryKey` from `auto_followup_depth` to a new key `overnight_autopilot` (added by FR-6). The old `auto_followup_depth` key stays in the glossary and is reused by the chain panel's remaining-depth indicator.
  - The system **MUST NOT** change the underlying wire contract — the `Select` still emits `undefined` for "Off" and `1..5` for the depth values; `config.auto_followup_depth` validation at the API stays untouched.
  - The system **MAY** retain the `data-testid="cs-auto-followup"` attribute for backward-compatible E2E selectors (existing wizard tests can keep referencing it).
- **Notes:** Copy locked by idea preflight (idea.md §"First-class '🌙 Run overnight (compound automatically)' toggle in the create-study wizard"). The "still open every PR by hand" half-sentence is the canonical human-merge framing; tutorial copy (FR-5) and the chain-panel header copy (FR-4) MUST be consistent with it. **The exact label string `🌙 Run overnight (compound automatically)` (including the leading moon emoji + the space) is the contract** — all assertions, glossary references, tutorial citations, hint copy, and tests MUST quote it verbatim.

### FR-2: Inline hint coupling `Deep (1000)` preset selection with the overnight toggle (text only — no auto-set)

- **Requirement:**
  - The system **MUST** render an inline hint immediately beneath the preset selector (above the numeric inputs grid) when *both* conditions hold: (a) the currently-selected preset is `deep` AND (b) `auto_followup_depth` is `undefined` or `0`. Suggested copy: *"💡 Tip — this is a long study. Enable '🌙 Run overnight (compound automatically)' below to chain follow-up runs while you're away."*
  - The system **MUST NOT** auto-set `auto_followup_depth` when the preset changes (idea Q2 locked default — keep independent).
  - The system **MUST** hide the hint as soon as `auto_followup_depth ≥ 1` is selected (the trigger condition no longer holds).
  - The system **SHOULD** render the hint with a `data-testid="cs-overnight-hint"` so it can be asserted by the wizard test suite.
- **Notes:** The hint lives in the same step (Step 5 — "Objective + config") as both the preset selector and the overnight toggle, so there is no scroll latency between seeing the hint and acting on it.

### FR-3: `GET /api/v1/studies/{study_id}/chain` — rolled-up chain summary

- **Requirement:**
  - The system **MUST** expose `GET /api/v1/studies/{study_id}/chain` returning the response shape defined in §8.
  - The system **MUST** resolve the chain's *anchor* (the ancestor with `parent_study_id IS NULL` reachable by walking `parent_study_id` from the requested study), then enumerate every descendant of that anchor (the full chain, regardless of which member the operator landed on). The returned `links[]` array is `[anchor, ...descendants_ordered_by_created_at_asc]`.
  - The system **MUST** populate each `links[]` entry with `id`, `name`, `status`, `best_metric`, `baseline_metric`, `direction` (from `objective.direction`, defaulting to `"maximize"`), `delta_from_prev` (`null` for the anchor, otherwise `best_metric - prev.best_metric` sign-flipped under `minimize`; **also `null` when either this link's or the prior link's `best_metric` is `null`** — i.e., when either side is still in-flight or failed without a best). `proposal_id` is selected per the deterministic rule in §9 ("Proposal selection per link MUST be deterministic"): most-recent non-rejected proposal whose `study_id == this_link.id`, or `null` if no proposal exists.
  - The system **MUST** compute `cumulative_lift` and the top-level `best_*` fields from the **completed-link subset** only (`status = 'completed'` AND `best_metric IS NOT NULL`). In-flight, queued, failed, and cancelled links never count toward `best_link_id` regardless of their `best_metric` value — the human-merge framing only makes sense for terminal-with-a-result links. Compute `cumulative_lift` consistently across the chain length, including the single-link case: `best_of_completed.best_metric - anchor.baseline_metric` when the anchor has `baseline_metric IS NOT NULL`; otherwise `best_of_completed.best_metric - first_decile_max(anchor)` (mirroring `evaluate_chain_gate`'s FR-2a fallback at [`backend/app/domain/study/auto_followup.py:77-114`](../../../../../backend/app/domain/study/auto_followup.py#L77-L114)). Sign-flipped for `minimize`. `null` when the completed subset is empty OR when both `anchor.baseline_metric` is `null` AND `first_decile_max(anchor)` is `null`.
  - The system **MUST** compute `best_link_id` as `argmax(best_metric)` over the completed-link subset when direction is `maximize` (`argmin` when `minimize`), tie-breaking by `created_at ASC`. `null` when the completed subset is empty.
  - The system **MUST** compute `stop_reason` by reusing the same direction-aware lift-and-baseline semantics as `evaluate_chain_gate` (not a copy of its branching, but the same input fields and epsilon). Mapping into one of `{depth_exhausted, no_lift, budget, parent_failed, cancelled, in_flight}`. Decision matrix in §9 "State transitions."
  - The system **MUST** return `404 STUDY_NOT_FOUND` (matching the existing `_err(404, "STUDY_NOT_FOUND", …)` pattern) when `study_id` does not exist.
  - The system **MUST** return `200 OK` with a single-link payload (anchor only) for a study that has no parent and no children — this is the trivial "non-chained study" case, so the panel can degrade gracefully when an operator visits a regular study. The universal formulas from the prior bullets still apply: `cumulative_lift` is computed by the same `best_of_completed - anchor_baseline` rule (may be non-zero for a completed study where best_metric > baseline_metric), `stop_reason` is computed by §9 conditions 1-8 against the single link, `best_link_id` reflects the anchor when completed-with-metric or `null` when not.
  - The endpoint **MUST NOT** be paginated. Maximum chain length is bounded by depth 5 (per `_validate_auto_followup_depth` upper bound) plus the anchor = 6 links worst case; well under any reasonable page size.
  - The endpoint **MUST NOT** require any query parameters. It is a pure id-keyed read.
- **Notes:** New repo function `get_chain_for_study(db, study_id)` lives in [`backend/app/db/repo/study.py`](../../../../../backend/app/db/repo/study.py); algorithm enforces the linear-chain invariant explicitly:
    1. **Upward walk** from `study_id` via `parent_study_id` with a visited set, capped at 10 hops. Stop when `parent_study_id IS NULL` (anchor found) OR when the cap is hit (degrade: treat the cap-stop point as the anchor; log WARN).
    2. **Downward walk** from the anchor — iteratively (NOT a fan-out recursive CTE): start with `current_id = anchor_id`, then at each step `SELECT id, created_at FROM studies WHERE parent_study_id = :current_id ORDER BY created_at ASC, id ASC LIMIT 1`. Continue while a child exists AND traversal depth < 5 descendants (i.e., max 6 total rows including the anchor). Log a WARN if `LIMIT 1` truncated additional siblings (linear-chain invariant violated in the data).
    3. Issue a single `SELECT * FROM studies WHERE id IN (:link_ids)` after the id walk to hydrate all columns; reorder client-side `created_at ASC, id ASC`.
    4. Proposal lookup (D-11): `SELECT DISTINCT ON (study_id) id, study_id FROM proposals WHERE study_id = ANY(:link_ids) AND status != 'rejected' ORDER BY study_id, created_at DESC, id DESC`. Rejected proposals are EXCLUDED at the WHERE clause — when a link's proposals are all rejected, the `DISTINCT ON` returns no row for that link and `proposal_id` is `null` in the response.

  Total query budget: 1 to 6 upward `SELECT … WHERE id = :parent_id` calls (PK-indexed) + up to 5 downward `SELECT … WHERE parent_study_id = :current_id LIMIT 1` calls (seq-scan today — see §13) + 1 hydration `SELECT … WHERE id IN (…)` + 1 proposals `SELECT DISTINCT ON` + at most 1 anchor-trials lookup (only when `anchor.baseline_metric IS NULL`) = ≤ 14 queries worst case. p99 < 200ms (§13) holds at MVP2 row-counts.

  New domain helper in [`backend/app/domain/study/`](../../../../../backend/app/domain/study/) (filename `chain_summary.py`) computes the aggregated fields (`derive_chain_stop_reason`, `compute_cumulative_lift`, `select_best_link`) from a list[Study] + dict[study_id → Proposal | None]; pure functions, no I/O.

### FR-4: Extend `AutoFollowupChainPanel` with the rolled-up chain summary

- **Requirement:**
  - The system **MUST** call `GET /api/v1/studies/{study_id}/chain` from the panel (new TanStack Query hook `useStudyChain(studyId)`). The summary lines (header, ordered link list, cumulative-lift, best-config, stop-reason) MUST render whenever the operator opted into chaining — concretely when **any** of: `links.length >= 2` (a real multi-link chain) OR `hasParent` (the local study is a descendant) OR `chain.links[0].auto_followup_depth_remaining != null` (the anchor explicitly enabled chaining, even if no child has spawned yet). The "hide when no chain context" rule still applies for ordinary single-link studies that opted out: panel returns `null` when `!hasParent && !hasDepth && !hasChildren && chain.links[0].auto_followup_depth_remaining == null`.
  - The system **MUST** render, in order: (a) chain header *"Overnight chain — {N} studies"*, (b) the ordered link list with each link's name, status, best-metric, and `delta_from_prev` formatted as `±0.0123` (4 decimals), (c) a `Cumulative lift` row, (d) a `Best config` row whose branch behavior is defined in the next bullet, (e) a `Stop reason` row mapping the wire value to a short human phrase: `depth_exhausted → "depth budget exhausted"`, `no_lift → "no further improvement"`, `budget → "daily LLM budget reached"`, `parent_failed → "parent study failed or was cancelled"`, `cancelled → "operator cancelled the chain"`, `in_flight → "chain still running"`.
  - The system **MUST** preserve the existing parent-study link + remaining-depth + direct-children-table display when the local study is mid-chain — those three rows already work for navigating one hop at a time and the test coverage (`auto-followup-chain-panel.test.tsx`) is anchored to them.
  - The system **MUST** preserve the existing test cases for the "hide when no chain context" rule (the `null` return path captured in the previous bullet). The existing test at [`auto-followup-chain-panel.test.tsx:81-83`](../../../../../ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx#L81-L83) continues to pass unchanged.
  - The system **MUST** branch the `Best config` row deterministically: **when `proposal_id_for_best_link` is non-null**, render a single `<Link>` to `/proposals/{proposal_id_for_best_link}` whose text is the best link's study name; **when `proposal_id_for_best_link` is null AND `best_link_id` is non-null**, render plain text `Best config: <best_link_name> (Awaiting proposal)` with NO link (no `/studies/{id}` link either) so the human-merge boundary is never elided into a fake CTA; **when `best_link_id` is null** (completed subset empty), render plain text `Best config: —`.
  - The system **SHOULD** add a `data-testid="chain-summary"` on the summary container so the E2E suite (FR-7 of the test strategy) can assert on it.
- **Notes:** Uses existing primitives (`Card`, `Link`, `InfoTooltip`). The `useStudyChain` hook's refetch contract is locked by D-10 (§19): default refetch-on-window-focus + post-cancel invalidation + viewed-study-status-transition invalidation + a 15s chain-specific `refetchInterval` while the previous response carries `in_flight` OR while a bounded grace condition holds for `no_lift` / `budget` (`tail.completed_at` < 120 seconds old). Stops on `{depth_exhausted, parent_failed, cancelled}` or after the grace window expires. Does NOT join the existing 3s study-detail poll.

### FR-5: Tutorial section "Run the loop overnight"

- **Requirement:**
  - The system **MUST** add a new H2 section to [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) titled `## Step 12 — Run the loop overnight` placed after the existing `## Step 11 — (Optional) Upgrade your judgment list to UBI` and before `## Where to next`.
  - The section **MUST** walk through: (1) pick the `Deep (1000)` budget preset, (2) enable `🌙 Run overnight (compound automatically)` at depth 3, (3) start before logging off, (4) review the chain-summary panel in the morning, (5) open the winning proposal's PR.
  - The section **MUST** explicitly state the human-merge boundary in plain language: *"RelyLoop runs the exploration overnight unattended, but it never opens a PR on your behalf. The chain ends with a proposal you review and merge — your one decision."*
  - The section **MUST** name the cancel cascade affordance (`POST /studies/{id}/cancel?cascade=true` is the default — cancelling any mid-chain study halts pending children).
- **Notes:** Copy locked by idea preflight (§"Tutorial + docs: name the autopilot path").

### FR-6: Add the `overnight_autopilot` glossary key

- **Requirement:**
  - The system **MUST** add `overnight_autopilot` to [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) under the existing `feat_auto_followup_studies Story 3.1 — chain-panel + wizard entries` section.
  - The new entry **MUST** include `short` (≤ 120 chars) suitable for `InfoTooltip` and `long` (paragraph form) suitable for `HelpPopover`, mirroring the existing `auto_followup_chain` entry's shape.
  - Suggested `short`: *"Run additional studies overnight, each narrowing in on the previous winner. Stops on its own; you still open every PR."*
  - Suggested `long`: paragraph form covering the three trust pillars from FR-1: "what it does," "when it stops," and "you still open every PR."
- **Notes:** Required because the wizard control's framing changes meaning enough that reusing the existing `auto_followup_depth` key (whose `short` reads "Run up to N follow-up studies after this one completes…") would underplay the trust-restoring frame. The old key stays in place for the chain panel's remaining-depth row.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}/chain` | Return the rolled-up chain summary anchored at the chain's root ancestor. | `404 STUDY_NOT_FOUND` |

No other endpoints are added or modified.

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code`.
- Status codes **MUST** be deterministic per scenario.
- The endpoint is unpaginated (bounded chain depth ≤ 6 links).
- The endpoint **MUST NOT** carry a `Cache-Control` header beyond the project default — chains can update at any moment a study transitions to terminal, so server-side caching is not appropriate.

### 8.3 Response schema

**Top-level response (Pydantic model `StudyChainResponse`):**

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `anchor_study_id` | `str` (UUIDv7) | no | id of the anchor (root) study |
| `best_link_id` | `str` (UUIDv7) | yes | from completed-link subset; null when subset empty |
| `best_metric` | `float` | yes | best_metric of `best_link_id` (mirrors that link's value) |
| `cumulative_lift` | `float` | yes | universal formula per FR-3; null when no comparison baseline derivable |
| `direction` | `Literal["maximize","minimize"]` | no | from anchor.objective.direction (default `"maximize"`) |
| `stop_reason` | `Literal["depth_exhausted","no_lift","budget","parent_failed","cancelled","in_flight"]` | no | derived per §9; no `unknown` value (D-6) |
| `proposal_id_for_best_link` | `str` (UUIDv7) | yes | proposal selected by the §9 deterministic rule; null when best_link has no proposal |
| `links` | `list[StudyChainLink]` | no | ordered `created_at ASC, id ASC`; length 1..6 under D-7 linear-chain invariant |

**Per-link entry (Pydantic model `StudyChainLink`):**

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `str` (UUIDv7) | no | studies.id |
| `name` | `str` | no | studies.name |
| `status` | `Literal["queued","running","completed","cancelled","failed"]` | no | studies.status (existing CHECK constraint values) |
| `best_metric` | `float` | yes | studies.best_metric |
| `baseline_metric` | `float` | yes | studies.baseline_metric |
| `direction` | `Literal["maximize","minimize"]` | no | from this link's objective.direction (each link can in principle have its own, though in linear chains all links inherit the anchor's) |
| `delta_from_prev` | `float` | yes | null for anchor OR when either side's best_metric is null; otherwise `this.best_metric - prev.best_metric` direction-normalized |
| `proposal_id` | `str` (UUIDv7) | yes | selected by the §9 deterministic rule against this link's proposals |
| `auto_followup_depth_remaining` | `int` | yes | studies.config.get('auto_followup_depth') — null when key absent, 0 when post-decrement leaf |
| `failed_reason` | `str` | yes | studies.failed_reason — null unless status == 'failed' |
| `created_at` | `str` (ISO-8601 UTC) | no | studies.created_at |
| `completed_at` | `str` (ISO-8601 UTC) | yes | studies.completed_at — null until terminal |

### 8.4 Response examples

Success (chained study with 3 links, best at link 2, proposal exists for the best link):

```json
{
  "anchor_study_id": "01890000-0000-7000-8000-000000000001",
  "best_link_id": "01890000-0000-7000-8000-000000000002",
  "best_metric": 0.7421,
  "cumulative_lift": 0.0834,
  "direction": "maximize",
  "stop_reason": "no_lift",
  "proposal_id_for_best_link": "01890000-0000-7000-8000-0000000000a7",
  "links": [
    {
      "id": "01890000-0000-7000-8000-000000000001",
      "name": "ecommerce-q3 v1",
      "status": "completed",
      "best_metric": 0.6587,
      "baseline_metric": 0.6587,
      "direction": "maximize",
      "delta_from_prev": null,
      "proposal_id": "01890000-0000-7000-8000-0000000000a6",
      "auto_followup_depth_remaining": 3,
      "failed_reason": null,
      "created_at": "2026-05-30T22:14:03+00:00",
      "completed_at": "2026-05-31T01:02:11+00:00"
    },
    {
      "id": "01890000-0000-7000-8000-000000000002",
      "name": "ecommerce-q3 v1 (chain depth 2)",
      "status": "completed",
      "best_metric": 0.7421,
      "baseline_metric": null,
      "direction": "maximize",
      "delta_from_prev": 0.0834,
      "proposal_id": "01890000-0000-7000-8000-0000000000a7",
      "auto_followup_depth_remaining": 2,
      "failed_reason": null,
      "created_at": "2026-05-31T01:02:18+00:00",
      "completed_at": "2026-05-31T03:48:55+00:00"
    },
    {
      "id": "01890000-0000-7000-8000-000000000003",
      "name": "ecommerce-q3 v1 (chain depth 1)",
      "status": "completed",
      "best_metric": 0.7398,
      "baseline_metric": null,
      "direction": "maximize",
      "delta_from_prev": -0.0023,
      "proposal_id": null,
      "auto_followup_depth_remaining": 1,
      "failed_reason": null,
      "created_at": "2026-05-31T03:49:02+00:00",
      "completed_at": "2026-05-31T06:31:42+00:00"
    }
  ]
}
```

Failure — unknown study:

```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 01890000-0000-7000-8000-deadbeef0000 not found",
    "retryable": false
  }
}
```

HTTP `404`. Auth error shape: N/A (no auth in MVP1–MVP3).

### 8.5 Enumerated value contracts

Two enumerated fields are introduced on the response:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `stop_reason` | `depth_exhausted`, `no_lift`, `budget`, `parent_failed`, `cancelled`, `in_flight` | New `frozenset` `CHAIN_STOP_REASONS` in `backend/app/api/v1/studies.py` (or a new `backend/app/domain/study/chain_summary.py`) co-located with the derivation logic. Cite as `// Values must match backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS` in any frontend mapping. | Chain summary panel mapping table (FR-4) at `ui/src/components/studies/auto-followup-chain-panel.tsx`. |
| `direction` | `maximize`, `minimize` | Existing — `Study.objective['direction']`, defaulting to `"maximize"` per the pattern at [`backend/app/api/v1/studies.py:165`](../../../../../backend/app/api/v1/studies.py#L165). | Chain summary metric formatter (signs the cumulative-lift display). |

Wizard control values (Off / 1 / 2 / 3 / 4 / 5) are unchanged — see existing `AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES` enumeration; no spec patch needed.

### 8.6 Error code catalog

This feature introduces no new error codes. The single new endpoint emits only the existing `STUDY_NOT_FOUND` (404).

## 9) Data model and state transitions

### New/changed entities

**No schema changes. No migration.**

The endpoint reads existing columns only:

- From `studies`: `id`, `name`, `status`, `parent_study_id`, `best_metric`, `baseline_metric`, `objective` (for `direction`), `config` (for `auto_followup_depth`), `failed_reason`, `created_at`, `completed_at`.
- From `proposals` (existing model): `id`, `study_id` (FK). The router resolves `proposal_id` per link with a single batched lookup keyed by `study_id IN (link_ids)`.
- From `trials` (only when the anchor's `baseline_metric IS NULL` and the chain summary needs the first-decile fallback): all trials of the anchor, fed through `compute_first_decile_max` (the existing pure function at [`backend/app/domain/study/auto_followup.py:77-114`](../../../../../backend/app/domain/study/auto_followup.py#L77-L114)).

### Required invariants

- The anchor of a chain is reached by walking `parent_study_id` until `parent_study_id IS NULL`. The walk MUST terminate at depth ≤ 6 (anchor + 5 descendants) because the chaining engine enforces `auto_followup_depth ≤ 5` at study creation.
- A study that is its own ancestor (cyclic `parent_study_id` graph) MUST be impossible — the chaining engine inserts child rows pointing at the parent and never updates `parent_study_id` post-insert. The endpoint MUST defensively cap the upward walk at 10 hops and raise an internal log warning if the cap is hit (no `INTERNAL_ERROR` to the client — degrade by treating the walk-stop point as the anchor).
- **Downward traversal MUST enforce the linear-chain invariant deterministically.** Per D-7 (§19) the shipped chaining engine guarantees one direct child per parent via `list_children_of_study` idempotency at [`auto_followup.py:91-99`](../../../../../backend/workers/auto_followup.py#L91-L99). The descendant walk MUST pick at most one child per parent ordered by `(created_at ASC, id ASC)` and stop after anchor + 5 descendants. If the DB ever returns >1 child for a parent (e.g., manual `INSERT` outside the engine path), the walk takes the first by ordering and logs a WARN; additional siblings are dropped from the response and the contract still holds (linear path of ≤ 6 rows).
- **Proposal selection per link MUST be deterministic.** [`proposals.study_id`](../../../../../backend/app/db/models/proposal.py#L52) is nullable and **not unique** — multiple proposals can attach to the same study (e.g., digest regenerated after the first proposal landed). Per-link `proposal_id` is the most-recent **non-rejected** proposal whose `study_id == link.id`. SQL: `SELECT DISTINCT ON (study_id) id, study_id FROM proposals WHERE study_id = ANY(:link_ids) AND status != 'rejected' ORDER BY study_id, created_at DESC, id DESC`. Returns `null` when ALL proposals for a link have `status = 'rejected'` OR when no proposal exists — rejected proposals are NEVER surfaced as the chain summary's CTA (they dead-end the operator). Mirror the same rule for top-level `proposal_id_for_best_link` against the best link.
- The endpoint MUST NOT mutate any row. Pure read.

### State transitions

The new domain helper `derive_chain_stop_reason(chain_links)` (lives in `backend/app/domain/study/chain_summary.py`) reuses the same lift inputs and direction-aware semantics as [`evaluate_chain_gate`](../../../../../backend/app/domain/study/auto_followup.py) — it does NOT duplicate the gate's branching. The shared inputs:

- `direction = tail.objective.get('direction', 'maximize')` (matches `_summary` in `studies.py:165`).
- `epsilon = 0.005` (matches `evaluate_chain_gate`'s default at [`backend/app/domain/study/auto_followup.py:122`](../../../../../backend/app/domain/study/auto_followup.py#L122)).
- `tail_baseline = tail.baseline_metric` (when non-null) else `compute_first_decile_max(tail.trials, direction)` (mirroring `evaluate_chain_gate`'s FR-2a fallback) else `None`.

Stop reason derivation evaluated against the chain's *tail* — defined as `links[-1]` (the most-recent link by `created_at ASC`):

| Condition (evaluated in order; first match wins) | Derived `stop_reason` |
|---|---|
| 1. Any link has `status IN {'queued','running'}` | `in_flight` |
| 2. Tail `status = 'cancelled'` | `cancelled` |
| 3. Tail `status = 'failed'` | `parent_failed` |
| 4. Tail `status = 'completed'` AND `tail.config.auto_followup_depth IN (None, 0)` | `depth_exhausted` |
| 5. Tail `status = 'completed'` AND `tail.config.auto_followup_depth ≥ 1` AND `tail.best_metric IS NULL` | `no_lift` (defensive — mirrors `evaluate_chain_gate`'s `best_metric is None` branch) |
| 6. Tail `status = 'completed'` AND `tail.config.auto_followup_depth ≥ 1` AND `tail_baseline IS NULL` (no baseline + no usable first-decile) | `no_lift` (mirrors `evaluate_chain_gate`'s `first_decile_max is None` branch) |
| 7. Tail `status = 'completed'` AND `tail.config.auto_followup_depth ≥ 1` AND `direction_normalized_lift(tail.best_metric, tail_baseline, direction) <= epsilon` | `no_lift` |
| 8. Otherwise (tail completed + depth remaining + lift gate passed + no child enqueued) | `budget` |

**Rationale for the residual classification (the `budget` fallback, condition 8):** the chaining engine emits `auto_followup_skipped_budget` to logs but doesn't persist it. When all prior conditions (1–7) fail, budget is the only documented reason `enqueue_followup_study` returns early (other early returns — `auto_followup_skipped_parent_missing`, `auto_followup_enqueued_duplicate_dropped`, the unknown-model-pricing branch — are defensive races/edge cases; classifying them all as `budget` is a known approximation. Operator-facing copy "daily LLM budget reached" remains accurate for the >99% common case.) **Decision D-6** (§19) finalizes this approximation rather than introducing a seventh `unknown` wire value.

**Direction-aware semantics:** the `direction_normalized_lift` helper sign-flips for `minimize` so `lift > epsilon` always means "better than baseline" — same pattern as [`_direction_normalized_lift` at `auto_followup.py:219-227`](../../../../../backend/app/domain/study/auto_followup.py#L219-L227).

### Idempotency/replay behavior

Endpoint is `GET` and pure read — naturally idempotent. No replay semantics required.

## 10) Security, privacy, and compliance

- **Threats:**
  - Endpoint exposes parent/child study IDs the operator may not expect to see if they navigate via deep link. Mitigated by RelyLoop's single-tenant MVP2 posture (no cross-tenant exposure surface).
  - Stop-reason derivation could leak `failed_reason` text to the chain summary UI. Mitigated by reusing `failed_reason` as-is (already operator-visible on the study detail page) and never emitting LLM-internal cost figures.
- **Controls:** None new — relies on the existing single-tenant boundary.
- **Secrets/key handling:** N/A — no secrets touched.
- **Auditability:** N/A — `audit_log` lands at MVP3; this is a read endpoint with no state mutation.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement (wizard):** The relabeled control stays in **Step 5 ("Objective + config") of the create-study modal** — same position as today. No new step.
- **Navigation placement (chain panel):** Stays at `/studies/{id}` between `LinkedEntitiesRow` and `ConfidencePanel` (existing mount point at [`page.tsx:109`](../../../../../ui/src/app/studies/[id]/page.tsx#L109)).
- **Labeling taxonomy:**
  - Wizard label: `"🌙 Run overnight (compound automatically)"` (FR-1).
  - Wizard hint (FR-2): `"💡 Tip — this is a long study. Enable '🌙 Run overnight (compound automatically)' below to chain follow-up runs while you're away."`
  - Panel header for the rolled-up summary: `"Overnight chain — {N} studies"`.
  - Panel rows: `Cumulative lift`, `Best config`, `Stop reason`.
- **Content hierarchy (panel):** Existing rows first (parent link, remaining depth, direct-children table — when chain context is local), THEN the rolled-up summary (header, ordered links list, cumulative-lift, best-config, stop-reason). Existing tests on the original rows continue to pass.
- **Progressive disclosure:** The rolled-up summary appears only when `chain.links.length >= 2` (real chain). Single-link payloads (regular studies that opted out of chaining or anchored a chain that never spawned a child) leave the existing three-row display untouched, preserving today's UX for non-chained studies.
- **Relationship to existing pages:** Extends the existing `AutoFollowupChainPanel`; no replacement, no relocation. Coordinates with `feat_study_convergence_indicator` (sibling) for future per-link convergence verdicts — leave room in `links[]` for additive fields.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| Wizard label `"🌙 Run overnight (compound automatically)"` | (short) Run additional studies overnight, each narrowing in on the previous winner. Stops on its own; you still open every PR. | hover/focus on info icon | right of label | `overnight_autopilot` (NEW — FR-6, added in `ui/src/lib/glossary.ts`) |
| Wizard inline hint `"💡 Tip — this is a long study…"` | (no tooltip — the hint itself IS the help text) | — | inline beneath preset row | — |
| Panel header `"Overnight chain — {N} studies"` | (short) The chain links a sequence of studies via `studies.parent_study_id`… | hover/focus on info icon | right of header | `auto_followup_chain` (existing, reused) |
| Remaining-depth row (existing) | (short) Run up to N follow-up studies after this one completes… | hover/focus | right of value | `auto_followup_depth` (existing, reused) |
| `Cumulative lift` row | (short) Best metric across the whole chain, compared to the anchor study's baseline. Direction-aware. | hover/focus | right of label | `lift_gate` (existing, reused — semantics match) |
| `Stop reason: depth_exhausted` mapping label | (short) Run up to N follow-up studies… (same as `auto_followup_depth`) | hover/focus on info icon | right of mapped phrase | `auto_followup_depth` (existing, reused) |
| `Stop reason: budget` mapping label | (short) Daily LLM budget is near its cap — follow-up chains are paused until the budget resets at UTC midnight. | hover/focus | right of mapped phrase | `auto_followup_budget_skip` (existing, reused) |

### Primary flows

1. **Discovery flow.** Operator opens the create-study modal → progresses to Step 5 → sees the relabeled "🌙 Run overnight" toggle with the human-merge boundary copy in the helper text → optionally picks `Deep (1000)` → sees the FR-2 hint → toggles overnight depth to 3 → submits → study runs unattended through up to 4 total links.
2. **Morning review flow.** Operator opens `/studies/{any_chain_member_id}` next morning → chain panel shows "Overnight chain — 4 studies" with the ordered list, cumulative-lift line, "Best config: link 2" row, "Stop reason: no further improvement" row → clicks the best-config link → lands on the proposal page → clicks "Open PR" → ships.
3. **Mid-chain navigation flow.** Operator clicks a parent link in the panel → lands on the parent study's detail page → the same chain panel surfaces the same summary, anchored from the same chain root.
4. **Non-chained study flow.** Operator visits a regular non-chained study → panel calls `/chain` → response has `links.length = 1` → existing minimal panel state renders unchanged (no new rows appear) → confirms backward compatibility.

### Edge/error flows

- **Chain still in flight.** Operator visits mid-chain → `stop_reason = in_flight`, `best_link_id` reflects the best terminal link so far (or `null` if no link is yet complete), `cumulative_lift` reflects the best-so-far ascent (or `null`). Panel renders "Stop reason: chain still running" — no fake "complete" framing.
- **Chain anchor has `baseline_metric IS NULL` AND fewer than 1 complete trial.** `cumulative_lift` is `null`. Panel renders an em-dash for the cumulative-lift line.
- **No proposal yet for the best link.** Panel renders `Best config: <name> (Awaiting proposal)` — non-clickable string, never a fake CTA.
- **Cyclic `parent_study_id` graph (defensive).** Upward walk stops at 10 hops, treats the stop point as anchor, log warning. Client sees a payload; no `INTERNAL_ERROR`.
- **`study_id` not found.** `404 STUDY_NOT_FOUND` per existing pattern.

### Recovery

If the operator wants to abort an in-flight chain, the existing `POST /studies/{id}/cancel?cascade=true` (default) halts pending children — no change needed.

## 12) Given/When/Then acceptance criteria

### AC-1: Wizard relabel (FR-1)

- Given the create-study modal is open on Step 5
- When the operator reads the auto-followup-chain row
- Then the label reads exactly `"🌙 Run overnight (compound automatically)"` (`data-testid="cs-auto-followup"`) and the helper text reads exactly the FR-1 paragraph
- Example values: see FR-1.

### AC-2: Wizard preset hint (FR-2)

- Given the operator selects the `Deep (1000)` preset AND `auto_followup_depth` is currently `Off`
- When the form re-renders
- Then an inline hint with `data-testid="cs-overnight-hint"` appears beneath the preset row reading exactly the FR-2 paragraph; setting depth to any value `1..5` hides the hint within the same render cycle.

### AC-3: New chain endpoint returns rolled-up summary (FR-3)

- Given three studies S1 (anchor, complete, best=0.65, baseline=0.60), S2 (parent=S1, complete, best=0.72), S3 (parent=S2, complete, best=0.74) all with direction=maximize; S2 has a proposal P2
- When the client calls `GET /api/v1/studies/{S2}/chain`
- Then HTTP `200` returns `anchor_study_id = S1`, `best_link_id = S3`, `best_metric = 0.74`, `cumulative_lift = 0.14` (i.e., `0.74 - 0.60`), `proposal_id_for_best_link = null` (S3 has no proposal), `links.length = 3`, ordered S1 → S2 → S3 by `created_at ASC`, with `delta_from_prev = null, 0.07, 0.02` respectively.

### AC-4: 404 on unknown study (FR-3)

- Given `study_id = "01890000-0000-7000-8000-deadbeef0000"` does not exist
- When the client calls `GET /api/v1/studies/{study_id}/chain`
- Then the response is `404 { "detail": { "error_code": "STUDY_NOT_FOUND", "message": "study 01890000-0000-7000-8000-deadbeef0000 not found", "retryable": false } }`.

### AC-5: Non-chained study (FR-3 degrade-gracefully)

- Given a study X with `parent_study_id IS NULL`, no children, `status = 'completed'`, `best_metric = 0.74`, `baseline_metric = 0.65`, `direction = 'maximize'`, `config.auto_followup_depth IN (None, 0)`
- When the client calls `GET /api/v1/studies/{X}/chain`
- Then HTTP `200` returns `links.length = 1`, `cumulative_lift = 0.09` (universal formula: `best_of_completed - anchor.baseline_metric = 0.74 - 0.65`), `stop_reason = "depth_exhausted"`, `best_link_id = X`. When `best_metric IS NULL` instead: `cumulative_lift = null`, `best_link_id = null`. When the study is still running (`status IN {'queued','running'}`): `stop_reason = "in_flight"`, `cumulative_lift = null` (completed subset empty), `best_link_id = null`.

### AC-6: Stop-reason derivation — no_lift (FR-3 + §9 state transitions)

- Given a 2-link chain where the tail study has `status = 'completed'`, `config.auto_followup_depth = 2` (depth was not exhausted), no children, `direction = 'maximize'`, `tail.baseline_metric = 0.60`, `tail.best_metric = 0.601`
- When the chain endpoint runs `derive_chain_stop_reason` (§9 condition 7 — lift = `0.001` ≤ `epsilon=0.005`)
- Then `stop_reason = "no_lift"`.
- Direction-aware companion: given the same shape but `direction = 'minimize'`, `tail.baseline_metric = 0.60`, `tail.best_metric = 0.599`: lift = `0.001` (post sign-flip) ≤ epsilon → `stop_reason = "no_lift"`.

### AC-7: Stop-reason derivation — depth_exhausted (FR-3)

- Given a 4-link chain where the tail study has `status = 'completed'` and `config.auto_followup_depth = 0` (post-decrement leaf)
- When the chain endpoint runs the derivation
- Then `stop_reason = "depth_exhausted"`.

### AC-8: Stop-reason derivation — in_flight (FR-3)

- Given a 2-link chain where any link has `status IN {'queued','running'}`
- When the chain endpoint runs the derivation
- Then `stop_reason = "in_flight"`.

### AC-9: Stop-reason derivation — cancelled (FR-3)

- Given a 3-link chain where the most-recent terminal link has `status = 'cancelled'`
- When the chain endpoint runs the derivation
- Then `stop_reason = "cancelled"`.

### AC-10: Stop-reason derivation — parent_failed (FR-3)

- Given a 3-link chain where the most-recent terminal link has `status = 'failed'` with non-null `failed_reason`
- When the chain endpoint runs the derivation
- Then `stop_reason = "parent_failed"`.

### AC-11: Panel renders rolled-up summary (FR-4)

- Given the chain endpoint returns the AC-3 payload
- When `<AutoFollowupChainPanel>` mounts under `/studies/{S2}`
- Then `data-testid="chain-summary"` renders showing the ordered list S1 → S2 → S3, a `Cumulative lift` row showing `+0.1400`, a `Best config` row linking to `/proposals/{null}` is NOT rendered as a link (no proposal for S3) — instead the row shows `"Best config: <S3.name> (Awaiting proposal)"` plain text.

### AC-12a: Anchor enabled chaining but no child has spawned (FR-4 single-link with opt-in)

- Given a study A with `parent_study_id IS NULL`, `config.auto_followup_depth = 3` (operator opted in), `status = 'completed'`, `best_metric = 0.66`, `baseline_metric = 0.65`, NO children yet (chain gate skipped due to `no_lift`)
- When `<AutoFollowupChainPanel>` mounts
- Then `data-testid="chain-summary"` renders showing the single link, `Cumulative lift: +0.0100`, `Stop reason: no further improvement`, `Best config: A` linking to A's proposal (or `Awaiting proposal` if none).

### AC-12: Panel hides when no chain context (FR-4 — preserve existing behavior)

- Given a study with `parent_study_id IS NULL`, no children, no `config.auto_followup_depth`
- When `<AutoFollowupChainPanel>` mounts
- Then the panel returns `null` (no DOM rendered). The existing test case at `auto-followup-chain-panel.test.tsx:81-83` continues to pass.

### AC-13: Tutorial section exists (FR-5)

- Given the tutorial page is rendered
- When an operator scrolls past the "Open the PR" step
- Then a new H2 "Run the loop overnight" appears with the five steps named in FR-5 and the explicit human-merge boundary line.

### AC-14: Glossary key exists (FR-6)

- Given the glossary file `ui/src/lib/glossary.ts`
- When the Vitest value-lock test at `ui/src/__tests__/lib/glossary.test.ts` asserts on `glossary['overnight_autopilot']`
- Then the entry has both `short` (string, length ≤ 120) and `long` (string) fields; `short` includes the phrase "you still open every PR" verbatim.

## 13) Non-functional requirements

- **Performance:** the chain endpoint p99 SHOULD be < 200ms for the worst-case 6-link chain. Achieved by the bounded query budget in FR-3 Notes: ≤ 6 upward `SELECT ... WHERE id = :parent_id` lookups (indexed via `studies.id` PK) + ≤ 5 downward `SELECT ... WHERE parent_study_id = :current_id LIMIT 1` lookups + 1 hydration `SELECT ... WHERE id IN (...)` + 1 proposals `SELECT DISTINCT ON (study_id) ...` + at most 1 anchor-trials lookup (only when `anchor.baseline_metric IS NULL`). Net: ≤ 14 queries; each microsecond-fast at MVP2 row-counts (Study table size is < 1000 rows in any operator's deployment). **Index note:** `studies.parent_study_id` is a FK column but has **no explicit index** in migration 0003 (Postgres does not auto-index FKs). The downward `WHERE parent_study_id = :current_id` is a seq-scan today. At MVP2 scale (target deployments are tens to low hundreds of studies; deepest dogfood instance has 7) the seq-scan completes in sub-millisecond. **Out of scope for this feature: adding the index.** If a future spec lifts the deployment-size assumption beyond ~10k rows, add an explicit `ix_studies_parent_study_id` migration then. No N+1 in the algorithm as specified.
- **Reliability:** no new write paths; no new failure surface. The cyclic-walk defensive cap (§9 invariants) ensures the endpoint can never spin indefinitely.
- **Operability:** no new env vars, no new metrics, no new alerts. Reuses existing study/digest/proposals logging.
- **Accessibility:** the FR-2 inline hint MUST use `role="note"` and the wizard label MUST keep its `<Label htmlFor="…">` association. Tooltip glossary entries MUST include `ariaLabel` (existing pattern).

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `domain/study/chain_summary.py` (new) — `derive_chain_stop_reason` matrix (AC-6 through AC-10), `compute_cumulative_lift` (maximize + minimize + null-anchor-baseline + first-decile fallback), `select_best_link` with completed-only filter, single-link aggregation (AC-5). Pure-function tests only — no DB.
- **Integration tests (`backend/tests/integration/`):**
  - `tests/integration/api/test_studies_chain.py` (new) — three-link chain happy path (AC-3), 404 STUDY_NOT_FOUND (AC-4), in-flight stop-reason (AC-8), cancelled stop-reason (AC-9), failed stop-reason (AC-10), non-chained single-study payload (AC-5), **`get_chain_for_study` traversal coverage**: anchor-walk cap-at-10 with seeded cyclic data + degraded-anchor log, downward `LIMIT 1` truncation behavior when a parent has multiple children (manually seeded outside the engine), proposal selection rule (multiple proposals per study: newest non-rejected wins).
- **Contract tests (`backend/tests/contract/`):**
  - `tests/contract/test_studies_chain_contract.py` (new) — response schema (top-level keys, `links[]` item keys, `stop_reason` enum values match the `CHAIN_STOP_REASONS` frozenset).
- **Vitest (UI unit/component) (`ui/src/__tests__/`):**
  - `auto-followup-chain-panel.test.tsx` extension — rolled-up summary renders (AC-11), single-link-with-opt-in renders (AC-12a), proposal-link branch + Awaiting-proposal branch, "hide when no chain context" still passes (AC-12), stop-reason mapping table.
  - `create-study-modal.*.test.tsx` extension — wizard label assertion (AC-1), hint show/hide (AC-2).
  - `ui/src/__tests__/lib/glossary.test.ts` (new or extended) — value-lock for `overnight_autopilot` (AC-14): entry exists, `short` and `long` are strings, `short.length <= 120`, `short` includes the verbatim phrase `"you still open every PR"`.
- **E2E (`ui/tests/e2e/`):**
  - `overnight-chain.spec.ts` (new) — seed via API: anchor + 2 chain children + a proposal on the middle link; navigate to the anchor's detail page; assert `data-testid="chain-summary"` renders with the expected link names, cumulative-lift formatted as `+0.0834`, stop-reason phrase visible, best-config link target. Per `CLAUDE.md` E2E rules — real backend, no `page.route()` mocking.

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — add a row for the new `GET /api/v1/studies/{id}/chain` endpoint in the studies sub-resource list.
- `docs/01_architecture/data-model.md` — no schema change to document; OPTIONALLY add a one-line note that `chain summary` is derived from existing columns + clarify `parent_study_id` semantics if not already covered.
- `docs/01_architecture/ui-architecture.md` — note the chain-summary surface on the study detail page (mirrors the existing UBI panel paragraph format).
- `docs/03_runbooks/` — no new runbook; the existing study/auto-followup runbooks cover the underlying engine.
- `docs/04_security/` — no change.
- `docs/05_quality/testing.md` — no change.
- `docs/08_guides/tutorial-first-study.md` — add the new H2 section per FR-5.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none — read-only endpoint + UI rendering + tutorial copy.
- **Migration/backfill expectations:** none — no schema change.
- **Operational readiness gates:** none beyond standard CI (lint + typecheck + tests + coverage + smoke).
- **Release gate:** all AC-1 through AC-14 pass; the existing `auto-followup-chain-panel.test.tsx` cases still pass; the chain endpoint contract test asserts the `stop_reason` enum matches the backend frozenset.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (wizard relabel) | AC-1 | Story 1 (UI) | `create-study-modal.*.test.tsx` | `ui-architecture.md` |
| FR-2 (preset hint) | AC-2 | Story 1 (UI) | `create-study-modal.*.test.tsx` | — |
| FR-3 (`/chain` endpoint) | AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10 | Story 2 (backend domain), Story 3 (backend repo + router) | `test_studies_chain.py`, `test_studies_chain_contract.py`, `domain/test_chain_summary.py` | `api-conventions.md` |
| FR-4 (panel extension) | AC-11, AC-12 | Story 4 (UI) | `auto-followup-chain-panel.test.tsx` (extended) | — |
| FR-5 (tutorial) | AC-13 | Story 5 (docs) | (none) | `tutorial-first-study.md` |
| FR-6 (glossary key) | AC-14 | Story 1 (UI) | `glossary.test.ts` (value-lock) | — |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-14) pass in CI.
- [ ] Backend unit + integration + contract layers green.
- [ ] UI vitest + Playwright E2E green; existing `auto-followup-chain-panel.test.tsx` cases still pass unmodified.
- [ ] `api-conventions.md` + `ui-architecture.md` + `tutorial-first-study.md` updated and merged.
- [ ] Coverage gate ≥ 80% (existing threshold) holds.
- [ ] Rollout gates from §16 satisfied (no schema change, no migration, no flag).
- [ ] No open questions remain in §19 (Decision D-1 applied or escalated).

## 19) Open questions and decision log

### Open questions

_All open questions resolved before implementation per the spec-gen findings gate._

- **OQ-1 (resolved at idea preflight)** — Where the morning summary lives. **Resolved**: study-detail chain panel (per idea Q1 default).
- **OQ-2 (resolved at idea preflight)** — `Deep`/overnight coupling. **Resolved**: keep independent; surface FR-2 hint (per idea Q2 default).
- **OQ-3 (resolved at idea preflight)** — Chain-complete notification webhook. **Resolved**: out of scope; backlog idea (per idea Q3 default).
- **OQ-4 (resolved at idea preflight)** — Endpoint shape. **Resolved**: new dedicated `GET /api/v1/studies/{id}/chain` (per idea Q4 default — confirmed against codebase audit; no existing endpoint carries the rolled-up summary).
- **OQ-5 (resolved at GPT-5.5 cycle 1, F6)** — Should `stop_reason` carry an `unknown` wire value for the residual classification path? **Resolved as D-6**: NO. The §9 condition-8 `budget` classification is the documented approximation; operator-facing copy "daily LLM budget reached" is accurate for the >99% common case. Adding an `unknown` wire value now would force frontend mapping, contract tests, and panel copy to carry a never-emitted-in-practice branch.

### Decision log

- **D-1 (2026-05-31)** — Use a new dedicated `GET /api/v1/studies/{id}/chain` endpoint rather than extending the existing study-detail payload. Rationale: chain payload is meaningful only for chained studies (currently 0% of studies); bloating the detail payload would penalize the common case. Cleaner caching boundary if MVP3 introduces ETags.
- **D-2 (2026-05-31)** — Stop reason is DERIVED from study state, not persisted. Rationale: existing telemetry events are log-only; no `audit_log` until MVP3; persisting a new column requires migration and reopens shipped surface. Derivation matrix in §9 is unambiguous for the documented cases; the residual `budget` classification is a documented approximation (D-6 finalizes).
- **D-3 (2026-05-31)** — Wizard control adds a NEW glossary key `overnight_autopilot` rather than overloading the existing `auto_followup_depth` key. Rationale: the relabeled control's trust framing materially changes meaning; the existing key still fits the chain-panel's remaining-depth row context.
- **D-4 (2026-05-31)** — `Deep (1000)` (NOT a fictional "Thorough (overnight)") is the canonical "long overnight study" preset. Rationale: the shipped wire values from `chore_study_default_stop_conditions` are `focused | standard | deep | custom`; the idea brief's "Thorough (overnight)" name was a leftover from an earlier draft and is corrected throughout this spec.
- **D-5 (2026-05-31)** — Phase 2 (`/studies` "ran while away" card) defers to `phase2_idea.md`. Rationale: requires a visited-state model not present today; carries enough product/UX surface to deserve its own scoping pass.
- **D-6 (2026-05-31, GPT-5.5 cycle 1 F6 accept)** — `stop_reason` ships with six wire values exactly: `depth_exhausted, no_lift, budget, parent_failed, cancelled, in_flight`. No `unknown` value. The §9 condition-8 `budget` classification covers the residual case as an accepted approximation. Rationale: every additional wire value carries frontend mapping cost (FR-4 stop-reason translation table, contract tests, panel copy), and the unknown branch is practically unreachable in production.
- **D-7 (2026-05-31, GPT-5.5 cycle 1 F1 accept)** — `/chain` ships against the **linear-chain invariant** of the shipped chaining engine (one direct child per parent, max depth 5 → max chain length 6). No fan-out resilience in Phase 1. Rationale: the chaining engine enforces single-child per parent via `list_children_of_study` idempotency check at `auto_followup.py:91-99`; spec-level fan-out support would force `parent_study_id` per link, branch-level stop reasons, and pagination — all premature.
- **D-8 (2026-05-31, GPT-5.5 cycle 1 F3 accept)** — `best_link_id`, top-level `best_metric`, `cumulative_lift`, and `proposal_id_for_best_link` are computed from the **completed-link subset only** (`status = 'completed'` AND `best_metric IS NOT NULL`). Rationale: the human-merge boundary only makes sense for terminal-with-a-result links; partial in-flight metrics are not "winners."
- **D-9 (2026-05-31, GPT-5.5 cycle 1 F4 accept)** — `cumulative_lift` uses the universal formula even for single-link chains; never short-circuited to `0`. Rationale: backend simplicity (one helper, no special-case branch) and test consistency.
- **D-13 (2026-05-31, GPT-5.5 cycle 3 F1 accept)** — Panel render predicate is "operator opted into chaining," not "≥2 links." Concretely: render the rolled-up summary when `links.length >= 2` OR `hasParent` OR `chain.links[0].auto_followup_depth_remaining != null`. Rationale: an anchor whose first study didn't spawn a child (no_lift / budget / failure) is the most important case for the operator to understand — hiding the summary there would silently revert the trust-restoring frame to the old "Auto-followup chain (hidden when no kids)" UX.
- **D-11 (2026-05-31, GPT-5.5 cycle 2 F4 + cycle 3 F2 accept)** — Per-link proposal selection rule: most-recent non-rejected (`status != 'rejected'`) proposal whose `study_id == link.id`, ordered `created_at DESC, id DESC`. **Rejected proposals are EXCLUDED at the WHERE clause**, not just deprioritized — when all proposals for a study are rejected, the response carries `proposal_id = null` and the panel shows "Awaiting proposal" rather than a dead-end CTA. Rationale: `proposals.study_id` is nullable + non-unique (a digest re-run creates additional proposals); the chain summary's "Best config" CTA must always point at the proposal an operator can actually ship.
- **D-12 (2026-05-31, GPT-5.5 cycle 2 F6 accept)** — Downward traversal in `get_chain_for_study` is iterative with `LIMIT 1` per parent (NOT a fan-out recursive CTE). Rationale: enforces the linear-chain invariant at the data layer, so a malformed DB state (fan-out from manual INSERT) degrades to a linear path rather than violating the bounded response shape. WARN-logs the truncation for operability.
- **D-10 (2026-05-31, GPT-5.5 cycle 1 F7 + cycle 2 F3 + cycle 3 F3 accept)** — Chain panel refetch policy: `useStudyChain` does NOT join the existing 3-second study-detail poll unconditionally. It refetches on (a) window focus (TanStack default), (b) after the `cancel_study` mutation settles, (c) whenever the viewed study's `useStudy` query observes a status transition `running → {completed,cancelled,failed}`, and (d) at a chain-specific `refetchInterval = 15s` while a **bounded grace condition** holds. Grace rules per stop_reason:
  - `{depth_exhausted, parent_failed, cancelled}` — **terminal-immediate**, never poll.
  - `in_flight` — **poll while in_flight** (no grace bound; only transitions when a link transitions).
  - `no_lift`, `budget` — **transient grace poll**: continue 15s polling **only while the tail's `completed_at` is < 120 seconds old** (5 ticks max). After the grace window expires without observing a child row, treat as terminal and stop polling. Operationally this covers the worker enqueue race window (digest commit → `enqueue_followup_study` dispatch → child row INSERT typically completes within 10-30 seconds; a 120-second grace is 4-12x headroom).

  Rationale: chain shape changes on link transitions; `no_lift` and `budget` are derived approximations that can flip to `in_flight` during the worker enqueue-followup race window (tail just completed, child not yet enqueued — `evaluate_chain_gate` runs in `enqueue_followup_study`, which is dispatched by the digest worker AFTER the parent's digest commits). The bounded 120s grace closes the race window without polling indefinitely against a legitimate terminal outcome.
