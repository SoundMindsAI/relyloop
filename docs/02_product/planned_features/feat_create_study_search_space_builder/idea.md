# Visual builder UI for Step 4 (search space)

**Date:** 2026-05-19
**Status:** Idea — surfaced during a UX review of parameter-tuning ergonomics on 2026-05-19.
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). Even after `chore_create_study_wizard_polish` auto-fills Step 4 with a starter JSON, the surface is still raw text. A relevance engineer's natural interaction with parameter bounds is "drag a slider," not "edit a JSON literal." This idea adds a per-param visual builder overlaid on the canonical JSON view.
**Depends on:** `chore_create_study_wizard_polish` (the `search-space-defaults.ts` heuristic and the create-time validator are the foundation this UI binds to). Lands after that chore so the canonical JSON remains the source of truth and the builder is purely a presentation layer.

## Problem

Today Step 4 is a JSON textarea ([`ui/src/components/studies/create-study-modal.tsx:331-337`](../../../../ui/src/components/studies/create-study-modal.tsx#L331-L337)). After `chore_create_study_wizard_polish` lands, it'll be a *pre-filled* JSON textarea — better, but still asks the user to:

1. Type numeric bounds for each param (no slider/spinner UI).
2. Know whether `log: true` is the right modifier (no toggle).
3. Estimate the search-space cardinality in their head (the 10⁶ cap is enforced at submit but never previewed during editing).
4. Recognize illegal combinations (e.g., `low > high`, empty categorical `choices`, `log: true` with `low <= 0`) by reading Pydantic error messages.

The cumulative effect is that Step 4 *feels* like the part of the wizard that's still in alpha even when steps 1–3 and 5 are polished. The relevance engineer's mental model is "tune these knobs," but the UI doesn't have knobs.

## Proposed capabilities

### Per-parameter row builder

For each entry in `declared_params`, render a row containing:

- **Name** (read-only, from the template).
- **Description** (from `declared_params[name]`, shown as a subtitle).
- **Type selector** — `float` / `int` / `categorical`. Default chosen from the same heuristic as `search-space-defaults.ts`.
- **For `float` / `int` types:**
  - `low` and `high` numeric inputs with up/down spinners.
  - `log` toggle (disabled when `low <= 0`; tooltip explains why).
  - Optional `step` input (collapsed by default; revealed via "Advanced" disclosure).
- **For `categorical`:**
  - A multi-add input that builds the `choices` array as removable chips.
- **Cardinality contribution** — small inline counter showing how many discrete states this param contributes to the total search space (e.g., "≈ 50 states (log float, ~50 buckets)").

Implementation: a controlled component `<SearchSpaceBuilder value={spec} onChange={...} />` where `value` is the canonical `dict[str, ParamSpec]` and `onChange` mutates the same object that the JSON textarea binds to. The two surfaces (builder + JSON textarea) round-trip the same state — both are visible side-by-side (split view) or toggled (tab view) — open spec decision.

### Live cardinality counter

- The builder header shows a running total: `"Search space: ~12,500 combinations (10⁶ cap)"` updated as the user edits.
- Computed client-side via the same logic as [`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py)'s `estimate_cardinality()` (port a small TS helper; cover it with vitest snapshots against backend test fixtures so the two implementations stay aligned).
- When cardinality exceeds 10⁶, the counter turns red, the "Next" button disables, and a one-line hint suggests which param contributes the most (so the user knows which one to narrow).

### Inline validation

- Each row validates locally: `low < high`, `choices` non-empty, `log` requires `low > 0`, `step` divides the range.
- Red-bordered field + inline error message; no waiting for server round-trip.
- The full search space's cross-param checks (cardinality, unknown-param, missing-declared-param — all introduced by `chore_create_study_wizard_polish`) still run server-side as the canonical gate.

### "Add custom param" escape hatch

- If the user *needs* to tune a param the template doesn't declare, they shouldn't be locked out — but the right answer is "edit the template." The builder shows a disabled "Add custom param" button with a tooltip that links to the template detail page and explains: "Tunable params come from the template's `declared_params`. To tune a new one, add it to the template body and `declared_params` list, then return here."
- Keeps the create-time validation rule (`SEARCH_SPACE_UNKNOWN_PARAM`) discoverable instead of mysterious.

## Scope signals

- **Backend:** ~0 LOC. All canonicalization lives client-side; backend already validates per `chore_create_study_wizard_polish`.
- **Frontend:** ~600–900 LOC. New `<SearchSpaceBuilder>` component + 4–6 sub-components (param row, type-specific editors, cardinality counter, advanced disclosure); a TS port of `estimate_cardinality()` with snapshot parity against backend; vitest unit coverage of the builder ↔ JSON round-trip; one or two playwright tests covering the builder happy path. Likely a 1–2 week feature with one design pass before code.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none (presentation layer only).

## Why not implemented inline today

Three reasons:

1. **Genuinely a new component family.** A 600+ LOC component with sub-components, a cardinality math port, and design choices around split vs. tabbed view — outside the inline-fix budget per [`CLAUDE.md`](../../../../CLAUDE.md).
2. **Design surface.** Single-axis sliders vs. dual-handle range sliders, log-scale knob shape, cardinality color thresholds, "Advanced" disclosure scope — these are real product/design decisions worth a spec round.
3. **Ordering with `chore_create_study_wizard_polish`.** The wizard polish chore ships the foundational defaults heuristic and the validation surface. Building the visual builder before that exists would mean duplicating the heuristic in two places and racing two specs. Sequence: wizard polish → this builder.

## Relationship to other work

- **Builds on** `chore_create_study_wizard_polish`. Shares the defaults heuristic and validation rules.
- **Composes with** `feat_study_clone_from_previous`. When a study is cloned, the builder simply renders the clone's pre-filled params instead of fresh-template defaults.
- **Composes with** `feat_agent_propose_search_space`. When the agent proposes a search space, the builder renders it for editing instead of dumping JSON.
- **Independent of** `chore_template_library_expansion` — the library widens the *templates* the user picks; the builder shapes how *params* within any one template are tuned.
