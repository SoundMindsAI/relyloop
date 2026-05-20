# Visual builder UI for Step 4 (search space)

**Date:** 2026-05-19 (audited 2026-05-20 — `chore_create_study_wizard_polish` has now shipped and the cardinality TS port already exists; the foundational dependency is in `main`)
**Status:** Idea — surfaced during a UX review of parameter-tuning ergonomics on 2026-05-19. Foundational chore merged 2026-05-20; this idea is now unblocked for `/pipeline`.
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). Even with `chore_create_study_wizard_polish` auto-filling Step 4 with a starter JSON, the surface is still raw text. A relevance engineer's natural interaction with parameter bounds is "drag a slider," not "edit a JSON literal." This idea adds a per-param visual builder overlaid on the canonical JSON view.
**Builds on:** [`chore_create_study_wizard_polish`](../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/) (PR #157 `075c46b`, merged 2026-05-20). Shipped artifacts the builder consumes verbatim: `ui/src/lib/search-space-defaults.ts` (`HEURISTIC_RULES` + `buildStarterSearchSpace` + `estimateCardinality` already exported and parity-tested against the Python source-of-truth), the `validate_against_template` server-side validator + matching client-side mirror inside `create-study-modal.tsx`, and three forward-compat glossary entries (`study.search_space.param_spec`, `.log`, `.cardinality`) added specifically as hooks for the per-row tooltips this feature will surface. The canonical JSON textarea remains the source of truth; the builder is purely a presentation layer that round-trips the same `dict[str, ParamSpec]` state.

## Problem

Today Step 4 is a JSON textarea ([`ui/src/components/studies/create-study-modal.tsx:538-552`](../../../../ui/src/components/studies/create-study-modal.tsx#L538-L552), post-`chore_create_study_wizard_polish`). It's already a *pre-filled* JSON textarea (PR #157 added the auto-fill effect at lines 200-258 + a client-side validation mirror at lines 263-303), but it still asks the user to:

1. Type numeric bounds for each param (no slider/spinner UI).
2. Know whether `log: true` is the right modifier (no toggle).
3. Estimate the search-space cardinality in their head (the 10⁶ cap is enforced at submit but never previewed during editing).
4. Recognize illegal combinations (e.g., `low > high`, empty categorical `choices`, `log: true` with `low <= 0`) by reading Pydantic error messages.

The cumulative effect is that Step 4 *feels* like the part of the wizard that's still in alpha even when steps 1–3 and 5 are polished. The relevance engineer's mental model is "tune these knobs," but the UI doesn't have knobs.

## Proposed capabilities

### Per-parameter row builder

For each entry in `declared_params`, render a row containing:

- **Name** (read-only, from the template).
- **Simple-form hint** (the value of `declared_params[name]`, e.g. `'float'` / `'int'` / `'bool'` / `'string'`, shown as a small chip next to the name). NOT a free-text description — `declared_params` is `dict[str, str]` where the value is the heuristic-fallback type name, not a description. Surfacing it explains why the heuristic picked the default it did. See "Open questions" below for the question of whether to add per-param descriptions to the template schema.
- **Type selector** — `float` / `int` / `categorical`. Default chosen from the same heuristic as [`ui/src/lib/search-space-defaults.ts`](../../../../ui/src/lib/search-space-defaults.ts) (`HEURISTIC_RULES` + simple-form fallbacks). **Wire-value contract:** the selector's three values are the `type` discriminator of `ParamSpec` at [`backend/app/domain/study/search_space.py:83-89`](../../../../backend/app/domain/study/search_space.py#L83-L89); per CLAUDE.md's "Enumerated Value Contract Discipline" rule, the option list MUST carry a source-of-truth comment and a vitest assertion. There is no backend enum to mirror (the values are baked into the discriminated union); the spec should pin this in a `// Values must match backend/app/domain/study/search_space.py ParamSpec discriminator` comment + a tiny parity test.
- **For `float` / `int` types:**
  - `low` and `high` numeric inputs with up/down spinners.
  - `log` toggle (disabled when `low <= 0`; tooltip explains why — wire the `study.search_space.log` glossary entry already in `glossary.ts:85`).
  - Optional `step` input (collapsed by default; revealed via "Advanced" disclosure).
- **For `categorical`:**
  - A multi-add input that builds the `choices` array as removable chips.
- **Cardinality contribution** — small inline counter showing how many discrete states this param contributes (e.g., "≈ 100 states (log float)") — same math as `estimateCardinality()` but factored per-param. Wire the `study.search_space.cardinality` glossary entry already in `glossary.ts:90` for a tooltip explaining the calculation.

Implementation: a controlled component `<SearchSpaceBuilder value={spec} onChange={...} />` where `value` is the canonical `dict[str, ParamSpec]` and `onChange` mutates the same object that the JSON textarea binds to (currently `search_space_text: string` on the form — the spec needs to decide whether the form state stays a string with the builder parsing/stringifying on every change, or moves to a `ParamSpec` dict with the textarea becoming a serialized view). The two surfaces (builder + JSON textarea) round-trip the same state. **Split-vs-tab view is an open spec decision** — see "Open questions" below.

### Live cardinality counter

- The builder header shows a running total: `"Search space: ~12,500 combinations (10⁶ cap)"` updated as the user edits.
- The TS port of `estimate_cardinality()` already exists at [`ui/src/lib/search-space-defaults.ts:92`](../../../../ui/src/lib/search-space-defaults.ts#L92) (shipped in `chore_create_study_wizard_polish` Story 2.1), with shared-JSON-fixture parity to the Python source-of-truth at [`backend/tests/_fixtures/search_space_cardinality_fixtures.json`](../../../../backend/tests/_fixtures/search_space_cardinality_fixtures.json). The builder consumes `estimateCardinality()` directly — no porting needed.
- When cardinality exceeds 10⁶, the counter turns red, the "Next" button disables, and a one-line hint suggests which param contributes the most (so the user knows which one to narrow). The per-param contribution math is the same logic factored out of `estimateCardinality()`'s loop body — straightforward to add as a sibling helper.

### Inline validation

- Each row validates locally: `low < high`, `choices` non-empty, `log` requires `low > 0`, `step` divides the range.
- Red-bordered field + inline error message; no waiting for server round-trip.
- The full search space's cross-param checks (cardinality, unknown-param, missing-declared-param — all introduced by `chore_create_study_wizard_polish`) still run server-side as the canonical gate.

### "Add custom param" escape hatch

- If the user *needs* to tune a param the template doesn't declare, they shouldn't be locked out — but the right answer is "edit the template." The builder shows a disabled "Add custom param" button with a tooltip that links to the template detail page and explains: "Tunable params come from the template's `declared_params`. To tune a new one, add it to the template body and `declared_params` list, then return here."
- Keeps the create-time validation rule (`SEARCH_SPACE_UNKNOWN_PARAM`) discoverable instead of mysterious.

## Scope signals

- **Backend:** ~0 LOC. All canonicalization lives client-side; backend already validates per `chore_create_study_wizard_polish` (`validate_against_template` + Pydantic ParamSpec validation).
- **Frontend:** ~500–800 LOC (revised down — the cardinality TS port and the heuristic table both already exist, removing ~100 LOC from the original estimate). New `<SearchSpaceBuilder>` component + 4–6 sub-components (param row, type-specific editors, cardinality counter, advanced disclosure); vitest unit coverage of the builder ↔ JSON round-trip (the critical contract — every builder edit must produce JSON that round-trips to identical builder state on re-parse); one or two playwright tests covering the builder happy path against the real backend. Likely a 1–2 week feature with one design pass before code.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (MVP1 — no audit_log table yet; the builder is a pure presentation layer that mutates the same form state the existing textarea already binds to).

## Open questions for /spec-gen

1. **Split-view vs tab-view layout.** Side-by-side (builder left, JSON textarea right; both visible always) vs tabbed (one or the other, with a toggle). Recommended default: **split view on desktop (≥1024px), tab view on narrow viewports**. Reason: desktop has the horizontal real estate; the canonical artifact (JSON) staying visible reinforces that it's the source-of-truth. Narrow viewports can't fit both without truncation. Locked unless the design pass surfaces a UX-research reason to override.
2. **Form state representation.** Does the form's `search_space_text: string` stay the canonical form field with the builder parsing/stringifying on every edit, or does the form migrate to a `search_space: ParamSpec` dict with the textarea becoming a serialized view? Recommended default: **keep `search_space_text: string`**, builder parses on mount + stringifies on every onChange. Reason: the existing auto-fill effect, validation mirror, and Undo flow all bind to `search_space_text`; changing the form state shape would cascade through ~5 useEffect call sites and the autoFillSignatures `Set<string>` logic. Builder-as-controlled-component-over-string is the lower-risk path.
3. **Per-param description schema extension.** `declared_params` is `dict[str, str]` (param-name → simple-form type name); the value is NOT a free-text description. Should the QueryTemplate schema grow a separate `declared_params_descriptions: dict[str, str]` (or refactor `declared_params` to `dict[str, ParamDeclaration]` with both `type` and `description` fields)? Recommended default: **defer**. The builder ships without per-param descriptions; the simple-form chip + the heuristic-derived default convey the intent. Adding descriptions is a separate spec (touches backend schema, migration, query-templates UI, this builder) — file a follow-up idea if the design pass surfaces a strong need.
4. **"Advanced" disclosure scope.** Which fields hide behind it? Recommended default: **`step` only**. `log` is common enough to keep in the primary surface. Single-handle vs dual-handle sliders for `low`/`high` is a design call (recommended: numeric inputs + spinners for MVP — sliders sound nice but get into pixel-precision pain on log-scale ranges; ship spinners and revisit if users ask).

## Why not implemented inline today

Three reasons:

1. **Genuinely a new component family.** A 600+ LOC component with sub-components, a cardinality math port, and design choices around split vs. tabbed view — outside the inline-fix budget per [`CLAUDE.md`](../../../../CLAUDE.md).
2. **Design surface.** Single-axis sliders vs. dual-handle range sliders, log-scale knob shape, cardinality color thresholds, "Advanced" disclosure scope — these are real product/design decisions worth a spec round.
3. **Ordering with `chore_create_study_wizard_polish`.** The wizard polish chore ships the foundational defaults heuristic and the validation surface. Building the visual builder before that exists would mean duplicating the heuristic in two places and racing two specs. Sequence: wizard polish → this builder.

## Relationship to other work

- **Builds on** [`chore_create_study_wizard_polish`](../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/) (PR #157 `075c46b`, merged 2026-05-20). Shares the defaults heuristic (`HEURISTIC_RULES`), cardinality estimator (`estimateCardinality`), validation rules (`validate_against_template`), and 3 forward-compat glossary entries (`study.search_space.param_spec` / `.log` / `.cardinality`) that PR #157 added specifically as hooks for this feature's per-row tooltips.
- **Composes with** [`feat_study_clone_from_previous`](../feat_study_clone_from_previous/). When a study is cloned, the builder simply renders the clone's pre-filled params instead of fresh-template defaults — both feed the same form state.
- **Composes with** [`feat_agent_propose_search_space`](../feat_agent_propose_search_space/). When the agent proposes a search space, the builder renders it for editing instead of dumping JSON — the agent's proposed `dict[str, ParamSpec]` is the same shape the builder accepts as `value`.
- **Independent of** [`chore_template_library_expansion`](../chore_template_library_expansion/) — the library widens the *templates* the user picks; the builder shapes how *params* within any one template are tuned. The two land in any order.
