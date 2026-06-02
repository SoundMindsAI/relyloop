# Implementation Plan — Studies-list convergence visibility + real demo data

**Date:** 2026-06-02
**Status:** Complete — Epic 1 via PR #421 (`e5c3b8b9`), Epic 2 via PR #422 (squash-merged `49a0e1b0`, 2026-06-02)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md (conventions, absolute rules); `feat_study_convergence_indicator` (classifier reuse)

---

## 0) Planning principles

- Every story traces to FRs from the spec.
- Reuse `classify_convergence` + the detail-page direction resolution — never fork verdict logic.
- No migration (trial_count + verdict are computed per request).
- Epic A is deterministic UI/API; Epic B is empirical data authoring validated by a deterministic engine-backed headroom test.

## 1) Scope traceability (FR → epics)

| FR ID | Epic | Notes |
|---|---|---|
| FR-1 (trial_count) | Epic 1 / Story 1.1 | non-baseline count, batched aggregate |
| FR-2 (convergence_verdict) | Epic 1 / Story 1.1 | gate order in-flight→direction→count→classifier |
| FR-3 (perf budget) | Epic 1 / Story 1.1 | 2 bounded queries |
| FR-4 (frontend columns + badge) | Epic 1 / Story 1.2 | reuse enum + glossary |
| FR-5 (demo real lift) | Epic 2 / Story 2.1, 2.3 | enriched docs + graded judgments; headroom test |
| FR-6 (max_trials 12→50) | Epic 2 / Story 2.2 | LLM + UBI studies |
| FR-7 (single-source + parity) | Epic 2 / Story 2.1, 2.2 | keep SCENARIOS import; slug guard |

Single phase — no deferred phases, no `phaseN_idea.md` needed.

## 2) Delivery structure — Epic → Story → Tasks → DoD

### Conventions
- Repo functions take `db: AsyncSession` first; `db.flush()`/`execute`, caller commits; export via `__all__`.
- Services are async; domain is pure (no DB/IO/async).
- Pydantic response models re-export domain types (`ConvergenceVerdict`) the same way `StudyDetail.convergence` re-exports `StudyConvergenceShape`.
- Frontend `StudySummary` is **generated** from the backend OpenAPI schema (`components['schemas']['StudySummary']` at `ui/src/lib/api/studies.ts:18`) — adding backend fields requires an OpenAPI type regen, not a hand-edit.

### AI Agent Execution Protocol
Standard (read architecture.md + state.md first; backend → tests → frontend → E2E → docs). No migration round-trip (no schema change).

---

## Epic 1 — Studies-list trial count + convergence badge (FR-1…FR-4)

### Story 1.1 — Backend: trial_count + convergence_verdict on the list response
**Outcome:** `GET /api/v1/studies` items carry `trial_count` (non-baseline total) and `convergence_verdict`, computed in 2 bounded queries, reusing the shipped classifier.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/trial.py` | Add `count_trials_for_studies(db, study_ids)` (one `GROUP BY study_id`; `total` via `is_baseline.is_(False)`, `complete` via `is_baseline.is_not(True) AND status=='complete'`) + `list_complete_optuna_trials_for_studies(db, study_ids)` (batched `WHERE study_id IN (...)`, grouped in Python). |
| `backend/app/db/repo/__init__.py` | Export the two helpers via `__all__`. |
| `backend/app/services/study_convergence.py` | Add `resolve_list_convergence_verdicts(db, studies, trial_counts)` — gates 1–3 per study (in-flight → `_resolve_direction` → count), batch-load `complete≥50` subset, classify in memory (try/except per study → None). Reuse existing `_resolve_direction` + `_IN_FLIGHT_STATUSES`. |
| `backend/app/api/v1/schemas.py` | `StudySummary` += `trial_count: int` and `convergence_verdict: ConvergenceVerdict | None = None` (import/re-export `ConvergenceVerdict` from `backend.app.domain.study.convergence`). |
| `backend/app/api/v1/studies.py` | In `list_studies`: after `repo.list_studies(...)`, call `count_trials_for_studies(db, [r.id for r in rows])` + `resolve_list_convergence_verdicts(...)`; change `_summary(row)` → `_summary(row, trial_count, verdict)` to populate the two fields. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies` | — (unchanged query params) | `200` `StudyListResponse` — each `data[]` item now includes `trial_count: int`, `convergence_verdict: "converged"\|"still_improving"\|"too_few_trials"\|null` | unchanged |

