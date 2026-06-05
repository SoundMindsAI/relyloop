# Implementation Plan — Side-by-side UBI-vs-LLM study comparison view

**Date:** 2026-05-31
**Status:** Complete (PR #461, merged 2026-06-05)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** `CLAUDE.md` (Absolute Rules #4 adapter, read-only posture), `docs/01_architecture/api-conventions.md`, `docs/01_architecture/ui-architecture.md`

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs (§1 below).
- Read-only feature: **no migration, no audit_log emission, no write path, no new env var, no adapter call** (spec §9, §10). Alembic head stays `0022_solr_engine_auth_check`.
- Fail-loud tests: assert explicit status/shape/error codes for all three endpoints.
- Cache reuse over re-serialization: the page reuses the warm `useStudy`/`useStudyDigest` TanStack caches; the pairing endpoint returns metadata only.
- Honor the wire-value facts locked in spec review: trial status is `complete` (not `completed`); no `best_trial_id` trials filter; kind discriminator `generation_kind == 'ubi'` only (no `'hybrid'`); `studies.judgment_list_id` non-unique → lookup returns None on 0-or-many; metric label from `confidence.headline.metric`; malformed-but-length-valid id → 404; `/pair` no-counterpart → `200 {study_id:null, kind:null}`.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.2 | `GET /api/v1/studies/compare` route + contract; route ordering before `/studies/{study_id}`. |
| FR-2 | Epic 1 / Story 1.1 + 1.2 | `classify_judgment_kind`, `validate_compare_pair`, `find_paired_ubi_llm_study`, `get_completed_study_for_judgment_list`. |
| FR-3 | Epic 3 / Story 3.1 | `/studies/compare` route + `<StudyComparisonPage>` shell + `useStudyComparePairing` hook + column normalization. |
| FR-4 | Epic 3 / Story 3.3 | Digest-narrative diff panel + `narrative-diff.ts` (`diffSentences`). |
| FR-5 | Epic 3 / Story 3.4 | Best-trial parameter-table diff (digest.recommended_config + trials fallback). |
| FR-6 | Epic 3 / Story 3.2 | Best-metric scalar comparison (kind-normalized delta, direction-aware, confidence-aware). |
| FR-7 | Epic 3 / Story 3.5 | Convergence overlay — consume-when-present + fallback derivation. |
| FR-8 | Epic 2 / Story 2.1 + Epic 4 / Story 4.1 | `GET /studies/{id}/pair` + `useStudyPair` + study-detail entry button. |
| FR-9 | Epic 2 / Story 2.2 + Epic 4 / Story 4.2 | `GET /judgment-lists/{id}/study` + `get_completed_study_for_judgment_list` + value-delta affordance. |
| FR-10 | Epic 3 / Story 3.6 | Responsive stacked layout (narrow viewport). |
| FR-11 | Epic 5 / Story 5.1 | Tutorial Step 11 subsection + screenshots. |

All 11 FRs covered. Single-phase — no deferred phases, no `phase2_idea.md` (spec §3 "Phase boundaries"). The cluster-detail rung badge and dashboard "Compare ↔" badge are separate artifacts (`chore_cluster_detail_rung_badge` + a §19 deferral) — NOT phases of this feature.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Five epics:

1. **Epic 1 — Backend pairing/validation core** (Stories 1.1, 1.2): service + repo helpers + `GET /studies/compare`.
2. **Epic 2 — Discovery endpoints** (Stories 2.1, 2.2): `GET /studies/{id}/pair`, `GET /judgment-lists/{id}/study`.
3. **Epic 3 — Comparison page + panels** (Stories 3.0–3.6): dependency add, page shell, four diff panels, responsive layout.
4. **Epic 4 — Entry points** (Stories 4.1, 4.2): study-detail button, value-delta affordance.
5. **Epic 5 — Docs** (Story 5.1): tutorial subsection.

### Conventions (project-specific)

```
- Repo functions take `db: AsyncSession` first; use `db.flush()` (caller commits). Read-only here — no flush/commit.
- Services are async, accept `db: AsyncSession` first. This feature's service is a pure read orchestrator (no job_run — no long-running work).
- Domain/service helper `classify_judgment_kind` is pure (no DB, no async) — unit-testable.
- Routers use `_err(status, code, msg, retryable)` at backend/app/api/v1/studies.py:80 for the project envelope; return typed Pydantic response_model.
- New schemas live in backend/app/api/v1/schemas.py; export nothing extra (FastAPI resolves response_model from the module).
- Frontend: TanStack Query hooks in ui/src/lib/api/studies.ts; queryKeys reuse ['studies', id] + ['studies', id, 'digest'] for cache warmth. New keys: ['studies','compare',a,b], ['studies',id,'pair'], ['judgment-lists',id,'study'].
- Enum-source-of-truth comments above any frontend kind/warning-code map (// Values must match backend CompareKind / CompareWarningCode).
```

### AI Agent Execution Protocol

0. Read `architecture.md` + `state.md` before Story 1.1.
1. Backend first: schemas → service helper (`classify_judgment_kind`, `validate_compare_pair`) → repo helpers → routers.
2. Run `make test-unit` + targeted `test-integration` + `test-contract` for touched endpoints.
3. Frontend: dependency add → hooks → page shell → panels → entry points.
4. Run E2E scope (real-backend Playwright).
5. Update docs (api-conventions.md / ui-architecture.md + tutorial) in the same PR.
6. **No migration round-trip** — no schema change.
7. Attach evidence in PR.
8. After the final story, update `state.md` + `architecture.md`.

---

## Epic 1 — Backend pairing/validation core

### Story 1.1 — Kind classification + pair validation service + repo helpers

**Outcome:** A pure `classify_judgment_kind` helper, an async `validate_compare_pair` service that returns a typed `ComparePairing`, and two repo helpers for paired-study discovery, all unit/integration tested.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/study_comparison.py` | `classify_judgment_kind(generation_params) -> CompareKind` (pure); `validate_compare_pair(db, a_id, b_id) -> ComparePairing` (async); the `ComparePairing` dataclass + `CompareWarning` internal shape. Raises `_CompareError` (translated to `_err` envelopes at the router). |
| `backend/tests/unit/services/test_study_comparison.py` | Unit coverage for `classify_judgment_kind` (all branches) + `validate_compare_pair` warning computation with stubbed rows. |
| `backend/tests/integration/test_study_pairing.py` | DB-backed `find_paired_ubi_llm_study` + `get_completed_study_for_judgment_list` + `validate_compare_pair` against real rows. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/study.py` | Add `find_paired_ubi_llm_study(db, study_id) -> Study \| None` and `get_completed_study_for_judgment_list(db, judgment_list_id) -> Study \| None`. |
| `backend/app/db/repo/__init__.py` | Export both new functions via `__all__`. |
| `backend/app/api/v1/schemas.py` | Add `CompareKind`, `CompareWarningCode`, `CompareWarning`, `StudyComparePairing`, `StudyPairResponse`, `JudgmentListStudyResponse` (see §8.3 of spec). |

**Key interfaces**

```python
# services/study_comparison.py
CompareKind = Literal["llm", "ubi"]  # mirror in schemas; one canonical source

def classify_judgment_kind(generation_params: dict | None) -> CompareKind: ...
#   generation_params.get("generation_kind") == "ubi" -> "ubi"; else "llm".
#   Defensive: non-dict / None / absent / any other value -> "llm".

@dataclass(frozen=True)
class CompareWarning:
    code: Literal["CROSS_CLUSTER", "TARGET_MISMATCH", "OBJECTIVE_MISMATCH"]
    message: str

@dataclass(frozen=True)
class ComparePairing:
    a_study_id: str
    b_study_id: str
    a_kind: CompareKind
    b_kind: CompareKind
    query_set_id: str
    warnings: list[CompareWarning]

class CompareValidationError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None: ...

async def validate_compare_pair(db: AsyncSession, a_id: str, b_id: str) -> ComparePairing: ...
#   404 STUDY_NOT_FOUND if either missing
#   422 COMPARE_STUDY_NOT_COMPLETED if either status != 'completed'
#   422 COMPARE_QUERY_SET_MISMATCH if query_set_id differs
#   422 COMPARE_NOT_LLM_UBI_PAIR if not exactly one llm + one ubi
#   warnings: CROSS_CLUSTER (cluster_id differ), TARGET_MISMATCH (target differ),
#             OBJECTIVE_MISMATCH (objective.metric OR objective.direction differ)

# db/repo/study.py
async def find_paired_ubi_llm_study(db: AsyncSession, study_id: str) -> Study | None: ...
#   None unless source exists AND status='completed'. Counterpart: same query_set_id,
#   status='completed', SAME cluster_id, opposite judgment-list kind. None on 0 or >1.
async def get_completed_study_for_judgment_list(db: AsyncSession, judgment_list_id: str) -> Study | None: ...
#   The single completed study whose judgment_list_id == arg. None on 0 OR >1 (no uniqueness constraint).
```

**Pydantic schemas** (added to `schemas.py`)

```python
CompareKind = Literal["llm", "ubi"]
CompareWarningCode = Literal["CROSS_CLUSTER", "TARGET_MISMATCH", "OBJECTIVE_MISMATCH"]

class CompareWarning(BaseModel):
    code: CompareWarningCode
    message: str

class StudyComparePairing(BaseModel):
    a_study_id: str
    b_study_id: str
    a_kind: CompareKind
    b_kind: CompareKind
    query_set_id: str
    warnings: list[CompareWarning]

class StudyPairResponse(BaseModel):
    study_id: str | None
    kind: CompareKind | None

class JudgmentListStudyResponse(BaseModel):
    study_id: str | None
```

**Tasks**
1. Add the schemas above to `schemas.py` (keep `CompareKind`/`CompareWarningCode` as the canonical Literals; the service imports them).
2. Implement `classify_judgment_kind` defensively (guard non-dict `generation_params`).
3. Implement `validate_compare_pair`: load both studies via `repo.get_study`; raise `CompareValidationError` for each hard gate; load each study's judgment list via `repo.get_judgment_list`; classify; compute the three non-fatal warnings from already-loaded `studies` rows (no digest/trial loads).
4. Implement the two repo helpers in `study.py` (SQLAlchemy `select`; `find_paired_ubi_llm_study` joins/filters on `query_set_id`, `status`, `cluster_id`, and resolves kind via the counterpart's judgment list; `get_completed_study_for_judgment_list` filters `judgment_list_id == arg AND status='completed'`, returns None when row count != 1).
5. Export new repo functions in `__init__.py` `__all__`.
6. Write unit + integration tests.

**Definition of Done (DoD)**
- `classify_judgment_kind` unit tests cover: `{generation_kind:'ubi'}` → `ubi`; hybrid-converter list (`{generation_kind:'ubi', converter:'hybrid_ubi_llm'}`) → `ubi`; `None`/`{}`/non-dict/`{generation_kind:'something_else'}` → `llm`.
- `validate_compare_pair` integration tests assert each 422 code + the 404, plus the three warning payloads (`CROSS_CLUSTER`, `TARGET_MISMATCH`, `OBJECTIVE_MISMATCH`) appear on `200`-eligible pairs.
- `find_paired_ubi_llm_study` integration: returns counterpart for a valid pair; returns `None` on 0 / >1 / wrong-kind / not-completed / running-source / cross-cluster.
- `get_completed_study_for_judgment_list` integration: returns the study when exactly 1 completed study references the list; `None` on 0 OR >1.
- `make test-unit` + `make test-integration` (targeted) green.

### Story 1.2 — `GET /api/v1/studies/compare` endpoint + route ordering

**Outcome:** The compare endpoint validates a pair and returns `StudyComparePairing`, declared before `/studies/{study_id}` so `compare` is not captured as a path param.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Add `@router.get("/studies/compare", response_model=StudyComparePairing)` handler. **Declare it ABOVE the existing `/studies/{study_id}` route (currently at line 549).** Translate `CompareValidationError` → `_err(...)`. |
| `backend/tests/contract/test_studies_compare.py` (new) | Contract coverage (see Endpoints). |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/compare?a={id}&b={id}` | `a`,`b` = `Query(..., min_length=1, max_length=36)` | `200` `StudyComparePairing` | `STUDY_NOT_FOUND` (404), `COMPARE_STUDY_NOT_COMPLETED` (422), `COMPARE_QUERY_SET_MISMATCH` (422), `COMPARE_NOT_LLM_UBI_PAIR` (422), `VALIDATION_ERROR` (422 — missing/empty/too-long param, via global `validation_exception_handler`) |

Error shape: `{ "detail": { "error_code", "message", "retryable" } }` (project envelope, `_err` at `studies.py:80`). No auth dependency (single-tenant).

**Tasks**
1. Add the handler before `/studies/{study_id}`. Both params required via `Query(..., min_length=1, max_length=36)`.
2. Call `validate_compare_pair`; on `CompareValidationError`, raise `_err(e.status, e.code, e.message, retryable=False)`.
3. Return `StudyComparePairing` built from the `ComparePairing` dataclass.
4. Contract tests (see DoD).

**Definition of Done (DoD)**
- Contract test `test_studies_compare.py` asserts: AC-1 (`200` `a_kind/b_kind/query_set_id/warnings=[]`); AC-1b (`200` + `CROSS_CLUSTER` warning); AC-1c (`200` + `TARGET_MISMATCH` warning); `OBJECTIVE_MISMATCH` warning case; AC-2 (`422 COMPARE_NOT_LLM_UBI_PAIR`); AC-3 (`422 COMPARE_QUERY_SET_MISMATCH`); AC-4 (`422 COMPARE_STUDY_NOT_COMPLETED`); AC-5 (`404 STUDY_NOT_FOUND`).
- **AC-8 route-ordering assertion**: `GET /api/v1/studies/compare` with no query params returns `422 VALIDATION_ERROR` (compare handler), never `404 STUDY_NOT_FOUND`.
- `make test-contract` green.

**Epic 1 gate:** 1 of the 3 endpoints (`/studies/compare`) live with full contract + integration + unit coverage; all 6 error codes for the compare endpoint asserted.

---

## Epic 2 — Discovery endpoints

### Story 2.1 — `GET /api/v1/studies/{id}/pair`

**Outcome:** Discover the single valid LLM↔UBI counterpart for a study. `200 {study_id, kind}` when found; `200 {study_id:null, kind:null}` when none; `404` only when `{id}` itself is missing.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Add `@router.get("/studies/{study_id}/pair", response_model=StudyPairResponse)`. Declare before `/studies/{study_id}` (or after `/studies/compare`) — `/pair` suffix is more specific so FastAPI resolves it correctly regardless, but list it among the literal/specific routes. |
| `backend/tests/contract/test_studies_compare.py` | Extend with `/pair` cases. |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{id}/pair` | — | `200` `{study_id: str\|null, kind: "llm"\|"ubi"\|null}` | `STUDY_NOT_FOUND` (404 — only when `{id}` itself missing) |

**Tasks**
1. Handler: `repo.get_study(db, study_id)`; if None → `_err(404, "STUDY_NOT_FOUND", ...)`. Else call `find_paired_ubi_llm_study`; if None → `StudyPairResponse(study_id=None, kind=None)`; else resolve counterpart kind via `classify_judgment_kind(counterpart_jl.generation_params)` and return both.
2. Contract tests.

**Definition of Done (DoD)**
- Contract: AC-6 (`200 {study_id:<ubi_id>, kind:"ubi"}`); AC-7 (`200 {study_id:null, kind:null}` — no counterpart); `404 STUDY_NOT_FOUND` when `{id}` itself missing.
- `make test-contract` green.

### Story 2.2 — `GET /api/v1/judgment-lists/{id}/study`

**Outcome:** Resolve the single completed study for a judgment list (FR-9 step 1). `200 {study_id}` or `200 {study_id:null}`; `404` only when the list itself is missing.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/judgments.py` | Add `@router.get("/judgment-lists/{judgment_list_id}/study", response_model=JudgmentListStudyResponse)`. Uses the same `_err` envelope + `repo.get_judgment_list`. |
| `backend/tests/contract/test_judgment_list_study.py` (new) | Contract coverage. |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/judgment-lists/{id}/study` | — | `200` `{study_id: str\|null}` | `JUDGMENT_LIST_NOT_FOUND` (404 — only when `{id}` itself missing) |

**Tasks**
1. Handler: `repo.get_judgment_list(db, id)`; if None → `_err(404, "JUDGMENT_LIST_NOT_FOUND", ...)`. Else `get_completed_study_for_judgment_list`; return `{study_id: row.id if row else None}`.
2. Contract tests.

**Definition of Done (DoD)**
- Contract: found (`200 {study_id:<id>}`); null (`200 {study_id:null}` — 0 or >1 completed studies reference the list); `404 JUDGMENT_LIST_NOT_FOUND` when `{id}` missing.
- `make test-contract` green.

**Epic 2 gate:** all 3 endpoints live; every error code in spec §8.5 asserted in a contract test (`STUDY_NOT_FOUND`, `COMPARE_STUDY_NOT_COMPLETED`, `COMPARE_QUERY_SET_MISMATCH`, `COMPARE_NOT_LLM_UBI_PAIR`, `JUDGMENT_LIST_NOT_FOUND`, `VALIDATION_ERROR`).

---

## Epic 3 — Comparison page + panels

### Story 3.0 — Add the `diff` (jsdiff) dependency

**Outcome:** `diff` + `@types/diff` are dependencies of the `ui` package; `pnpm install` resolves cleanly; the `license-inventory` gate stays green.

**Modified files**

| File | Change |
|---|---|
| `ui/package.json` | Add `diff` (BSD-licensed, no native module) + `@types/diff` (devDep). |
| `ui/pnpm-lock.yaml` | Regenerated by `pnpm add`. |

**Tasks**
1. From `ui/`: `pnpm add diff` and `pnpm add -D @types/diff`.
2. Verify `pnpm install` + `pnpm typecheck` succeed.
3. Run `python scripts/gen_license_inventory.py` (or the repo's license-inventory regen) if the gate requires the inventory committed; confirm `diff` is permissive (BSD) and adds no violation.

**Definition of Done (DoD)**
- `diff` + `@types/diff` in `ui/package.json`; lockfile updated.
- `cd ui && pnpm typecheck` green.
- `license-inventory` gate green (no new non-permissive license).

### Story 3.1 — Comparison route + page shell + pairing hook + column normalization

**Outcome:** `/studies/compare?a=&b=` renders `<StudyComparisonPage>`: resolves the pair, reuses warm study/digest caches, labels columns by kind, and normalizes column order to LLM-left / UBI-right regardless of URL order. Renders a keyed error state on pairing failure.

**New files**

| File | Purpose |
|---|---|
| `ui/src/app/studies/compare/page.tsx` | Route entry; reads `a`/`b` from `searchParams`; renders `<StudyComparisonPage>` inside a `<Suspense>` (matches the `/studies/[id]` Suspense pattern at `page.tsx:223`). |
| `ui/src/components/studies/study-comparison-page.tsx` | `<StudyComparisonPage>` — orchestrates pairing + the four panels + warning banner + synthetic chip per panel + responsive grid. |
| `ui/src/__tests__/components/studies/study-comparison-page.test.tsx` | Column-normalization (AC-18), error-state, warning-banner render tests. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/studies.ts` | Add `useStudyComparePairing(a, b)` (queryKey `['studies','compare',a,b]`, hits `GET /api/v1/studies/compare`), `useStudyPair(studyId)` (queryKey `['studies', studyId, 'pair']`, hits `GET /api/v1/studies/{id}/pair`). Export `StudyComparePairing`, `StudyPairResponse` types from `components['schemas']`. |
| `ui/src/lib/api/judgments.ts` | Add `useJudgmentListStudy(judgmentListId)` (queryKey `['judgment-lists', id, 'study']`, hits `GET /api/v1/judgment-lists/{id}/study`). |

**UI element inventory**
- Page title "Study comparison — LLM vs UBI" (heading).
- Two column headers: "LLM judgments" (left/A), "UBI judgments" (right/B) — **derived from resolved `a_kind`/`b_kind`, not URL order**.
- Per-panel synthetic-data chip via `isDemoSyntheticUbiClusterName(cluster.name)` (reuse `@/lib/demo-data` + the existing chip; do NOT invent a new disclosure surface).
- Warning banner: renders `pairing.warnings[]` (CROSS_CLUSTER / TARGET_MISMATCH / OBJECTIVE_MISMATCH) as non-fatal callouts.
- Error state: keyed off the pairing error code → message + `<Link href="/studies">` "Back to studies".
- Four panel slots (Stories 3.2–3.5).

**State dependency analysis**
```
Data plumbed into panels (all available — verified):
  - StudyDetail (useStudy(a), useStudy(b)): best_metric, best_trial_id, objective, confidence, convergence?, cluster_id, query_set_id
  - DigestResponse (useStudyDigest(a/b)): narrative, recommended_config — 404 DIGEST_NOT_READY suppressed via the hook's meta.suppressErrorCodes (digests.ts:48)
  - StudyComparePairing (useStudyComparePairing): a_kind, b_kind, warnings — drives column normalization
Cluster name for the chip: useCluster(study.cluster_id) (same wrapper pattern as StudyHeaderWithSyntheticChip at studies/[id]/page.tsx:203).
```

**Tasks**
1. Add the three hooks (two in `studies.ts`, one in `judgments.ts`); regenerate `ui/src/lib/types.ts` from the OpenAPI schema if the project pins generated types (check `pnpm run gen:types` or equivalent — the new schemas must surface in `components['schemas']`).
2. Build `page.tsx` reading `searchParams.a` / `searchParams.b`; missing either → render the same "invalid pair" empty state (do not crash).
3. Build `<StudyComparisonPage>`: call `useStudyComparePairing(a, b)`; on error render the keyed error state; on success derive `llmStudyId`/`ubiStudyId` from `a_kind`/`b_kind`, fetch `useStudy`/`useStudyDigest` for both, render the LLM study left and UBI right.
4. Render the warning banner from `pairing.warnings`.
5. Source-of-truth comment above any kind-label map: `// Values must match backend CompareKind`; above any warning-code map: `// Values must match backend CompareWarningCode`.

**Definition of Done (DoD)**
- AC-18: vitest asserts that a `?a={ubiId}&b={llmId}` (reversed) pairing renders LLM in the left column, UBI in the right.
- Error-state vitest: a `COMPARE_NOT_LLM_UBI_PAIR` pairing error renders the keyed message + back link.
- Warning-banner vitest: a pairing with `CROSS_CLUSTER` warning renders the banner.
- `cd ui && pnpm typecheck && pnpm test` green.

### Story 3.2 — Best-metric scalar comparison panel

**Outcome:** Both studies' `best_metric` + a kind-normalized signed delta (`ubi - llm`), direction-aware framing, confidence context, metric label from `confidence.headline.metric`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/comparison/best-metric-panel.tsx` | The scalar + delta + confidence context. |
| `ui/src/__tests__/components/studies/comparison/best-metric-panel.test.tsx` | Direction framing + null handling + OBJECTIVE_MISMATCH qualifier. |

**UI element inventory**
- Two `best_metric` values (LLM, UBI). Em-dash when either is `null` (suppress delta).
- Signed delta computed `ubi.best_metric - llm.best_metric` (NOT URL order). "Better/worse" respects `objective.direction` (default `"maximize"` via `objective.direction ?? 'maximize'`).
- Metric label from `confidence.headline.metric` when present; else neutral "primary metric".
- Confidence context (bootstrap CI / runner-up gap) reusing `<ConfidencePanel>` data shape or a compact variant when `confidence` present.
- "metrics differ — delta is not directly comparable" caption when pairing has an `OBJECTIVE_MISMATCH` warning.
- Info tooltip (see UI Guidance).

**Tasks**
1. Compute delta over kind-normalized operands; frame by direction.
2. Read label via `confidence?.headline?.metric` with neutral fallback.
3. Surface confidence context when present; suppress delta on null `best_metric`.
4. Qualify the delta when the parent passes the `OBJECTIVE_MISMATCH` warning flag.

**Definition of Done (DoD)**
- AC-12 vitest: `direction="minimize"`, A=0.40, B=0.30 → B framed as better; delta sign reflects it.
- Null-metric vitest: em-dash + no delta.
- OBJECTIVE_MISMATCH vitest: qualifier caption renders.
- `pnpm test` green.

### Story 3.3 — Digest-narrative diff panel + `narrative-diff.ts`

**Outcome:** Sentence-level diff of the two digest narratives via `diffSentences`, change-count summary per side, graceful per-side placeholder when a digest is `404 DIGEST_NOT_READY`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/diff/narrative-diff.ts` | Wraps `diffSentences(a, b)` from `diff`; returns added/removed segments + per-side change counts. Documented fallback to `diffWordsWithSpace`. |
| `ui/src/components/studies/comparison/digest-diff-panel.tsx` | Renders both narratives + center diff column (added flagged on B, removed on A) + change-count summary. |
| `ui/src/__tests__/lib/narrative-diff.test.ts` | `diffSentences` change-count assertions. |
| `ui/src/__tests__/components/studies/comparison/digest-diff-panel.test.tsx` | Digest-missing placeholder render. |

**Tasks**
1. Implement `narrative-diff.ts` (single point of swap to `diffWordsWithSpace`).
2. Build the panel; when either `useStudyDigest` returned a 404, render "digest not available for this study" for that side, keep the other side.
3. `+`/`−` text markers (not color-only) per accessibility NFR.

**Definition of Done (DoD)**
- AC-11 vitest: two differing narratives produce a per-side change-count summary from `diffSentences`.
- Digest-missing vitest: one-side placeholder + other side renders.
- `pnpm test` green.

### Story 3.4 — Best-trial parameter-table diff panel

**Outcome:** One column per study, one row per parameter key, `=`/`Δ` flag, em-dash for keys present on only one side. Primary source `digest.recommended_config`; trials fallback when digest missing.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/comparison/param-diff-panel.tsx` | The parameter table + flags. |
| `ui/src/lib/diff/param-diff.ts` | Pure helper: merge two config dicts → rows `{key, aValue, bValue, flag}`. |
| `ui/src/__tests__/components/studies/comparison/param-diff-panel.test.tsx` | `=`/`Δ`/em-dash flag coverage. |

**Tasks**
1. `param-diff.ts`: union of keys across both `recommended_config` dicts; flag `=` when equal, `Δ` otherwise; em-dash for the missing side (always `Δ`).
2. Panel renders rows; center column shows `=`/`Δ` with aria-labels.
3. Fallback: when a study's digest is `404`, fetch trials via `useStudyTrials(studyId, { sort })` where `sort = direction === 'minimize' ? 'primary_metric_asc' : 'primary_metric_desc'` (winning direction → best trial on page 1, since **no `best_trial_id` filter exists**), select the row whose `id === study.best_trial_id`, use `TrialDetail.params`. Page forward until found; if not found within budget, render "best-trial params unavailable" for that side.

**Definition of Done (DoD)**
- AC-16 vitest: shared `tie_breaker` equal → `=`; differing `boost` → `Δ`; key on one side only → em-dash + `Δ`.
- Fallback unit test (param-diff helper or panel with mocked trials): selects `best_trial_id` row from a `primary_metric_desc` page.
- `pnpm test` green.

### Story 3.5 — Convergence-curve overlay (consume-when-present + fallback)

**Outcome:** A two-series Recharts `<LineChart>` of both studies' best-so-far curves, with a kind-named legend. Consumes `StudyDetail.convergence.best_so_far_curve` when present; **otherwise derives the curve client-side** from `/studies/{id}/trials`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/comparison/convergence-overlay.tsx` | Two-series `<LineChart>` (new chart variant — only `<BarChart>` exists today at `parameter-importance-chart.tsx`). |
| `ui/src/lib/diff/best-so-far-curve.ts` | Fallback derivation util: `deriveBestSoFarCurve(trials, direction) -> {trial_number, best_so_far}[]`. Output shape MUST match the borrowed `best_so_far_curve` exactly. |
| `ui/src/__tests__/components/studies/comparison/convergence-overlay.test.tsx` | Consume-when-present (no trials fetch) + fallback-derivation + empty-state. |
| `ui/src/__tests__/lib/best-so-far-curve.test.ts` | Running-max (maximize) / running-min (minimize) over filtered trials. |

**Tasks**
1. **Consume-when-present path:** when `study.convergence?.best_so_far_curve` is present, plot it directly — no trials fetch.
2. **Fallback derivation path:** when `study.convergence` is absent, call `useStudyTrials(studyId, { sort: 'optuna_trial_number_asc' })`, page through all trials (demo caps at `max_trials=12`, < one page), filter `status === 'complete'` (**not `completed`** — `TrialStatusWire` is `complete|failed|pruned`) AND `is_baseline === false`, sort by `optuna_trial_number` ASC, running-max (or running-min for `minimize`) over `primary_metric` → `{trial_number, best_so_far}[]`.
3. Render both series on one `<LineChart>` (different lengths overlay fine); legend names each series by kind. **Empty state** "no convergence data yet" when neither source available for a study.
4. Disambiguation guard in code comment: use top-level `StudyDetail.convergence`, NOT nested `confidence.convergence` (winner-timing only, no curve).

**Definition of Done (DoD)**
- AC-13 vitest: both payloads carry `convergence.best_so_far_curve` → two series plotted, **no client-side trials fetch** (assert the trials hook is not called / `enabled:false`).
- AC-14 vitest: `convergence` null for both → curves derived from `/studies/{id}/trials` (complete, non-baseline, running-max/min).
- `best-so-far-curve.test.ts`: running-max + running-min correctness; baseline + non-complete rows excluded.
- Empty-state vitest.
- `pnpm test` green.

### Story 3.6 — Responsive / narrow-viewport stacked layout

**Outcome:** Below the `lg` breakpoint, study A stacks above study B with inline per-element diff annotations (no center column); two-column grid at `lg+`. Digest diff degrades to two stacked blocks each preceded by its change-count summary.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/study-comparison-page.tsx` | Tailwind responsive grid: `grid-cols-1 lg:grid-cols-[1fr_auto_1fr]` (or equivalent); center diff column hidden below `lg`, diff annotations rendered inline. |
| Panel components (3.2–3.5) | Each accepts a `stacked?: boolean` (or reads a layout context) to switch between center-column and inline-annotation rendering. |

**Tasks**
1. Two-column grid at `lg+`; single column below with inline diff annotations.
2. Digest panel: stacked blocks + per-block change-count summary on narrow.
3. Keep the page fully reachable (no hidden content) on narrow.

**Definition of Done (DoD)**
- AC-15 (E2E narrow viewport, Story-3.7 E2E): study A stacks above B, no center column, page reachable.
- `pnpm typecheck && pnpm test` green.

**Epic 3 gate:** `/studies/compare` renders all four panels from warm cache; `diff` dependency added; column normalization + responsive layout in place.

---

## Epic 4 — Entry points

### Story 4.1 — Study-detail "Compare with the {UBI|LLM} study" button

**Outcome:** A button on the study-detail page header/action area, rendered only when `useStudyPair(studyId).data.study_id !== null`, labeling the *other* kind, linking to `/studies/compare?a={llmId}&b={ubiId}` (canonical LLM-as-`a`).

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/studies/[id]/page.tsx` | Add a `useStudyPair(studyId)` call (the hook from Story 3.1); render the compare button in the header/action area only when `pair.study_id != null`. Build the canonical link: identify which of `{thisStudyId, pair.study_id}` is LLM vs UBI using the current study's kind (resolve via `useJudgmentList(study.judgment_list_id)` — already imported at line 25) + `pair.kind`. |
| `ui/src/__tests__/app/studies/...` (study-detail tests) | Add: button absent when `pair.study_id === null`; button present + correct label + canonical href when a pair exists. |

**UI element inventory**
- `<Button asChild><Link href={...}>` "Compare with the UBI study" / "Compare with the LLM study" (label names the *other* kind).
- Hidden entirely when no pair (no disabled state — idea Q-4).

**State dependency analysis**
```
Available on the study-detail page (verified):
  - study.judgment_list_id, study.id (StudyDetail, useStudy at page.tsx:59)
  - useJudgmentList(study.judgment_list_id) already called at line 25 (kind discriminator)
  - pair.study_id + pair.kind from new useStudyPair(studyId)
Link construction: a = the LLM study id, b = the UBI study id (canonical), derived from this study's kind + pair.kind.
```

**Tasks**
1. Call `useStudyPair(studyId)`; gate the button on `pair.study_id != null`.
2. Determine this study's kind (`generation_kind === 'ubi'`) and use `pair.kind` to assign LLM/UBI ids; build `?a={llm}&b={ubi}`.
3. Label names the other kind.

**Definition of Done (DoD)**
- AC-9 (E2E): button absent on a study with no counterpart.
- AC-10 (E2E): "Compare with the UBI study" visible on an LLM study; click navigates to `/studies/compare?a={llm_id}&b={ubi_id}`.
- Component vitest: hidden when `pair.study_id===null`; correct label + href when present.
- `pnpm test` green.

### Story 4.2 — Judgment-list value-delta "View matched study comparison" affordance

**Outcome:** A "View matched study comparison" affordance on `<ValueDeltaCard>` (or its container on the judgment-list page), shown only when the two-step resolution (list→UBI study, UBI study→LLM counterpart) succeeds.

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/judgments/[id]/page.tsx` | Resolve the pair in two steps: `useJudgmentListStudy(listId)` (Story 3.1 hook) → if `study_id`, `useStudyPair(study_id)` → if `pair.study_id`, build `?a={llmStudyId}&b={ubiStudyId}` and pass a `compareHref` to `<ValueDeltaCard>`. |
| `ui/src/components/judgments/value-delta-card.tsx` | Add an optional `compareHref?: string \| null` prop; render the "View matched study comparison" `<Link>` only when present. (Additive — existing render paths unchanged.) |
| `ui/src/__tests__/components/judgments/value-delta-card.test.tsx` | Extend: affordance present when `compareHref` set; absent when null/undefined. |

**UI element inventory**
- New optional `<Link href={compareHref}>` "View matched study comparison" inside `<ValueDeltaCard>` (additive; the card's two existing variants are untouched).

**State dependency analysis**
```
Two-step resolution on the judgment-list page:
  step 1: useJudgmentListStudy(listId) -> { study_id } (the UBI study for this list)
  step 2: useStudyPair(ubiStudyId)     -> { study_id: llmStudyId, kind }
compareHref = study_id && pair.study_id ? `/studies/compare?a=${llmStudyId}&b=${ubiStudyId}` : null
The page already renders <ValueDeltaCard> at judgments/[id]/page.tsx:131.
```

**Tasks**
1. Wire the two hooks on the judgment-list page; compute `compareHref` (null on either step yielding no result).
2. Thread `compareHref` into `<ValueDeltaCard>`; render the link conditionally.

**Definition of Done (DoD)**
- AC-17: affordance visible + links to `/studies/compare?a={llmStudyId}&b={ubiStudyId}` when a valid LLM counterpart exists; absent when none (component vitest + E2E covers the visible path).
- `value-delta-card.test.tsx`: link present with `compareHref`, absent without.
- `pnpm test` green.

### Story 3.7 / 4.3 — E2E (real-backend Playwright)

**Outcome:** A real-backend E2E spec exercises the LLM-study-detail → compare flow end to end.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/study-comparison.spec.ts` | Real-backend Playwright (no `page.route()`). Pattern: anchor to `demo-ubi.spec.ts` — reseed/seed a demo cluster with a dual LLM/UBI pair via API helpers in `beforeAll`, then drive the browser. |

**Tasks**
1. Setup via API helpers (`request`): ensure a seeded demo cluster with a completed LLM study + completed UBI study on the same query set (reuse the demo reseed the `demo-ubi.spec.ts` uses; gate behind `SKIP_HEAVY_CI` like the other heavy specs).
2. `page.goto` the LLM study detail; assert the "Compare with the UBI study" button (`page` interaction); click it; assert the comparison page renders both columns + the four panels (best-metric, param table, digest diff, convergence).
3. Assert the button is **absent** on a study with no counterpart.
4. (AC-15) narrow-viewport: set viewport below `lg`, assert stacked layout reachable.

**Definition of Done (DoD)**
- AC-9, AC-10, AC-15 asserted via `page` browser interactions (assertions verify browser-visible behavior; `request` only for setup).
- No `page.route()` mocking.
- Spec gated behind `SKIP_HEAVY_CI` per the heavy-lane convention.

**Epic 4 gate:** both entry points self-gate on pair existence; E2E green (or skipped under `SKIP_HEAVY_CI` with the documented gate).

---

## Epic 5 — Documentation

### Story 5.1 — Tutorial Step 11 "Compare LLM vs UBI on the same dataset"

**Outcome:** Tutorial Step 11 gains the comparison subsection with at least one comparison-view screenshot reference; api-conventions.md / ui-architecture.md note the new endpoints + chart variant.

**Modified files**

| File | Change |
|---|---|
| `docs/08_guides/tutorial-first-study.md` | Add the "Compare LLM vs UBI on the same dataset" subsection to Step 11 (closes the Phase-1 deferral) with ≥1 screenshot reference. |
| `docs/01_architecture/api-conventions.md` (or `ui-architecture.md`) | Note `GET /studies/compare`, `GET /studies/{id}/pair`, `GET /judgment-lists/{id}/study` read endpoints + the two-series convergence overlay chart variant + `/studies/compare` route. |

**Tasks**
1. Write the subsection; capture/reference screenshots (via `guide-gen` or manual).
2. Add the endpoint + UI notes to the architecture docs.

**Definition of Done (DoD)**
- AC-19: Step 11 contains the subsection + ≥1 comparison-view screenshot reference.
- Architecture doc note present.

---

## 3) Testing workstream

### 3.1 Unit tests
- `backend/tests/unit/services/test_study_comparison.py` (Story 1.1) — `classify_judgment_kind` all branches; `validate_compare_pair` warning computation with stubbed rows.
- `ui/src/__tests__/lib/narrative-diff.test.ts` (Story 3.3) — `diffSentences` change counts.
- `ui/src/__tests__/lib/best-so-far-curve.test.ts` (Story 3.5) — running-max/min fallback derivation.
- `ui/src/__tests__/components/studies/comparison/best-metric-panel.test.tsx` (Story 3.2) — direction framing + null + OBJECTIVE_MISMATCH.
- `ui/src/__tests__/components/studies/comparison/param-diff-panel.test.tsx` (Story 3.4) — `=`/`Δ`/em-dash.
- `ui/src/__tests__/components/studies/comparison/convergence-overlay.test.tsx` (Story 3.5) — consume-vs-fallback + empty state.
- `ui/src/__tests__/components/studies/study-comparison-page.test.tsx` (Story 3.1) — column normalization (AC-18) + error state + warning banner.
- `ui/src/__tests__/components/studies/comparison/digest-diff-panel.test.tsx` (Story 3.3) — digest-missing placeholder.
- `ui/src/__tests__/components/judgments/value-delta-card.test.tsx` (Story 4.2, extend) — affordance present/absent.
- Study-detail button tests under `ui/src/__tests__/app/studies/...` (Story 4.1) — present/absent + href.

### 3.2 Integration tests
- `backend/tests/integration/test_study_pairing.py` (Story 1.1) — `find_paired_ubi_llm_study` (counterpart / None on 0,>1,wrong-kind,not-completed,running-source,cross-cluster); `get_completed_study_for_judgment_list` (1 → study, 0/>1 → None); `validate_compare_pair` against real rows (each gate + warnings).

### 3.3 Contract tests
- `backend/tests/contract/test_studies_compare.py` (Stories 1.2 + 2.1) — `/studies/compare` success + `CROSS_CLUSTER`/`TARGET_MISMATCH`/`OBJECTIVE_MISMATCH` warning payloads + every 422/404 code + **AC-8 route-ordering** (no-param → `422 VALIDATION_ERROR`); `/studies/{id}/pair` found + null + `404 STUDY_NOT_FOUND`.
- `backend/tests/contract/test_judgment_list_study.py` (Story 2.2) — `/judgment-lists/{id}/study` found + null + `404 JUDGMENT_LIST_NOT_FOUND`.

**Error-code coverage check (spec §8.5):** `STUDY_NOT_FOUND` ✓ (compare + pair), `COMPARE_STUDY_NOT_COMPLETED` ✓, `COMPARE_QUERY_SET_MISMATCH` ✓, `COMPARE_NOT_LLM_UBI_PAIR` ✓, `JUDGMENT_LIST_NOT_FOUND` ✓, `VALIDATION_ERROR` ✓. All 6 covered.

### 3.4 E2E tests
- `ui/tests/e2e/study-comparison.spec.ts` (Story 3.7/4.3) — real-backend, `page`-driven; AC-9, AC-10, AC-15. No `page.route()`. Gated behind `SKIP_HEAVY_CI`.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/judgments/value-delta-card.test.tsx` | value-delta render | existing | **Extend** — add `compareHref` present/absent cases. Existing assertions unchanged (prop is additive/optional). |
| `ui/src/__tests__/app/studies/...` (study-detail) | study-detail DOM | existing | **Extend** — add compare-button present/absent. The button is additive + hidden by default; existing assertions safe. |
| `backend/tests/contract/test_studies_api_contract.py` | `StudyDetail` shape | existing | **No change** — this feature adds no field to `StudyDetail` (it consumes the sibling's `convergence` only when present; sibling owns that schema change). |
| `backend/tests/contract/test_openapi_surface.py` | endpoint surface count | existing | **Check** — three new endpoints will change the OpenAPI surface; update the expected-path assertion if it enumerates paths. |

### 3.5b Migration verification
- **N/A** — no schema change. Alembic head stays `0022_solr_engine_auth_check`.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test` (vitest)
- [ ] `cd ui && pnpm typecheck && pnpm lint && pnpm build`
- [ ] E2E `study-comparison.spec.ts` (skipped under `SKIP_HEAVY_CI`)
- [ ] `license-inventory` gate (new `diff` dep)

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — update "Last 5 merges" + drop oldest (move narrative to `state_history.md`); active branch; note feature shipped. Alembic head unchanged. No new debt expected.
- **`architecture.md`** — add the `/studies/compare` route + `<StudyComparisonPage>` + two-series convergence overlay variant to the frontend page/component inventory; note the three read endpoints.
- **`CLAUDE.md`** — Feature Status: mark `feat_ubi_llm_study_comparison` shipped (move folder reference to implemented_features at finalize time — NOT in this plan's scope).

### 4.1 Architecture docs
- `docs/01_architecture/api-conventions.md` or `ui-architecture.md` — the three read endpoints + comparison route + chart variant (Story 5.1).

### 4.2–4.5
- `docs/08_guides/tutorial-first-study.md` Step 11 (Story 5.1). Product/runbook/security/quality: n/a (read-only, no new data flow, no ops procedure).

**Documentation DoD**
- `state.md` + `architecture.md` consistent with shipped behavior.
- Tutorial Step 11 + architecture endpoint note merged.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Centralize kind classification in the single `classify_judgment_kind` helper (no duplicate `generation_kind === 'ubi'` logic spreading on the backend). The frontend discriminator at `studies/[id]/page.tsx:211` stays (it's a display gate, not a wire-value producer), but new server-resolved `a_kind`/`b_kind` mean the comparison page never re-derives kind client-side.

### 5.2 Planned refactor tasks
- [ ] Backend: one `classify_judgment_kind` consumed by `validate_compare_pair` + `find_paired_ubi_llm_study` + `/pair`.
- [ ] Frontend: one `narrative-diff.ts` wrapper (single swap point) + one `best-so-far-curve.ts` derivation util (shape-matched to the borrowed curve).

### 5.3 Refactor guardrails
- [ ] Behavioral parity proven by tests (existing value-delta + study-detail tests stay green).
- [ ] Lint/typecheck green.
- [ ] No product-scope expansion (no rung badge, no dashboard badge).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_demo_ubi_study_comparison` Phase 1 | whole feature | **shipped (PR #320)** | nothing to compare |
| `feat_study_convergence_indicator` (`StudyDetail.convergence.best_so_far_curve`) | Story 3.5 consume path | **Approved, not implemented (same branch)** | **soft** — Story 3.5 fallback derives the curve from `/studies/{id}/trials`; feature still ships |
| `feat_pr_metric_confidence` (`StudyDetail.confidence`) | Story 3.2 | **shipped** | FR-6 degrades to plain scalar delta (acceptable; `confidence` nullable) |
| `diff` (jsdiff) npm package | Story 3.0 → 3.3 | **not yet in `ui/package.json`** | FR-4 has no clean diff path — Story 3.0 adds it first |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `/studies/compare` swallowed by `/studies/{study_id}` | M | H | Declare `compare` (+ `/pair`) before `/studies/{study_id}`; AC-8 contract test asserts no-param → `422`, not `404` |
| Generated `ui/src/lib/types.ts` not regenerated → new schemas missing from `components['schemas']` | M | M | Story 3.1 task 1 regenerates types from OpenAPI before the hooks compile |
| Sibling convergence lands mid-feature, changing `StudyDetail.convergence` shape | L | L | Story 3.5 consumes the documented `{trial_number, best_so_far}[]` shape; fallback is order-independent — neither landing order blocks the other |
| `OpenAPI surface` contract test enumerates paths and fails on 3 new endpoints | M | L | §3.5 audit flags `test_openapi_surface.py` for update |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Digest not ready for one side | `404 DIGEST_NOT_READY` | That side's digest + param-from-digest panels show a placeholder; the rest renders; param panel falls back to trials | auto (per-panel degradation) |
| Convergence data absent | `StudyDetail.convergence` null | Fallback derives curve from trials; if too few complete trials → "no convergence data yet" | auto |
| Hand-edited cross-cluster URL | `a.cluster_id != b.cluster_id` | `200` + `CROSS_CLUSTER` warning banner (NOT a 422) | auto |
| Malformed-but-length-valid id | `a="abc"` | Falls through to service lookup → `404 STUDY_NOT_FOUND` (not 422) | auto |
| Ambiguous judgment-list → study | 0 or >1 completed studies reference the list | `get_completed_study_for_judgment_list` → None; affordance hidden | auto |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 (backend core) → 2. Epic 2 (discovery endpoints) → 3. Story 3.0 (dep add) → 4. Story 3.1 (page shell + hooks) → 5. Stories 3.2–3.5 (panels) → 6. Story 3.6 (responsive) → 7. Epic 4 (entry points + E2E) → 8. Epic 5 (docs).

### Parallelization opportunities
- Epic 1 and Story 3.0 (dep add) are independent — can run in parallel.
- Panels 3.2–3.5 are independent of each other once the page shell (3.1) lands — parallelizable.
- Epic 5 (docs) can draft in parallel; screenshots need the UI built (after Epic 3).

## 8) Rollout and cutover plan

- Rollout: no flag — entry points self-gate on pair existence (invisible until a valid pair exists; demo data provides one).
- Migration/cutover: none (no schema change).
- Release gate: all AC-* green; `diff` passes `license-inventory`; no new TS/ESLint violations.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — service + repo helpers
- [ ] Story 1.2 — `/studies/compare`
- [ ] Story 2.1 — `/studies/{id}/pair`
- [ ] Story 2.2 — `/judgment-lists/{id}/study`
- [ ] Story 3.0 — `diff` dependency
- [ ] Story 3.1 — page shell + hooks + column normalization
- [ ] Story 3.2 — best-metric panel
- [ ] Story 3.3 — digest diff panel + `narrative-diff.ts`
- [ ] Story 3.4 — param diff panel
- [ ] Story 3.5 — convergence overlay + fallback
- [ ] Story 3.6 — responsive layout
- [ ] Story 4.1 — study-detail button
- [ ] Story 4.2 — value-delta affordance
- [ ] Story 3.7/4.3 — E2E
- [ ] Story 5.1 — tutorial + arch docs

## 10) Story-by-Story Verification Gate

Per story, attach evidence for:
- [ ] Files created/modified match the story's New/Modified tables
- [ ] Endpoint contract implemented exactly (method/path/params/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Tests added/updated at every layer the story touches
- [ ] Commands passed: `make test-unit`, targeted `make test-integration`, `make test-contract`, `cd ui && pnpm test` (UI), E2E if UX touched
- [ ] **No migration round-trip** (no schema change) — confirm Alembic head unchanged
- [ ] Docs updated in the same PR when behavior/contract changed

## 11) Plan consistency review

**Pass 1 — plan-internal consistency**
1. **Endpoint count:** spec §8.1 lists 3 endpoints; plan defines exactly 3 (Stories 1.2, 2.1, 2.2). ✓
2. **Error-code coverage:** all 6 codes in spec §8.5 mapped to contract tests (§3.3 check above). ✓
3. **FR coverage:** all 11 FRs in §1 traceability, each ≥1 story. ✓
4. **Story internal consistency:** endpoint tables match the Pydantic schemas (`StudyComparePairing`, `StudyPairResponse`, `JudgmentListStudyResponse`); DoD references correct codes/statuses; no new-file ownership conflicts (each new file in exactly one story). ✓
5. **Test file count/assignment:** every test file in §3 assigned to exactly one story's DoD. ✓
6. **Gate arithmetic:** Epic 2 gate = 3 endpoints live + 6 codes asserted — matches stories. ✓
7. **Open questions:** spec §19 has none blocking; both forks resolved (one thin `/judgment-lists/{id}/study` endpoint; `digest.recommended_config` + trials fallback). ✓
8. **Frontend UI Guidance completeness:** present below (insertion points, analogous JSX, layout, visual consistency, interaction, handlers, IA placement, tooltips). No component >100 LOC is deleted/migrated — **no Legacy Behavior Parity table required** (`<ValueDeltaCard>` + study-detail button are additive; nothing removed).

**Pass 2 — codebase accuracy (verification ledger)**

| Claim | Verified by | Status |
|---|---|---|
| Migrations dir `migrations/versions/`, head `0022_solr_engine_auth_check` | `ls migrations/versions/ \| tail` | Verified — **no migration needed** |
| `_err(status, code, msg, retryable)` envelope | Read `studies.py:80-84` | Verified |
| `/studies/{study_id}` route at line 549 (compare must precede) | Read `studies.py:549-562` | Verified |
| `repo.get_study` + `repo.get_judgment_list` exist | Read `repo/study.py:65`, grep `repo/judgment_list.py:51` | Verified |
| `TrialStatusWire = Literal["complete","failed","pruned"]` | `schemas.py:350` | Verified — status is `complete` not `completed` |
| trials endpoint has no `best_trial_id` filter; sorts incl. `primary_metric_asc/desc`, `optuna_trial_number_asc` | Read `studies.py:667-704` | Verified |
| `HeadlineShape.metric: str` (label source) | Read `confidence.py:131-146` | Verified |
| `studies` router + `judgments` router both mounted at `/api/v1` | Read `main.py:214-215` | Verified |
| `useStudy` key `['studies', id]`; `useStudyDigest` key `['studies', id, 'digest']` (cache reuse) | Read `studies.ts:77`, `digests.ts:36` | Verified |
| `useStudyDigest` suppresses `DIGEST_NOT_READY` toast | Read `digests.ts:48` | Verified |
| `<ValueDeltaCard>` rendered at `judgments/[id]/page.tsx:131` | Spec §2 + grep | Verified |
| Study-detail page imports `useJudgmentList` (line 25) + `isDemoSyntheticUbiClusterName` (line 28) | Read `studies/[id]/page.tsx:25,28` | Verified |
| Only `<BarChart>` exists today (overlay is a new `<LineChart>` variant) | Read `parameter-importance-chart.tsx` | Verified |
| sibling `best_so_far_curve` = `list[{trial_number, best_so_far}]` | Read convergence spec §8.3 (lines 286-294) | Verified |
| `diff` not in `ui/package.json` | spec §5 dependency note | Verified |
| E2E real-backend pattern (no `page.route()`) | Read `demo-ubi.spec.ts:1-45` | Verified |

9. **Frontend data plumbing:** every prop into the panels traces to `useStudy`/`useStudyDigest`/pairing data available on the page (§Story 3.1 state analysis). ✓
10. **Persistence scope:** no `localStorage`/`sessionStorage` used. ✓
11. **Enumerated value contract audit:** `a_kind`/`b_kind`/`kind` + `warnings[].code` are **response-only** (backend produces, frontend renders) — no user-submitted wire value drifts. Source-of-truth comments required above the frontend kind-label + warning-code maps (Story 3.1 task 5). ✓
13. **Audit-event coverage:** the feature adds **no state-mutating** endpoint or service function — every endpoint is a pure `GET` read (spec §6, §10). No `audit_log` emission applies. Explicitly justified. ✓

No unresolved findings.

---

## UI Guidance

### Reference: current component structure

- **`ui/src/app/studies/[id]/page.tsx`** (~229 lines). Composes `<StudyHeader>` (via `StudyHeaderWithSyntheticChip` at 203), `<ConfidencePanel>`, `<DigestPanel>`, `<TrialsTable>`, `<StudyActionBar>`, `<AutoFollowupChainPanel>`. Already calls `useStudy` (59), `useJudgmentList` (25-imported), `useCluster`, `isDemoSyntheticUbiClusterName`. **Insertion point for the compare button:** the header/action area near `<StudyActionBar>` (additive — no existing element removed).
- **`ui/src/components/judgments/value-delta-card.tsx`** (75 lines). Two render variants (coverage-only / delta). **Insertion point:** a new optional `compareHref` `<Link>` after the `<CardContent>` paragraph (additive).
- **`ui/src/components/common/parameter-importance-chart.tsx`** (37 lines) — the canonical Recharts pattern to mirror for the overlay (swap `<BarChart>`→`<LineChart>`, `<Bar>`→two `<Line>`).

### Analogous markup patterns

```tsx
{/* Recharts overlay — adapt from parameter-importance-chart.tsx:24-35 */}
<div data-testid="convergence-overlay" style={{ width: '100%', height: 280 }}>
  <ResponsiveContainer width="100%" height="100%">
    <LineChart margin={{ top: 8, right: 16, bottom: 8, left: 24 }}>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis dataKey="trial_number" type="number" />
      <YAxis type="number" />
      <Tooltip formatter={(v) => Number(v).toFixed(4)} />
      <Legend />
      <Line data={llmCurve} dataKey="best_so_far" name="LLM judgments" stroke="#3b82f6" dot={false} />
      <Line data={ubiCurve} dataKey="best_so_far" name="UBI judgments" stroke="#16a34a" dot={false} />
    </LineChart>
  </ResponsiveContainer>
</div>
```

```tsx
{/* Compare button — Button-asChild + Link (matches existing Button usage in study detail) */}
{pair.data?.study_id != null && (
  <Button asChild variant="secondary">
    <Link href={`/studies/compare?a=${llmId}&b=${ubiId}`}>
      Compare with the {thisIsLlm ? 'UBI' : 'LLM'} study
    </Link>
  </Button>
)}
```

```tsx
{/* Value-delta affordance — mirrors the existing prior-link in value-delta-card.tsx:56-62 */}
{compareHref && (
  <Link href={compareHref} className="text-blue-600 underline-offset-4 hover:underline"
    data-testid="value-delta-compare-link">
    View matched study comparison
  </Link>
)}
```

### Layout and structure
- `<StudyComparisonPage>`: a `grid grid-cols-1 lg:grid-cols-[1fr_auto_1fr] gap-6` — LLM left, center diff column, UBI right at `lg+`; single column with inline annotations below `lg`.
- Content hierarchy (top → bottom, per spec §11): header pair → **best-metric** (headline) → param diff → digest diff → convergence. Best-metric + param table always visible; digest diff + convergence may be `<details>`-collapsible on narrow.
- Reuse `<Card>/<CardHeader>/<CardTitle>/<CardContent>` (shadcn) for every panel, matching `parameter-importance-chart`/`value-delta-card`.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Land on `/studies/compare?a&b` | resolve pairing → normalize columns by kind → fetch warm study/digest | `GET /studies/compare`, then `GET /studies/{a}`, `/studies/{b}`, `/studies/{a}/digest`, `/studies/{b}/digest` |
| View an LLM/UBI study detail | gate compare button on pair existence | `GET /studies/{id}/pair` |
| View a UBI judgment list | two-step resolve → gate affordance | `GET /judgment-lists/{id}/study`, then `GET /studies/{ubiId}/pair` |
| Digest 404 for one side | per-side placeholder; param panel falls back to trials | (digest 404 suppressed); `GET /studies/{id}/trials` (fallback) |

### Handler / hook patterns

```ts
// ui/src/lib/api/studies.ts — additions
export function useStudyComparePairing(a: string | undefined, b: string | undefined) {
  return useQuery<StudyComparePairing, ApiError>({
    queryKey: ['studies', 'compare', a, b],
    queryFn: async () => {
      const { data } = await apiClient.get<StudyComparePairing>('/api/v1/studies/compare', { params: { a, b } });
      return data;
    },
    enabled: Boolean(a) && Boolean(b),
    retry: false,
    meta: { suppressErrorCodes: ['COMPARE_NOT_LLM_UBI_PAIR','COMPARE_QUERY_SET_MISMATCH','COMPARE_STUDY_NOT_COMPLETED','STUDY_NOT_FOUND'] },
  });
}
export function useStudyPair(studyId: string) {
  return useQuery<StudyPairResponse, ApiError>({
    queryKey: ['studies', studyId, 'pair'],
    queryFn: async () => (await apiClient.get<StudyPairResponse>(`/api/v1/studies/${studyId}/pair`)).data,
  });
}
```

### Information architecture placement
- No top-level sidebar entry — the view is contextual (reached from study-detail button + value-delta affordance). Route `/studies/compare` is shareable/linkable. Canonical column order (A=LLM, B=UBI) is enforced server-side via resolved kind + frontend normalization (AC-18) so shared/reversed URLs render stably.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment | Pattern |
|---|---|---|---|---|---|---|
| Best-metric delta | "Difference in {metric} between the UBI-judged and LLM-judged study on the same queries. Inside the confidence band = likely noise." | info icon | top | `study_comparison_delta` (new, register in `glossary.ts`) | `// Source-of-truth: backend/app/domain/study/confidence.py HeadlineShape` | `<InfoTooltip glossaryKey="study_comparison_delta" />` (existing primitive, imported at `studies/[id]/page.tsx:10`) |
| Convergence overlay | "Best metric seen so far at each trial, for both studies. Compare where each path plateaued." | info icon | top | `study_comparison_convergence` (new) | `// Source-of-truth: feat_study_convergence_indicator best_so_far_curve` | `<InfoTooltip glossaryKey="study_comparison_convergence" />` |
| `Δ` parameter flag | "These two studies' best trials chose different values for this parameter." | hover | inline | (plain `title` — self-explanatory; no glossary key required per spec §11) | — | `<span title="...">Δ</span>` |
| Synthetic-data chip | (reuses Phase-1 chip copy — no new key) | hover | inline | (existing) | — | reuse existing chip |

New glossary keys (`study_comparison_delta`, `study_comparison_convergence`) MUST be added to `ui/src/lib/glossary.ts` following the `short`/`long` pattern.

### Component composition
- `<StudyComparisonPage>` orchestrates; four panels extracted into `ui/src/components/studies/comparison/*` (each accepts the two studies' data + a `stacked?` flag). `narrative-diff.ts`, `param-diff.ts`, `best-so-far-curve.ts` are pure utils (unit-testable, no React). Rationale: panels are independently testable and the diff/curve math must be unit-covered without rendering.

### Legacy behavior parity
**No legacy behavior parity table** — no user-facing component >100 LOC is deleted or migrated. `<ValueDeltaCard>` gains an optional additive prop; the study-detail button is additive; all four panels are net-new.

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, Endpoints (where API-facing), Key interfaces, Tasks, DoD.
- [x] Test layers (unit/integration/contract/e2e) explicitly scoped + assigned.
- [x] Documentation updates planned (tutorial + architecture).
- [x] Lean refactor scope + guardrails explicit.
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed — no unresolved findings.

## Review log

- **Mode:** Generate.
- **Source spec:** `feature_spec.md` (Approved, 614 lines, 11 FRs, 21 ACs).
- **Cross-model review:** **Skipped — Opus-only internal passes per operator decision** (feature 4 of 5 on `feature/mvp2-top5-plans`). 2 internal consistency passes (Pass 1 + Pass 2) performed; no GPT-5.5 cycle.
- **Verification ledger:** §11 Pass 2 table — 16 material claims checked against the live codebase, all Verified (notably: no migration needed; route ordering; `complete` not `completed`; no `best_trial_id` filter; `confidence.headline.metric` label; sibling `best_so_far_curve` shape; `diff` absent).
- **Spec-plan alignment:** all 11 FRs covered; all 3 endpoints have stories + contract tests; all 6 error codes asserted; convergence overlay implements BOTH consume-when-present and fallback-derivation; `diff` dependency-add is its own story (3.0).
- **Open questions:** none (spec §19 forks resolved).
- **Proposed doc updates:** `state.md` + `architecture.md` deferred to finalize-time (post-implementation), not this plan.
