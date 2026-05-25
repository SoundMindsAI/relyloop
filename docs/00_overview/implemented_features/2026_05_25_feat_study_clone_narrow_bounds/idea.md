# Clone study — "narrow bounds" smart-rewrite action

**Date:** 2026-05-24
**Status:** Idea — deferred follow-up of [`feat_study_clone_from_previous`](../feat_study_clone_from_previous/) (per that spec's locked D-3).
**Priority:** P2 — "exploit, don't explore" iteration mode. Unblocked once `feat_study_clone_from_previous` ships.
**Origin:** [`feat_study_clone_from_previous/feature_spec.md`](../feat_study_clone_from_previous/feature_spec.md) §3 "Out of scope", §19 D-3 + OQ-1. Split out of the v1 idea after the preflight + spec cycles agreed bundling would balloon the v1 review surface for marginal additional value.
**Depends on:** `feat_study_clone_from_previous` (v1 must ship first — this builds on the same `?clone_from` deep-link + prefill helper + cloneSource UI metadata).

## Problem

`feat_study_clone_from_previous` v1 ships verbatim-copy + editable-fields. The next iteration friction is: after cloning, the engineer must manually narrow the `search_space` bounds around the best-trial values (read from the source study's winning trial or the proposal's recommended config). Today that's another JSON edit; the "exploit don't explore" mode is the most common follow-up shape per the relevance-tuning loop's UX review (2026-05-19).

## Proposed capability

### Checkbox on Step 4 (search space) of the cloned modal

- **Label:** "Narrow bounds around the source study's winning params (±20%)"
- **Visibility:** only when `initialValues.cloneSource` is present (the v1 surface — never on the bare "New study" flow). Further gated on source-study readiness — see OQ-N4.
- **Default:** unchecked. The engineer opts in.
- **When checked:** the prefilled `search_space_text` JSON is rewritten so each `low/high` clamps to ±20% around the best-trial's value for that param. The winning param values are reachable via two existing endpoints (no backend changes needed):
  - **Preferred:** `GET /api/v1/studies/{id}/digest` → `recommended_config` (winning config as a flat param→value map, written by the digest worker on study completion; verified at [`backend/app/api/v1/proposals.py:258-308`](../../../../backend/app/api/v1/proposals.py#L258-L308)). Returns 404 `DIGEST_NOT_READY` if the source isn't `completed` or the digest hasn't been written yet — see OQ-N4.
  - **Fallback:** `GET /api/v1/studies/{id}` → `best_trial_id`, then `GET /api/v1/studies/{id}/trials?sort=primary_metric_desc&limit=…` and select the row whose `id === best_trial_id` (each trial row carries `params` per [`backend/app/api/v1/studies.py:716-733`](../../../../backend/app/api/v1/studies.py#L716-L733)). There is no single-trial GET; the list endpoint is the canonical read.

### Optional: read-only "best trial params" reference panel

- Per `feat_study_clone_from_previous` OQ-1. A collapsed panel on Step 4 showing the source's best-trial params as a read-only reference table so the engineer can eyeball "narrow around these" before opting in.
- Decide at spec time: bundle or split. Recommended default: bundle into this follow-up (the reference panel is tightly coupled to the smart-rewrite UX — both need the same data fetches).

## Scope signals

- **Backend:** ~0 LOC. Best-trial data is already exposed via `GET /studies/{id}/digest` + `GET /studies/{id}/trials` (see "Proposed capability" §1).
- **Frontend:** ~140–160 LOC. Smart-rewrite helper (`narrowBoundsAroundWinner`) + UI checkbox + collapsed reference panel + digest-fetch wiring (likely a new `useStudyDigest(sourceId)` hook against the existing endpoint) + vitest for the rewrite helper (numeric clamp, categorical skip, missing-param skip per OQ-N1/N2) + one Playwright case that clones → narrows → submits → asserts the resulting `search_space` matches the ±20% clamp shape.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none (pre-MVP2).

## Why deferred

`feat_study_clone_from_previous` v1 already ships ~210 LOC across backend + frontend + 4 test layers. Bundling the smart-rewrite would have added ~60 LOC + new test surface (rewrite logic edge cases — what if a param has no best-trial value? what about non-numeric params like `tie_breaker`? what about params not present in the source's search_space?). The v1 review surface is already large; splitting keeps each PR reviewable and lets the team validate the manual-clone usage signal before committing to the smart-rewrite UX. Per the project's "tangential discoveries" rubric, the implementation path here exceeds 60 minutes once edge-case tests are accounted for, so it qualifies as a genuine follow-up rather than an inline addition.

## Open questions for /spec-gen

- **OQ-N1:** What's the right rewrite for a param with no best-trial value (e.g., the param was added to `search_space` after the winning trial was scored)? Options: skip (leave bounds untouched), or clamp to a default range. Recommended default: skip.
- **OQ-N2:** Non-numeric params (e.g., a `categorical` param like `fuzziness` with `choices: ["AUTO", "0", "1", "2"]` or `operator` with `["AND", "OR"]` — per [`backend/app/domain/study/search_space_defaults.py:59`](../../../../backend/app/domain/study/search_space_defaults.py#L59))? Recommended default: leave the `choices` array untouched; "narrow" only meaningfully applies to numeric `low/high` ranges. (Note: `tie_breaker` is treated as a `float` in [0.0, 1.0] per the same defaults file line 55 — it IS narrowable.)
- **OQ-N3:** Should the checkbox label show the actual ±X% value derived from the source's metric variance (smart) or the fixed ±20% (simple)? Recommended default: fixed 20% for v1 of this follow-up; smart-variance is a v2 elaboration.
- **OQ-N4:** What happens when the source study has no digest yet (status is `running`, `cancelled`, or `failed`, OR completed but the digest worker hasn't written the digest yet — `GET /studies/{id}/digest` returns 404 `DIGEST_NOT_READY`)? Options: (a) hide the checkbox + reference panel entirely until the source is `completed` AND has a digest; (b) show the checkbox disabled with an explanatory tooltip; (c) fall through to the trials-list read path (which is available the moment any trial completes) and surface "best so far" instead of "winner". Recommended default: (a) — keeps the UX honest about what "narrow around the winner" means. Bare `running`/`failed`/`cancelled` clones still work in v1 (verbatim-copy); they just don't get this smart action.

## Relationship to other work

- **Hard depends on** `feat_study_clone_from_previous` (must ship first; this extends its surface).
- **Independent of** [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/feature_spec.md) (shipped via [PR #175](https://github.com/SoundMindsAI/relyloop/pull/175) on 2026-05-21) — agent-proposed search spaces are a separate prefill source consumed today by Step 4 autofill ([`ui/src/components/studies/create-study-modal.tsx:447-463`](../../../../ui/src/components/studies/create-study-modal.tsx#L447-L463)); both can coexist as different opt-in modes on Step 4. Implication for /spec-gen: the smart-rewrite must compose cleanly with the existing autofill — when the engineer opts into "narrow bounds", the rewrite operates on the prefilled (autofilled-or-clone-sourced) `search_space_text`, not on a freshly-built one.
