# Clone study from a previous study

**Date:** 2026-05-19 (original) · 2026-05-24 (preflight refresh: line numbers re-grounded; superseding work by `feat_auto_followup_studies` + `feat_digest_executable_followups` shipped 2026-05-24 acknowledged; open forks locked with recommended defaults).
**Status:** Idea — ready for `/pipeline` after preflight 2026-05-24.
**Priority:** P2 — UX nicety. Removes the "rebuild entire create-study form for every follow-up" friction.
**Scope:** ~60 LOC backend + ~150 LOC frontend (clone v1; "narrow bounds" smart action split to a separate follow-up per locked D-3 below).
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). The relevance-tuning loop is iterative — engineers run a study, read the digest, then run a follow-up with narrower bounds or a different objective. Today every manual follow-up rebuilds the entire create-study form from scratch even though 90% of the fields are identical.
**Depends on:**
- [`feat_studies_ui`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/) — shipped. The create-study modal exists at [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx).
- [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/) — shipped. The `studies.parent_study_id` self-FK column was declared here.
**Coordinates with (shipped, must not regress):**
- [`feat_auto_followup_studies`](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/) (PR #223, merged 2026-05-24). The auto-followup worker [`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py) already populates `studies.parent_study_id` when auto-spawning a child study from a `completed` parent. Clone joins as a **second writer of the same column with identical semantics** ("this study was forked from another study"). The cancel-cascade action bar at [`ui/src/components/studies/study-action-bar.tsx`](../../../../ui/src/components/studies/study-action-bar.tsx) is the surface this work extends.
- [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/) (PR #225, merged 2026-05-24). Added `studies.parent_proposal_id` + `studies.parent_proposal_followup_index` columns plus the `ParentFollowupRef` field on `CreateStudyRequest` ([`backend/app/api/v1/schemas.py:614-630`](../../../../backend/app/api/v1/schemas.py#L614-L630)) for the proposal-followup lineage. **Clone is a separate lineage axis** — it sets `parent_study_id`, not `parent_proposal_id`. See §"Coordination with existing parent fields" below for the wire-shape decision.

## Problem

A relevance engineer's normal manual follow-up workflow after a study completes:

1. Read the digest's parameter-importance bars.
2. Decide which params mattered, narrow their bounds, possibly switch objective metric, possibly extend trial budget.
3. Re-run.

Step 3 today means clicking "New study", picking the cluster + target + query set + judgment list + template + objective again, then pasting a hand-edited copy of the previous study's `search_space` JSON into Step 4. The umbrella spec ([`docs/00_overview/product/relevance-copilot-spec.md`](../../../00_overview/product/relevance-copilot-spec.md) §6, persona description) frames RelyLoop as an iterative loop; the create-study modal treats every study as a green-field configuration exercise. The mismatch costs ~2–5 minutes per iteration and invites copy-paste errors in the JSON.

**Why this isn't already solved by the executable-followups work that shipped 2026-05-24:** `feat_digest_executable_followups` ships an LLM-prescribed "Run this followup" action on the **proposal-detail page** ([`feature_spec.md`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md)). That path is for LLM-suggested narrow follow-ups with prefilled `search_space` — useful, but distinct from "the engineer wants to iterate on their own terms." The clone surface targets the manual-iteration path: same config + every field editable, anchored on the **study-detail page** (the source-of-truth view for "did the last study work?").

There is no schema gap blocking this:
- `studies.search_space`, `studies.objective`, `studies.config` (sampler, pruner, max_trials, etc.), and the FK columns (`cluster_id`, `target`, `query_set_id`, `judgment_list_id`, `template_id`) all persist on the source study and are already returned by `GET /api/v1/studies/{id}` (see [`StudyDetail` at `backend/app/api/v1/schemas.py:668-698`](../../../../backend/app/api/v1/schemas.py#L668-L698)).
- The lineage column is already in the schema: [`backend/app/db/models/study.py:78-81`](../../../../backend/app/db/models/study.py#L78-L81) defines `parent_study_id: String(36), ForeignKey("studies.id"), nullable=True` with the comment `"Self-FK for fork lineage (MVP2 surface)."` That column is **actively populated** by `auto_followup`; this work makes the API path populate it too.
- Migration [`0003_study_lifecycle_schema.py:183`](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183) declared the column; no new migration required.

## Proposed capabilities

### Capability 1 — "Clone study" entry point on the study-detail page

- On `/studies/{id}` ([`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx)), add a "Clone study" action in the study header action bar ([`ui/src/components/studies/study-action-bar.tsx`](../../../../ui/src/components/studies/study-action-bar.tsx)) alongside the existing "Cancel study" button.
- **Visibility:** always visible (no status gate). Cloning is legal for any `status` — see locked D-2 below for the `running` case.
- **NOT exposed from the digest panel** ([`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx)). The digest panel's "Suggested follow-ups" section (renamed from "What to try next" by Story 4.1 of `feat_digest_executable_followups`) renders LLM-prescribed followups as bullets only on the study page; the rich "Run this followup" CTA lives on the proposal-detail page. Adding "Clone study" to the digest panel would put two competing iterate-from-here CTAs in one place. Clone stays exclusively on the study header.

### Capability 2 — Pre-fill the create-study modal with source-study fields

- Action handler opens the create-study modal in a new "clone mode" that pre-fills every step:
  - **Step 1** (cluster + target): copied from source.
  - **Step 2** (query set + judgment list): copied.
  - **Step 3** (template): copied.
  - **Step 4** (search space): copied verbatim.
  - **Step 5** (objective + config): copied.
- A small "Cloned from study {source.name}" banner sits above the wizard with a link back to the source study.
- Every field remains editable — clone is a starting point, not a hard copy.
- **Deep link:** `/studies/new?clone_from=<source_study_id>` so the clone state is shareable / bookmarkable / refresh-stable. The modal reads the URL param and fetches `GET /api/v1/studies/{clone_from}` to populate.

### Capability 3 — Persist lineage via the existing `parent_study_id` self-FK

- The create-study request gains an optional top-level `parent_study_id: str | None` field on [`CreateStudyRequest`](../../../../backend/app/api/v1/schemas.py#L633-L655). When the clone action initiates the modal, this field is set to the source study's id and forwarded on POST. See §"Coordination with existing parent fields" for why this is a new top-level field rather than an extension of the existing `parent: ParentFollowupRef`.
- Server stores it in the existing `studies.parent_study_id` column ([`backend/app/db/models/study.py:78-81`](../../../../backend/app/db/models/study.py#L78-L81)). `StudyDetail` already returns `parent_study_id` at [`schemas.py:684`](../../../../backend/app/api/v1/schemas.py#L684) — no response-shape change required.
- **Validation:** `parent_study_id` must reference an existing study on the same `cluster_id` (clone across clusters isn't useful and would mask copy-paste mistakes). Reject with `error_code: PARENT_STUDY_NOT_FOUND` or `PARENT_STUDY_WRONG_CLUSTER` accordingly. Both are 4xx (404 / 422 respectively); both `retryable: false`.
- **No mutual exclusion with `parent: ParentFollowupRef`** at the schema layer. In practice the frontend only sets one or the other (clone vs. executable followup); requests that set both are technically valid (e.g. clone-of-a-followup-study) and the server records both lineage signals. The DB has no cross-pair constraint — `parent_study_id` is independent of the `parent_proposal_*` pair.
- The model comment "fork lineage (MVP2 surface)" stays self-fulfilling: auto_followup already writes the column today (since 2026-05-24); clone joins as a second writer with identical semantics. An MVP2 fork-tree view has data to render from existing auto_followup chains AND from clones once this ships.

### Capability 4 (deferred) — "Narrow bounds" smart action

- Per locked D-3 below, this is **split to a follow-up idea**, not bundled in clone v1. A stretch checkbox on Step 4 that says "Narrow bounds around the source study's winning params" — when toggled, the `search_space` JSON is rewritten so each param's `low`/`high` clamps to ±20% around the best trial's value (read from `proposals[study_id].config` or the source study's winning trial). Pure-frontend transformation.
- Will land as a separate idea folder (`feat_study_clone_narrow_bounds`) after clone v1 produces usage signal. Not a blocker.

## Coordination with existing parent fields

`feat_digest_executable_followups` added `parent: ParentFollowupRef | None` to `CreateStudyRequest` ([`schemas.py:655`](../../../../backend/app/api/v1/schemas.py#L655)) where `ParentFollowupRef = {proposal_id: str, followup_index: int}`. That field exclusively carries **proposal-followup lineage**, populating `studies.parent_proposal_id` + `studies.parent_proposal_followup_index` (see [`backend/app/api/v1/studies.py:333-401`](../../../../backend/app/api/v1/studies.py#L333-L401)).

The clone work needs to carry **study lineage** (sets `studies.parent_study_id`). The two are independent axes:

| Mechanism | Wire field | DB column(s) | Producer |
|---|---|---|---|
| Proposal followup | `parent: ParentFollowupRef` | `parent_proposal_id` + `parent_proposal_followup_index` | "Run this followup" button on proposal-detail page |
| Auto-followup | (none — worker writes directly) | `parent_study_id` | `backend/workers/auto_followup.py:enqueue_followup_study` |
| **Manual clone (this work)** | **`parent_study_id: str \| None` (new top-level field)** | `parent_study_id` | "Clone study" button on study-detail page |

**Locked decision (D-1):** add `parent_study_id` as a **new top-level optional field** on `CreateStudyRequest`. Do NOT extend `ParentFollowupRef` into a discriminated union or rename `parent` to a union shape. Reasoning:
- The two parent mechanisms address orthogonal lineage axes (proposal vs. study); collapsing them into one field obscures the semantics.
- The proposal-followup ref is a 2-field tuple (`proposal_id` + `followup_index`); the study clone is a 1-field reference (`parent_study_id`). The shapes don't unify cleanly.
- `feat_digest_executable_followups` is two weeks old and its wire shape is stable; reshaping it would require a coordinated spec patch and frontend rewrite for zero benefit.
- The DB already has both columns side-by-side; matching the wire shape to the DB columns is the simplest mapping.

## Scope signals

- **Backend:** ~60 LOC. `CreateStudyRequest` gains optional `parent_study_id: str | None`; [`backend/app/api/v1/studies.py:_create_study`](../../../../backend/app/api/v1/studies.py) validates it (exists? same cluster?) and writes it through to the existing column via the existing `repo.create_study()` helper (which already accepts `parent_study_id` per the auto_followup integration — see [`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py)). Two new error codes: `PARENT_STUDY_NOT_FOUND` (404, retryable: false), `PARENT_STUDY_WRONG_CLUSTER` (422, retryable: false). Contract test + integration test (DB-backed; assert lineage stored, assert wrong-cluster rejection).
- **Frontend:** ~150 LOC. Action button in `study-action-bar.tsx` + URL param (`?clone_from=<study_id>`) deep-link reading in the create-study page, pre-fill helper in `create-study-modal.tsx`, "Cloned from {name}" banner component, vitest for the pre-fill helper, one Playwright e2e that clones a seeded completed study and asserts every step is pre-filled, the POST carries `parent_study_id`, and the new study's `parent_study_id` resolves on `GET /api/v1/studies/{new_id}`.
- **Migration:** none — `parent_study_id` column already exists from migration `0003_study_lifecycle_schema` (see [`migrations/versions/0003_study_lifecycle_schema.py:183`](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183)). `repo.create_study` already plumbs the parameter through (auto_followup uses it).
- **Config:** none.
- **Audit events:** none in MVP1 (the `audit_log` table activates at MVP2 — see [`CLAUDE.md`](../../../../CLAUDE.md) "Activates at MVP2"). The MVP2 catalog should add a `study.cloned` variant of `study.created` so clone vs. organic vs. auto-followup vs. executable-followup lineages are distinguishable in the audit trail. Captured here; not implemented now.

## Locked decisions

- **D-1 (wire shape):** `parent_study_id` is a separate top-level optional field on `CreateStudyRequest`, not a reshape of `parent: ParentFollowupRef`. See §"Coordination with existing parent fields" for rationale.
- **D-2 (cloning a `running` study):** allowed, with a confirmation modal. Mechanically legal (snapshot is the row at clone-time); the modal surfaces "this study isn't done yet — clone the in-progress config?" so the operator can't trip into it accidentally. Status-gated visibility was considered and rejected: hiding the button on `running` would force the operator to wait or back-cancel just to start a follow-up, which loses the iteration speed gain.
- **D-3 ("narrow bounds" smart action):** split to a separate follow-up idea (`feat_study_clone_narrow_bounds`). Clone v1 ships only the verbatim-copy + editable-fields path. Splitting keeps v1 reviewable and lets the team validate the manual-clone usage signal before adding the smart-rewrite layer.
- **D-4 (template edited/deleted after source study completed):** clone the search_space as-is. The existing template-id FK validation in `POST /api/v1/studies` already catches a deleted template (`TEMPLATE_NOT_FOUND` → 404). For "template was edited but still exists," the create flow proceeds and any later runtime drift surfaces at trial-run time as it does today for non-cloned studies. No new wizard validation is introduced by this work; if `chore_create_study_wizard_polish` materializes later, it inherits this surface unchanged.
- **D-5 (`parent_study_id` mutual exclusion with `parent: ParentFollowupRef`):** not enforced at schema or DB layer. Both signals can coexist (clone of a followup study) and both columns get populated. The frontend will only set one in practice but the server is permissive.

## Open questions for /spec-gen

- **OQ-1:** Should the create-study modal show the source-study's last-known **best trial's params** anywhere on the wizard (read-only reference panel) so the engineer can eyeball "narrow around these"? Recommended default: **no** for v1 (deferred to the `feat_study_clone_narrow_bounds` follow-up that owns the smart-rewrite UX). Keep v1's surface = "same config, editable."
- **OQ-2:** Should `POST /api/v1/studies` emit a structured **lineage telemetry event** (Langfuse / SigNoz) so MVP2 observability can graph clone-rate / followup-rate / organic-rate? Recommended default: **no** for MVP1 (the audit_log machinery isn't live; one-off telemetry is debt). Capture as an MVP2 follow-up.

## Why not implemented inline today

It's a self-contained feature (~210 LOC + tests) but not zero-effort, and the value lands when the relevance engineer is in iteration mode — a stage the alpha tutorial doesn't demonstrate (the tutorial walks through study #1 only). Worth its own `/pipeline` cycle because:
- Backend adds a new validation surface (cross-cluster check + two new error codes).
- Frontend adds a new deep-link route param + pre-fill state machine that needs vitest + Playwright coverage.
- The coordination with two recently-shipped lineage mechanisms (`auto_followup`, `digest_executable_followups`) deserves a documented spec-level treatment so future readers understand why `studies` has three parent-column families.

## Relationship to other work

- **Coordinates with shipped `feat_auto_followup_studies`** (PR #223). Same `parent_study_id` column, identical lineage semantics. Clone is the manual-trigger counterpart of the auto-spawn path. The cancel-cascade behavior in `study-action-bar.tsx` already coordinates with chain children via `chainChildren` prop; clone adds a second action to that same component without touching cascade logic.
- **Independent of shipped `feat_digest_executable_followups`** (PR #225). Different lineage axis (proposal-followup vs. study-clone); both can coexist on a single study.
- **Pairs with future `chore_create_study_wizard_polish`** if/when that idea is written. Wizard-level template-drift validation would benefit clone but is not required for v1 (per locked D-4).
- **Lays groundwork for an MVP2 fork-tree view.** With auto_followup already populating `parent_study_id` and clone joining in, an MVP2 follow-up can render `/studies/{id}/lineage` showing both auto- and manual-fork iteration history. The schema is ready; only the renderer is missing. (Note: that future view would also surface proposal-followup lineage via the `parent_proposal_id` columns — three lineage axes total.)
- **Split-off follow-up:** `feat_study_clone_narrow_bounds` (per locked D-3). Smart-rewrite of cloned search_space. To be drafted after clone v1 ships and produces a usage signal.
