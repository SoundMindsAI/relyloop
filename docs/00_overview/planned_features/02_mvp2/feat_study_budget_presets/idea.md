# Study budget presets + sub-warmup guard ("don't ship a study the optimizer never woke up for")

**Date:** 2026-05-29
**Status:** Idea — surfaced from an operator dogfooding review of MVP1 studies (2026-05-29). Highest-leverage item in the "overnight autopilot ergonomics" theme.
**Priority:** P1 (for the theme) — directly fixes the root cause of the "studies feel like they need follow-ups" friction. Small, high-leverage, no new optimizer machinery.
**Origin:** Operator ran 7 studies through the full loop and felt follow-ups were near-mandatory. Tracing the actual `studies.config` values (2026-05-29) showed the cause: 6 of 7 studies ran `max_trials` of **12–15**. With Optuna TPE's ~10-trial random warmup ([`optimization.md`](../../../../01_architecture/optimization.md) §"Optuna configuration"), those studies did ~10 random samples + 2 TPE-guided trials + 1 baseline — the Bayesian optimizer barely engaged before the stop condition fired. The unconverged result is what made the digest emit "narrow/widen" follow-ups, which *felt* like a required second pass but was really compensation for under-budgeting.
**Depends on:** MVP1 study lifecycle (shipped). No dependency on the MVP2 anchors; composes with them.

## Problem

Three connected gaps make under-budgeting the default outcome:

1. **No trial-budget default.** `StudyConfigSpec` requires the operator to supply `max_trials` or `time_budget_min` ([`backend/app/api/v1/schemas.py:629`](../../../../../backend/app/api/v1/schemas.py#L629)) — there is no preset, no recommended value, no wizard guidance. An operator with no intuition for "how many trials is enough" picks a small round number. The observed real-world picks were 12 and 15.

2. **No floor at the TPE warmup threshold.** Optuna's `TPESampler` runs its first ~10 trials as random search before the estimator guides sampling; `MedianPruner` is disabled under 50 trials ([`optimization.md`](../../../../01_architecture/optimization.md), [`backend/app/eval/optuna_runtime.py`](../../../../../backend/app/eval/optuna_runtime.py)). A study with `max_trials < ~20` therefore barely exercises the Bayesian optimizer at all — it is effectively random search. Nothing warns the operator that they are about to run a study that won't converge.

3. **The cost of under-budgeting is invisible and misattributed.** The unconverged study produces a digest with "narrow"/"widen" follow-ups. The operator reasonably reads that as "the tool needs me to iterate," when the real signal is "this study stopped before the optimizer learned anything." The friction the operator feels (too much manual follow-up work) is a defaults problem masquerading as a workflow problem.

**Evidence (traced 2026-05-29 against the live DB):** 7 studies total; `max_trials` distribution = `12 (×4), 15 (×2), 200 (×1)`; zero used `auto_followup_depth`; zero chain children. The single 200-trial study is the only one that would have converged.

## Proposed capabilities

### Budget presets in the create-study wizard

Replace the bare `max_trials` number input with a preset selector + an "advanced / custom" escape hatch. Recommended initial presets (exact numbers are a `/spec-gen` decision):

| Preset | `max_trials` | Intended use | Rough wall-clock at parallelism 8 |
|---|---|---|---|
| **Quick look** | ~30 | Smoke-test the search space / template wiring; not for decisions | minutes |
| **Standard** (default) | ~200 | The everyday "tune this and give me a real answer" run | tens of minutes |
| **Thorough (overnight)** | ~1000 | Wide space, many params, converge hard while you sleep | hours |
| **Custom** | operator-set | Power users; current behavior | — |

The defaults should be grounded, not arbitrary: Standard must comfortably clear the TPE warmup (≥ ~10× the warmup count) so the optimizer is the thing doing the work. Presets set `max_trials` (and optionally a sensible `parallelism` bump for the overnight preset) in `studies.config` — no schema change, just wizard ergonomics over the existing fields.

### Sub-warmup guard (the important half)

When an operator chooses Custom and enters a `max_trials` below a warmup-derived floor (e.g. `< 2 × n_startup_trials`, so ~20), surface a non-blocking inline warning at create time:

> "TPE runs its first ~10 trials as random search before it starts optimizing. At 12 trials this study is essentially random search and is unlikely to converge — consider ≥ 50 (Standard) for a result worth turning into a PR."

Non-blocking (the operator can still proceed — quick smoke tests are legitimate), but it makes the cost legible at the moment of the decision. This is the single change that would most have changed the operator's experience.

### Optional: surface the warmup boundary in the digest

When a completed study ran fewer trials than the warmup floor, the digest's narrative (or a small banner on the proposal) notes that the result is pre-convergence and that the right next step is *re-running with a larger budget*, not necessarily accepting a narrow/widen follow-up. This stops the misattribution at the point where the operator reads the result.

## Scope signals

- **Backend:** small. A warmup-floor constant + a create-time validation warning surfaced through the existing study-create response (warning, not error — does not block). Optionally a digest-narrative note when `trials_run < floor`. No migration (presets write existing `config` keys).
- **Frontend:** moderate. Preset selector component in the create-study wizard; inline sub-warmup warning; "advanced/custom" disclosure. Grounds the preset values in a backend-exposed constant per the Enumerated Value Contract Discipline so the wizard and backend can't drift.
- **Migration:** none.
- **Config:** none required; the warmup floor could be an optional `STUDIES_TPE_WARMUP_FLOOR` setting with a sane default.
- **Audit events:** N/A (MVP2 is pre-`audit_log`).

## Why not just tell people to set max_trials higher?

Because the data shows they won't, and the tool gives them no reason to. The whole point of the Karpathy-loop framing is that the operator shouldn't have to be a Bayesian-optimization expert to get a converged result — "tireless and structured" is the *tool's* job ([blog: haystack-to-relyloop](../../../../blog/2026-05-20-haystack-to-relyloop.md)). A defaulted, warmup-aware budget is the cheapest way to make the loop deliver on that promise.

## Relationship to other work

- **Sibling in the "overnight autopilot ergonomics" theme:** [`feat_overnight_autopilot`](../feat_overnight_autopilot/idea.md) (surfaces the already-shipped `auto_followup_depth` autonomous chaining as a first-class wizard toggle + morning results summary) and [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) (shows when a study actually plateaued, so the operator can tell whether the budget was enough). The three compose: presets prevent under-budgeting, the convergence indicator confirms it worked, and overnight-autopilot makes the whole thing unattended.
- **Composes with the MVP2 UBI anchor** ([`feat_ubi_judgments`](../feat_ubi_judgments/idea.md)): a converged overnight study is far more valuable scored against a fresh UBI judgment list than a 12-trial random sample against a static LLM snapshot.
- **Adjacent to the shipped** [`feat_auto_followup_studies`](../../../implemented_features/2026_05_24_feat_auto_followup_studies/) and [`feat_create_study_search_space_builder`](../../../implemented_features/2026_05_20_feat_create_study_search_space_builder/) — this idea changes the *budget* surface of the same wizard, not the search-space surface.

## Open questions for /spec-gen

1. Exact preset trial counts + whether the overnight preset also bumps `parallelism`.
2. Warmup floor: fixed constant vs derived from the configured `n_startup_trials` (if it's configurable per study).
3. Whether the digest convergence note belongs here or in [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) (avoid double-owning it).
