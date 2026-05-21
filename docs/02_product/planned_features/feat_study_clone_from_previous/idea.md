# Clone study from a previous study

**Date:** 2026-05-19
**Status:** Idea — surfaced during a UX review of parameter-tuning ergonomics on 2026-05-19.
**Priority:** P2 — UX nicety. Removes the "rebuild entire create-study form for every follow-up" friction. Pure frontend, no backend, but operators are working around it today.
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). The relevance-tuning loop is iterative — engineers run a study, read the digest, then run a follow-up with narrower bounds or a different objective. Today every follow-up rebuilds the entire create-study form from scratch even though 90% of the fields are identical.
**Depends on:** `feat_studies_ui` (shipped — the create-study modal exists at [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)). No backend work required beyond a tiny GET helper.

## Problem

A relevance engineer's normal workflow after the first study completes:

1. Read the digest's parameter-importance bars.
2. Decide which params mattered, narrow their bounds, possibly switch objective metric, possibly extend trial budget.
3. Re-run.

Step 3 today means clicking "New study", picking the cluster + target + query set + judgment list + template + objective again, then pasting a hand-edited copy of the previous study's `search_space` JSON into Step 4. The umbrella spec ([`docs/00_overview/product/relevance-copilot-spec.md`](../../../00_overview/product/relevance-copilot-spec.md) §6, persona description) frames RelyLoop as an iterative loop; the UI treats every study as a green-field configuration exercise. The mismatch costs ~2–5 minutes per iteration and invites copy-paste errors in the JSON.

There's no schema gap blocking this — `studies.search_space`, `studies.objective`, `studies.config` (sampler, pruner, max_trials, etc.), and the FK columns (`cluster_id`, `target`, `query_set_id`, `judgment_list_id`, `template_id`) all persist on the source study and are already returned by `GET /api/v1/studies/{id}` (see `StudyDetail` at [`backend/app/api/v1/schemas.py:566-589`](../../../../backend/app/api/v1/schemas.py#L566-L589)). And the lineage column is already in the schema: [`backend/app/db/models/study.py:72-75`](../../../../backend/app/db/models/study.py#L72-L75) defines `parent_study_id: String(36), ForeignKey("studies.id"), nullable=True` with the explicit comment `"Self-FK for fork lineage (MVP2 surface)."` Clone *is* fork; we populate the column that's already waiting.

## Proposed capabilities

### "Clone study" entry point on a finished study

- On `/studies/{id}` ([`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx)), add a "Clone study" action in the study header action bar ([`ui/src/components/studies/study-action-bar.tsx`](../../../../ui/src/components/studies/study-action-bar.tsx)). Visible when `study.status in {'completed', 'failed', 'cancelled'}` (cloning a running study is legal but probably not what the user wants — gate behind a confirm if the source is `running`).
- Also surface from the digest panel's "What to try next" section ([`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx)) — that's the moment the engineer has decided to iterate.

### Pre-fill the create-study modal with source-study fields

- Action handler opens the create-study modal in a new "clone mode" that pre-fills every step:
  - **Step 1** (cluster + target): copied from source.
  - **Step 2** (query set + judgment list): copied.
  - **Step 3** (template): copied.
  - **Step 4** (search space): copied verbatim.
  - **Step 5** (objective + config): copied.
- A small "Cloned from study {source.name}" banner sits above the wizard with a link back to the source study.
- Every field remains editable — clone is a starting point, not a hard copy.

### Persist lineage via the existing `parent_study_id` self-FK

