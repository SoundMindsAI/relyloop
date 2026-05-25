# Implementation Plan — feat_study_clone_from_previous

**Date:** 2026-05-24
**Status:** Draft (pending GPT-5.5 cycle 1)
**Primary spec:** [feature_spec.md](feature_spec.md) (15 FRs, 17 ACs, 12 locked decisions)
**Target branch:** `feature/study-clone-from-previous` (already created off `origin/main` be98b9b1 in the active worktree)

## 0) Planning principles

- **No new migration.** `studies.parent_study_id` already exists at [`migrations/versions/0003_study_lifecycle_schema.py:183`](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183) and is actively written by `feat_auto_followup_studies`. Current Alembic head: `0019_digests_suggested_followups_jsonb` (verified `ls migrations/versions/ | sort | tail -1`). This feature ships pure code.
- **Single phase, single PR.** Per spec §3, the "narrow bounds" smart-rewrite is split to [`feat_study_clone_narrow_bounds/idea.md`](../feat_study_clone_narrow_bounds/idea.md). One PR ships v1.
- **Forward-only.** Per CLAUDE.md `feedback_no_legacy_preservation`: no compat shim, no legacy preservation. New optional field on the request; existing clients unaffected by construction.
- **Spec-as-contract.** Every story DoD asserts the exact ACs from the spec; the spec's error codes, validation order, and decision log are not re-litigated at plan time.

## 1) Scope traceability (FR → epics/stories)

| FR | Spec section | Implementing story | Test layer(s) |
|---|---|---|---|
| FR-1 (Clone button placement) | §7 | Story 2.2 | Vitest study-action-bar; Playwright |
| FR-2 (No clone on digest panel) | §7 | Story 2.2 (regression assertion only — no edit to `digest-panel.tsx`) | Vitest assertion |
| FR-3 (Navigate to ?clone_from) | §7 | Story 2.2 | Vitest study-action-bar |
| FR-4 (Deep-link honored, param normalization, lifecycle) | §7 | Story 2.3 | Vitest studies/page; Playwright (stable outcomes) |
| FR-5 (`buildPrefillFromStudy` helper + cloneSource mapping) | §7 | Story 2.1 | Vitest prefill-from-study (pure-function) |
| FR-6 (POST carries `parent_study_id`; excludes `cloneSource`) | §7 | Story 2.1 (serializer hygiene) + Story 2.2 (modal submit) | Vitest create-study-modal request-body assertion |
| FR-7 (`CreateStudyRequest.parent_study_id` field) | §7 + §8 | Story 1.1 | Contract test_create_study_parent (schema + length bound) |
| FR-8 (Validation: exists? same cluster?) + D-9 placement | §7 + §8 | Story 1.2 | Contract test_studies_error_codes + Integration cases (b,c,e) |
| FR-9 (Persist via `repo.create_study(parent_study_id=…)`) | §7 | Story 1.2 | Integration case (a) |
| FR-10 (Independent of `parent: ParentFollowupRef`) | §7 | Story 1.2 (no exclusion check) | Integration case (d) |
| FR-11 (Running-confirm AlertDialog) | §7 | Story 2.2 | Vitest study-action-bar (running path) |
| FR-12 (Cloned-from banner; reads `cloneSource`) | §7 | Story 2.1 (type) + Story 2.2 (render in modal) | Vitest create-study-modal banner cases |
| FR-13 (Glossary entries `study.clone_button` + `study.cloned_from_banner`) | §7 | Story 2.1 (glossary) | Existing glossary lint test catches new keys |
| FR-14 (Cancel-cascade chain participation; no new code) | §7 | Story 1.3 (regression integration test (f)) | Integration case (f) |
| FR-15 (Auto_followup self-suppression; no new code) + D-10 | §7 | Story 1.3 (regression integration test (g)) | Integration case (g) |

**All 15 FRs mapped. Every FR has at least one story owner and at least one test layer.**

## 2) Delivery structure

3 epics, 7 stories. Sequence: Epic 1 (backend) → Epic 2 (frontend) → Epic 3 (E2E + docs). Frontend depends on backend's wire-shape change for OpenAPI codegen; E2E depends on both.

### Story-level conventions for this plan

- **Backend Python:** `make fmt && make lint && make typecheck && make test-unit && make test-contract` before each story marks DoD-done.
- **Backend integration tests:** require running Postgres + ES + OpenSearch via `make up`. Each integration story runs `make test-integration` before DoD-done.
- **Frontend:** `cd ui && pnpm lint && pnpm typecheck && pnpm test` before each frontend story marks DoD-done. `pnpm build` runs at the end of Epic 2.
- **E2E:** real backend per CLAUDE.md "E2E Testing Rules" — NO `page.route()` mocking. Setup via `request`, assertions via `page`. Pattern reference: [`ui/tests/e2e/dashboard-reseed.spec.ts`](../../../../ui/tests/e2e/dashboard-reseed.spec.ts).
- **Schema regen:** after Story 1.1, the OpenAPI schema regenerates `ui/src/lib/api/openapi-types.ts` (auto via `pnpm` codegen — confirm by `grep parent_study_id ui/src/lib/api/openapi-types.ts`). Frontend stories pick this up automatically.

### AI Agent Execution Protocol

Per CLAUDE.md absolute rule #9: use `/impl-execute` to drive stories. Each story's DoD lists the exact gates (`make` targets, file existence, AC mappings) that must be green before marking it complete.

---

## Epic 1 — Backend: schema field + validation + persistence + regression tests

### Story 1.1 — Add `parent_study_id` to `CreateStudyRequest`

