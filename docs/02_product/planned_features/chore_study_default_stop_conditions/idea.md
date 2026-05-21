# Study Default Stop Conditions — recommended `max_trials` + `time_budget_min` defaults at the create-study surfaces

**Date:** 2026-05-21
**Status:** Idea — surfaced during the 2026-05-21 Karpathy-loop audit of the Studies workflow.
**Origin:** Standalone audit at `~/.claude/plans/compressed-sparking-hamming.md` — the "within-study loop" section. Verified live via grep of [`backend/app/api/v1/schemas.py:550-580`](../../../../backend/app/api/v1/schemas.py) + [`ui/src/components/studies/create-study-modal.tsx:98-100`](../../../../ui/src/components/studies/create-study-modal.tsx).
**Depends on:** None. Pure decision-support change at the create-study surfaces; no schema migration, no service-layer behavior change.

## Problem

The server-side `StudyConfigSpec` validator at [`backend/app/api/v1/schemas.py:572-580`](../../../../backend/app/api/v1/schemas.py) correctly **requires** at least one of `max_trials` or `time_budget_min` — so studies cannot be created with no stop condition. The system is safe. What it is not is **opinionated** about what a sensible overnight run looks like.

Today, the two paths a study gets created on each surface this problem differently:

1. **The create-study wizard** at [`ui/src/components/studies/create-study-modal.tsx:98-100`](../../../../ui/src/components/studies/create-study-modal.tsx) declares both fields as optional empty inputs (`max_trials?: number | ''` and `time_budget_min?: number | ''`). It pre-fills `parallelism: 4` at [line 136](../../../../ui/src/components/studies/create-study-modal.tsx#L136) but leaves both stop-condition inputs blank. A user creating a study via the wizard hits "Submit," gets the validator's 422 ("at least one of `max_trials` or `time_budget_min`"), and then types in *something* — usually whatever round number comes to mind. The Karpathy-loop discipline of "this experiment runs for exactly N trials / X minutes" is delegated entirely to the user's intuition.
2. **The `create_study` agent tool** at [`backend/app/agent/tools/studies/create_study.py`](../../../../backend/app/agent/tools/studies/create_study.py) reuses `CreateStudyRequest` (= `StudyConfigSpec`) verbatim. The LLM must pick a value with no project guidance — only the bare Pydantic schema constraints (`ge=1, le=100_000` for `max_trials`; `gt=0` for `time_budget_min`). There is no glossary entry or system-prompt directive that recommends a starting range.

The compounding observation: the only existing per-trial time-box (`trial_timeout_s`, default 60s via [`backend/app/core/settings.py:282`](../../../../backend/app/core/settings.py)) is **the right shape** for Karpathy-loop discipline. The missing layer is a **per-study time-box default** with a recommended value, plus a wizard that surfaces "what overnight looks like" as a one-click preset.

Karpathy's loop runs roughly 100–120 experiments per 8-hour overnight session. RelyLoop's per-trial timeout is 60s. With `parallelism=4` and assume average 30s actual cost per trial (ES queries return faster than 60s in the common case), an 8-hour overnight session at full parallelism is `8 × 3600 × 4 / 30 = 3,840` trials — which is far more than Karpathy needs because each trial is much cheaper than ML training. A sensible default for an "overnight" preset is much lower than the upper bound and should match what TPE actually benefits from. Per Optuna docs and [`backend/app/eval/optuna_runtime.py:116-157`](../../../../backend/app/eval/optuna_runtime.py): pruning kicks in only at `max_trials >= 50`; TPE warms up around 10 trials; diminishing returns past 200–500 for most low-dimensional search spaces.

## Proposed capabilities

Tiered. Tier A is the small UI change that captures most of the leverage. Tier B is the optional preset selector.

### Tier A — wizard pre-fill + recommended-default copy

- **Wizard pre-fill on Step 5.** Set the form default for `max_trials` to **200** when the input is empty on first render. Keep `time_budget_min` empty (so the user explicitly opts in to either kind of cap). Reasoning: 200 is well past TPE warmup (10) and median-pruner activation (50), within Optuna's diminishing-returns sweet spot, and at `parallelism=4` × 30s ≈ 25 minutes wall-clock — short enough for an interactive session, long enough to be meaningful.
- **Glossary copy update** in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) for the existing `study.max_trials` + `study.time_budget_min` keys. Add a one-sentence recommendation: "200 trials is a sensible default for a first study on a low-dimensional search space; 500–1000 for overnight runs."
- **InfoTooltip surfaces the recommendation.** The wizard already wires `<InfoTooltip glossaryKey="study.max_trials" />` ([`create-study-modal.tsx:851`](../../../../ui/src/components/studies/create-study-modal.tsx#L851)) and `study.time_budget_min` ([line 862](../../../../ui/src/components/studies/create-study-modal.tsx#L862)). The glossary update propagates automatically via the existing `InfoTooltip` component.
- **System prompt entry** in [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) — add a sentence to the Studies tools section: "When the user has not specified a stop condition, propose `max_trials=200` as a first study or `max_trials=500–1000` (or `time_budget_min=240–480`) for overnight runs."

### Tier B — "Quick" vs "Overnight" preset selector on Step 5

- **Preset radio above the numeric inputs.** Three options:
  - `Quick (50 trials, ~5 min)` — `max_trials=50, parallelism=4, trial_timeout_s=60`
  - `Standard (200 trials, ~25 min)` — `max_trials=200, parallelism=4, trial_timeout_s=60` (Tier A default)
  - `Overnight (max 8h, 1000 trials)` — `max_trials=1000, time_budget_min=480, parallelism=4, trial_timeout_s=60` (the first-of stop condition wins)
  - `Custom` — leaves the existing fields manually editable; preset selection has no effect.
- **Selecting a preset writes the four fields and disables them** (with a "Switch to Custom" link to re-enable). This makes the Karpathy-loop preset visible and one-click; the existing manual path remains available.
- **Frontend-only state** — no new wire-value enum, no new backend logic. The preset selector is purely a form-prefill convenience.

### Out of scope

- **Adaptive parallelism** (auto-scale `parallelism` up or down based on observed trial latency) — interesting but real product-design surface. Defer.
- **A separate "Karpathy mode" preset that combines `max_trials=200` + auto-followup chaining** — that belongs to [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md), not here.
- **Backend-side default changes** (changing `default=None` to `default=200` in the Pydantic field) — rejected. The existing validator behavior (force the user to opt in) is the right safety net for the API surface. Backend defaults would silently apply to legacy callers without an upgrade signal; wizard pre-fill is the right place.

## Scope signals

- **Backend:** Tier A: ~5 LOC in [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md). Tier B: nothing.
- **Frontend:** Tier A: ~15 LOC (form default + 2 glossary entries + 1 test asserting the pre-fill renders). Tier B: ~150 LOC (preset radio + 3 vitest cases asserting each preset writes the right field bundle + 1 case for Custom mode).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Tests:** Tier A: 1 vitest case in `create-study-modal.test.tsx` asserting the `max_trials` field renders with `200` by default. Tier B: 4 cases (3 presets + custom).

## Why not inline today

This idea is **borderline** on the inline-fix rubric in [`CLAUDE.md`](../../../../CLAUDE.md) "Inline-fix vs idea-file rubric." Tier A alone is ≤50 LOC and touches a single subsystem — by the rubric it should be **implemented inline** on the next PR that touches the wizard. The reason it's captured as an idea file rather than landed inline:

1. **Product call on the recommended-default number.** "200" is defensible but not obviously right — 100, 250, 500 are all candidates. Picking the wrong number means every new study created via the wizard gets that number, which is a one-way change. Worth a deliberate decision rather than a drive-by commit.
2. **Tier B is the more interesting unit.** A preset selector that surfaces "Quick / Standard / Overnight" as one-click options is a real UX addition, not a tweak. Pairing the default tweak (Tier A) with the preset (Tier B) in one PR gives reviewers the full picture; landing Tier A alone in a drive-by would leave the bigger UX gap for later.
3. **Cross-surface coordination.** Tier A modifies both the wizard AND the orchestrator system prompt. Two surfaces is the upper bound of "drive-by"; doing it as a planned chore keeps the change traceable.

## Relationship to other work

- **Substrate for [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md)** — that feature relies on every study having a known finite stop condition so chained follow-ups inherit a sensible budget. The default-stop-condition work makes "chained study with depth=3" mean something concrete (e.g., "three 200-trial studies, ~75 min total").
- **Aligned with [`feat_pr_metric_confidence`](../feat_pr_metric_confidence/idea.md)** — convergence-trajectory and late-trial noise-floor analytics in the PR body are most meaningful when the operator knows the study had room to converge. A 50-trial study with "best found at trial 49" reads very differently from a 200-trial study with "best found at trial 87."
- **Composes with [`feat_create_study_search_space_builder`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/)** (shipped 2026-05-20) — the search-space builder is the substantive Step 4. This chore polishes Step 5, the "how long do we run it" surface.