**Key interfaces**
```python
# db/repo/trial.py
async def count_trials_for_studies(db: AsyncSession, study_ids: list[str]) -> dict[str, TrialCounts]: ...   # {study_id: (total, complete)}
async def list_complete_optuna_trials_for_studies(db: AsyncSession, study_ids: list[str]) -> dict[str, list[Trial]]: ...

# services/study_convergence.py
async def resolve_list_convergence_verdicts(
    db: AsyncSession,
    studies: Sequence[Study],
    trial_counts: dict[str, TrialCounts],
) -> dict[str, ConvergenceVerdict | None]: ...
```

**Pydantic schemas**
```python
class StudySummary(BaseModel):
    # ...existing 8 fields...
    trial_count: int
    convergence_verdict: ConvergenceVerdict | None = None
```

**Tasks**
1. Add the two repo helpers + export; add a small `TrialCounts` NamedTuple/dataclass (or reuse a tuple) in `trial.py`.
2. Add `resolve_list_convergence_verdicts` mirroring `fetch_study_convergence`'s gates 1–2, then count gate, then batched classify.
3. Extend `StudySummary` + re-export `ConvergenceVerdict`; update `_summary` + `list_studies` builder.
4. Write unit + integration + contract tests (see §3).

**DoD**
- `GET /studies` returns both fields; `list.convergence_verdict == detail.convergence.verdict` for in-flight, invalid-direction, `<5`, `5–49`, `≥50` (AC-2, AC-3b).
- Bounded-query assertion passes (AC-5): **1 count aggregate always; + 1 batched trial-load ONLY when the `complete ≥ 50` subset is non-empty.** Test both M=0 (1 added query — e.g. a page of 12-trial studies) and M>0 (2 added queries — a page with a ≥50-trial study). (Plan-cycle-1 F1.)
- `make test-unit && make test-integration && make test-contract` green; `make lint && make typecheck` green.

