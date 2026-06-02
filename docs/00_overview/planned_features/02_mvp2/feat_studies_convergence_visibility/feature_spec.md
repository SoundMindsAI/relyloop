# Feature Specification — Studies-list convergence visibility + demo data that shows real optimization

**Date:** 2026-06-02
**Status:** Draft
**Owners:** soundminds.ai (Product + Engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`feat_study_convergence_indicator`](../../implemented_features/) (shipped PR #352 — classifier reused here)
- [`docs/03_runbooks/convergence-verdict.md`](../../../03_runbooks/convergence-verdict.md)
- [`infra_smoke_reseed_runtime_budget`](../infra_smoke_reseed_runtime_budget/idea.md) (seed-runtime interaction)

---

## 1) Purpose

- **Problem:** Two coupled gaps. (A) The `/studies` list shows name, cluster, status, best_metric (with a ceiling badge), and timestamps — but **not** how many trials a study ran, nor whether it converged. Both already exist on the study DETAIL page but an operator scanning the list can't tell "is this 0.99 a real win or just too few trials to trust?" without opening each one. (B) The five small demo scenarios index ~5 docs each with 1–2 mostly-grade-3 judgments per query and run 12 trials, so the optimizer trivially hits `best_metric ≈ 1.0` (NDCG@10) — the tool then honestly flags the `Pinned at metric ceiling` badge. The demo therefore showcases the *degenerate* case the tool warns about, not a real optimizer win.
- **Outcome:** The studies list shows a completed-trial count and a convergence badge (`Converged` / `Still improving` / `Too few trials`) per study, reusing the shipped classifier. The demo's small scenarios are enriched (more candidate docs + denser graded judgments + more trials) so studies land a believable, non-ceiling baseline that visibly improves over trials, and the convergence badge reads meaningfully instead of a uniform "too few trials." Operators evaluating RelyLoop see genuine optimization value at a glance.
- **Non-goal:** This does NOT hide or weaken the honest ceiling / too-few-trials signals — those stay and remain correct for genuinely sparse data. It does not change the convergence classifier, its constants, or the optimizer. It does not add multi-objective or new metrics.

## 2) Current state audit

### Existing implementations

- **`/studies` list page** — [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx) renders `<StudiesTable>` driven by [`ui/src/components/studies/studies-table.column-config.tsx`](../../../../ui/src/components/studies/studies-table.column-config.tsx) (6 columns: name, cluster, status, best_metric+ceiling badge, created, completed). API: `GET /api/v1/studies`. Note: the ceiling badge logic lives at column-config.tsx:32,93 (`METRIC_CEILING_THRESHOLD = 0.99`, gated on `direction !== 'minimize'`).
- **List API** — `GET /api/v1/studies` at [`backend/app/api/v1/studies.py:466`](../../../../backend/app/api/v1/studies.py); maps DB rows via `_summary(row)` at studies.py:172. Returns `StudySummary` (8 fields). **Does NOT load trials.** Cursor pagination + `X-Total-Count` (studies.py:536–551).
- **Detail trial count parity** — `aggregate_trials_summary` (trial.py:244) filters `is_baseline.is_(False)` (FR-11), so detail's `trials_summary.total` **excludes** the baseline trial. The list's new `trial_count` therefore counts **non-baseline** trials to match.
- **List item schema** — `StudySummary` at [`backend/app/api/v1/schemas.py:881`](../../../../backend/app/api/v1/schemas.py): `id, name, cluster_id, status, best_metric, direction, created_at, completed_at`.
- **Convergence classifier** — `classify_convergence(complete_trials, *, direction)` at [`backend/app/domain/study/convergence.py:158`](../../../../backend/app/domain/study/convergence.py) returns `StudyConvergenceShape | None`. Verdicts `converged` / `still_improving` / `too_few_trials`. Thresholds: `< CONVERGENCE_FLAT_MIN_COMPLETE` (5) → `None`; `total < STUDIES_TPE_WARMUP_FLOOR` (50) → `too_few_trials`; `improvement_in_window <= CONVERGENCE_FLAT_EPSILON` (0.005) → `converged`; else `still_improving`.
- **Detail convergence wiring** — service `fetch_study_convergence(db, study_row)` at [`backend/app/services/study_convergence.py:85`](../../../../backend/app/services/study_convergence.py): in-flight short-circuit (`queued`/`running` → `None`), direction resolution, loads trials via `list_complete_optuna_trials_for_study(db, study_id)` ([`backend/app/db/repo/trial.py:93`](../../../../backend/app/db/repo/trial.py)), wraps the classifier in try/except. Trial counts for detail come from `aggregate_trials_summary(db, study_id)` (trial.py:244, single GROUP BY).
- **Detail badge** — `VERDICT_BADGE` map at [`ui/src/components/studies/convergence-panel.tsx:48`](../../../../ui/src/components/studies/convergence-panel.tsx): `converged`→{`Converged`, success}, `still_improving`→{`Still improving when it stopped`, warning}, `too_few_trials`→{`Too few trials to tell`, warning}. Glossary key `convergence_verdict` ([`ui/src/lib/glossary.ts:871`](../../../../ui/src/lib/glossary.ts)).
- **Frontend verdict enum** — `CONVERGENCE_VERDICT_VALUES` at [`ui/src/lib/enums.ts:77`](../../../../ui/src/lib/enums.ts) (source-of-truth comment → `backend/app/domain/study/convergence.py ConvergenceVerdict`; lock test `ui/src/__tests__/lib/enums-convergence-discipline.test.ts`).
- **Demo scenarios** — `SCENARIOS` in [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) (5 small scenarios, lines ~186–805). `backend/app/services/demo_seeding.py:63` **imports** `SCENARIOS` (single source of truth — no duplication). Per-scenario: 5 docs, 5 queries, 5–10 judgments (mostly rating 3), 1–2 tunable float params [0.5,5.0] log. Study config `max_trials=12` (seed_meaningful_demos.py:950; constant `_REAL_STUDY_MAX_TRIALS=12` at demo_seeding.py:150). Objective `{metric: "ndcg", k: 10, direction: "maximize"}` (seed_meaningful_demos.py:948). Rich ESCI scenario: 1000 docs, `max_trials=15` (seed_meaningful_demos.py:1536; `_RICH_SCENARIO_MAX_TRIALS=15`).
- **UBI synthesis** — `fabricate_ubi_for_scenario(scenario_judgments_map=...)` consumes the same `judgments_map`, so enriching judgments automatically enriches synthetic UBI events (no separate UBI authoring).

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none) | — | — |