- The create-study request gains an optional `parent_study_id: str | None` field on [`CreateStudyRequest`](../../../../backend/app/api/v1/schemas.py) ([`schemas.py:536-553`](../../../../backend/app/api/v1/schemas.py#L536-L553)). When the clone action initiates the modal, this field is set to the source study's id and forwarded on POST.
- Server stores it in the existing `studies.parent_study_id` column ([`backend/app/db/models/study.py:72-75`](../../../../backend/app/db/models/study.py#L72-L75)). `StudyDetail` already returns `parent_study_id` at [`schemas.py:582`](../../../../backend/app/api/v1/schemas.py#L582) — no response-shape change required.
- Validation: `parent_study_id` must reference an existing study on the same `cluster_id` (clone across clusters isn't useful and would mask copy-paste mistakes). Reject with `error_code: PARENT_STUDY_NOT_FOUND` or `PARENT_STUDY_WRONG_CLUSTER` accordingly.
- The model comment "fork lineage (MVP2 surface)" becomes self-fulfilling — populating the column now means an MVP2 fork-tree view has data to render from day one.

### Optional: "Narrow bounds" smart action

- Stretch goal in this idea (could split into a follow-up): a checkbox on Step 4 that says "Narrow bounds around the source study's winning params." When toggled, the search_space JSON is rewritten so each param's `low`/`high` clamps to ±20% around the best trial's value (read from `proposals[study_id].config` or the source study's winning trial). This is the explicit "exploit, don't explore" iteration mode.
- Implementation is a pure-frontend transformation over the cloned JSON; no backend support needed.

## Scope signals

- **Backend:** ~60 LOC. `CreateStudyRequest` gains optional `parent_study_id: str | None`; the studies service validates it and writes it through to the existing column; two new error codes (`PARENT_STUDY_NOT_FOUND`, `PARENT_STUDY_WRONG_CLUSTER`); contract test + integration test. All other source-study data is already on `GET /api/v1/studies/{id}`; the optional "narrow bounds" feature reads `proposals` / `trials` from existing endpoints.
- **Frontend:** ~150 LOC. Action button + URL param (`?clone_from=<study_id>`), pre-fill helper in `create-study-modal.tsx`, banner component, vitest for the pre-fill helper, one e2e test that clones a seeded completed study and asserts every step is pre-filled and the new study's `parent_study_id` resolves. The "narrow bounds" stretch adds ~60 LOC + tests.
- **Migration:** none — `parent_study_id` column already exists from migration `0003_study_lifecycle_schema` (see [`migrations/versions/0003_study_lifecycle_schema.py:183`](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183)).
- **Config:** none.
- **Audit events:** none in MVP1 (the `audit_log` table activates at MVP2 — see [`CLAUDE.md`](../../../../CLAUDE.md) "Activates at MVP2"). The MVP2 catalog should add a `study.cloned` variant of `study.created` so fork lineage is visible in the audit trail.

## Why not implemented inline today

It's a self-contained feature (~200 LOC + tests) but not zero-effort, and the value lands when the relevance engineer is in iteration mode — a stage the alpha tutorial barely demonstrates (tutorial walks through study #1 only). Worth a spec to settle:

- Whether the "narrow bounds" smart action ships in v1 or as a follow-up. Bundling is simpler but bigger; splitting keeps v1 reviewable.
- What happens when the source study's template has since been edited or deleted. Probably: clone the search space as-is and let the wizard's template validation (introduced in `chore_create_study_wizard_polish`) catch any drift.
- Whether to allow cloning a `running` study. Legal mechanically (the snapshot is just the row at clone-time), but probably wants a confirmation modal to surface "this study isn't done yet — clone the in-progress config?"

## Relationship to other work

- **Pairs with** `chore_create_study_wizard_polish`. That work introduces the validation that catches drift between cloned search_space and a since-edited template — without it, a clone could silently inherit a bad search space.
- **Pairs with** `feat_agent_propose_search_space`. The agent's proposal flow can call the same pre-fill helper to seed Step 4 from an LLM suggestion.
- **Independent of** `feat_create_study_search_space_builder` — clone fills the JSON textarea regardless of whether a visual builder also exists.
- **Lays groundwork for an MVP2 fork-tree view.** Once `parent_study_id` is consistently populated (which this idea drives), an MVP2 follow-up can render `/studies/{id}/lineage` showing the iteration history. The schema is ready; only the renderer is missing.