### Story 1.2 — Frontend: Trials column + convergence badge
**Outcome:** `/studies` shows a "Trials" count column and a convergence badge column.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| (generated) `ui/src/lib/api/*` OpenAPI types | Regenerate from backend OpenAPI so `StudySummary` carries `trial_count` + `convergence_verdict` (run the project's openapi-typescript regen; do NOT hand-edit). |
| `ui/src/components/studies/studies-table.column-config.tsx` | Add a `trials` column (renders `trial_count`) and a `convergence` badge column (maps verdict → label/variant; `null` → em-dash). Import `CONVERGENCE_VERDICT_VALUES` for the source-of-truth comment. |
| `ui/src/lib/glossary.ts` | Add `study.trial_count` entry (tooltip: "Number of optimization trials this study ran (excludes the baseline trial)."). Reuse existing `convergence_verdict` key for the badge. |

**UI element inventory**
- "Trials" column — header "Trials"; data `row.original.trial_count`; right-aligned numeric; hideable; `InfoTooltip glossaryKey="study.trial_count"` on header.
- "Convergence" badge column — header "Convergence"; data `row.original.convergence_verdict`; renders `<Badge variant>` per the map below; `null` → `<span className="text-muted-foreground">—</span>`; `InfoTooltip glossaryKey="convergence_verdict"` adjacent. Compact labels: `converged`→"Converged"(success), `still_improving`→"Improving"(warning), `too_few_trials`→"Too few trials"(warning). **The label/variant map MUST be typed against the enum** — `const VERDICT_BADGE = {...} satisfies Record<ConvergenceVerdict, {label,variant}>` where `ConvergenceVerdict = (typeof CONVERGENCE_VERDICT_VALUES)[number]` — so a missing/extra verdict is a compile error, not just a comment. Source-of-truth comment: `// Verdict values must match backend/app/domain/study/convergence.py ConvergenceVerdict (via CONVERGENCE_VERDICT_VALUES)`. (Plan-cycle-1 F3.)

**Tasks**
1. Regenerate OpenAPI types (after Story 1.1 backend lands).
2. Add the two columns to `studiesColumns` mirroring the existing `best_metric` ceiling-badge JSX pattern (Badge + InfoTooltip).
3. Add the `study.trial_count` glossary entry.
4. Vitest column-config tests (badge per verdict + null em-dash + trial_count render) + an E2E assertion on `/studies`.

**DoD**
- `/studies` renders Trials + Convergence columns; badge values from `CONVERGENCE_VERDICT_VALUES`.
- `pnpm typecheck && pnpm lint && pnpm test && pnpm build` green; the enum-discipline + glossary lint guards pass.
- E2E (real backend) asserts the columns render against seeded studies.

**Epic 1 gate:** both list fields live + rendered; AC-1…AC-6 covered by tests.

---

## Epic 2 — Demo data enrichment for real optimization value (FR-5…FR-7)

### Story 2.1 — Enrich the 5 small scenarios (docs + graded judgments)
**Outcome:** Each small scenario indexes more candidate docs with denser graded judgments so the baseline config under-ranks and the optimizer finds real lift.

**Modified files**

| File | Change |
|---|---|
| `scripts/seed_meaningful_demos.py` | For each of the 5 small `SCENARIOS` (acme-products-prod, corp-docs-search, news-search-staging, jobs-marketplace-prod, acme-kb-docs-solr): expand `docs` to ~12–20/index and rewrite `judgments_map` to ~5–8 graded docs per query spanning ratings 3/2/1/0, designed so the default param values mis-rank (baseline NDCG@10 ∈ [0.40,0.70]) and a better param set lifts ≥0.10. Keep slugs, targets, template params, and search spaces. |

**Design method (per scenario):** author judgments that create a tunable tradeoff — e.g. acme-products (title_boost vs description_boost): some queries whose best answer matches on `description` (reward higher description_boost) and others on `title`, so no single default wins and the optimizer must balance. Use the existing template params; do NOT add new params. `demo_seeding.py` inherits via the `SCENARIOS` import (FR-7) — no second edit. Enriched judgments automatically enrich synthetic UBI (`fabricate_ubi_for_scenario` consumes `judgments_map`).

**Tasks**
1. Per scenario: add candidate docs (varied relevance) + rewrite `judgments_map` with graded ratings.
2. Validate iteratively against the headroom test (Story 2.3) — adjust until baseline/lift bounds hold for all 5.
3. Update any hardcoded doc/judgment counts in existing scenario tests.

**DoD**
- Engine-backed headroom test (Story 2.3) **passes (hard) for the 4 ES/OS scenarios** — an unreachable ES/OS container fails the test (CI-infra error), it does NOT skip. The Solr scenario skip-gates only when Solr is unreachable.
- `verify_demo_slug_parity.sh` green (slugs unchanged); `demo_seeding.py` still imports `SCENARIOS` (no duplication).

### Story 2.2 — Raise demo `max_trials` 12 → 50
**Outcome:** Small-scenario studies run 50 trials so convergence reads `converged`/`still_improving`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/demo_seeding.py` | `_REAL_STUDY_MAX_TRIALS: Final[int] = 12` → `50` (line ~150); confirm the study `config` dict at ~1039 uses the constant. Applies to both the LLM and UBI studies per scenario (D-12). |
| `scripts/seed_meaningful_demos.py` | `config` `max_trials: 12` → `50` (line ~950) for the small-scenario `_create_one_study`. Keep the rich scenario at 15. |

**Single-source requirement (plan-cycle-1 F5):** the small-scenario `max_trials` value MUST be single-sourced — define one shared constant (e.g. `DEMO_SMALL_STUDY_MAX_TRIALS = 50`) imported by both `demo_seeding.py` and `seed_meaningful_demos.py` so the two paths cannot drift. If a shared import is genuinely infeasible, a **hard** parity contract test asserting both paths resolve to the same value is required (not optional). `verify_demo_slug_parity.sh` stays slug-only.

**Tasks**
1. Introduce the shared constant `DEMO_SMALL_STUDY_MAX_TRIALS = 50`; reference it from both the service constant `_REAL_STUDY_MAX_TRIALS` and the script config; keep rich at 15.
2. Add a test asserting both paths read the same value (belt-and-suspenders even with the shared constant).

**DoD**
- Enriched LLM studies show `trial_count == 50` and a non-`too_few_trials` verdict (AC-8) in the `@slow` seed test.

### Story 2.3 — Demo enrichment tests
**Outcome:** All 5 enriched scenarios are guarded in CI deterministically; the full pipeline is validated end-to-end for one.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_demo_scenarios_headroom.py` | Engine-backed headroom test parameterized over all 5 scenarios: render template with default vs known-better params, evaluate NDCG@10 (`backend/app/eval/scoring.py`) against authored docs+judgments, assert `0.40≤baseline≤0.70`, `better−baseline≥0.10`, `better<0.99`. **CI scope (D-18):** the 4 ES/OS scenarios are hard CI gates; the Solr scenario skip-gates via `is_engine_reachable` (no Solr container in backend CI) and is covered by the manual operator-path. |
| `backend/tests/unit/scripts/test_scenarios_judgment_density.py` | Pure shape invariants: each enriched scenario has ≥ target docs, each query has ≥ N graded judgments spanning ≥3 distinct ratings, ratings ∈ {0,1,2,3}. |

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_full.py` (+ siblings) | Add/adjust a `@pytest.mark.slow` end-to-end seed assertion reading persisted `Study.baseline_metric`/`best_metric`/`convergence_verdict` for one representative scenario (AC-7 pipeline + AC-8). Update any counts that assumed 5 docs / sparse judgments / 12 trials. |

**DoD**
- Headroom test: 4 ES/OS scenarios pass as hard gates (ES/OS unreachable → fail); Solr scenario skip-gates only when Solr is unreachable. Shape test passes; the `@slow` seed test passes locally.
- Existing seeding/scenario tests updated and green.

**Epic 2 gate:** `make seed-demo FORCE=1` (operator-path) shows all 5 small scenarios with `best_metric < 0.99`, visible lift, and `converged`/`still_improving` badges.

---

## 3) Testing workstream

### 3.1 Unit (`backend/tests/unit/`)
- [ ] `test_list_convergence_resolver.py` — gate logic: in-flight→null, invalid-direction→null at 5–49 (AC-3b), `<5`→null, `5–49`→too_few_trials, `≥50`→classifier; no trial-load for `<50`.
- [ ] `test_scenarios_judgment_density.py` — enriched-data shape invariants (Story 2.3).
- [ ] `count_trials_for_studies` parity unit (total≡`is_(False)`, complete≡classifier filter) on a fixture.

### 3.2 Integration (`backend/tests/integration/`)
- [ ] `test_studies_list_convergence.py` (new, mirrors `test_studies_api_convergence.py`) — list returns correct `trial_count` (non-baseline) + verdict at each band + in-flight + invalid-direction; **bounded-query assertion** via a statement counter: M=0 page → 1 added query; M>0 page → 2 added queries.
- [ ] `test_demo_scenarios_headroom.py` (new) — all-5 headroom bounds (Story 2.3).
- [ ] `@slow` end-to-end seed assertion (Story 2.3).

### 3.3 Contract (`backend/tests/contract/`)
- [ ] Extend `test_studies_api_contract.py` — `StudySummary` JSON schema includes `trial_count` (integer) + `convergence_verdict` (`ConvergenceVerdict | null`); a list item carries both.

### 3.4 E2E (`ui/tests/e2e/`)
- [ ] `/studies` renders Trials column + convergence badge against the real backend (real `page` interactions; no `page.route()`).

### 3.5 Frontend unit (vitest)
- [ ] `studies-table.column-config` test: badge per verdict + null em-dash + trial_count cell; verdict values sourced from `CONVERGENCE_VERDICT_VALUES`.

### 3.5 Existing test impact

| Test file | Pattern | Action |
|---|---|---|
| `backend/tests/contract/test_studies_api_contract.py` | StudySummary schema | Add new-field assertions. |
| `backend/tests/unit/scripts/test_scenarios_ubi_config.py` | scenario pairs/counts | Verify still passes after enrichment (slugs/pairs unchanged); update any count asserts. |
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | seeded counts/metrics | Update doc/judgment/trial-count expectations + add AC-7/8 assertions. |
| `ui/src/__tests__/components/studies/*` | studies-table render | Add new-column assertions. |

### 3.6 CI gates
- [ ] `make test-unit` / `make test-integration` / `make test-contract`
- [ ] `cd ui && pnpm test && pnpm build`
- [ ] `scripts/ci/verify_demo_slug_parity.sh`

No migration (§3.5 migration verification N/A).

## 4) Documentation update workstream

- [ ] `state.md` — record on merge (Epic A + B; no Alembic head change).
- [ ] `docs/03_runbooks/convergence-verdict.md` — note the verdict now also appears on the studies list.
- [ ] `docs/01_architecture/ui-architecture.md` — studies-table column inventory gains Trials + Convergence.
- [ ] `docs/08_guides/tutorial-first-study.md` — refresh any "what you'll see" copy now that demo studies show non-ceiling lift (guide-gen impact assessed at impl-execute).

## 5) Lean refactor workstream
- [ ] Ensure the `max_trials` demo value is single-sourced across CLI + service (Story 2.2) — collapse to one constant if cheap.
- [ ] No speculative redesign. The list verdict reuses the classifier; do not duplicate it.

## 6) Dependencies, risks, mitigations

### Dependencies
| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `classify_convergence` + repo helper + frontend enum/glossary | Epic 1 | implemented (PR #352) | N/A |
| OpenAPI type regen tooling | Story 1.2 | implemented (`ui/src/lib/api`) | frontend type drift |
| Running ES/OS (+ Solr local) | Story 2.3 headroom test | available | Solr skip-gated in CI |

### Risks
| Risk | L | I | Mitigation |
|---|---|---|---|
| Authored judgments don't hit baseline/lift bounds for some scenario | H | M | Iterate against the deterministic headroom test (fast feedback, seed=42); adjust docs/judgments per scenario until bounds hold. |
| 50-trial seed too slow locally | M | L | Smoke is opt-in/off (state.md); 50 is the floor minimum; rich stays 15. If prohibitive, follow-up (D-11), not a re-scope. |
| List verdict diverges from detail | L | H | AC-2/AC-3b cross-check tests; reuse the same classifier + `_resolve_direction`. |
| Solr unreachable in backend CI | M | L | Headroom test skip-gates Solr (mirrors `is_engine_reachable`); manual operator-path covers it. |

### Failure mode catalog
| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Per-study classifier exception on the list | malformed trial data | that study's verdict → `null`, list 200 (mirror `fetch_study_convergence` try/except) | auto |
| **Solr** unreachable during headroom test | no Solr container in backend CI | skip the Solr scenario only (covered by manual operator-path) | auto |
| **ES/OS** unreachable during headroom test | required CI service container down | **FAIL** — ES + OpenSearch are required backend-CI infra; a down ES/OS container is a CI infrastructure failure, NOT a tolerable skip (preserves the "4 ES/OS hard gates" contract) | alert/fix CI |

## 7) Sequencing
1. Epic 1 Story 1.1 (backend) → 1.2 (frontend; needs OpenAPI regen after 1.1).
2. Epic 2 Story 2.3 headroom test scaffold → 2.1 (author + iterate against it) → 2.2 (trial bump) → finalize 2.3 (@slow seed).
- Epic 1 and Epic 2 are independent; Epic 2 can proceed in parallel once 2.3's headroom harness exists.

## 8) Rollout
- No flags, no migration. After merge: re-run `make seed-demo FORCE=1` to refresh local demo data (note in runbook).

## 9) Execution tracker

**Epic 1 (shipped to main via PR #421 `e5c3b8b9` squash-merge, 2026-06-02):**
- [x] Story 1.1 — backend list fields (`b90d5477` on the feat branch, landed on main via PR #421; 8 unit + 7 integration + 3 contract tests green; latent `_summary` invalid-direction crash fixed inline as a tangential discovery surfaced by AC-3b; Epic-1 phase-review F1 parity bug (count-gate `primary_metric IS NOT NULL`) fixed in `a0c40d37`)
- [x] Story 1.2 — frontend Trials + Convergence columns (`ed5ca276` on the feat branch, landed on main via PR #421; 1012 vitest, build clean, E2E spec)
- [x] Epic 1 phase gate — GPT-5.5 review: 5 findings (4 accepted+fixed `a0c40d37`, F4 rejected with counter-evidence); re-review clean.

**Epic 2 (in flight as PR #422):**
- [x] Story 2.3 (scaffold) — engine-backed headroom harness (`d3db5fc2`; new `backend/tests/integration/fixtures/headroom_harness.py` + `opensearch_reachability.py`; 6 tests — 5 scenarios + resolver-parity guard; ES/OS hard-gated in CI per D-18)
- [x] Story 2.1 — enriched docs + judgments (5 scenarios) — same commit as 2.3 scaffold; per-scenario headroom held with margins (baseline 0.561–0.690, lift +0.230 to +0.295, all `better < 0.99`)
- [x] Story 2.2 — `max_trials` 12→50 via shared `DEMO_SMALL_STUDY_MAX_TRIALS` constant (`12b0944b`; 4 parity guards — warmup-floor + alias + rich-unchanged + CLI-source-inspection)
- [x] Story 2.3 (finalize) — shape invariants (`79050269`; 21 parametrized — full {0,1,2,3} rubric) + @slow seed test extended with AC-7/AC-8 block routing through the live list path (`resolve_list_convergence_verdicts`)
- [x] Epic 2 phase gate — GPT-5.5 review: cycle 1 returned 6 findings (4 accepted+fixed in `f2cb9e2b`, 1 accepted as comment, 1 deferred to docs step); cycle 2 clean.
- [x] Documentation (`bb51300c` + state-correction `e0742e71`) — convergence-verdict runbook + ui-architecture column inventory + state.md + guide-06 caption + tangential healthz subsystem fix.
- [x] Final GPT-5.5 cross-model review of the full PR diff: 2 findings — both rejected (Solr CLI scope is out-of-scope from `infra_adapter_solr` Story A13; header-tooltip UX matches sibling-column convention).

## 10) Story-by-Story Verification Gate
Standard checklist per story (files match scope; contract implemented; tests at touched layers; commands run + passed; docs updated). Operator-path verification for Epic 2: `make seed-demo FORCE=1` confirming FR-5/FR-6 ranges.

## 11) Plan consistency review

- **FR coverage:** all 7 FRs mapped (§1). ✓
- **Endpoint parity:** spec §8.1 has 1 endpoint (`GET /studies`, extended); plan Story 1.1 covers it. ✓
- **Error codes:** none new. ✓
- **Enumerated-value audit:** `convergence_verdict` values `converged`/`still_improving`/`too_few_trials` — backend source `backend/app/domain/study/convergence.py ConvergenceVerdict`; frontend `CONVERGENCE_VERDICT_VALUES` (`ui/src/lib/enums.ts:77`); source-of-truth comment required in column-config (Story 1.2). ✓
- **Audit-event audit:** read-only list + seed tooling — no state mutation, no audit event (spec §6 N/A). ✓
- **File ownership:** backend/frontend files each owned by one story. **`scripts/seed_meaningful_demos.py` is touched by both Story 2.1 (SCENARIOS docs/judgments) and Story 2.2 (the shared `max_trials` constant)** — disjoint regions, sequenced 2.1 → 2.2 on the same branch (plan-cycle-1 F2). `demo_seeding.py` likewise (2.2 only). No clobber risk given the ordering. ✓
- **Frontend data plumbing:** `StudySummary` (generated) carries the new fields after regen; the table already receives `StudySummary` rows — no new prop plumbing. ✓
- **Open questions:** spec §19 resolved (D-11/D-12). ✓
- **Migration:** none. ✓
- **Legacy behavior parity:** No legacy behavior parity table — no user-facing component >100 LOC is deleted or migrated (Story 1.2 only adds columns).

## 12) Definition of plan done
- [x] Every FR mapped to stories/tests/docs.
- [x] Stories include New/Modified files, interfaces, tasks, DoD.
- [x] Test layers scoped (unit/integration/contract/E2E/vitest).
- [x] Docs updates planned.
- [x] Gates measurable.
- [x] Consistency review performed (§11) — no unresolved findings.