**Outcome:** [`backend/app/api/v1/schemas.py:CreateStudyRequest`](../../../../backend/app/api/v1/schemas.py#L633) gains the optional `parent_study_id: str | None` field with the spec's 36-char length bound. OpenAPI schema regenerates and TS type surfaces the new field.

**Modified files:**
- `backend/app/api/v1/schemas.py` — add field to `CreateStudyRequest` (additive, after existing `parent: ParentFollowupRef | None = None` field at line 655).

**New files:** none.

**Tasks:**
1. Add `parent_study_id` field to `CreateStudyRequest` matching the spec's §8 Pydantic declaration verbatim:
   ```python
   parent_study_id: str | None = Field(
       default=None,
       min_length=36,
       max_length=36,
       description=(
           "feat_study_clone_from_previous FR-7 — when the operator clones an "
           "existing study via the study-detail Clone button, this carries the "
           "source study's id. Server validates existence (404 "
           "PARENT_STUDY_NOT_FOUND) and same-cluster (422 "
           "PARENT_STUDY_WRONG_CLUSTER) before persisting to studies.parent_study_id. "
           "Independent of the proposal-lineage 'parent' field (D-5); both may be set."
       ),
   )
   ```
2. Update `backend/tests/contract/test_create_study_parent.py` to add (i) a schema-introspection case for `parent_study_id` optional + length-bound (mirror existing `test_create_study_request_parent_is_optional`), AND (ii) **runtime 422 cases** — POST with `parent_study_id: "short"` (length < 36) and `parent_study_id: "x" * 37` (length > 36) → assert HTTP 422 with `detail.error_code == "VALIDATION_ERROR"` (proves AC-8, which requires the Pydantic length check to fire before the FK lookup). The runtime tests can use FastAPI's `TestClient` synchronously like the existing parent-validation router tests.
3. **Regenerate OpenAPI TS types.** Run the project's codegen command (verify in `ui/package.json` — typically `pnpm run codegen` or similar) which updates `ui/src/lib/api/openapi-types.ts`. If that file is checked in (verify with `git status` after regen), include it in the story's modified files list.
4. Run `make test-contract` — verify new cases green; existing cases unchanged.

**Modified files (revised):**
- `backend/app/api/v1/schemas.py` — add field (additive, after existing `parent: ParentFollowupRef | None = None` field at line 655).
- `backend/tests/contract/test_create_study_parent.py` — extend with new cases.
- `ui/src/lib/api/openapi-types.ts` — regenerated (if the project commits this file; otherwise just a build artifact regenerated at build time).

**DoD:**
- [ ] `grep -n "parent_study_id" backend/app/api/v1/schemas.py` shows the new field at line ~656-670.
- [ ] `make test-contract -- -k test_create_study_parent` green (both schema-introspection + runtime-422 cases).
- [ ] `python -c "from backend.app.api.v1.schemas import CreateStudyRequest; assert 'parent_study_id' in CreateStudyRequest.model_fields"` succeeds.
- [ ] `grep -n "parent_study_id" ui/src/lib/api/openapi-types.ts` returns a match (codegen picked up the new field).
- [ ] Validates FR-7 + AC-8 (runtime length-bound 422).

### Story 1.2 — Validate + persist `parent_study_id` in `_create_study`

**Outcome:** [`backend/app/api/v1/studies.py:_create_study`](../../../../backend/app/api/v1/studies.py#L200) validates `parent_study_id` (exists? same cluster?) immediately after cluster FK resolution and before template/qs/jl FK resolution (D-9 placement). Persists via `repo.create_study(..., parent_study_id=body.parent_study_id)`.

**Modified files:**
- `backend/app/api/v1/studies.py` — insert validation block after line 210 (after cluster FK resolution); add `parent_study_id=body.parent_study_id` to the `repo.create_study(...)` call at line 386.

**New files:** none. `repo.create_study(db, **fields)` already accepts variadic kwargs at [`backend/app/db/repo/study.py:47`](../../../../backend/app/db/repo/study.py#L47) — no repo signature change.

**Tasks:**
1. Add the parent-study validation block in `_create_study` immediately after `if cluster is None: raise _err(404, "CLUSTER_NOT_FOUND", ...)` (line 210):
   ```python
   # FR-8 / D-9: parent-study lineage validation, placed early so wrong-cluster
   # clones surface as PARENT_STUDY_WRONG_CLUSTER rather than as the downstream
   # JUDGMENT_CLUSTER_MISMATCH at studies.py:255.
   if body.parent_study_id is not None:
       parent_study = await repo.get_study(db, body.parent_study_id)
       if parent_study is None:
           raise _err(
               404,
               "PARENT_STUDY_NOT_FOUND",
               f"parent study {body.parent_study_id} not found",
               False,
           )
       if parent_study.cluster_id != body.cluster_id:
           raise _err(
               422,
               "PARENT_STUDY_WRONG_CLUSTER",
               (
                   f"parent study {body.parent_study_id} is on cluster "
                   f"{parent_study.cluster_id!r}; clone target cluster is "
                   f"{body.cluster_id!r}"
               ),
               False,
           )
   ```
2. Add `parent_study_id=body.parent_study_id` to the `repo.create_study(...)` keyword-args block (line 386) alongside the existing `parent_proposal_id=parent_proposal_id` arg.
3. Run `make test-unit && make test-contract` — verify no regressions on existing test_studies_error_codes / test_create_study_parent / test_studies_api_contract.

**DoD:**
- [ ] `grep -n "PARENT_STUDY_NOT_FOUND\|PARENT_STUDY_WRONG_CLUSTER" backend/app/api/v1/studies.py` returns two matches.
- [ ] Validation block lives after `if cluster is None:` (line ~210) and before template FK resolution (line ~211) — confirm via line-context grep.
- [ ] `repo.create_study(...)` call includes `parent_study_id=body.parent_study_id`.
- [ ] `make test-unit && make test-contract` green.
- [ ] Validates FR-8, FR-9, FR-10, D-9 placement.

### Story 1.3 — Backend regression tests (cascade-of-clone + auto_followup self-suppression + validation-order + happy-path)

**Outcome:** [`backend/tests/integration/test_studies_api.py`](../../../../backend/tests/integration/test_studies_api.py) gains the 5 new integration cases (a) happy clone, (b) missing parent → 404, (c) wrong-cluster → 422, (e) validation-order, (f) cascade-of-clone via API, (g) auto_followup self-suppression. `test_studies_error_codes.py` gains envelope-shape assertions for `PARENT_STUDY_NOT_FOUND` and `PARENT_STUDY_WRONG_CLUSTER`. The `(d)` round-trip case (both `parent_study_id` + `parent: ParentFollowupRef` set) lives in `test_create_study_parent.py`.

**Modified files:**
- `backend/tests/integration/test_studies_api.py` — add cases (a), (b), (c), (d), (e), (f).
- `backend/tests/integration/test_studies_clone_autofollowup.py` (new) — case (g) (worker-invocation test in its own file to keep `test_studies_api.py` under its current 50KB).
- `backend/tests/contract/test_studies_error_codes.py` — add 2 envelope-shape cases for the new error codes (static-grep + envelope-shape pattern, no DB).

**New files:**
- `backend/tests/integration/test_studies_clone_autofollowup.py` — case (g).

**Tasks:**
1. **Case (a) — happy clone:** seed cluster + template + query set + judgment list + source study (status=`completed` via existing fixtures); POST `/api/v1/studies` with `parent_study_id=source.id`; assert 201 + GET on new study returns `parent_study_id=source.id`.
2. **Case (b) — missing parent → 404:** POST with `parent_study_id="00000000-0000-7000-8000-000000000000"` (valid UUIDv7 length, no row); assert envelope `{error_code: "PARENT_STUDY_NOT_FOUND", retryable: false}`.
3. **Case (c) — wrong-cluster → 422:** seed two clusters X+Y; seed source study on X; POST with `cluster_id=Y, parent_study_id=source.id` (and all jl/qs/tmpl scoped to Y to isolate the FR-8 failure); assert envelope `{error_code: "PARENT_STUDY_WRONG_CLUSTER", retryable: false}`.
4. **Case (d) — round-trip both lineage axes (DB-backed integration):** seed cluster + source study + proposal + digest with followups; POST with BOTH `parent_study_id=source.id` AND `parent={proposal_id: ..., followup_index: 0}`; assert 201 + the persisted row in `studies` table has BOTH `parent_study_id == source.id` AND `parent_proposal_id == proposal.id` AND `parent_proposal_followup_index == 0`. **Lives in `test_studies_api.py`** (integration, NOT contract) because it asserts on persisted DB columns — contract tests have no DB. Validates FR-10.
5. **Case (e) — validation order (D-9):** seed source A on cluster X with a judgment-list-on-X; POST with `cluster_id=Y, parent_study_id=A.id, judgment_list_id=jl-on-X.id` (constructs a scenario where BOTH `PARENT_STUDY_WRONG_CLUSTER` (FR-8) AND `JUDGMENT_CLUSTER_MISMATCH` (existing line 255 check) would fail); assert the response error_code is `PARENT_STUDY_WRONG_CLUSTER` (proves FR-8 early placement).
6. **Case (f) — cascade-of-clone (FR-14):** (i) **Seed parent A directly via `repo.create_study(db, status="running", ...)`** (mirrors the `_seed_parent_chain` pattern at [`backend/tests/integration/test_auto_followup.py:37`](../../../../backend/tests/integration/test_auto_followup.py#L37) which already seeds parents at arbitrary `status` via the repo's variadic kwargs — bypassing the POST's `status="queued"` hardcoding is the established pattern); (ii) create clone B via the NEW code path — POST `/api/v1/studies` with `parent_study_id=A.id`; (iii) cancel A with `cascade=true` via the cancel endpoint; (iv) assert both A and B end in `cancelled` status. The test exercises the new write path (POST with clone lineage) AND the existing cascade logic against a clone child.
7. **Case (g) — auto_followup self-suppression (FR-15 / D-10) — matches AC-12 lifecycle:** (i) **Seed parent A as `status="running"`** directly via `repo.create_study(db, status="running", config={"auto_followup_depth": 1}, ...)`; (ii) create clone B via the NEW POST code path with `parent_study_id=A.id` (this is the AC-12 "clone exists before parent completes" precondition); (iii) seed N>=20 complete trials for A so the chain-gate lift check would pass if it ran (otherwise the worker could short-circuit on a different decision before reaching the LAYER-2 idempotency check — mirrors `_seed_parent_chain`'s `n_complete_trials=20` default); (iv) **transition A to `completed`** via direct DB update (e.g., `await db.execute(update(Study).where(Study.id == A.id).values(status="completed", best_metric=0.5)); await db.commit()`) — matches the AC-12 lifecycle "A transitions to `completed`" step; no service-layer helper needed since `_seed_parent_chain` itself uses direct repo writes for the same setup; (v) invoke `enqueue_followup_study(ctx, parent_study_id=A.id)` directly (existing test pattern at `backend/tests/integration/test_auto_followup.py`); (vi) assert log event `auto_followup_enqueued_duplicate_dropped` fires (via `caplog` or whatever log-capture fixture the existing auto_followup tests use — `grep -n "caplog\|structlog.*capture" backend/tests/integration/test_auto_followup.py` to confirm) AND `repo.list_children_of_study(db, A.id)` still returns exactly `[B]` (no new auto-spawned child).
8. **Envelope assertions (contract):** add 2 cases to `test_studies_error_codes.py` mirroring the existing per-code static-grep + envelope-shape pattern.

**DoD:**
- [ ] All 7 cases (a)–(g) implemented in the named files; case (d) lives in `test_studies_api.py` (integration) NOT in `test_create_study_parent.py` (contract).
- [ ] `make test-integration && make test-contract` green.
- [ ] Validates FR-9, FR-10, FR-14, FR-15, D-9, D-10. Also covers ACs 5, 6, 7, 10, 11, 12, 13.

---

## Epic 2 — Frontend: types + helper + UI components + page wiring

### Story 2.1 — Extend `PrefillValues` + write `buildPrefillFromStudy` helper + glossary entries

**Outcome:** [`ui/src/components/studies/create-study-modal.tsx:PrefillValues`](../../../../ui/src/components/studies/create-study-modal.tsx#L165-L187) is widened with `parent_study_id?: string` and `cloneSource?: { id, name }` and the existing `parent` field becomes optional. New helper `buildPrefillFromStudy(source: StudyDetail): PrefillValues` lives at `ui/src/components/studies/prefill-from-study.ts`. Glossary gains `study.clone_button` and `study.cloned_from_banner` entries.

**Modified files:**
- `ui/src/components/studies/create-study-modal.tsx` — widen `PrefillValues` interface (~5 line edit). Confirm existing callers (`proposals/[id]/page.tsx:181-215`) still type-check by re-running `pnpm typecheck`.
- `ui/src/lib/glossary.ts` — add two entries under a new `// Source-of-truth: feat_study_clone_from_previous spec §11 tooltip inventory` comment.

**New files:**
- `ui/src/components/studies/prefill-from-study.ts` — exports `buildPrefillFromStudy(source: StudyDetail): PrefillValues`. Pure function, no React imports.
- `ui/src/components/studies/__tests__/prefill-from-study.test.ts` — vitest for the pure function.

**Key interfaces:**

```typescript
// ui/src/components/studies/prefill-from-study.ts
import type { StudyDetail } from '@/lib/api/studies';
import type {
  ObjectiveMetric,
  ObjectiveK,
  ObjectiveDirection,
  SamplerKind,
  PrunerKind,
} from '@/lib/enums';   // these types live in ui/src/lib/enums.ts, NOT in create-study-modal
import type { PrefillValues } from './create-study-modal';

const SOURCE_NAME_MAX = 200;  // per spec FR-5: source name truncated to 200 chars (NO ellipsis added),
                              // then " (clone)" suffix concatenated → max final length ≤ 208 chars,
                              // well under the 256-char CreateStudyRequest.name bound.

export function buildPrefillFromStudy(source: StudyDetail): PrefillValues {
  const truncatedSourceName = source.name.slice(0, SOURCE_NAME_MAX);  // no ellipsis — per spec FR-5
  const objective = source.objective as {
    metric: ObjectiveMetric;
    k?: ObjectiveK;
    direction: ObjectiveDirection;
  };
  const config = source.config as {
    max_trials?: number;
    time_budget_min?: number;
    parallelism?: number;
    trial_timeout_s?: number;
    sampler?: SamplerKind;
    pruner?: PrunerKind;
    seed?: number;
  };
  return {
    cluster_id: source.cluster_id,
    target: source.target,
    template_id: source.template_id,
    query_set_id: source.query_set_id,
    judgment_list_id: source.judgment_list_id,
    name: `${truncatedSourceName} (clone)`,
    search_space_text: JSON.stringify(source.search_space, null, 2),
    metric: objective.metric,
    k: objective.k,
    direction: objective.direction,
    max_trials: config.max_trials,
    time_budget_min: config.time_budget_min,
    parallelism: config.parallelism,
    trial_timeout_s: config.trial_timeout_s,
    sampler: config.sampler,
    pruner: config.pruner,
    seed: config.seed,
    parent_study_id: source.id,
    cloneSource: { id: source.id, name: source.name },
    // parent intentionally omitted — clone path does not carry proposal-followup lineage
  };
}
```

**Glossary entries:**

```typescript
// In ui/src/lib/glossary.ts (under appropriate study.* section):
// Source-of-truth: feat_study_clone_from_previous spec §11 (FR-13)
'study.clone_button': {
  short:
    'Open the create-study form pre-filled with this study’s settings. Useful for iterating with narrowed bounds or a different objective.',
  ariaLabel: 'About the Clone study button',
},
'study.cloned_from_banner': {
  short:
    'This study will be created as a fork of the linked source. The lineage is recorded for future reference.',
  ariaLabel: 'About the cloned-from banner',
},
```

**Tasks:**
1. Widen `PrefillValues` interface — make `parent` optional, add `parent_study_id?: string`, add `cloneSource?: { id: string; name: string }`. Verify all 4 existing callers still compile: `grep -rn "PrefillValues" ui/src/` to enumerate them, then `pnpm typecheck`.
2. Create `prefill-from-study.ts` with the key interface above. Pure function, no side effects.
3. Create `__tests__/prefill-from-study.test.ts` with cases: (i) every field maps correctly from a fully-populated `StudyDetail`; (ii) `cloneSource.name` carries the un-truncated source name AND `cloneSource.id === source.id`; (iii) source.name = 250 chars → form-level `name` = `source.name.slice(0,200) + " (clone)"` (exactly 208 chars, NO ellipsis); (iv) source.name = 50 chars → form-level `name` = `"source.name (clone)"` (no truncation needed); (v) optional config keys missing → `undefined` (form defaults stand); (vi) `parent_study_id === source.id`; (vii) `parent` is undefined.
4. Add the 2 glossary entries. Re-run `pnpm test -- glossary` to confirm existing glossary lint passes the new keys.

**DoD:**
- [ ] `pnpm typecheck` green (proves existing `PrefillValues` callers in `proposals/[id]/page.tsx` still compile after `parent` became optional).
- [ ] `pnpm test -- prefill-from-study` green with all 6 vitest cases.
- [ ] `pnpm test -- glossary` green with new entries present.
- [ ] Validates FR-5, FR-13, D-12 (cloneSource type).

### Story 2.2 — "Clone study" button + running-confirm + cloned-from banner + payload serializer hygiene

**Outcome:** [`StudyActionBar`](../../../../ui/src/components/studies/study-action-bar.tsx) gains a "Clone study" button (with `data-testid="clone-study"`) to the left of "Cancel study", visible on every status. Clicking on `status === "running"` opens an `AlertDialog` (`data-testid="clone-running-confirm"`); other statuses navigate directly. [`CreateStudyModal`](../../../../ui/src/components/studies/create-study-modal.tsx) renders a banner above Step 1 when `initialValues.cloneSource` is present. The modal's submit serializer excludes `cloneSource` from the POST body.

**Modified files:**
- `ui/src/components/studies/study-action-bar.tsx` — add `useRouter` import (Next 16 App Router pattern), add "Clone study" button + handler + optional `AlertDialog` for running source. Existing Cancel-study path unchanged.
- `ui/src/components/studies/create-study-modal.tsx` — (a) render banner conditional on `initialValues.cloneSource`; (b) in submit handler, ensure the payload sent to `useCreateStudy.mutate(...)` is field-by-field assembled (or destructure-and-omit `cloneSource`) so the UI-only metadata never reaches the wire.
- `ui/src/components/studies/__tests__/study-action-bar.test.tsx` — extend (or create if absent) with clone-button cases.
- `ui/src/components/studies/__tests__/create-study-modal.test.tsx` — extend with banner + serializer cases (a), (b), (c), (e) from spec §14.

**New files:** none.

**Tasks:**
1. **`study-action-bar.tsx` — add Clone button:**
   ```tsx
   import { useRouter } from 'next/navigation';
   // ...inside component:
   const router = useRouter();
   const [cloneConfirmOpen, setCloneConfirmOpen] = useState(false);

   const handleClone = () => {
     if (study.status === 'running') {
       setCloneConfirmOpen(true);
     } else {
       router.push(`/studies?clone_from=${study.id}`);
     }
   };
   // ...in JSX, BEFORE the existing Cancel button:
   <Button variant="outline" onClick={handleClone} data-testid="clone-study">
     Clone study
   </Button>
   <InfoTooltip glossaryKey="study.clone_button" />
   ```
2. **`study-action-bar.tsx` — running-confirm `AlertDialog`:** mirror the existing cancel `AlertDialog` at lines 63-130. Copy: title "Clone an in-progress study?"; description "'{study.name}' is still running. The clone will use the current configuration but its trials are still being tuned."; primary action "Clone anyway" with `data-testid="clone-confirm-proceed"` → `router.push('/studies?clone_from=...')` + close dialog; cancel "Cancel" closes.
3. **`create-study-modal.tsx` — banner:** render above Step 1 content conditional on `initialValues?.cloneSource`:
   ```tsx
   {initialValues?.cloneSource && (
     <div className="mb-4 rounded-md border bg-muted/40 px-4 py-2 text-sm" data-testid="cloned-from-banner">
       Cloned from study <strong>{initialValues.cloneSource.name}</strong>
       {' · '}
       <Link href={`/studies/${initialValues.cloneSource.id}`} className="underline">
         view source
       </Link>
       <InfoTooltip glossaryKey="study.cloned_from_banner" />
     </div>
   )}
   ```
4. **`create-study-modal.tsx` — serializer hygiene:** locate the submit handler that calls `create.mutate(...)` (currently around line 350-400 — verify with `grep -n "create.mutate\|createMutation" ui/src/components/studies/create-study-modal.tsx`). Refactor to explicitly assemble the `CreateStudyRequest`-shaped payload field-by-field. The payload MUST include `parent: initialValues?.parent ?? undefined` (the existing proposal-followup lineage — must NOT be dropped during the refactor; the shipped proposal-detail "Run this followup" flow at `ui/src/app/proposals/[id]/page.tsx` depends on it) AND `parent_study_id: initialValues?.parent_study_id ?? undefined` (the new clone lineage from FR-7). MUST exclude `cloneSource` (UI-only per D-12) — no `...initialValues` spread that would carry it through. Add a comment `// cloneSource is UI-only — never serialize into POST per D-12. Both parent (proposal-followup) and parent_study_id (clone) are independent lineage axes per D-5 / FR-10.`
5. **Vitest study-action-bar.test.tsx:**
   - (a) Button renders for every status (parametrize over `'queued'|'running'|'completed'|'failed'|'cancelled'`).
   - (b) Clone click on `completed` source navigates to `/studies?clone_from={id}` (assert `router.push` mock called once with the right URL).
   - (c) Clone click on `running` source opens dialog (assert `data-testid="clone-running-confirm"` visible, no router.push yet); "Clone anyway" navigates; "Cancel" closes without navigation.
6. **Vitest create-study-modal.test.tsx:**
   - (a) `initialValues.parent_study_id` set → POST payload includes `parent_study_id` AND **lacks `cloneSource` as an own property** (assert via direct payload inspection, not `expect.not.objectContaining` which can miss `cloneSource: undefined` keys):
     ```typescript
     const payload = mockMutate.mock.calls[0][0];
     expect(payload).toHaveProperty('parent_study_id', 'X');
     expect(Object.prototype.hasOwnProperty.call(payload, 'cloneSource')).toBe(false);
     ```
     This catches both `cloneSource: { id, name }` leaks AND the subtler `cloneSource: undefined` leak that an `...initialValues` spread would produce.
   - (b) Banner renders when `initialValues.cloneSource` is present (assert `getByTestId('cloned-from-banner')`).
   - (c) Banner absent when `cloneSource` absent — including synthetic case where `parent_study_id` is present but `cloneSource` is not (assert `queryByTestId('cloned-from-banner')` is null).
   - (d) Regression: modal still works when neither `parent` nor `parent_study_id` nor `cloneSource` set (existing "New study" flow).
   - (e) Serializer shape: spread-pattern is forbidden — destructure-and-omit OR field-by-field assembly (verified by case (a)'s `hasOwnProperty` check).
   - (g) **Existing `parent: ParentFollowupRef` preservation (regression on the proposal-followup flow):** with `initialValues = { ...all_form_fields, parent: { proposal_id: "X", followup_index: 0 } }` (clone-mode keys absent), assert the POST payload includes `parent: { proposal_id: "X", followup_index: 0 }`. Regression guard against the serializer refactor accidentally dropping the proposal-followup lineage.
   - (h) **Both lineage axes set (clone-of-a-followup-study):** with `initialValues` containing BOTH `parent: { proposal_id: "X", followup_index: 0 }` AND `parent_study_id: "A"` AND `cloneSource: { id: "A", name: "..." }`, assert POST payload has BOTH `parent` AND `parent_study_id` AND `cloneSource` is absent (FR-10 + D-12 round-trip at the frontend layer; the backend round-trip is already covered by integration case (d)).
   - (f) **FR-2 regression assertion (covers AC-9):** import `DigestPanel` from `ui/src/components/studies/digest-panel.tsx`, render it with a minimal mock `DigestResponse` props (no special setup beyond the existing test fixtures — `digest-panel.test.tsx` likely already exists; if it does, extend it, otherwise create a new `__tests__/digest-panel.test.tsx`). Assert: `queryByTestId('clone-study')` returns null; the panel DOM contains no element with text matching `/Clone study/i`. Documents that Clone is intentionally NOT exposed from the digest panel (D-7 / FR-2).

**DoD:**
- [ ] `grep -n "clone-study\|clone-running-confirm\|cloned-from-banner" ui/src/` returns three distinct test-IDs.
- [ ] `pnpm test -- study-action-bar create-study-modal` green with all new cases.
- [ ] `pnpm typecheck` green.
- [ ] `grep -n "cloneSource" ui/src/components/studies/create-study-modal.tsx` shows the comment + the banner read + NO submit-time use.
- [ ] Validates FR-1, FR-2 (assertion-only, no edit to `digest-panel.tsx`), FR-3, FR-6, FR-11, FR-12, D-12 serializer hygiene. Covers ACs 1, 2, 4, 5, 9, 15, 16.

### Story 2.3 — Deep-link `?clone_from` wiring on `/studies` page + invalid-param handling

**Outcome:** [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx) reads `?clone_from=<id>` inside `StudiesPageInner` (under the existing `<Suspense>` boundary at the default export). Distinguishes presence-vs-absence-vs-empty/invalid per FR-4. Fetches the source via `useStudy(cloneFromId, { enabled })`, builds prefill via `buildPrefillFromStudy`, opens `CreateStudyModal` with `initialValues`, and `router.replace`s to clear the param.

**Modified files:**
- `ui/src/app/studies/page.tsx` — add the `?clone_from` reader inside `StudiesPageInner` (NOT in the default export — Next 16 requires Suspense wrapping).
- `ui/src/app/studies/__tests__/page.test.tsx` (new if absent) — vitest cases for the 4 deep-link states (absent, empty, garbage, valid).

**New files:** possibly `ui/src/app/studies/__tests__/page.test.tsx` if no test file currently exists for this page.

**Key interfaces:**

```tsx
// Inside StudiesPageInner — add ABOVE the existing useStudies query:
import { useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useStudy } from '@/lib/api/studies';
import { buildPrefillFromStudy } from '@/components/studies/prefill-from-study';
import type { PrefillValues } from '@/components/studies/create-study-modal';
import { toast } from 'sonner';
// ...
const router = useRouter();
const searchParams = useSearchParams();
const [cloneInitialValues, setCloneInitialValues] = useState<PrefillValues | null>(null);
// One-shot guard via useRef so exhaustive-deps lint stays clean (avoids
// the stale-closure issue from depending on cloneInitialValues inside the
// effect that sets it — per cycle-2 F3).
const cloneEffectFired = useRef(false);

const hasCloneFrom = searchParams.has('clone_from');
const cloneFromId = searchParams.get('clone_from')?.trim() || null;
const cloneFromValid =
  cloneFromId !== null && cloneFromId.length === 36;
const cloneSource = useStudy(cloneFromId ?? '', { enabled: cloneFromValid });

useEffect(() => {
  if (!hasCloneFrom) return;        // !hasCloneFrom path is a no-op (per FR-4 / D-11)
  if (cloneEffectFired.current) return; // one-shot
  if (!cloneFromValid) {
    cloneEffectFired.current = true;
    setCloneInitialValues(null); // ← per cycle-2 F2: explicit reset so stale prefill from a prior visit cannot leak
    toast.error('Invalid clone-from id — opening empty create form');
    router.replace('/studies');
    setCreateOpen(true);
    return;
  }
  if (cloneSource.isError) {
    cloneEffectFired.current = true;
    setCloneInitialValues(null); // ← cycle-2 F2 reset
    toast.error(`Source study ${cloneFromId} not found — opening empty create form`);
    router.replace('/studies');
    setCreateOpen(true);
    return;
  }
  if (cloneSource.data) {
    cloneEffectFired.current = true;
    setCloneInitialValues(buildPrefillFromStudy(cloneSource.data));
    setCreateOpen(true);
    router.replace('/studies');
  }
  // Dependencies: hasCloneFrom + cloneFromValid + cloneFromId + cloneSource state.
  // cloneInitialValues intentionally omitted — guarded by useRef one-shot.
}, [hasCloneFrom, cloneFromValid, cloneFromId, cloneSource.data, cloneSource.isError, router]);

// In JSX, pass initialValues:
<CreateStudyModal
  open={createOpen}
  onOpenChange={(open) => {
    setCreateOpen(open);
    if (!open) {
      setCloneInitialValues(null); // clear on close so next "Create study" click is fresh
      cloneEffectFired.current = false; // re-arm for future ?clone_from links in this session
    }
  }}
  initialValues={cloneInitialValues ?? undefined}
/>
```

**Tasks:**
1. Add the `?clone_from` reader logic to `StudiesPageInner` per the key interface above. Local state: `const [cloneInitialValues, setCloneInitialValues] = useState<PrefillValues | null>(null);`.
2. Pass `initialValues={cloneInitialValues ?? undefined}` to `CreateStudyModal`.
3. On modal close (`onOpenChange(false)`), reset `cloneInitialValues` to `null` so subsequent "Create study" clicks open a fresh modal.
4. Vitest cases in `ui/src/app/studies/__tests__/page.test.tsx`:
   - (i) URL `/studies` (no param) → no fetch, no modal auto-open, no toast (renders normal list).
   - (ii) URL `/studies?clone_from=` → fetch disabled, toast surfaced, `router.replace('/studies')` called, modal opens empty, `initialValues` is undefined.
   - (iii) URL `/studies?clone_from=garbage-not-36-chars` → fetch disabled, toast, `router.replace`, modal empty, `initialValues` undefined.
   - (iv) URL `/studies?clone_from=<valid-36-char-uuid>` → fetch enabled; on success, `initialValues` seeded, modal opens with prefill, `router.replace` clears param.
   - (v) URL `/studies?clone_from=<valid-uuid-but-404>` → fetch errors, toast, `router.replace`, modal empty, `initialValues` undefined.
   - (vi) **Stale-prefill regression (cycle-2 F2):** in a single test, sequence: (1) render with valid `/studies?clone_from=A` → assert modal opens with `initialValues.cloneSource.id === 'A'`; (2) close modal; (3) re-render with `/studies?clone_from=garbage`; (4) assert modal opens with `initialValues === undefined` (NOT with stale A prefill). Proves the invalid-path explicit `setCloneInitialValues(null)` reset is wired correctly.

**DoD:**
- [ ] `grep -n "hasCloneFrom\|cloneFromValid\|clone_from" ui/src/app/studies/page.tsx` shows the reader logic.
- [ ] Reader logic is inside `StudiesPageInner` (which is rendered under `<Suspense>` in the default export).
- [ ] `pnpm test -- studies/__tests__/page` green with cases (i)–(v).
- [ ] `pnpm typecheck && pnpm lint` green.
- [ ] Validates FR-4, FR-6 (prefill→POST), D-11. Covers ACs 3, 14, 17.

---

## Epic 3 — E2E + docs + follow-up tracking

### Story 3.1 — Playwright real-backend E2E + `ui-architecture.md` paragraph + follow-up idea verification

**Outcome:** New Playwright test at [`ui/tests/e2e/study-clone.spec.ts`](../../../../ui/tests/e2e/study-clone.spec.ts) exercises the full clone flow against a real backend (no `page.route()` mocking). [`docs/01_architecture/ui-architecture.md`](../../../../docs/01_architecture/ui-architecture.md) gains a short paragraph on the `?clone_from` deep-link pattern. The follow-up idea folder `feat_study_clone_narrow_bounds/idea.md` is already in place (created during spec-gen Step 10); verify it survived rebase / no edits needed.

**Modified files:**
- `docs/01_architecture/ui-architecture.md` — add ~6-line paragraph under the existing "Step-4 auto-fill" section (around line 347) describing the clone deep-link.
- `state.md` — handled by `/impl-execute` finalization (NOT this story).
- `architecture.md` — no edit (no new layers / data flows / services).
- `CLAUDE.md` — no edit (no new conventions or rules).

**New files:**
- `ui/tests/e2e/study-clone.spec.ts` — single spec file with the e2e per spec §14 row "E2E".

**Tasks:**
1. **Playwright e2e setup pattern** (mirroring `dashboard-reseed.spec.ts`):
   - `const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';`
   - Setup helper using `request` fixture to POST `/_test/studies/seed-completed` (the endpoint used by [`scripts/seed_meaningful_demos.py:672`](../../../../scripts/seed_meaningful_demos.py#L672)) to create a completed source study. Verify the endpoint accepts the shape the helper sends — read `scripts/seed_meaningful_demos.py:670-690` and `backend/app/api/v1/_test/` for the endpoint definition.
2. **Playwright e2e assertions** (stable outcomes only — no transient `?clone_from=` assertion, per cycle-2 finding F4; explicit navigation after submit since `CreateStudyModal` closes back to the studies list, not auto-navigating to the new study's detail page per spec §11 step 8):
   ```typescript
   test('clone a completed study via study-detail Clone button', async ({ page, request }) => {
     // Setup: seed a completed source study via the test-only endpoint, then
     // ALWAYS GET /api/v1/studies/{id} to canonicalize the StudyDetail shape
     // (the seed endpoint may return a reduced response).
     const seeded = await request
       .post(`${API_BASE}/_test/studies/seed-completed`, { data: { /* per endpoint contract */ } })
       .then((r) => r.json());
     const sourceId = seeded.id ?? seeded.study_id;
     const source = await request
       .get(`${API_BASE}/api/v1/studies/${sourceId}`)
       .then((r) => r.json());

     // Act: navigate to study-detail, click Clone study
     await page.goto(`/studies/${source.id}`);
     await page.getByTestId('clone-study').click();

     // Assert stable outcomes (deep-link lifecycle has already cleared by now):
     await page.waitForURL(/\/studies$/, { timeout: 5000 });
     await expect(page).not.toHaveURL(/clone_from/);
     await expect(page.getByTestId('cloned-from-banner')).toBeVisible();
     await expect(page.getByTestId('cloned-from-banner')).toContainText(source.name);

     // Spot-check that the form fields are pre-populated:
     // (verify the actual form field accessor names against
     // ui/src/components/studies/create-study-modal.tsx during implementation)
     // ...assert a few key fields match source

     // Submit and capture the new study id from the POST response:
     const postResponsePromise = page.waitForResponse(
       (r) => r.url().endsWith('/api/v1/studies') && r.request().method() === 'POST',
     );
     await page.getByTestId('submit-create-study').click();
     const postResponse = await postResponsePromise;
     const newStudy = await postResponse.json();
     expect(newStudy.parent_study_id).toBe(source.id);

     // Modal closes; per spec §11 step 8 the engineer stays on /studies (the
     // create modal does NOT auto-navigate to detail). Explicitly navigate to
     // the new study's detail page to confirm the row persisted via GET:
     await page.goto(`/studies/${newStudy.id}`);
     const reloaded = await request.get(`${API_BASE}/api/v1/studies/${newStudy.id}`).then((r) => r.json());
     expect(reloaded.parent_study_id).toBe(source.id);
   });
   ```
3. **`ui-architecture.md` paragraph** — insert under "Step-4 auto-fill (`chore_create_study_wizard_polish`)" (line 347):
   ```markdown
   ### Deep-link `?clone_from=<id>` (`feat_study_clone_from_previous`)

   The `/studies` page reads an optional `?clone_from=<source_study_id>` query
   param. When present, it fetches `GET /api/v1/studies/{id}`, builds prefill
   via `buildPrefillFromStudy` (at [`ui/src/components/studies/prefill-from-study.ts`](../../ui/src/components/studies/prefill-from-study.ts)),
   opens `CreateStudyModal` with `initialValues`, and clears the param via
   `router.replace('/studies')` so refresh/back-navigation does not reopen the
   modal. The `?clone_from` reader lives inside `StudiesPageInner` (under the
   `<Suspense>` boundary required by Next 16 `useSearchParams`). Invalid params
   (empty, non-UUID length) and source-fetch errors all converge on the same
   "toast + clear + open empty modal" UX. Banner display reads from the
   UI-only `PrefillValues.cloneSource` field, NOT from the editable `name`
   form value (D-12 in `feat_study_clone_from_previous/feature_spec.md`).
   ```
4. **Verify follow-up tracking:** `ls docs/02_product/planned_features/feat_study_clone_narrow_bounds/idea.md` exists (created during spec-gen Step 10). No edit; this story just confirms it's still in place.

**DoD:**
- [ ] `ui/tests/e2e/study-clone.spec.ts` exists.
- [ ] `cd ui && pnpm test:e2e -- study-clone.spec.ts` green against a running stack (verifies the full happy path with real backend).
- [ ] `grep -n "clone_from\|Deep-link" docs/01_architecture/ui-architecture.md` shows the new paragraph.
- [ ] `cd ui && pnpm build` green (catches any SSR / type issues).
- [ ] `make test` (full suite, all layers) green.
- [ ] `make lint && make typecheck` clean. `cd ui && pnpm lint && pnpm typecheck` clean.
- [ ] Coverage gate (80% backend) green.

---

## UI Guidance (required for frontend-facing work)

### Reference: current `StudyActionBar` component structure

The component at [`ui/src/components/studies/study-action-bar.tsx`](../../../../ui/src/components/studies/study-action-bar.tsx) is 133 lines, single `StudyActionBar` export. Today's structure:
- Lines 1-31: imports, prop interface (`StudyActionBarProps` with `study: StudyDetail` + optional `chainChildren: StudySummary[]`)
- Lines 33-51: component setup — `useState` for cancel dialog, `useCancelStudy` mutation, `canCancel` and `showCascadeRadio` derived state
- Lines 53-132: JSX — outer `<div className="flex items-center gap-3">` wrapping the Cancel button + nested `<AlertDialog>` for the cancel confirm

**Insertion point for Clone button:** inside the outer `<div>` at line 54, IMMEDIATELY BEFORE the existing `<Button variant="destructive">` at line 55. The flex container handles spacing; no layout edits needed.

**Insertion point for Clone-confirm `AlertDialog`:** nest a SECOND `<AlertDialog>` adjacent to the existing one at line 63 (Cancel dialog). Each dialog has its own `open`/`onOpenChange` state. Keep the structure parallel for review-friendliness.

### Analogous markup patterns (required for new UI sections)

**Clone-confirm `AlertDialog`** — copy the structural shape of the existing cancel dialog at lines 63-130, simplified (no cascade radio):

```tsx
<AlertDialog open={cloneConfirmOpen} onOpenChange={setCloneConfirmOpen}>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Clone an in-progress study?</AlertDialogTitle>
      <AlertDialogDescription>
        &ldquo;{study.name}&rdquo; is still running. The clone will use the current configuration
        but its trials are still being tuned.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel>Cancel</AlertDialogCancel>
      <AlertDialogAction
        data-testid="clone-confirm-proceed"
        onClick={() => {
          setCloneConfirmOpen(false);
          router.push(`/studies?clone_from=${study.id}`);
        }}
      >
        Clone anyway
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

**Cloned-from banner** — analogous pattern: there's no exact precedent for a top-of-modal info banner, but the closest is the `<Card>`-based `CardHeader`/`CardContent` styling. Use a lightweight bordered notice instead:

```tsx
{initialValues?.cloneSource && (
  <div
    className="mb-4 rounded-md border bg-muted/40 px-4 py-2 text-sm"
    data-testid="cloned-from-banner"
  >
    Cloned from study <strong>{initialValues.cloneSource.name}</strong>
    {' · '}
    <Link
      href={`/studies/${initialValues.cloneSource.id}`}
      className="underline hover:text-foreground/80"
    >
      view source
    </Link>
    <span className="ml-1">
      <InfoTooltip glossaryKey="study.cloned_from_banner" />
    </span>
  </div>
)}
```

### Layout and structure

- StudyActionBar stays single-row horizontal flex. Clone button sits to the LEFT of Cancel (per FR-1 spec). Both buttons inherit the existing `gap-3` spacing.
- Cloned-from banner sits inside `CreateStudyModal`'s `<DialogContent>`, above Step 1's content. Full-width relative to the modal's inner padding.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Click "Clone study" on `completed`/`failed`/`cancelled`/`queued` source | `router.push('/studies?clone_from=<id>')` | (none — navigation only) |
| Click "Clone study" on `running` source | Open `AlertDialog` with `data-testid="clone-running-confirm"` | (none — dialog only) |
| Click "Clone anyway" in dialog | Close dialog + `router.push('/studies?clone_from=<id>')` | (none) |
| Click "Cancel" in dialog | Close dialog | (none) |
| Land on `/studies?clone_from=<valid-id>` | Fetch source, build prefill, open modal with prefill, `router.replace('/studies')` | `GET /api/v1/studies/{clone_from}` |
| Land on `/studies?clone_from=` / `garbage` / `<deleted-id>` | Toast error, `router.replace('/studies')`, open modal empty | (none for invalid; 404 for deleted-id) |
| Submit modal (clone mode) | POST with `parent_study_id` + all form fields; on success, close modal + invalidate `['studies']` query | `POST /api/v1/studies` |
| Close modal | Reset `cloneInitialValues` to `null` | (none) |

### Component composition

Clone button + dialog stay INLINE in `StudyActionBar` (analogous to Cancel — no extraction). Banner stays INLINE in `CreateStudyModal` (one-time use, no reuse motivation). Prefill helper IS extracted (`prefill-from-study.ts`) because it's a pure function with vitest needs and could be reused by future clone entry points (e.g., the deferred narrow-bounds follow-up).

### Information architecture placement

- "Clone study" sits in the **study-detail header action bar** alongside Cancel — per spec D-7 the only entry point. NOT on the digest panel (D-7 / FR-2 regression assertion). NOT on the proposal-detail page (D-7 — "Run this followup" is the dedicated proposal-side flow).
- The banner sits **inside the create-study modal** — visible across all 5 wizard steps, not gated to Step 1.

### Tooltips and contextual help

| Element | Glossary key | Trigger | Placement | Source-of-truth |
|---|---|---|---|---|
| "Clone study" button | `study.clone_button` | `<InfoTooltip>` adjacent to button | Right of button label | `// Source-of-truth: feat_study_clone_from_previous spec §11 (FR-13)` comment in `ui/src/lib/glossary.ts` |
| Cloned-from banner | `study.cloned_from_banner` | `<InfoTooltip>` at end of banner line | After "view source" link | Same |

Both keys use the existing `InfoTooltip` pattern documented in [`docs/01_architecture/ui-architecture.md`](../../../../docs/01_architecture/ui-architecture.md) §"Tooltips and glossary". Existing test at [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) automatically validates the new entries (length bounds, no implementation jargon).

### Visual consistency

| New element | CSS class / pattern source |
|---|---|
| Clone button | `<Button variant="outline">` — matches secondary-action convention (Cancel is `destructive`) |
| Clone-confirm dialog | Mirrors existing Cancel `AlertDialog` structure (line 63-130 of `study-action-bar.tsx`) |
| Cloned-from banner | `rounded-md border bg-muted/40 px-4 py-2 text-sm` — Tailwind tokens consistent with other notice/info surfaces in the modal |

### Legacy behavior parity

**Not applicable.** This plan does NOT delete or replace any existing user-facing component. `StudyActionBar` and `CreateStudyModal` gain additive UI; `digest-panel.tsx` is touched only by an assertion (no edit). The Legacy Behavior Parity discipline (CLAUDE.md / impl-plan-gen guidance) applies to >100 LOC deletions, which this plan does not perform.

---

## 3) Testing workstream

### 3.1 Unit tests

- `ui/src/components/studies/__tests__/prefill-from-study.test.ts` (Story 2.1) — 6 vitest cases for the pure prefill helper.

### 3.2 Integration tests (DB-backed; require Postgres + ES + OpenSearch via `make up`)

- `backend/tests/integration/test_studies_api.py` (Story 1.3) — append cases (a), (b), (c), (e), (f).
- `backend/tests/integration/test_studies_clone_autofollowup.py` (Story 1.3 — new file) — case (g).
- `backend/tests/integration/test_studies_with_parent_followup.py` (existing) — NO change; coverage of proposal-followup path is unaffected. Run as a regression check.

### 3.3 Contract tests

- `backend/tests/contract/test_create_study_parent.py` (Story 1.1 — extend) — schema-introspection case for `parent_study_id` optionality + length bound. Story 1.3 also extends with case (d) round-trip.
- `backend/tests/contract/test_studies_error_codes.py` (Story 1.3 — extend) — envelope-shape assertions for `PARENT_STUDY_NOT_FOUND` and `PARENT_STUDY_WRONG_CLUSTER`.

### 3.4 E2E tests

- `ui/tests/e2e/study-clone.spec.ts` (Story 3.1) — single real-backend test exercising the full clone flow per spec §14.

### 3.5 Existing test impact audit

| File | Affected? | Action |
|---|---|---|
| `backend/tests/integration/test_auto_followup.py` | Regression risk (FR-15 interaction) | Run as regression — no source edit; verify cases at lines 220, 425 still pass |
| `backend/tests/integration/test_studies_with_parent_followup.py` | No edit, regression check only | Run as regression |
| `backend/tests/integration/test_studies_parent_proposal_check.py` | No edit, regression check only | Run as regression |
| `backend/tests/integration/test_study_cancel.py` | No edit, regression check only (cascade behavior validated under new write path by Story 1.3 case (f)) | Run as regression |
| `ui/src/components/studies/__tests__/study-action-bar.test.tsx` | Extend with clone cases (Story 2.2) | Extend; existing cancel cases unchanged |
| `ui/src/components/studies/__tests__/create-study-modal.test.tsx` | Extend with banner + serializer cases (Story 2.2) | Extend; existing cases unchanged. Verify all existing `initialValues.parent` cases still pass after `parent` field becomes optional. |
| `ui/src/app/proposals/[id]/page.tsx` | Type-check regression risk (consumes `PrefillValues`) | No edit; `pnpm typecheck` after Story 2.1 confirms compatibility |

### 3.5 Migration verification

**Not applicable.** No new migration.

### 3.6 CI gates

- `make lint && make typecheck && make test` green.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- 80% backend coverage gate green (`pyproject.toml` `[tool.coverage.report].fail_under = 80`).
- Conventional Commits format on each commit (pre-commit hook enforced).
- `pnpm test:e2e -- study-clone.spec.ts` green against a running stack (run before PR merge).

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — handled by `/impl-execute` finalization step (not this plan). Will update: branch context, recent changes (new entry for this feature post-merge), Alembic head (unchanged — no migration), in-flight list.
- **`architecture.md`** — no edit (no new layers, services, or data flows).
- **`CLAUDE.md`** — no edit (no new rules, conventions, or env vars).

### 4.1 Architecture docs (`docs/01_architecture/`)

- **`ui-architecture.md`** (Story 3.1) — add ~6-line subsection on the `?clone_from` deep-link pattern under the existing "Step-4 auto-fill" section.

### 4.2 Product docs (`docs/02_product/`)

- `pipeline_status.md` (this feature's directory) — updated by `/impl-execute` finalization to mark Implementation: Complete.
- `feat_study_clone_narrow_bounds/idea.md` — already created during spec-gen Step 10. Story 3.1 verifies it's still in place; no edit.

### 4.3 Runbooks (`docs/03_runbooks/`)

No edit. No new operational concern.

### 4.4 Security docs (`docs/04_security/`)

No edit. No new secret, no new auth surface.

### 4.5 Quality docs (`docs/05_quality/`)

No edit. Coverage gate unchanged.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- **`PrefillValues.parent` widening:** make optional (was required). Strictly type-level — existing callers already always set `parent`, so behavior is unchanged at runtime.
- **`CreateStudyModal` submit serializer:** switch from any implicit `...initialValues` spread (if present) to explicit field-by-field assembly OR destructure-and-omit `cloneSource`. Prevents future `PrefillValues` additions from accidentally leaking to the wire.

### 5.2 Planned refactor tasks

Both refactors land inline with their owning stories (2.1 for the type widening; 2.2 for the serializer hygiene). No separate refactor story needed.

### 5.3 Refactor guardrails

- `pnpm typecheck` after Story 2.1 must pass — proves `PrefillValues.parent` widening didn't break any consumer.
- Vitest case (a) in Story 2.2 asserts the serializer excludes `cloneSource` — prevents regression.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

- **Backend → frontend:** Story 2.1 depends on Story 1.1's `parent_study_id` field landing in the OpenAPI schema (frontend uses the auto-generated `components['schemas']['CreateStudyRequest']` type). Sequence Epic 1 before Epic 2.
- **Frontend internal:** Story 2.3 depends on Story 2.1's `buildPrefillFromStudy` helper. Story 3.1 (e2e) depends on all of Epic 2.
- **Test infrastructure:** Story 1.3 case (g) depends on existing `enqueue_followup_study` worker function being callable from tests; verified at [`backend/workers/auto_followup.py:63`](../../../../backend/workers/auto_followup.py#L63) — it's a top-level `async def` and existing tests at `test_auto_followup.py` invoke it directly.
- **E2E seed endpoint:** Story 3.1 depends on `POST /_test/studies/seed-completed` (used by `scripts/seed_meaningful_demos.py:672`). Verify the endpoint is registered + returns a usable shape during Story 3.1 task 1.

### Risks

- **R-1 (Type-widening breakage):** widening `PrefillValues.parent` from required to optional could surface a strict-null caller that I haven't grepped. Mitigation: full `pnpm typecheck` is part of Story 2.1 DoD; any breakage surfaces immediately.
- **R-2 (E2E seed endpoint not exposed in test env):** if `/_test/studies/seed-completed` is only registered in specific env modes, the e2e setup could 404. Mitigation: Story 3.1 task 1 verifies the endpoint shape before writing assertions.
- **R-3 (`useStudy({ enabled: false })` edge):** TanStack Query's `useQuery({ enabled: false })` still calls the hook but skips fetch. Story 2.3's `enabled: cloneFromValid` flag correctly gates fetch; vitest case (i) "no param" verifies no fetch fires when not requested.
- **R-4 (Auto_followup interaction surfacing as a "bug" later):** FR-15 / D-10 locks the suppression behavior as intended. Mitigation: spec, plan, and integration test (g) all document this explicitly so future bug-fix-protocol invocations correctly find the "intended" framing and don't roll it back.

### Failure mode catalog

| Failure | Catch layer | Recovery |
|---|---|---|
| Field added to `CreateStudyRequest` but TS codegen doesn't pick it up | Story 2.1 DoD (`pnpm typecheck` would fail when story 2.3 references the field) | Re-run `pnpm` codegen (project-specific command in `package.json`); if still missing, investigate `openapi-typescript` config |
| `parent_study_id` validation accidentally runs before cluster FK resolution | Integration test (b) would 422 with `VALIDATION_ERROR` instead of 404 `PARENT_STUDY_NOT_FOUND` (cluster doesn't exist either) | Re-read FR-8 / D-9 placement; the `if cluster is None` check at line 209 must fire first |
| `cloneSource` accidentally leaks into POST body | Vitest case (a) in Story 2.2 (`expect.not.objectContaining({ cloneSource })`) | Refactor submit serializer to explicit field selection |
| Deep-link param not cleared, modal reopens on refresh | Vitest case (iv) in Story 2.3 + e2e final-URL assertion | Confirm `router.replace('/studies')` runs in all three terminal effect branches |
| Auto_followup suppresses incorrectly (e.g., for a clone of an UNRELATED study) | Integration test (g) | The `list_children_of_study` query is FK-equality keyed on the *parent's* id, not the clone's — so suppression scope is correct by construction; test (g) regression-guards this |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (backend schema field) — unlocks frontend TS codegen.
2. **Story 1.2** (backend validation + persistence) — unblocks integration tests.
3. **Story 1.3** (backend tests) — Epic 1 closeout.
4. **Story 2.1** (frontend types + helper + glossary) — unblocks UI stories.
5. **Story 2.2** (UI button + dialog + banner + serializer) — unblocks page wiring.
6. **Story 2.3** (page deep-link wiring) — Epic 2 closeout.
7. **Story 3.1** (E2E + docs) — Epic 3 closeout; gate the PR.

### Parallelization opportunities

- Stories 2.1 / 2.2 / 2.3 are mostly independent file edits (different components); one developer can sequence them serially, but if the project later has multiple contributors, 2.1 (foundational) must finish before 2.2 and 2.3 start.
- Story 1.1 and Story 2.1 cannot run in parallel because TS codegen depends on 1.1's OpenAPI surface.

---

## 8) Rollout and cutover plan

Per spec §16: backend + frontend deploy together from a single PR (RelyLoop CI default). No staged rollout, no feature flag, no migration. PR merges to `main`; staging deploy (if remote staging existed; MVP1 is local-only per CLAUDE.md) would fire. No data backfill, no operator handoff.

---

## 9) Execution tracker

### Current sprint

- [x] **Story 1.1** — Add `parent_study_id` to `CreateStudyRequest`
- [x] **Story 1.2** — Validate + persist `parent_study_id` in `_create_study`
- [x] **Story 1.3** — Backend regression tests (cascade-of-clone + auto_followup self-suppression + validation-order + happy-path)
- [x] **Story 2.1** — Extend `PrefillValues` + write `buildPrefillFromStudy` helper + glossary entries
- [x] **Story 2.2** — "Clone study" button + running-confirm + cloned-from banner + payload serializer hygiene
- [x] **Story 2.3** — Deep-link `?clone_from` wiring on `/studies` page + invalid-param handling
- [ ] **Story 3.1** — Playwright real-backend E2E + `ui-architecture.md` paragraph + follow-up idea verification

### Blocked items

- None at plan time.

### Done this sprint

- (none yet)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

For every story above, before marking the execution tracker `[x]`:

1. All DoD bullets satisfied (each one has a `grep` / `make` / `pnpm` validation).
2. All FR/AC mappings referenced in the story header are exercised by at least one new or extended test.
3. `make lint && make typecheck` clean (backend) AND `pnpm lint && pnpm typecheck` clean (frontend) on the changed surface.
4. Conventional Commits format on every commit added during the story.
5. No file modified that wasn't listed in the story's "Modified files" or "New files".

---

## 11) Plan consistency review (required before execution)

### Spec ↔ plan endpoint count

Spec §8 lists exactly 1 endpoint with additive changes: `POST /api/v1/studies` (gain `parent_study_id`). Plan covers this in Story 1.1 (schema field) + Story 1.2 (handler logic). **Endpoint count parity: 1 spec endpoint = 1 plan-covered endpoint. ✓**

### Spec ↔ plan error code coverage

Spec §8.4 lists 2 NEW error codes:
- `PARENT_STUDY_NOT_FOUND` (404) — Story 1.2 raises + Story 1.3 contract test + integration case (b)
- `PARENT_STUDY_WRONG_CLUSTER` (422) — Story 1.2 raises + Story 1.3 contract test + integration cases (c), (e)

**Error code coverage: 2 spec / 2 plan-covered. ✓**

### Spec ↔ plan FR coverage

15 FRs in spec. All 15 mapped to stories in §1 above. **FR coverage: 15/15. ✓**

### Story internal consistency

- Story 1.1 — `CreateStudyRequest` schema matches §8 verbatim (verified by inline declaration).
- Story 1.2 — endpoint error codes match §8.4 verbatim.
- Story 1.3 — integration test cases (a–g) match AC mappings in §1 traceability.
- Story 2.1 — `PrefillValues` widening matches §8 type declaration.
- Story 2.2 — banner reads `cloneSource` per FR-12 / D-12 (not form name).
- Story 2.3 — param-presence logic matches FR-4 (post-cycle-3 patch).

**No file claimed by multiple stories.** Files touched:
| File | Story owner |
|---|---|
| `backend/app/api/v1/schemas.py` | 1.1 only |
| `backend/app/api/v1/studies.py` | 1.2 only |
| `backend/tests/contract/test_create_study_parent.py` | 1.1 + 1.3 (different cases) |
| `backend/tests/contract/test_studies_error_codes.py` | 1.3 only |
| `backend/tests/integration/test_studies_api.py` | 1.3 only |
| `backend/tests/integration/test_studies_clone_autofollowup.py` (new) | 1.3 only |
| `ui/src/components/studies/create-study-modal.tsx` | 2.1 (type) + 2.2 (banner + serializer) |
| `ui/src/components/studies/study-action-bar.tsx` | 2.2 only |
| `ui/src/components/studies/prefill-from-study.ts` (new) | 2.1 only |
| `ui/src/components/studies/__tests__/prefill-from-study.test.ts` (new) | 2.1 only |
| `ui/src/components/studies/__tests__/study-action-bar.test.tsx` | 2.2 only |
| `ui/src/components/studies/__tests__/create-study-modal.test.tsx` | 2.2 only |
| `ui/src/lib/glossary.ts` | 2.1 only |
| `ui/src/app/studies/page.tsx` | 2.3 only |
| `ui/src/app/studies/__tests__/page.test.tsx` (may be new) | 2.3 only |
| `ui/tests/e2e/study-clone.spec.ts` (new) | 3.1 only |
| `docs/01_architecture/ui-architecture.md` | 3.1 only |

Three files have multiple story owners. Each owner edits distinct sections (type vs banner; schema field vs new case file). No conflicts.

### Test file count and assignment

12 test-touching files; every one is assigned to exactly one story (or two stories with non-overlapping case additions). ✓

### Gate arithmetic

Epic 1 gate: "all 2 new error codes implemented + 6 new integration cases + 2 new contract envelope cases" ↔ matches Story 1.1 + 1.2 + 1.3 task counts. ✓
Epic 2 gate: "PrefillValues widened + helper exported + 3 UI surfaces edited + deep-link wired" ↔ matches Story 2.1 + 2.2 + 2.3 deliverables. ✓
Epic 3 gate: "E2E green + doc paragraph added + follow-up idea verified in place" ↔ matches Story 3.1 deliverables. ✓

### Open questions resolved

Spec §19 has 4 OQs (OQ-1, OQ-2, OQ-3, OQ-4), all with recommended defaults. The plan inherits the defaults:
- OQ-1 (read-only best-trial panel): deferred to `feat_study_clone_narrow_bounds`. Not in plan scope.
- OQ-2 (lineage telemetry event): deferred to MVP2. Not in plan scope.
- OQ-3 (clone name suffix `(clone)`): adopted. Story 2.1 helper uses this verbatim.
- OQ-4 (running-confirm copy): adopted. Story 2.2 dialog uses the spec's draft copy verbatim.

**All open questions resolved at plan time. ✓**

### Frontend UI Guidance completeness

The plan has a complete UI Guidance section (above) with: Reference component structure ✓; Analogous markup patterns ✓ (with actual JSX); Layout ✓; Interaction behavior ✓ (table); Component composition ✓; Information architecture ✓; Tooltips ✓ (with glossary keys + source-of-truth comments); Visual consistency ✓ (table); Legacy parity ✓ (N/A justified). ✓

---

## 12) Definition of plan done

- All 7 story execution-tracker bullets `[x]`.
- All 17 spec ACs verified by at least one test.
- Single PR opened against `main`; CI green; Gemini findings adjudicated; one final GPT-5.5 cross-model review pass clean.
- Glossary entries shipped; `ui-architecture.md` paragraph shipped; `feat_study_clone_narrow_bounds/idea.md` confirmed in place.
- `pipeline_status.md` Implementation section updated to "Complete (PR #N)".
- Feature folder moved to `docs/00_overview/implemented_features/YYYY_MM_DD_feat_study_clone_from_previous/` post-merge.
- `state.md` updated with the new shipped feature.
