# Create-study wizard polish — Step 4 starter & validation, Step 5 metric+k clarity, glossary

**Date:** 2026-05-19
**Status:** Idea — surfaced during a UX review of parameter-tuning ergonomics on 2026-05-19.
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). The create-study wizard at [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) has rich contextual help on Steps 1–3 and most of Step 5, but Step 4 (search space) sits alone as a blank JSON textarea, and one Step-5 friction (metric+k coupling) is silent. Bundles four small, related polish items into one wizard-level PR.
**Depends on:** None — all foundations shipped. `template.declared_params` is populated by the existing `query_templates` resource; `SearchSpace.model_validate()` already runs on POST ([`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py)) and emits the `INVALID_SEARCH_SPACE` error_code; the `<InfoTooltip>` + glossary surface shipped with `feat_contextual_help` (PR #122, 2026-05-15 — 49 keys live at [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts)). The new error codes this idea introduces extend the existing `INVALID_SEARCH_SPACE` pattern.

## Problem

Three connected paper-cuts in one wizard:

1. **Step 4 = blank JSON textarea.** The selected template declares its tunable parameters in `declared_params: dict[name, description]`, but Step 4 does not surface that contract. Users either memorize the names or open the template detail page in a second tab.

2. **Typo'd param names succeed at create time.** [`SearchSpace.model_validate()`](../../../../backend/app/domain/study/search_space.py) checks JSON shape and bound integrity but not template alignment. A search space that names `boos_title` instead of `boost_title` is accepted; the trial worker hard-fails on trial 1 at [`backend/app/adapters/elastic.py:493-495`](../../../../backend/app/adapters/elastic.py#L493-L495):

   ```python
   missing = set(template.declared_params) - set(params.keys())
   if missing: raise ValueError(...)
   ```

   *Why hard-fail and not "use template defaults":* [`backend/app/domain/study/template_defaults.py`](../../../../backend/app/domain/study/template_defaults.py) exposes `compute_default_params(template_row)` that *would* pick safe values for any declared param. But a grep across the app code (`backend/app/workers/`, `backend/app/services/`, `backend/app/agent/`, `backend/app/api/`) shows **no call site** for it — only its own unit tests reference it. So today, an omitted declared param at trial time = trial failure, not a defaulted run. The validation behavior the wizard should enforce must match that reality.

3. **Step 5 metric+k coupling is silent.** Three metrics (NDCG, precision, recall) require `k`; three don't (MAP, MRR, ERR). The form shows this with `required` / `optional` placeholders at [`create-study-modal.tsx:377`](../../../../ui/src/components/studies/create-study-modal.tsx#L377), and the gating set is already a frontend constant: `K_REQUIRED` at [`create-study-modal.tsx:46`](../../../../ui/src/components/studies/create-study-modal.tsx#L46). The glossary entry for `study.k` ([`ui/src/lib/glossary.ts:96-107`](../../../../ui/src/lib/glossary.ts#L96-L107)) is excellent — but the *reason* k is required for one set and ignored for another never surfaces inline. New users supply a `k` for MAP, see it accepted, and assume it's being used (it isn't).

4. **No contextual help on Step 4.** `glossary.ts` covers metric (line 57), k (96), direction (110), max_trials (123), time_budget_min (128), parallelism (133), seed (138), sampler (145), pruner (164) — but not `search_space`, `ParamSpec`, `log` scale, or the 10⁶ cardinality cap. Step 4 has zero tooltips while every other input on the wizard has one.

## Proposed capabilities

### Auto-fill Step 4 from the selected template's `declared_params`

- When Step 3 (template selection) finalizes, the create-study modal fetches `GET /api/v1/query-templates/{id}` and pre-fills the Step 4 textarea with one `ParamSpec` per `declared_params` key, using conservative defaults:
  - Names matching `^(field_boost|boost_)` → `{"type": "float", "low": 0.5, "high": 10.0, "log": true}`
  - Names matching `tie_breaker|*_weight` → `{"type": "float", "low": 0.0, "high": 1.0}`
  - Names matching `slop|min_should_match|*_size` → `{"type": "int", "low": 0, "high": 5}`
  - `fuzziness` → `{"type": "categorical", "choices": ["AUTO", "0", "1", "2"]}`
  - Anything else → `{"type": "float", "low": 0.0, "high": 1.0}` with a one-line comment hint that the user should adjust.
- These defaults pick *ranges* (Optuna search bounds), not *values* — a deliberately different concept from [`backend/app/domain/study/template_defaults.py`](../../../../backend/app/domain/study/template_defaults.py)'s `compute_default_params` (which picks per-param midpoint/first-categorical concrete values for a single trial). The two should not share an implementation but the spec should note both exist and explain the distinction.
- If the user has already edited Step 4 and goes back to change the template, prompt before overwriting (toast + Undo).
- The defaults mapping lives in a single module at `ui/src/lib/search-space-defaults.ts` so it has a unit test home and can be referenced by `feat_agent_propose_search_space`'s backend tool.

### Create-time validation: search-space keys must match `declared_params`

- Extend [`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py) with a `validate_against_template(search_space, template)` function that:
  - Rejects with `error_code: SEARCH_SPACE_UNKNOWN_PARAM` (HTTP 400, `message: "Param '{x}' is not declared by template '{t}'."`) when a search-space key isn't in `declared_params`. (HTTP 400 mirrors the existing `INVALID_SEARCH_SPACE` status — the search-space-shape errors are 400 in this codebase, not 422.)
  - **Also rejects** with `error_code: SEARCH_SPACE_MISSING_DECLARED_PARAM` when a declared param is missing from the search space. Rationale: today's run_trial path doesn't merge in `template_defaults.compute_default_params`, so a missing declared param = guaranteed trial failure at the adapter's hard-fail at [`backend/app/adapters/elastic.py:493-495`](../../../../backend/app/adapters/elastic.py#L493-L495). Failing fast at create time matches the reality of the trial worker.
  - **Spec-phase decision** (call out, don't decide here): instead of hard-rejecting on missing-declared-param, we could wire `compute_default_params` into the trial path and downgrade this to a 200-with-warning. Currently `compute_default_params` looks like dead code (confirmed: no app-code call sites; only referenced by its own unit tests); resolving that is a separate `chore_` or `bug_` (capture independently per the tangential-discoveries rule). For *this* idea, the simpler "reject at create time" path is correct because it matches present behavior.
- Wire into `POST /api/v1/studies` ([`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py)) before persisting. The two new error codes flow through the router-local `_error()` helper that already exists in every `backend/app/api/v1/*.py` file (e.g., [`backend/app/api/v1/clusters.py:94`](../../../../backend/app/api/v1/clusters.py#L94)) — there is no centralized error-code constants module today, so this idea introduces the codes as string literals at their call sites, consistent with the codebase's current pattern. The envelope contract is defined in [`backend/app/api/errors.py`](../../../../backend/app/api/errors.py).
- Frontend: React Hook Form validator runs the same check client-side using the cached template fetch from Step 3, so the error appears inline rather than waiting for the server round-trip.
- Contract test asserts both new error codes are in the OpenAPI schema; integration test covers the round-trip from POST → 400.

### Step 5: surface metric+k coupling explicitly

The backend treatment is **tri-state**, not binary (verified during spec generation against [`backend/app/eval/scoring.py:32`](../../../../backend/app/eval/scoring.py#L32)):

- When the user picks a metric on Step 5, the form re-renders the `k` field with a contextual sub-label:
  - **Required-k** — `ndcg`, `precision`, `recall` (the existing `K_REQUIRED` set at [`create-study-modal.tsx:46`](../../../../ui/src/components/studies/create-study-modal.tsx#L46)): `"Top-k cutoff (required for {metric})"` + `<InfoTooltip glossaryKey="study.k" />`.
  - **Optional-k** — `map` only: `"Top-k cutoff (optional — leave empty for full-recall MAP)"`. Presence of k computes `map@k`; absence computes full-recall MAP. The `<Select>` includes a clearable "—" entry.
  - **Ignored-k** — `mrr`, `err` (a new frontend `K_IGNORED` predicate): hide the `k` input entirely with a one-line caption: `"{metric} evaluates the full ranked list — no cutoff used."`
- Both `K_REQUIRED` and the new `K_IGNORED = {mrr, err}` stay as frontend source-of-truth predicates; the backend's `ObjectiveSpec` validator and `scoring.py` metric token mapper are the canonical sources tested for drift.
- Extend the existing `study.metric` and per-metric glossary entries (`study.metric` at [`glossary.ts:57`](../../../../ui/src/lib/glossary.ts#L57), `.ndcg`/`.map`/`.precision`/`.recall`/`.mrr`/`.err` at lines 70/74/78/82/86/90) with one line per metric explicitly stating whether k applies.
- Backend already enforces the coupling via `ObjectiveSpec` ([`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py)); this is a pure UI clarity change. No backend code touched.

### Glossary entries for Step 4 concepts

Add to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) using the same key + body shape as existing entries (matches the `feat_contextual_help` PR #122 contract — `kind`, `short`, optional `long` markdown):

- `study.search_space` — what it is, link to the template's declared params, link to the parameter cheatsheet doc (planned in `chore_template_library_expansion`).
- `study.search_space.param_spec.float` / `.int` / `.categorical` — when to pick each.
- `study.search_space.param_spec.log` — why log scale for boosts; rule of thumb "use log when high/low > 10".
- `study.search_space.cardinality` — the 10⁶ cap, why it exists (Optuna search-time vs. trial budget), how to estimate.

Surface the entries via the existing `<InfoTooltip glossaryKey="..." />` component (shipped at [`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx) via `feat_contextual_help`) next to the Step 4 label and next to each ParamSpec row when the builder UI lands (see `feat_create_study_search_space_builder`).

## Scope signals

- **Backend:** ~100 LOC. One new function in `backend/app/domain/study/search_space.py`, two `_error()` call sites in `backend/app/api/v1/studies.py` introducing the new error-code string literals (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) — no central error-code module exists today, so we follow the existing per-router pattern (see [`backend/app/api/v1/clusters.py:94`](../../../../backend/app/api/v1/clusters.py#L94) for the helper shape). Contract test + integration test.
- **Frontend:** ~180 LOC. New file `ui/src/lib/search-space-defaults.ts` (~60 LOC + tests), wiring in `create-study-modal.tsx` for Step-4 auto-fill (~30 LOC), Step-5 metric+k conditional rendering reusing the existing `K_REQUIRED` set (~30 LOC), 5–6 new/extended glossary entries (~40 LOC), client-side validator (~20 LOC). Vitest coverage for the defaults mapping + metric+k rendering.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none in MVP1 (the `audit_log` table activates at MVP2 — see [`CLAUDE.md`](../../../../CLAUDE.md) "Activates at MVP2"). MVP1 structlog records are unchanged.

## Why not implemented inline today

Per the inline-fix vs idea-file rubric in [`CLAUDE.md`](../../../../CLAUDE.md), this work is borderline-inline at ~280 LOC plus tests, single-subsystem (UI + thin API surface), no operator-environment changes. Two reasons to capture as an idea instead:

1. The four sub-improvements are independently valuable but share a wizard-coherence narrative — bundling into one PR with one feature spec keeps the review focused on the wizard as a whole (the defaults mapping, the two validation error codes, the Step-5 metric+k presentation, the glossary copy are all UX choices that benefit from being decided together).
2. The defaults mapping is naming-convention-heuristic (`^(field_boost|boost_)` → log scale). That's a product decision worth a spec round so the convention is durable and matches the curated template library coming in `chore_template_library_expansion`.

If the user authorizes pulling forward, this is a 1-PR chore that could ship in 1–2 days.

## Relationship to other work

- **Pairs with** `feat_create_study_search_space_builder` (the per-param builder UI). This idea is the JSON-side polish; the builder is the visual overlay. They can land in either order.
- **Pairs with** `chore_template_library_expansion` (curated template library + per-engine cheatsheet). The cheatsheet is what the new `search_space` glossary entry links to.
- **Pairs with** `feat_agent_propose_search_space`. The agent's `propose_search_space` tool would reuse the same `search-space-defaults.ts` heuristic, mirrored to backend.
- **Surfaces but does not fix** the apparent dead-code state of [`backend/app/domain/study/template_defaults.py`](../../../../backend/app/domain/study/template_defaults.py). Capture as `chore_template_defaults_dead_code` or `bug_template_defaults_unused` separately.
- **Does not conflict with** any in-flight work.