No routes/links move. The list gains columns; the detail page is unchanged.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_studies_api_contract.py` | `StudySummary` schema importability (lines 51–77) | 1 | Add a list-item field assertion for `trial_count` + `convergence_verdict`. |
| `ui/src/__tests__/components/studies/*` (studies-table render) | column render snapshot/asserts | n | Add new-column render assertions. |
| `backend/tests/unit/scripts/test_scenarios_ubi_config.py` + sibling scenario tests | scenario counts / judgment maps | n | Update any hardcoded judgment/doc counts to match enriched data. |
| `backend/tests/integration/test_demo_seeding*.py` | seeded study assertions | n | Update expectations if they assert metric/trial counts. |

### Existing behaviors affected by scope change

- **Demo `best_metric` values change.** Current: small scenarios ≈ 0.80–1.0 (several at the 0.99 ceiling). New: baseline lands ~0.4–0.7 with best improving to < 0.99 with visible lift. Decision needed: no (this is the explicit goal, D-1).
- **Demo seed wall-clock increases** (more docs/judgments + `max_trials` 12→50). Decision needed: no — accepted (D-9); smoke job is opt-in/off by default per `state.md`.
- **`StudySummary` payload grows by 2 fields.** Downstream consumers of the list response: `ui/src/lib/api/studies.ts` (`StudySummary` TS type) + the studies table. Both updated in scope.

---

## 3) Scope

### In scope

- **Epic A — list trial count + convergence badge:** Add `trial_count` and `convergence_verdict` to `StudySummary`; compute them efficiently on the list endpoint (batched count + count-gated classifier); render a Trials column + a convergence badge column on `<StudiesTable>`, reusing the existing verdict enum, glossary entry, and badge labels.
- **Epic B — demo data enrichment:** Rework the five small `SCENARIOS` (more candidate docs + denser graded judgments spanning ratings 3/2/1/0, designed so the baseline config under-ranks and the optimizer finds real lift) and raise their `max_trials` so studies land a non-ceiling baseline that visibly improves and the convergence badge reads meaningfully.

### Out of scope

- Changing the convergence classifier, its constants (`CONVERGENCE_FLAT_*`, `STUDIES_TPE_WARMUP_FLOOR`), or the optimizer/sampler.
- Removing or weakening the ceiling badge or the `too_few_trials` verdict (they stay; D-3).
- The rich ESCI scenario (already shows real lift — untouched).
- Any new IR metric, multi-objective, or new search-space param types.
- A migration / new persisted column (trial_count + verdict are computed per request).

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md):
- **Endpoint prefix:** `/api/v1/studies` (business endpoint). No new endpoint — extends the existing `GET /api/v1/studies` response model.
- **Router:** `backend/app/api/v1/studies.py`.
- **Error envelope:** unchanged — this change adds response fields only; no new error codes.
- **Auth:** N/A — single-tenant, no auth surface (MVP2).

### Phase boundaries

**Single phase.** Epics A and B ship together because the list convergence badge is only compelling in the demo once the demo studies (B) produce enough trials and real lift to read something other than a uniform "too few trials." Both are in scope for this spec's implementation plan. The plan sequences Epic A (deterministic UI/API) before Epic B (empirical data authoring) so the API/UI is verifiable independently of the seed tuning.

## 4) Product principles and constraints

- **Reuse the shipped classifier — never fork it.** The list verdict MUST come from `classify_convergence` (the same function the detail page uses), via a count-gated path; no parallel verdict logic.
- **Honest signals stay honest.** The ceiling badge and `too_few_trials` verdict remain correct for sparse/low-trial studies; this feature makes the *demo* avoid the degenerate case, it does not suppress the signal.
- **Single source of truth for demo scenarios.** `SCENARIOS` is defined once (`seed_meaningful_demos.py`) and imported by `demo_seeding.py`; edits land in one place and both seed paths inherit them.
- **Wire-value discipline.** The frontend verdict values MUST be sourced from `CONVERGENCE_VERDICT_VALUES` (`ui/src/lib/enums.ts`), which mirrors the backend `ConvergenceVerdict` Literal.
- **List performance.** The list endpoint MUST NOT regress into an unbounded N+1: per-study trial counts come from one batched GROUP BY; the full classifier runs only for studies with ≥ `STUDIES_TPE_WARMUP_FLOOR` complete trials.

### Anti-patterns

- **Do not** embed the full `StudyConvergenceShape` (with `best_so_far_curve`) on every list row — the list needs only the verdict + count; the curve stays detail-only (payload bloat + per-row trial load).
- **Do not** run `classify_convergence` for every study on the page unconditionally — gate on the cheap complete-count first (`<5` → null, `5–49` → `too_few_trials`, `≥50` → classify).
- **Do not** lower `STUDIES_TPE_WARMUP_FLOOR` to make the demo read "converged" — that silently changes the verdict semantics for every study everywhere; raise demo trials instead.
- **Do not** make the demo metric non-ceiling by switching the IR metric or k — fix the judgment density/doc set, not the measurement.
- **Do not** author enriched judgments whose "correct" ordering is already produced by the baseline param defaults — the judgments must create a tradeoff the optimizer resolves, or the metric won't show lift.
- **Do not** duplicate the scenario dicts into `demo_seeding.py` — keep the single import.

## 5) Assumptions and dependencies

- **Dependency:** `feat_study_convergence_indicator` (classifier + repo helper + frontend enum/glossary). Status: implemented (PR #352). Risk if missing: N/A — shipped.
- **Dependency:** A running stack (`make seed-demo`) to empirically validate Epic B's baseline/lift targets. Status: available locally. Risk if missing: Epic B's ACs can't be verified — escalate.
- **Interaction:** `infra_smoke_reseed_runtime_budget` — raising `max_trials` lengthens the demo reseed; the smoke job is opt-in/off by default (`state.md`), so this is not a CI blocker, but the plan should keep the bump as small as achieves `converged` (target 50).

## 6) Actors and roles

- Primary actor: Relevance Engineer (views the studies list; runs the demo seed).
- Role model: N/A — single-tenant install, no auth surface.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — this feature adds no state-mutating endpoint or service. The list endpoint is read-only; the demo seed writes are install-side, not audited (`audit_log` instrumentation arrives with MVP3 product mutations, not seed tooling).

## 7) Functional requirements

### FR-1: Studies-list item carries a trial count
- The system **MUST** add `trial_count: int` to `StudySummary`, representing the study's **non-baseline** trial rows — matching the detail page's `trials_summary.total` semantics exactly (`aggregate_trials_summary` filters `is_baseline.is_(False)`). The system **MUST** compute it via a single batched aggregate across the page's studies (no per-study query).
- Notes: non-baseline so a 50-optimization-trial study shows `trial_count == 50` (the baseline trial is the separate `baseline_metric` row, not an optimization trial). Convergence (FR-2) uses the **complete non-baseline** count internally.

### FR-2: Studies-list item carries a convergence verdict
- The system **MUST** add `convergence_verdict: ConvergenceVerdict | None` to `StudySummary` (verdict literal only — NOT the full `StudyConvergenceShape`).
- The system **MUST** compute it consistently with `fetch_study_convergence`, applying the gates **in this order** (the first three are cheap — no trial load):
  1. **In-flight short-circuit:** status ∈ {`queued`,`running`} → `None`.
  2. **Direction resolution:** resolve `direction` from objective JSON exactly as `fetch_study_convergence`/`_resolve_direction` does (default `maximize`); if direction is invalid → `None`.
  3. **Count gate** (using the batched complete-non-baseline count): `< CONVERGENCE_FLAT_MIN_COMPLETE` (5) → `None`; `5 ≤ complete < STUDIES_TPE_WARMUP_FLOOR` (50) → `too_few_trials`.
  4. **Classifier:** `complete ≥ 50` → `classify_convergence(...).verdict` (`converged` / `still_improving`).
- The system **MUST** derive steps 1–3 without loading trials, and **MUST** invoke `classify_convergence` only for studies passing to step 4 (`complete ≥ 50`).
- The system **MUST** reuse `classify_convergence` + the existing direction resolution (no forked logic). Because steps 1–2 fire before the count gate, the list verdict equals the detail verdict for every case including an invalid-direction completed study (both `None`).

### FR-3: List endpoint stays within performance budget
- The system **MUST** add at most **two** queries per list request beyond today: (1) one batched trial-count aggregate (`GROUP BY study_id`) across the page's study IDs; (2) at most one batched trial-load (`WHERE study_id IN (...)` for the subset with `complete ≥ 50`), classified in memory. No per-study query. The system **SHOULD** keep p99 list latency comparable to today for demo-scale data.

### FR-4: Frontend renders trials + convergence columns
- The system **MUST** add a "Trials" column (renders `trial_count`) and a convergence badge column to `<StudiesTable>`.
- The badge **MUST** map verdicts to labels using the same taxonomy as the detail panel: `converged`→"Converged" (success), `still_improving`→"Improving" (warning; the list uses the compact label — see §11), `too_few_trials`→"Too few trials" (warning). A `null` verdict renders an em-dash "—" (no badge).
- The frontend verdict values **MUST** be sourced from `CONVERGENCE_VERDICT_VALUES` (`ui/src/lib/enums.ts`); the badge **MUST** carry the `convergence_verdict` glossary tooltip.

### FR-5: Demo scenarios show real optimization lift
- The system **MUST** enrich the five small `SCENARIOS` (docs + graded judgments) so that, after `make seed-demo`, each enriched scenario's primary (LLM) study lands a baseline NDCG@10 in roughly `[0.40, 0.70]` and a best NDCG@10 that (a) is `< 0.99` (no ceiling badge) and (b) improves over the baseline by `≥ 0.10` absolute.
- Notes: This is empirical — the judgments must encode a ranking tradeoff the tunable params (e.g., `title_boost` vs `description_boost`) can resolve. Authored against more candidate docs per index (target ~12–20) with graded judgments spanning ratings 3/2/1/0 (target ~5–8 graded docs/query).

### FR-6: Demo trial budget reads a meaningful convergence verdict
- The system **MUST** raise the small-scenario `max_trials` from 12 to `STUDIES_TPE_WARMUP_FLOOR` (50) so the convergence verdict can read `converged` / `still_improving` rather than a uniform `too_few_trials`.
- The system **SHOULD** keep the bump no larger than needed to clear the warmup floor (50), to limit seed wall-clock. The rich scenario's `max_trials` is unchanged.

### FR-7: Single-source + parity preserved
- The enriched `SCENARIOS` **MUST** remain defined once in `seed_meaningful_demos.py` and imported by `demo_seeding.py`. The slug-parity guard (`scripts/ci/verify_demo_slug_parity.sh`) **MUST** still pass (slugs unchanged). The UBI allowlist pairs are unchanged.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies` | List studies — response items gain `trial_count` + `convergence_verdict` | (unchanged; read-only) |

No new endpoint. The detail endpoint `GET /api/v1/studies/{id}` is unchanged (already carries the full `convergence` shape + `trials_summary`).

### 7.2 Contract rules

- The two new fields are additive and non-breaking. `convergence_verdict` is nullable.
- `trial_count` is always present (int, ≥ 0).

### 7.3 Response examples

`GET /api/v1/studies` success (one item shown):
```json
{
  "data": [
    {
      "id": "019e8875-4be3-74d2-8b38-d47626b86fe0",
      "name": "tune-product-title-boost-baseline (LLM)",
      "cluster_id": "019e886f-6e7f-7a22-80df-8ee87839c34c",
      "status": "completed",
      "best_metric": 0.842,
      "direction": "maximize",
      "trial_count": 50,
      "convergence_verdict": "converged",
      "created_at": "2026-06-02T12:00:00Z",
      "completed_at": "2026-06-02T12:06:00Z"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

In-flight / low-trial item (verdict null):
```json
{
  "id": "019e8877-...",
  "name": "tune-jobtitle-vs-company-boost (UBI)",
  "status": "running",
  "best_metric": null,
  "direction": "maximize",
  "trial_count": 7,
  "convergence_verdict": null,
  "created_at": "2026-06-02T12:10:00Z",
  "completed_at": null
}
```

Failure example (unchanged envelope — e.g. bad cursor): per api-conventions `{ "detail": { "error_code": "VALIDATION_ERROR", "message": "...", "retryable": false } }`.

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `convergence_verdict` | `converged`, `still_improving`, `too_few_trials`, `null` | `backend/app/domain/study/convergence.py` (`ConvergenceVerdict` `Literal[...]`) | convergence badge column in `ui/src/components/studies/studies-table.column-config.tsx`; values from `CONVERGENCE_VERDICT_VALUES` (`ui/src/lib/enums.ts:77`) |
| `?status` (studies, unchanged) | `queued`, `running`, `completed`, `cancelled`, `failed` | `backend/app/api/v1/schemas.py` (`StudyStatusWire`) | status filter (`STUDY_STATUS_VALUES`) |

### 7.5 Error code catalog

No new error codes (read-only additive fields).

## 9) Data model and state transitions

### New/changed entities

**No migration.** Both new fields are computed per request, not persisted.

**Modified schema (not a DB table): `StudySummary`** (`backend/app/api/v1/schemas.py`)
- Add `trial_count: int` — total trial rows for the study.
- Add `convergence_verdict: ConvergenceVerdict | None` — verdict literal (re-export the `ConvergenceVerdict` type from the domain module, as `StudyDetail.convergence` already re-exports `StudyConvergenceShape`).

**New repo helper:** `count_trials_for_studies(db, study_ids: list[str]) -> dict[str, TrialCounts]` in `backend/app/db/repo/trial.py` — one `GROUP BY study_id` returning `(total, complete)` per study. **Predicate precision (GPT-5.5 cycle 2 F1):** `trials.is_baseline` is `BOOLEAN NOT NULL DEFAULT FALSE` (model `trial.py:114`; migration `0020`), so no NULL rows exist and `is_(False)` ≡ `is_not(True)` today. To keep each count's parity target unambiguous, the helper MUST mirror the predicate of the path it claims parity with: `total` uses `is_baseline.is_(False)` (matches `aggregate_trials_summary` → `trials_summary.total`); `complete` uses `is_baseline.is_not(True)` + `status == "complete"` (matches `list_complete_optuna_trials_for_study`, the classifier's own filter). A unit test asserts both counts equal their parity source on the same fixture.

**New repo helper:** `list_complete_optuna_trials_for_studies(db, study_ids: list[str]) -> dict[str, list[Trial]]` in `backend/app/db/repo/trial.py` — the batched sibling of `list_complete_optuna_trials_for_study`: one `SELECT ... WHERE study_id IN (...) AND status='complete' AND is_baseline IS NOT TRUE ORDER BY study_id, optuna_trial_number`, grouped in Python. Called once per list request for the `complete ≥ 50` subset only.

**New service helper:** `resolve_list_convergence_verdicts(db, studies, trial_counts) -> dict[str, ConvergenceVerdict | None]` in `backend/app/services/study_convergence.py` — applies gates 1–3 (in-flight → direction → count) per study without loading trials, collects the `complete ≥ 50` subset, batch-loads their trials via `list_complete_optuna_trials_for_studies`, and classifies each in memory via `classify_convergence` (try/except per study → `None` on exception, mirroring `fetch_study_convergence`). Reuses the existing `_resolve_direction`.

### Required invariants

- The list verdict for a given study MUST equal `fetch_study_convergence(...).verdict` (when non-null) — same classifier, same inputs. (Asserted by a cross-check test.)
- Demo `SCENARIOS` remain a single definition imported by both seed paths.

### State transitions

None — read-only feature + seed-data change.

### Idempotency/replay behavior

N/A.

## 10) Security, privacy, and compliance

- Threats: none new — read-only additive fields + demo seed data. No secrets, no PII (demo data is synthetic).
- Controls: existing list-endpoint validation unchanged.
- Auditability: N/A (read-only).
- Data retention: N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** `/studies` list table (existing). Two new columns added to `<StudiesTable>`.
- **Labeling taxonomy:** "Trials" (numeric count); convergence badge column header "Convergence". Badge labels (compact for the dense list): `Converged` (success/green), `Improving` (warning/amber), `Too few trials` (warning/amber), `—` for null. The detail panel keeps its fuller labels ("Still improving when it stopped", "Too few trials to tell").
- **Content hierarchy:** Trials column sits after `best_metric`; Convergence badge sits adjacent so the operator reads "metric — trials — did it converge?" left to right. Both are hideable via the column-visibility menu (default visible).
- **Progressive disclosure:** The list badge is the at-a-glance cue; the detail page's `<ConvergencePanel>` remains the deep view (curve, window numerics). The badge tooltip links to the convergence runbook (via the existing `convergence_verdict` glossary entry).
- **Relationship to existing pages:** Extends the existing list; the ceiling badge (best_metric column) and the new convergence badge are complementary — a ceiling-pinned study that also reads `too_few_trials` now visibly explains *why* the 0.99 isn't trustworthy.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Convergence badge | (reuse existing glossary key `convergence_verdict`) | info icon / hover | inline next to badge |
| "Trials" column header | "Number of optimization trials this study ran." (new glossary key `study.trial_count` — added in Epic A) | hover | column header |

Both trace to `ui/src/lib/glossary.ts` (one existing key reused; one new key `study.trial_count` added in scope per the contextual-help discipline).

### Primary flows

1. Operator opens `/studies` → sees each study's trial count + a convergence badge → identifies which studies actually converged vs. ran too few trials, without opening each.
2. Operator runs `make seed-demo` → opens `/studies` → the enriched demo studies show non-ceiling best_metrics with visible lift and `Converged` badges (after 50 trials).

### Edge/error flows

- Study with `< 5` complete trials → no badge (em-dash). Trials column still shows the count.
- In-flight (`running`/`queued`) study → no badge (verdict null) even if trial_count > 5.
- `minimize`-direction study → convergence still computed (direction-aware); ceiling badge already suppressed for minimize (existing behavior).
- A study with `≥ 50` trials whose tail is still rising → `Improving` badge.

## 12) Given/When/Then acceptance criteria

### AC-1: List item exposes trial_count
- Given a completed study with N non-baseline trial rows (plus its 1 baseline row)
- When `GET /api/v1/studies` returns it
- Then the item has `trial_count == N` (baseline excluded), equal to the detail page's `trials_summary.total`.
- Example: study run with `max_trials=50` → 50 non-baseline trials + 1 baseline → `trial_count == 50`.

### AC-2: List verdict matches detail verdict
- Given any study
- When both `GET /api/v1/studies` (list) and `GET /api/v1/studies/{id}` (detail) are called
- Then `list.convergence_verdict == detail.convergence.verdict` (treating detail `convergence: null` as a null verdict), for every case: in-flight, invalid-direction, `<5`, `5–49`, and `≥50`.

### AC-3: Cheap path for low-trial studies
- Given a completed study with 12 complete non-baseline trials
- When the list is built
- Then `convergence_verdict == "too_few_trials"` AND no trial-load query runs for that study (count-gated).
- Example values: complete=12 → `too_few_trials`; complete=4 → `null`; complete=60 → classifier invoked.

### AC-3b: Invalid-direction parity (direction gate before count gate)
- Given a `completed` study with 12 complete trials whose `objective.direction` is invalid/unrecognized
- When both list and detail are built
- Then both yield a null verdict (`list.convergence_verdict == null` AND `detail.convergence == null`) — the direction gate fires before the count gate, so it does NOT incorrectly read `too_few_trials`.

### AC-4: In-flight short-circuit
- Given a `running` study with 30 complete trials
- When the list is built
- Then `convergence_verdict == null`.

### AC-5: Bounded queries — no N+1
- Given a page of K studies of which M have `complete ≥ 50`
- When the list is built
- Then trial data is produced by exactly two queries regardless of K and M: one count aggregate (`GROUP BY study_id`) + one batched trial-load (`WHERE study_id IN (...)`, only when M > 0). No per-study query.

### AC-6: Frontend renders columns + badge
- Given the list response above
- When `/studies` renders
- Then a "Trials" cell shows `50` and a convergence badge shows "Converged"; a null-verdict row shows "—"; the badge values come from `CONVERGENCE_VERDICT_VALUES`.

### AC-7: Demo studies show real lift (no ceiling)
- Given a freshly run `make seed-demo FORCE=1` (deterministic — `seed=42`, TPE sampler, fixed scenario data)
- When each enriched small scenario's LLM study completes
- Then, reading the persisted `Study.baseline_metric` and `Study.best_metric` columns (both exposed on `GET /studies/{id}`):
  - `best_metric < 0.99` (no ceiling badge), AND
  - `best_metric - baseline_metric ≥ 0.10`, AND
  - `0.40 ≤ baseline_metric ≤ 0.70`.
- Verification (all FIVE enriched scenarios guarded in CI — GPT-5.5 cycle 2 F2):
  1. **Engine-backed headroom test, parameterized over all 5 scenarios** (integration; needs ES/OS/Solr per scenario, deterministic — no optimizer): render each scenario's template with its **default/baseline** param values and with a **known-better** param set, evaluate NDCG@10 against the authored docs+judgments via the existing eval engine, and assert `0.40 ≤ baseline ≤ 0.70`, `better − baseline ≥ 0.10`, and `better < 0.99`. This proves the authored data has real optimization headroom for every scenario without running a full study.
  2. **One `@pytest.mark.slow` end-to-end seed test** for a representative scenario: seeds + runs the actual 50-trial study and asserts the persisted `Study.baseline_metric`/`best_metric`/`convergence_verdict` (validates the full pipeline + AC-8).
  3. **Manual `make seed-demo FORCE=1`** operator-path at release gate (all 5, real engines).
- Because the seed is deterministic (`seed=42`), bounds are reproducible (not flaky).
- Example: `jobs-marketplace-prod` baseline ≈ 0.55 → best ≈ 0.80.

### AC-8: Demo convergence reads meaningfully
- Given the enriched scenarios run `max_trials=50` (the warmup floor)
- When their LLM studies complete
- Then `trial_count == 50` and `convergence_verdict ∈ {converged, still_improving}` (NOT `too_few_trials`) for every enriched LLM study.

### AC-9: Parity + single-source preserved
- Given the enriched `SCENARIOS`
- When `scripts/ci/verify_demo_slug_parity.sh` runs
- Then it passes (slugs unchanged); `demo_seeding.py` still imports `SCENARIOS` (no duplicated dicts).

## 13) Non-functional requirements

- Performance: list endpoint p99 comparable to today at demo scale; bounded queries per FR-3.
- Reliability: the list MUST degrade gracefully — a classifier exception for one study yields a null verdict for that study (mirroring `fetch_study_convergence`'s try/except), never a 500 for the whole list.
- Operability: no new logs required; reuse existing convergence WARN logs if a per-study classify fails.
- Accessibility: convergence badge carries an aria-label via the existing `InfoTooltip` pattern.

## 14) Test strategy requirements

- **Unit** (`backend/tests/unit/`): the gate logic in `resolve_list_convergence_verdicts` (in-flight null, **invalid-direction null even at 5–49 trials** per AC-3b, null `<5`, `too_few_trials` `5–49`, classifier `≥50`); demo scenario shape invariants (graded-rating spread spanning 3/2/1/0, doc/judgment counts) in `backend/tests/unit/scripts/`.
- **Integration** (`backend/tests/integration/`): list endpoint returns correct `trial_count` (non-baseline) + `convergence_verdict` against seeded trials at the count bands + an in-flight study + an invalid-direction study; the **bounded-query assertion** (exactly 2 added queries regardless of page size — count via a query-counter/`echo` capture or an explicit assertion on the batched helpers). the **engine-backed headroom test parameterized over all 5 enriched scenarios** (baseline vs known-better param NDCG@10 bounds — the primary FR-5 CI guard, deterministic, no optimizer) + one `@pytest.mark.slow` end-to-end seed test for a representative scenario asserting persisted `Study.baseline_metric`/`best_metric`/`convergence_verdict`.
- **Contract** (`backend/tests/contract/`): `StudySummary` JSON schema includes `trial_count` (int) + `convergence_verdict` (`ConvergenceVerdict | null`); list response item shape.
- **E2E** (`ui/tests/e2e/`): `/studies` renders the Trials column + convergence badge against the real backend (real-browser assertion, no `page.route()` mocking).
- **Frontend unit** (vitest): studies-table column config renders the badge per verdict + null; verdict values sourced from enums (the existing discipline lint guard covers drift).

## 15) Documentation update requirements

- `docs/03_runbooks/convergence-verdict.md`: note the verdict now also appears on the studies list (not just detail).
- `docs/01_architecture/ui-architecture.md`: studies-table gains Trials + Convergence columns (if the table's column inventory is documented there).
- `docs/08_guides/tutorial-first-study.md`: if it screenshots the studies list or describes demo metrics, refresh the "what you'll see" copy (the demo now shows non-ceiling lift). Guide-gen impact assessed at impl-execute.
- `state.md`: record the feature on merge.

## 16) Rollout and migration readiness

- Feature flags: none (additive read-only fields + demo data).
- Migration/backfill: none (no schema change).
- Operational readiness: `make seed-demo` re-run after merge to refresh local demo data; document in the runbook.
- Release gate: backend lint/typecheck/tests + 80% coverage; frontend lint/tsc/vitest/build; the new E2E; `verify_demo_slug_parity.sh` green; a manual `make seed-demo FORCE=1` confirming FR-5/FR-6 ranges (operator-path verification).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-5 | Epic A: schema + `count_trials_for_studies` + list builder | contract `test_studies_api_contract.py`; integration `test_studies_list_convergence.py` | ui-architecture |
| FR-2 | AC-2, AC-3, AC-4 | Epic A: `resolve_list_convergence_verdicts` + list builder | unit `test_list_convergence_resolver.py`; integration | convergence-verdict runbook |
| FR-3 | AC-5 | Epic A: batched query + count gate | integration (query-count assertion) | — |
| FR-4 | AC-6 | Epic A: column-config + badge + glossary key | vitest column-config test; E2E | ui-architecture |
| FR-5 | AC-7 | Epic B: enrich docs + judgments | unit scenario-shape; integration demo-seed | tutorial |
| FR-6 | AC-8 | Epic B: max_trials 12→50 | integration demo-seed | — |
| FR-7 | AC-9 | Epic B: keep single import; parity guard | `verify_demo_slug_parity.sh`; scenario tests | — |

## 18) Definition of feature done

- [ ] All AC-1…AC-9 pass in CI.
- [ ] Unit/integration/contract/E2E + frontend vitest green.
- [ ] `verify_demo_slug_parity.sh` green.
- [ ] Manual `make seed-demo FORCE=1` confirms FR-5/FR-6 ranges (operator-path verification logged).
- [ ] Docs (runbook, ui-architecture, tutorial copy) updated.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

_None — Q1 and Q2 resolved below (D-11, D-12) so the plan can assign concrete trial budgets and test assertions._

### Decision log
- 2026-06-02 — **D-1** (user): enrich judgments + bump trials (vs. judgments-only / rich-flagship / leave-as-is).
- 2026-06-02 — **D-2** (user): list shows trial count + full convergence verdict badge (vs. count-only / 'too-few' flag only).
- 2026-06-02 — **D-3** (user): keep the honest ceiling + `too_few_trials` badges; this fixes the demo, it does not hide the signal.
- 2026-06-02 — **D-4**: list adds `trial_count` (total) + `convergence_verdict` (verdict literal only); full `StudyConvergenceShape` stays detail-only (payload + perf).
- 2026-06-02 — **D-5**: compute verdict via cheap count-gate (`<5` null / `5–49` too_few / `≥50` classify) over one batched count query; classifier runs only for `≥50`. No N+1 for demo scale.
- 2026-06-02 — **D-6**: reuse `classify_convergence` + `list_complete_optuna_trials_for_study` + existing direction resolution; no forked verdict logic.
- 2026-06-02 — **D-7**: frontend verdict values from `CONVERGENCE_VERDICT_VALUES`; reuse `convergence_verdict` glossary key; compact list labels ("Improving", "Too few trials").
- 2026-06-02 — **D-8**: demo enrichment targets — ~12–20 docs/index, ~5–8 graded docs/query spanning 3/2/1/0, baseline NDCG@10 ∈ [0.40,0.70], best `< 0.99` with `≥ 0.10` absolute lift. Rich scenario untouched.
- 2026-06-02 — **D-9**: accept seed wall-clock increase from the bump; smoke is opt-in/off (`state.md`), so not a CI blocker; keep the bump ≤ 50.
- 2026-06-02 — **D-10**: single phase, two epics (A then B), both in scope (honors `--all`).
- 2026-06-02 — **D-11** (resolves Q1, GPT-5.5 cycle 1 F5): lock small-scenario `max_trials = 50` (the warmup floor) — non-negotiable for AC-8. The seed-wall-clock cost is accepted (D-9); if it ever proves prohibitive that is a separate follow-up, not a re-scope of this feature.
- 2026-06-02 — **D-12** (resolves Q2): bump BOTH the LLM and the UBI study per scenario to `max_trials = 50` for symmetry; AC-8 gates on the LLM studies.
- 2026-06-02 — **D-13** (GPT-5.5 cycle 1 F1/F8): `trial_count` = **non-baseline** trials, matching `trials_summary.total` (which excludes baseline per FR-11). A `max_trials=50` study shows `trial_count=50`; the "optimization trials" tooltip is therefore correct.
- 2026-06-02 — **D-14** (GPT-5.5 cycle 1 F6): batch the `complete ≥ 50` trial load into one `WHERE study_id IN (...)` query (`list_complete_optuna_trials_for_studies`), classify in memory → exactly 2 added queries per list request regardless of page size.
- 2026-06-02 — **D-15** (GPT-5.5 cycle 1 F2): gate order on the list is in-flight → direction-validity → count → classifier; the first two are cheap and fire before the count gate, guaranteeing list/detail verdict parity for invalid-direction completed studies (AC-3b).
- 2026-06-02 — **D-16** (GPT-5.5 cycle 1 F4/F7): Epic B verification reads persisted `Study.baseline_metric` + `Study.best_metric`; the seed's `seed=42` determinism makes AC-7's bounds reproducible; AC-7 ships as a `@pytest.mark.slow` CI gate on the seed lane plus the manual operator-path check.
- 2026-06-02 — **D-17** (GPT-5.5 cycle 2 F1): `is_baseline` is `BOOLEAN NOT NULL DEFAULT FALSE`, so `is_(False)` ≡ `is_not(True)`; the new count helper pins `total → is_(False)` (parity with `aggregate_trials_summary`) and `complete → is_not(True)` (parity with `list_complete_optuna_trials_for_study`), with a unit test asserting equality to each parity source.
- 2026-06-02 — **D-18** (GPT-5.5 cycle 2 F2): all 5 enriched scenarios are guarded in CI by a deterministic **engine-backed headroom test** (baseline-vs-better-param NDCG@10 bounds, no optimizer); the full 50-trial study run is exercised end-to-end for one representative scenario (`@pytest.mark.slow`) + manually for all 5 at release gate. This avoids 5×50-trial CI cost while keeping FR-5 a CI gate, not manual-only.
