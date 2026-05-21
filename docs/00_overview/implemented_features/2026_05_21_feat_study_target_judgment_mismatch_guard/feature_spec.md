# Feature Specification — feat_study_target_judgment_mismatch_guard

**Date:** 2026-05-21
**Status:** Implemented (PR #184, squash-merged `ce3fcf4` on 2026-05-21)
**Owners:** RelyLoop maintainers
**Related docs:**
- [idea.md](idea.md)
- [api-conventions.md](../../../01_architecture/api-conventions.md)
- [data-model.md](../../../01_architecture/data-model.md)
- Sibling: [feat_study_preflight_overlap_probe](../feat_study_preflight_overlap_probe/idea.md)
- Sibling: [feat_orchestrator_zero_streak_abort](../feat_orchestrator_zero_streak_abort/idea.md)
- Upstream: [chore_e2e_test_rows_isolation](../chore_e2e_test_rows_isolation/idea.md)

**Depends on:** None. Feature is purely additive (no migration, no new external dep). Builds on the existing studies POST validator at [`backend/app/api/v1/studies.py:240-247`](../../../../backend/app/api/v1/studies.py#L240-L247) and the existing judgment-list listing filter pattern at [`backend/app/db/repo/judgment_list.py:58-140`](../../../../backend/app/db/repo/judgment_list.py#L58-L140).

---

## 1) Purpose

- **Problem:** Operators can create a study whose `study.target` (the index/collection the study queries) does not match the `judgment_list.target` (the index the judgments were authored against). When these mismatch, the judgment doc IDs cannot intersect search results from the study's target — pytrec_eval scores 0 on every (params, query) pair by construction. The orchestrator burns the entire trial budget producing `best_metric=0.0`. Real incident: study `019e4be6-207e-7c32-9889-f6c3003f57c2` ran 1000 trials in 4.5 minutes with `best_metric=0.0` because `study.target = "docs-articles"` but `judgment_list.target = "e2e-target"` (an E2E-test leftover).
- **Outcome:** `POST /api/v1/studies` rejects the mismatch at create time with a specific machine-readable error code (`JUDGMENT_TARGET_MISMATCH`, 422). The create-study modal pre-filters the judgment-list dropdown to only judgment lists matching the selected target, so the operator can't even submit the mismatched pair. The backend rejection is the defense-in-depth net for non-modal callers (chat-agent `create_study` tool, direct API users).
- **Non-goal:** Detecting *same-target-but-stale* mismatches (re-indexed corpus, judgments authored on a rotated index, etc.) — that's the sibling [feat_study_preflight_overlap_probe](../feat_study_preflight_overlap_probe/idea.md). Detecting mid-flight signal loss is the sibling [feat_orchestrator_zero_streak_abort](../feat_orchestrator_zero_streak_abort/idea.md). This feature covers ONLY the deterministic string-equality case.

## 2) Current state audit

### Existing implementations

- **`backend/app/api/v1/studies.py:240-247`** — the `POST /api/v1/studies` cross-entity check that enforces `judgment_list.query_set_id == body.query_set_id`. Returns generic `VALIDATION_ERROR` (422). The new target-mismatch check sits directly after this, using the same `_err(...)` helper at [`studies.py:74-78`](../../../../backend/app/api/v1/studies.py#L74-L78). No structural change to the handler; one additional `if` block.
- **`backend/app/db/repo/judgment_list.py:58-112`** — `list_judgment_lists()` already accepts `query_set_id` + `cluster_id` filters (added by `bug_judgment_lists_listing_ignores_query_set_filter`, PR #163). The new `?target=` filter follows the same shape: parameter on the function signature → `WHERE` clause guarded by `if target is not None`.
- **`backend/app/db/repo/judgment_list.py:115-140`** — `count_judgment_lists()` mirrors the listing filters for `X-Total-Count` consistency. Must add `target` symmetrically.
- **`backend/app/api/v1/judgments.py:113-122`** — `_summary()` builder for the list response. Currently omits `target`. Detail at [`judgments.py:125-146`](../../../../backend/app/api/v1/judgments.py#L125-L146) includes `target=row.target`. The summary must add the same field so frontends can filter and label by target without fetching detail per row.
- **`backend/app/api/v1/schemas.py:760-769`** — `JudgmentListSummary` Pydantic model. Add `target: str` field (the underlying ORM column at [`backend/app/db/models/judgment_list.py:46`](../../../../backend/app/db/models/judgment_list.py#L46) is `Text, nullable=False`, so the Pydantic field is non-optional).
- **`backend/app/api/v1/judgments.py:339-383`** — `list_judgment_lists_endpoint` route. Add `target` query parameter alongside the existing `query_set_id` + `cluster_id` params (those are `Annotated[str | None, Query(min_length=1, max_length=36)]` because they're UUIDv7-shaped FKs). `target` is free-form so its bound is `min_length=1, max_length=255` (the ES/OpenSearch index-name ceiling — the underlying `Text` column has no length limit at the DB layer).
- **`ui/src/components/studies/create-study-modal.tsx:190-193`** — current `useJudgmentLists` call passes only `{ query_set_id, limit: 200 }`. Extend to `{ query_set_id, cluster_id, target, limit: 200 }`. `cluster_id` adoption is symmetric with the new `target` adoption (wire param exists, modal already has `clusterId` in scope at line 142; passing both is cheaper than passing one without the other).
- **`ui/src/components/studies/create-study-modal.tsx:594-597`** — existing `query_set_id`-change handler that resets `judgment_list_id` to `''`. New mirror handler on `target` change (at the existing Step-1 target picker at lines 539-561) must call `form.setValue('judgment_list_id', '')` for the same reason (a stale judgment_list_id from a prior target survives in the form state otherwise).
- **`ui/src/lib/api/judgments.ts:30-35`** — `JudgmentListsFilter` TypeScript interface. Add `target?: string | undefined` field.
- **`ui/src/lib/api/judgments.ts:37-51`** — `useJudgmentLists` hook. Destructure + pass `target` through `params` (mirrors the existing `query_set_id` + `cluster_id` pattern).
- **`ui/src/lib/types.ts`** — generated from live OpenAPI; must be regenerated after the `JudgmentListSummary` shape change.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (no URL/route changes) | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_studies_error_codes.py` | Asserts error envelopes for `POST /api/v1/studies` failure paths | (no change) | Add 1 new case for `JUDGMENT_TARGET_MISMATCH` (422). |
| `backend/tests/contract/test_studies_api_contract.py` | Asserts response shapes for studies endpoints | (no change) | (No change needed — this spec doesn't alter the success path of POST /studies.) |
| `backend/tests/contract/test_judgments_api_contract.py` | Asserts `JudgmentListSummary` OpenAPI shape | 1 | Update fixture to expect the new `target` field on the summary; assert OpenAPI surface lists `target` as required. |
| `backend/tests/integration/test_studies_api.py` | Studies POST integration tests (target='stub-index' at line 73) | (no change) | Add 1 new case that seeds a study + judgment list with mismatched `target` values → asserts 422 + `JUDGMENT_TARGET_MISMATCH`. |
| `backend/tests/integration/test_judgments_api.py` | Tests for `GET /api/v1/judgment-lists` listing | 1 | Add 1 new case asserting `?target=X` filters correctly across 2 lists with different targets. |
| `ui/src/components/studies/__tests__/create-study-modal*.test.tsx` | Create-study modal unit tests | (no change) | Add 1 vitest case asserting the dropdown filters by `target`; add 1 case asserting `target`-change resets `judgment_list_id`. |
| `ui/src/components/query-sets/associated-judgment-lists.tsx` (callers using `useJudgmentLists` without `target`) | Calls `useJudgmentLists({ query_set_id, limit: 50 })` | 1 | No change — `target` is optional; existing callers continue to work unfiltered (additive change). |
| `ui/src/app/page.tsx:66` (dashboard count widget) | Calls `apiClient.get<JudgmentListListResponse>('/api/v1/judgment-lists', ...)` for `X-Total-Count` header | 1 | No change — header-only call, additive `target` field on summary is ignored. |

### Existing behaviors affected by scope change

- **Existing studies with mismatched targets:** Current: pass create-time validation (only `query_set_id` cross-check exists); orchestrator runs all trials at 0.0 metric; finalize cleanly. New: such studies cannot be created via `POST /api/v1/studies`. Existing queued/running rows that already passed the (weaker) prior check are NOT retroactively rejected. **Decision needed: no** — locked in idea.md "Locked decisions". Mid-flight detection of pre-existing rows is owned by [feat_orchestrator_zero_streak_abort](../feat_orchestrator_zero_streak_abort/idea.md).
- **`JudgmentListSummary` wire shape:** Current: 7 fields (`id, name, description, query_set_id, cluster_id, status, created_at`). New: 8 fields with `target: str` added. **Decision needed: no** — additive for tolerant JSON consumers (the existing TanStack Query callers + the dashboard count widget at `ui/src/app/page.tsx:66` ignore unknown fields), but NOT no-impact for strict consumers: the OpenAPI snapshot at `backend/tests/contract/test_openapi_surface.py` and the generated TS types at `ui/src/lib/types.ts` BOTH must be regenerated in the same PR. Any future external client generating from the OpenAPI must also re-pull.
- **`GET /api/v1/judgment-lists` query params:** Current: 7 params (`cursor, limit, since, q, sort, query_set_id, cluster_id`). New: 8 params with `target` added. **Decision needed: no** — additive optional param; existing callers ignore.
- **`useJudgmentLists` TanStack queryKey:** Current key shape `['judgment-lists', { query_set_id, cluster_id, cursor, limit }]`. New: adds `target` to the key. Existing cache entries (keyed without `target`) coexist; new entries with `target` set are scoped separately. No cache invalidation needed. **Decision needed: no**.

---

## 3) Scope

### In scope

- **(B1) Backend create-time rejection — target.** New `if judgment_list.target != body.target: raise _err(422, "JUDGMENT_TARGET_MISMATCH", ...)` block immediately after the existing `query_set_id` cross-check at `studies.py:240-247` and after the new cluster_id check (B1b).
- **(B1b) Backend create-time rejection — cluster_id.** New `if judgment_list.cluster_id != body.cluster_id: raise _err(422, "JUDGMENT_CLUSTER_MISMATCH", ...)` block between the `query_set_id` cross-check and the new target check. Closes the cross-cluster judgment-list reuse gap surfaced by GPT-5.5 cycle-1 review.
- **(B2) Backend listing surface extension.** Add `target: str` field to `JudgmentListSummary`; extend `_summary()` builder to populate it. Add `?target=` query param to `GET /api/v1/judgment-lists`; thread to `list_judgment_lists` + `count_judgment_lists` repo functions.
- **(B3) Error-code registration.** New `JUDGMENT_CLUSTER_MISMATCH` + `JUDGMENT_TARGET_MISMATCH` rows added to `docs/01_architecture/api-conventions.md` alongside the existing studies-endpoint codes (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`).
- **(F1) Frontend dropdown filtering.** Update create-study modal's `useJudgmentLists` call to pass `{ query_set_id, cluster_id, target, limit: 200 }`. The backend `?target=` filter does the work server-side; the dropdown only sees matching rows.
- **(F2) Frontend cascade reset.** When EITHER `target` OR `cluster_id` changes via the Step-1 picker, reset `judgment_list_id` to `''`. Two reset triggers: target change AND cluster change. Mirrors the existing `query_set_id`-change reset at line 596. Without the cluster trigger, an operator who picks cluster A → target `products` → judgment list → returns to Step 1 → switches cluster to B (target name still `products`) → submits would see the backend FR-1b 422 (because `judgment_list.cluster_id = A ≠ B = body.cluster_id`) — the cascade reset closes the loop in-UI.
- **(F3) Frontend empty-state copy.** When zero judgment lists match, render an empty-state via the existing `EntitySelect.emptyState` prop (precedent at [`create-study-modal.tsx:556-561`](../../../../ui/src/components/studies/create-study-modal.tsx#L556-L561) for the targets dropdown's `target_filter`-aware empty state). Copy: `"No judgment lists for target \"{target}\" on this cluster + query set. Generate a new one from /judgments."` with a `cta` linking to `/judgments`.
- **(F4) Frontend type regeneration.** Regenerate `ui/src/lib/types.ts` from live OpenAPI after the `JudgmentListSummary` shape change. Add `target?: string` to the `JudgmentListsFilter` interface in `ui/src/lib/api/judgments.ts`.

### Out of scope

- **Stale-judgment / overlap detection** — same target name, doc IDs disjoint (post-reindex, etc.). Owned by [feat_study_preflight_overlap_probe](../feat_study_preflight_overlap_probe/idea.md).
- **Mid-flight zero-streak abort** — orchestrator-level catch for studies that pass create-time gates but produce all-zero trials anyway. Owned by [feat_orchestrator_zero_streak_abort](../feat_orchestrator_zero_streak_abort/idea.md).
- **Retroactive rejection of pre-existing studies.** Pre-existing queued/running rows with mismatched targets continue executing.
- **Renaming the existing `VALIDATION_ERROR` code** returned by the `query_set_id` cross-check at `studies.py:242-247`. `api-conventions.md` line 196 forbids renaming shipped codes; the inconsistency (one specific, one generic) is accepted in exchange for backwards compatibility.
- **Enforcing `query_set.cluster_id == body.cluster_id` at `POST /studies`.** The studies handler at [`backend/app/api/v1/studies.py:228-247`](../../../../backend/app/api/v1/studies.py#L228-L247) does NOT currently cross-check that the query_set's `cluster_id` matches the study's `cluster_id`. This pre-existing gap is independent of the judgment-list mismatch this feature closes — queries themselves are plain text strings and don't have cluster-scoped doc IDs, so a `query_set.cluster_id` mismatch doesn't directly cause the zero-signal failure mode this feature targets. If a follow-up wants to close this contract inconsistency, file as `bug_studies_query_set_cluster_consistency`. The create-study modal already cascade-resets `query_set_id` on cluster change (verified at [`create-study-modal.tsx:508`](../../../../ui/src/components/studies/create-study-modal.tsx#L508)), so the operator can't accidentally trigger this from the UI.
- **Migration.** No schema changes; `judgment_lists.target` already exists.
- **Audit-event emission.** Pre-MVP2 — `audit_log` table not present yet.
- **Display of target in the dropdown rows.** The dropdown item label remains `j.name` (per [`create-study-modal.tsx:608`](../../../../ui/src/components/studies/create-study-modal.tsx#L608)) — adding a target subtitle is an ergonomic improvement deferred to a follow-up `chore_*` if needed; the empty-state copy already surfaces the target value to the operator.
- **Deep-link prefill on the empty-state CTA.** The `/judgments` page in MVP1 does not support URL prefill query params for the judgment-generation modal (verified — the route's create modal opens with empty defaults). Deep-linking `/judgments?cluster_id=...&query_set_id=...&target=...` would require a separate follow-up adding prefill support to the judgments-generate flow. For this feature, the CTA href is the static `/judgments` and the operator copies the target value mentally from the empty-state copy.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints. Verified in [`backend/app/api/v1/studies.py:188`](../../../../backend/app/api/v1/studies.py#L188) (POST `/studies`) and [`backend/app/api/v1/judgments.py:335`](../../../../backend/app/api/v1/judgments.py#L335) (GET `/judgment-lists`). No new endpoints introduced.
- **Router file:** `backend/app/api/v1/studies.py` (B1); `backend/app/api/v1/judgments.py` (B2 endpoint).
- **HTTP methods:** No new endpoints; the existing POST `/studies` and GET `/judgment-lists` keep their methods.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per the `_err(...)` helper at [`studies.py:74-78`](../../../../backend/app/api/v1/studies.py#L74-L78) (identical to [`judgments.py:86-90`](../../../../backend/app/api/v1/judgments.py#L86-L90)). The new `JUDGMENT_TARGET_MISMATCH` follows this exact shape.
- **Auth error shape:** N/A in MVP1 (no auth surface).

### Phase boundaries

Single phase. The entire feature ships in one PR. No deferred phases.

## 4) Product principles and constraints

- **Fail fast on deterministic problems.** A string-equality mismatch costs one comparison; catch it at the API boundary, not 4.5 minutes into the trial budget.
- **Backend contract, frontend UX.** The 422 is the contract; the modal filter is a UX prefetch. Chat-agent and direct API callers fall through to the same backend gate (no separate enforcement).
- **Specific over generic error codes** when the failure has a deterministic recovery path. The frontend can render a targeted helper UI (link to judgment generation against the right target) instead of a generic toast.
- **Don't rename shipped error codes.** `VALIDATION_ERROR` returned by the existing `query_set_id` cross-check stays as-is per `api-conventions.md:196`.

### Anti-patterns

- **Do not** make the frontend filter judgment lists client-side after over-fetching — duplicates the count-semantics work the backend already does, and the dropdown's "no matches" empty state becomes inconsistent with `X-Total-Count`. Use the wire filter.
- **Do not** add `target` only to `JudgmentListDetail` and require a per-row detail fetch on the frontend — that's N+1 latency on the modal open. Add it to the summary.
- **Do not** rename the existing `VALIDATION_ERROR` returned for the `query_set_id` mismatch — would silently break any external caller (or future chat-agent error handler) branching on that code.
- **Do not** raise the new error before the FK-existence and `query_set_id` checks. The order in [`studies.py:206-247`](../../../../backend/app/api/v1/studies.py#L206-L247) is meaningful (FK first → query_set consistency → target consistency); reordering changes which 404 vs 422 the caller sees for ambiguous failures.
- **Do not** retroactively reject pre-existing studies. The check fires only at `POST /studies`; existing rows are out-of-scope.

## 5) Assumptions and dependencies

- **`judgment_lists.target` is non-nullable.** Confirmed at [`backend/app/db/models/judgment_list.py:46`](../../../../backend/app/db/models/judgment_list.py#L46) (`Mapped[str] = mapped_column(Text, nullable=False)`). Every row has a target, so the equality check is always well-defined.
- **`studies.target` is non-nullable.** Confirmed at [`backend/app/db/models/study.py:50`](../../../../backend/app/db/models/study.py#L50).
- **`CreateStudyRequest.target` is required.** Confirmed at [`studies.py:259`](../../../../backend/app/api/v1/studies.py#L259) (`target=body.target` passed unconditionally to `repo.create_study`).
- **No FTS impact.** `judgment_lists.search_vector` is `GENERATED ALWAYS AS … STORED` over `name + target` per migration `0012_search_vector_judgment_lists.py`. Adding a wire `?target=` filter is orthogonal to the existing FTS `?q=` path — operators can use either.
- **OpenAPI surface lock.** `backend/tests/contract/test_openapi_surface.py` snapshots the OpenAPI schema. The summary's new `target` field will fail this snapshot until updated — must be in the same PR.

## 6) Actors and roles

- **Primary actor:** Relevance engineer (per umbrella spec §6).
- **Role model:** N/A — single-tenant install, no auth surface (MVP1).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface (per [`docs/01_architecture/tech-stack.md` "Canonical release matrix"](../../../01_architecture/tech-stack.md)).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). Pre-MVP2, mutations do not emit audit events.

## 7) Functional requirements

### FR-1: Reject mismatched targets at POST /studies

- Requirement:
  - The system **MUST** return HTTP 422 with `error_code = "JUDGMENT_TARGET_MISMATCH"` from `POST /api/v1/studies` when the resolved `judgment_list.target` does not equal `body.target` (byte-for-byte string equality — no normalization, no case-folding, no whitespace trimming).
  - The system **MUST** evaluate this check AFTER the FK resolution (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`), AFTER the existing `query_set_id` cross-check at [`studies.py:240-247`](../../../../backend/app/api/v1/studies.py#L240-L247), and AFTER the new `cluster_id` cross-check from FR-1b.
  - The error message **MUST** include both target values for operator diagnosis and **SHOULD** suggest the two recovery paths (regenerate judgments against the study's target, OR change the study target to the judgment list's target).
  - The error envelope **MUST** match the canonical shape from `_err(...)` at [`studies.py:74-78`](../../../../backend/app/api/v1/studies.py#L74-L78): `{"detail": {"error_code": "JUDGMENT_TARGET_MISMATCH", "message": "...", "retryable": false}}`.
- Notes: Equality check, no normalization. ES/OpenSearch index names are case-sensitive (lowercased by convention but not enforced); a target string of `Docs-Articles` differs from `docs-articles` at the index layer and must differ here too. The 422 status matches the existing `query_set_id` mismatch precedent at line 242.

### FR-1b: Reject mismatched cluster_id at POST /studies

- Requirement:
  - The system **MUST** return HTTP 422 with `error_code = "JUDGMENT_CLUSTER_MISMATCH"` from `POST /api/v1/studies` when the resolved `judgment_list.cluster_id` does not equal `body.cluster_id`.
  - The system **MUST** evaluate this check AFTER the FK resolution and AFTER the existing `query_set_id` cross-check at [`studies.py:240-247`](../../../../backend/app/api/v1/studies.py#L240-L247), and BEFORE the FR-1 target check (cluster mismatch is the broader failure — even with matching target name, different physical clusters have different doc IDs).
  - The error envelope **MUST** match the canonical shape: `{"detail": {"error_code": "JUDGMENT_CLUSTER_MISMATCH", "message": "...", "retryable": false}}`.
- Notes: This closes the residual gap GPT-5.5 cycle-1 surfaced — without this check, a chat-agent or direct API caller could submit `body.cluster_id=B` + `judgment_list_id=` (with `judgment_list.cluster_id=A`, `judgment_list.target="foo"`) + `body.target="foo"` and pass FR-1 because target names match. Doc IDs are scoped to the physical cluster, so distinct clusters with the same target name still produce zero overlap. The `judgment_list.cluster_id` column exists at [`backend/app/db/models/judgment_list.py:45`](../../../../backend/app/db/models/judgment_list.py#L45) (`String(36) NOT NULL FK clusters.id`).

### FR-2: Extend GET /api/v1/judgment-lists with ?target= filter

- Requirement:
  - The system **MUST** accept an optional `?target=<string>` query parameter on `GET /api/v1/judgment-lists`.
  - When `target` is present, the system **MUST** filter the listing AND the `X-Total-Count` header to only rows where `judgment_lists.target = target` (exact byte-for-byte match, no `LIKE`, no normalization).
  - The system **MUST** combine `?target=` with the existing `?query_set_id=` + `?cluster_id=` filters using AND semantics (consistent with the pattern at [`backend/app/db/repo/judgment_list.py:87-90, 133-136`](../../../../backend/app/db/repo/judgment_list.py#L87-L90)).
  - The parameter **MUST** be bounded `min_length=1, max_length=255`. Rationale: 255 is the Elasticsearch / OpenSearch index-name ceiling (the only meaningful cap on a target string today; the underlying `Text` column has no length limit at the DB layer). Out-of-bounds → 422 with `error_code = "VALIDATION_ERROR"` per the canonical envelope from `validation_exception_handler` at [`backend/app/api/errors.py:102-118`](../../../../backend/app/api/errors.py#L102-L118) (the project translates FastAPI's `RequestValidationError` into the standard `{detail: {error_code, message, retryable}}` shape — not FastAPI's default `detail: [{...}]` list).
- Notes: Out-of-bounds (length 0 or >255) returns the canonical `VALIDATION_ERROR` envelope — no new code needed. The same envelope applies to the existing `query_set_id` / `cluster_id` length violations on this endpoint.

### FR-3: Add target to JudgmentListSummary

- Requirement:
  - The system **MUST** add `target: str` (non-nullable) to the `JudgmentListSummary` Pydantic model at [`backend/app/api/v1/schemas.py:760-769`](../../../../backend/app/api/v1/schemas.py#L760-L769).
  - The `_summary()` builder at [`backend/app/api/v1/judgments.py:113-122`](../../../../backend/app/api/v1/judgments.py#L113-L122) **MUST** populate the new field from `row.target`.
  - The OpenAPI surface contract test **MUST** be updated to assert `target` is present in the `JudgmentListSummary` schema definition.
- Notes: Additive non-breaking change. Existing TanStack Query consumers tolerate unknown additive fields. The OpenAPI shape-lock test catches the surface drift and must be updated in the same PR.

### FR-4: Frontend create-study modal — target-aware dropdown + cascade reset

- Requirement:
  - The frontend **MUST** pass `target` (sourced from `form.watch('target')`) through the `useJudgmentLists` filter at [`create-study-modal.tsx:190-193`](../../../../ui/src/components/studies/create-study-modal.tsx#L190-L193): `useJudgmentLists({ query_set_id: querySetId || undefined, cluster_id: clusterId || undefined, target: target || undefined, limit: 200 })`. `cluster_id` is added at the same time for symmetry.
  - When EITHER `target` (via the Step-1 picker — `<Input>` manual mode at line 527, `<EntitySelect>` dropdown mode at lines 546-561) OR `cluster_id` (via the cluster picker — existing `onChange` at line 504-507 already resets `target` per the prior FR-4 cascade; this spec extends that same handler to ALSO reset `judgment_list_id`) changes, the frontend **MUST** reset `judgment_list_id` to `''`. Mirror the existing `query_set_id`-change reset at line 596.
  - When the filtered list returns zero rows, the dropdown **MUST** render the existing `EntitySelect.emptyState` (per [`entity-select.tsx:33-36`](../../../../ui/src/components/common/entity-select.tsx#L33-L36)) with message `"No judgment lists for target \"{target}\" on this cluster + query set. Generate a new one from /judgments."` and `cta = { label: "Generate judgments", href: "/judgments" }`.
  - The `JudgmentListsFilter` interface at [`ui/src/lib/api/judgments.ts:30-35`](../../../../ui/src/lib/api/judgments.ts#L30-L35) **MUST** add `target?: string | undefined`.
  - The TanStack queryKey **MUST** include `target` so cache entries are correctly scoped (existing cache entries keyed without `target` remain valid for filter-less callers like `associated-judgment-lists.tsx`).
  - The generated OpenAPI types at `ui/src/lib/types.ts` **MUST** be regenerated to reflect the new `JudgmentListSummary.target` field and the new wire filter param.
- Notes: Step 1 (`'Cluster + target'`) gates Step-2 advance with `Boolean(values.cluster_id && values.target)` (per [`create-study-modal.tsx:384`](../../../../ui/src/components/studies/create-study-modal.tsx#L384)) — `target` is always set by the time the user reaches the judgment-list dropdown, so the "no target yet" branch the original idea proposed is dead code and not implemented.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | Create + enqueue start_study | `JUDGMENT_CLUSTER_MISMATCH` (422 — new, fires first), `JUDGMENT_TARGET_MISMATCH` (422 — new); existing: `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `INVALID_SEARCH_SPACE` (400), `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400), `VALIDATION_ERROR` (422). |
| `GET` | `/api/v1/judgment-lists` | List with cursor pagination + filters | `VALIDATION_ERROR` (422 — cursor decode or query-param bounds). |

### 7.2 Contract rules

- Error body **MUST** include `error_code` (machine-readable, never renamed once shipped).
- Status code 422 **MUST** be deterministic per scenario: target mismatch → `JUDGMENT_TARGET_MISMATCH`; query_set mismatch (existing) → `VALIDATION_ERROR`; FK lookup → 404 with the specific entity code.
- The new validator **MUST** fire AFTER all FK resolutions to preserve the 404-before-422 ordering operators rely on.

### 7.3 Response examples

**Success — POST /api/v1/studies (existing shape, unchanged):**
```json
{
  "id": "01990000-0000-7000-8000-000000000001",
  "name": "tune-products-boost",
  "cluster_id": "01990000-0000-7000-8000-000000000010",
  "target": "products",
  "template_id": "01990000-0000-7000-8000-000000000020",
  "query_set_id": "01990000-0000-7000-8000-000000000030",
  "judgment_list_id": "01990000-0000-7000-8000-000000000040",
  "search_space": {"params": {"boost": {"kind": "float", "low": 0.5, "high": 10}}},
  "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
  "config": {"max_trials": 100, "sampler": "tpe", "pruner": "median"},
  "status": "queued",
  "failed_reason": null,
  "optuna_study_name": "01990000-0000-7000-8000-000000000001",
  "...": "...remaining StudyDetail fields..."
}
```

**Failure — POST /api/v1/studies, target mismatch (NEW):** HTTP 422
```json
{
  "detail": {
    "error_code": "JUDGMENT_TARGET_MISMATCH",
    "message": "judgment_list target='e2e-target' does not match study target='products'; judgments would have no overlap with search results from the study's target. Use a judgment list generated against 'products' or change study.target to 'e2e-target'.",
    "retryable": false
  }
}
```

**Success — GET /api/v1/judgment-lists?target=products (NEW filter, summary shape extended):** HTTP 200, header `X-Total-Count: 2`
```json
{
  "data": [
    {
      "id": "01990000-0000-7000-8000-000000000040",
      "name": "products-judgments-v1",
      "description": "Initial 200-judgment seed.",
      "query_set_id": "01990000-0000-7000-8000-000000000030",
      "cluster_id": "01990000-0000-7000-8000-000000000010",
      "target": "products",
      "status": "complete",
      "created_at": "2026-05-20T18:42:11.000Z"
    },
    {
      "id": "01990000-0000-7000-8000-000000000041",
      "name": "products-judgments-v2",
      "description": null,
      "query_set_id": "01990000-0000-7000-8000-000000000030",
      "cluster_id": "01990000-0000-7000-8000-000000000010",
      "target": "products",
      "status": "complete",
      "created_at": "2026-05-21T09:14:02.000Z"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

**Failure — GET /api/v1/judgment-lists?target=&lt;empty&gt;:** HTTP 422 (FastAPI's `VALIDATION_ERROR` for `min_length=1` violation; shape per FastAPI's `RequestValidationError` handler — same as any other bounds violation on this endpoint, no new code).

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `POST /studies` `error_code` | `JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH` (both new, in firing order); existing per `studies.py` `_err(...)` call sites | `backend/app/api/v1/studies.py` (`_err(...)` invocations) — codes are string literals, not a centralized Literal | None on frontend yet — the modal pre-filters so the operator can't submit a mismatch. The chat agent's `create_study` tool surfaces the error via the orchestrator's existing 422-handler; no new branching needed. |
| `GET /judgment-lists` `?target=` | Any non-empty string up to 255 chars | `judgments.py:347-348` (FastAPI `Annotated[str \| None, Query(min_length=1, max_length=255)]`) | `useJudgmentLists` filter — but the value flows through opaquely; no allowlist on the frontend side. |

No new option lists, status enums, or filter chips introduced. No new `<select>` dropdowns added — only an additional filter param on an existing call.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `JUDGMENT_CLUSTER_MISMATCH` | 422 | `judgment_list.cluster_id` does not equal `body.cluster_id` on `POST /api/v1/studies`. `retryable: false`. Recovery: pick a judgment list authored on the same cluster as the study, or change the study's cluster. Fires before the target check. |
| `JUDGMENT_TARGET_MISMATCH` | 422 | `judgment_list.target` does not equal `body.target` on `POST /api/v1/studies`. `retryable: false`. Recovery: caller must either pick a judgment list authored against the study's target, or change the study's target to match the judgment list's target. |

Register in BOTH the feature spec §7.5 (this section, canonical) AND `docs/01_architecture/api-conventions.md` alongside `SEARCH_SPACE_UNKNOWN_PARAM` and `SEARCH_SPACE_MISSING_DECLARED_PARAM` per the `chore_create_study_wizard_polish` precedent at api-conventions.md:72-77.

## 9) Data model and state transitions

### New/changed entities

**Modified table: (none)** — no schema changes. `judgment_lists.target` and `studies.target` already exist with the right shape.

**Modified Pydantic schema: `JudgmentListSummary`**
- Add `target: str` (non-nullable, no default) — populated by `_summary()` from `row.target`. Underlying ORM column is `Text NOT NULL` per [`judgment_list.py:46`](../../../../backend/app/db/models/judgment_list.py#L46).

**Modified Pydantic schema: `CreateStudyRequest`** — none; `target` is already required.

### Required invariants

- **Cross-entity consistency at create:** `studies.target == judgment_lists.target` for every newly created `studies` row where `judgment_list_id` is set. Enforced at the API boundary (FR-1). Pre-existing rows are out of scope.
- **Listing-count consistency:** when `?target=X` is supplied, `len(data) ≤ X-Total-Count`, and `X-Total-Count` reflects the row count under the same filter. Verified by mirroring the WHERE clause across `list_judgment_lists` + `count_judgment_lists`.

### State transitions

None. Feature is purely validation; no new state machine states or transitions.

### Idempotency/replay behavior

N/A — this is a synchronous validator on the request handler. No event delivery, no Arq job, no Redis state.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Operator submits a mismatched (target, judgment_list) pair via the chat agent's `create_study` tool, bypassing the modal filter. Mitigated by the backend `POST /studies` rejection (FR-1) — the contract layer is the security/correctness boundary.
  2. Frontend over-fetching exposes unrelated tenant judgment lists via the `?target=` filter. **Not applicable in MVP1** — single-tenant install; `?target=` returns rows from the same single-tenant DB. MVP4+ multi-tenant: the existing tenant scoping at the repo layer (not present in MVP1) will scope the filter automatically.
- **Controls:** Pure validation logic; no new attack surface. The new `?target=` wire param is a stricter version of the existing `?q=` FTS filter on `judgment_lists.search_vector` (which covers `name + target`); both are bounded by `max_length`.
- **Secrets/key handling:** N/A.
- **Auditability:** N/A in MVP1 (`audit_log` lands at MVP2).
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new routes. Frontend changes are confined to the create-study modal triggered from `/studies` ([`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)).
- **Labeling taxonomy:** No new labels. Existing labels in scope:
  - "Cluster" (Step-1)
  - "Target index / collection" (Step-1)
  - "Query set" (Step-2)
  - "Judgment list" (Step-2)
- **Content hierarchy:** Step 1 ("Cluster + target") above Step 2 ("Query set + judgments"). Existing 5-step wizard preserved.
- **Progressive disclosure:** None. The empty-state copy only renders when filtered results are empty; otherwise the dropdown looks identical to today.
- **Relationship to existing pages:** Extends the existing create-study modal — does not replace or rename anything.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| Judgment list dropdown (Step 2) | (no new tooltip — existing `study.judgment_list` glossary entry already explains the field) | hover/focus on adjacent `<InfoTooltip>` (already present per `glossary.ts`) | top |
| Empty-state CTA "Generate judgments" | (link label is self-explanatory; no tooltip) | inline | below dropdown |

No new tooltip placements. The empty-state message itself is the contextual help when the dropdown is empty.

### Primary flows

1. **Happy path — operator picks a matching pair via the modal.**
   - Step 1: operator selects cluster `acme-products-prod` + target `products` (via dropdown or manual entry).
   - Step 2: dropdown loads `GET /api/v1/judgment-lists?query_set_id=<X>&cluster_id=<Y>&target=products&limit=200` → returns 2 matching judgment lists.
   - Operator picks one; modal advances to Step 3. Study creates successfully.

2. **Happy path — operator changes target after picking a judgment list.**
   - Step 1: operator picks target `products` → advances → Step 2 picks judgment list → returns to Step 1 → changes target to `articles`.
   - Cascade reset (FR-4): `judgment_list_id` reset to `''`. Step-2 advance gate fails until operator re-picks.
   - Dropdown now returns judgment lists matching `target=articles`. Operator picks; study creates.

3. **Backend rejection — chat agent or direct API caller submits mismatched pair.**
   - `POST /api/v1/studies` body has `target="products"` and `judgment_list_id` → judgment list with `target="e2e-target"`.
   - Handler resolves FKs (pass), checks `query_set_id` cross-consistency (pass), checks `target == judgment_list.target` (FAIL) → returns 422 `JUDGMENT_TARGET_MISMATCH`.
   - Caller sees the structured error envelope with both target values and the recovery suggestion.

### Edge/error flows

- **Empty filter result:** dropdown shows the empty-state copy with CTA linking to `/judgments`. Step-2 advance gate fails (no `judgment_list_id` set).
- **Target dropdown failure (TARGETS_FORBIDDEN auto-engages manual mode per existing FR-5 at `create-study-modal.tsx:170-173`):** operator enters target manually. Same flow — `target` is set, `useJudgmentLists` filters by the manually entered value.
- **Pre-existing studies with mismatched targets:** out of scope (existing rows continue executing). Operator-visible failure mode is the existing "trials all score 0.0" pathology, which `feat_orchestrator_zero_streak_abort` will catch mid-flight.
- **Chat-agent-initiated mismatch:** the chat agent's `create_study` tool already routes through `POST /api/v1/studies`. The new 422 surfaces in the conversation as a structured error; the agent's existing error-handling renders it to the user.

## 12) Given/When/Then acceptance criteria

### AC-1: Mismatched targets rejected at POST /studies

- Given a cluster, query set, query template, and a judgment list with `target = "e2e-target"` all exist
- And the judgment list's `query_set_id` matches the query set
- When the operator calls `POST /api/v1/studies` with body `{cluster_id: ..., target: "docs-articles", template_id: ..., query_set_id: ..., judgment_list_id: ..., name: "study2", search_space: {...}, objective: {...}, config: {...}}`
- Then the response is HTTP 422 with body `{"detail": {"error_code": "JUDGMENT_TARGET_MISMATCH", "message": "...e2e-target...docs-articles...", "retryable": false}}`
- And no row is inserted into `studies`
- And no Arq job is enqueued
- Example values:
  - judgment_list.target: `"e2e-target"`
  - body.target: `"docs-articles"`
  - Expected message contains both `"e2e-target"` and `"docs-articles"` substrings

### AC-2: Matching targets pass create-time validation

- Given the same setup as AC-1 except `judgment_list.target = "docs-articles"`
- When `POST /api/v1/studies` is called with `body.target = "docs-articles"`
- Then the response is HTTP 201 with the existing `StudyDetail` shape (`status: "queued"`)
- And a row is inserted into `studies` with the same `target`
- And `start_study(study_id)` is enqueued

### AC-3: Target check fires AFTER FK checks

- Given a `judgment_list_id` that does NOT exist in `judgment_lists`
- When `POST /api/v1/studies` is called with `target = "docs-articles"` and a target-mismatched `judgment_list` (hypothetically — the row doesn't exist)
- Then the response is HTTP 404 with `error_code = "JUDGMENT_LIST_NOT_FOUND"` (not 422 `JUDGMENT_TARGET_MISMATCH`)
- And the target check is never reached

### AC-4: Target check fires AFTER query_set_id check

- Given a judgment list with `query_set_id = "qs-A"` and `target = "indexA"`
- When `POST /api/v1/studies` is called with `query_set_id = "qs-B"` and `target = "indexB"`
- Then the response is HTTP 422 with `error_code = "VALIDATION_ERROR"` (query_set mismatch wins — fires first per the ordering at `studies.py:240-247`)
- And the target check is never reached

### AC-5: GET /judgment-lists?target=X filters correctly

- Given 3 judgment lists exist: list A with `target="products"`, list B with `target="products"`, list C with `target="articles"`
- When `GET /api/v1/judgment-lists?target=products` is called
- Then the response is HTTP 200 with `data = [list_A, list_B]` (order per the existing default sort `created_at DESC, id DESC`)
- And the `X-Total-Count` header is `2`
- And `next_cursor` is `null`, `has_more` is `false`

### AC-6: JudgmentListSummary includes target

- Given list A with `target="products"` exists
- When `GET /api/v1/judgment-lists` is called
- Then each item in `data` has a `target` field of type `string`
- And the OpenAPI schema lists `target` as a required field on `JudgmentListSummary`

### AC-7: Modal dropdown filters by target

- Given the create-study modal is open at Step 2 with `target="products"` set in Step 1
- And 3 judgment lists exist (2 with `target="products"`, 1 with `target="articles"`) all matching the query_set + cluster
- When the dropdown opens
- Then only the 2 `products`-target judgment lists are rendered
- And `articles`-target list is not visible

### AC-8: Empty-state copy renders when filter returns zero

- Given the create-study modal is at Step 2 with `target="products"` set
- And no judgment lists have `target="products"` for the chosen query_set + cluster
- When the dropdown opens
- Then the empty-state message renders: `"No judgment lists for target \"products\" on this cluster + query set. Generate a new one from /judgments."`
- And the CTA `"Generate judgments"` links to `/judgments`

### AC-9: Target change cascades reset of judgment_list_id

- Given the create-study modal is at Step 2 with `target="products"` and `judgment_list_id="jl-abc"` set
- When the operator returns to Step 1 and changes target to `"articles"`
- Then `judgment_list_id` is reset to `''`
- And Step-2 advance is gated until the operator re-picks

### AC-10: Pre-existing studies on read paths are not affected

- Given a study row with mismatched `target` was inserted before this feature shipped (or seeded by a fixture for the test)
- When `GET /api/v1/studies/{id}` is called for that row
- Then the response is HTTP 200 with the existing `StudyDetail` shape (no new exception class raised by the read path)
- Notes: This is a negative-existence test — proves the new validator did not leak into the repo / serializer / state-machine read paths. Mid-flight orchestrator behavior on such studies is owned by [feat_orchestrator_zero_streak_abort](../feat_orchestrator_zero_streak_abort/idea.md) and is not asserted here.

### AC-12: Cluster change cascades reset of judgment_list_id

- Given the create-study modal is at Step 2 with `cluster_id="C1"`, `target="products"`, `judgment_list_id="jl-c1-abc"` set
- When the operator returns to Step 1 and changes the cluster picker to `C2`
- Then `judgment_list_id` is reset to `''` (along with the existing `target` reset from line 504-507)
- And Step-2 advance is gated until the operator re-picks both
- Notes: Catches the cluster-change branch of FR-2/FR-4 cascade — separate from AC-9 (target change).

### AC-11: cluster_id mismatch rejected at POST /studies

- Given a cluster `C1`, query set `Q` (whose `cluster_id = C1`), query template, and a judgment list with `cluster_id = C2, query_set_id = Q.id, target = "products"`
- And cluster `C1` and target `"products"` are passed in the study POST body
- When `POST /api/v1/studies` is called with `{cluster_id: C1, target: "products", query_set_id: Q.id, judgment_list_id: ..., ...}`
- Then the response is HTTP 422 with body `{"detail": {"error_code": "JUDGMENT_CLUSTER_MISMATCH", "message": "...", "retryable": false}}`
- And no row is inserted into `studies`
- Notes: This ordering test confirms FR-1b fires before FR-1 — even though target matches, the cluster mismatch is detected first.

## 13) Non-functional requirements

- **Performance:** New validator runs in O(1) — one string comparison after the existing FK + query_set checks. Adds <1ms to `POST /api/v1/studies` p99. New `?target=` filter adds one `WHERE` clause to an indexed-or-soon-indexed (matches existing `query_set_id` / `cluster_id` filter cost — same physical scan).
- **Reliability:** Pure synchronous validator with no external calls; cannot fail except via the 422 response shape itself. Zero new error budget impact.
- **Operability:** No new logs; the existing FastAPI access log captures the 422. No new metrics; the existing `/healthz` is unaffected.
- **Accessibility/usability:** Frontend cascade reset prevents stale form state — operator does not need to manually clear the judgment-list field after changing target. Empty-state message includes the exact target value the operator typed (or picked) so the recovery path is unambiguous.

## 14) Test strategy requirements (spec-level)

| Layer | Required tests |
|---|---|
| Unit (backend) | None new — no new pure domain logic. The validator is a single conditional inside the route handler; covered by contract + integration tests. |
| Integration (backend) | (1) Studies POST with mismatched targets → 422 `JUDGMENT_TARGET_MISMATCH`. (2) Studies POST with mismatched clusters → 422 `JUDGMENT_CLUSTER_MISMATCH` (FR-1b). (3) Studies POST with matching cluster + target → 201 (AC-2 happy path). (4) `GET /judgment-lists?target=X` filters across 2 lists with different targets, with `X-Total-Count` matching. (5) **AND-semantics + count consistency:** seed 4 lists spanning 2 clusters × 2 query_sets × shared target `products`; call `GET /judgment-lists?target=products&cluster_id=C1&query_set_id=Q1` and assert `data` contains exactly the 1 matching list AND `X-Total-Count: 1` (catches the regression where the filter applies to `list_judgment_lists` but not `count_judgment_lists`, or vice versa). (6) `GET /studies/{id}` for a pre-existing fixture row with mismatched target returns 200 — read paths are NOT validated (FR-1 fires only at POST). |
| Contract (backend) | (1) New `JUDGMENT_TARGET_MISMATCH` error envelope in `test_studies_error_codes.py`. (2) New `JUDGMENT_CLUSTER_MISMATCH` error envelope (separate assertion — both codes must be locked). (3) OpenAPI surface lock in `test_openapi_surface.py` updated to include `JudgmentListSummary.target` AND both new error codes if the surface test enumerates them. (4) Existing `test_studies_api_contract.py` ordering checks (404-before-422, VALIDATION_ERROR-before-JUDGMENT_CLUSTER_MISMATCH-before-JUDGMENT_TARGET_MISMATCH). |
| E2E (frontend) | None new. The dropdown filtering + cascade reset is exercised by vitest at the component level. **Existing seed audit required:** the Playwright helper at [`ui/tests/e2e/helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) (around lines 400-413) creates judgment lists with `target: 'products'` matching the cluster's seeded products index. Confirmed compatible — no change needed. If a future spec adds a fixture where `judgment_list.target` diverges from `study.target`, that spec must be updated to set them consistently OR it must explicitly exercise the 422 path. |
| Unit (frontend / vitest) | (1) Assert `useJudgmentLists` is called with `{ query_set_id, cluster_id, target, limit: 200 }` when the user has set those values in the form (verifies the component DELEGATES filtering to the wire — NOT that it filters client-side, which the anti-pattern rule forbids). (2) `target` change resets `judgment_list_id` (FR-4 cascade — AC-9). (3) `cluster_id` change resets `judgment_list_id` (FR-4 cascade — AC-12; mirrors case 2). (4) Empty-state copy renders with the exact target value + CTA href when the mocked hook returns `{ data: [], next_cursor: null, has_more: false }`. |

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — add BOTH `JUDGMENT_CLUSTER_MISMATCH` AND `JUDGMENT_TARGET_MISMATCH` rows to the studies-endpoint error-code table (after `SEARCH_SPACE_MISSING_DECLARED_PARAM`), in firing order.
- `docs/02_product/planned_features/feat_study_target_judgment_mismatch_guard/` — this spec file.
- `docs/03_runbooks/` — no new runbook (the 422 is self-explanatory; existing study-lifecycle-debugging runbook already covers POST /studies failure modes).
- `docs/04_security/` — no change (no new attack surface).
- `docs/05_quality/` — no change (existing test layers cover the new code).
- `state.md` — updated with the feature in the "Most recent meaningful changes" log on merge.
- `architecture.md` — no change (no new layer, no new flow).
- `CLAUDE.md` — no change (no new convention, no new env var, no new absolute rule).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Feature is a hard-gate at the API boundary; staged rollout would mean half the operators get the 422 and half don't — strictly worse than shipping atomically.
- **Migration/backfill expectations:** None — no schema changes.
- **Operational readiness gates:** None new — existing CI gates (`make lint`, `make typecheck`, `make test-unit`, `make test-integration`, `make test-contract`, `pnpm test`, `pnpm typecheck`, `pnpm build`) plus the OpenAPI-shape-lock contract test catch all regressions.
- **Release gate:**
  - All 12 ACs (AC-1 through AC-12) pass in CI.
  - The OpenAPI snapshot contract test is updated in the same PR.
  - `api-conventions.md` is updated in the same PR.
  - At least 1 cycle of GPT-5.5 cross-model review on the implementation plan.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-3, AC-4, AC-10 | (B1) Add validator block to `studies.py` between lines 247 and 249, after the new FR-1b cluster check | `tests/contract/test_studies_error_codes.py`, `tests/integration/test_studies_api.py` | `api-conventions.md`, this spec §7.5 |
| FR-1b | AC-11 | (B1b) Add cluster_id cross-check before the target check | `tests/contract/test_studies_error_codes.py`, `tests/integration/test_studies_api.py` | `api-conventions.md`, this spec §7.5 |
| FR-2 | AC-5 | (B2a) Extend `list_judgment_lists` + `count_judgment_lists` + `list_judgment_lists_endpoint` with `target` param | `tests/integration/test_judgments_api.py` | (none — covered by FastAPI auto-OpenAPI) |
| FR-3 | AC-6 | (B2b) Add `target` to `JudgmentListSummary` Pydantic + `_summary()` builder | `tests/contract/test_judgments_api_contract.py`, `tests/contract/test_openapi_surface.py` | (auto-OpenAPI) |
| FR-4 | AC-7, AC-8, AC-9 | (F1) Pass `target` to `useJudgmentLists`; (F2) cascade reset; (F3) empty-state copy; (F4) types regen | `ui/src/components/studies/__tests__/create-study-modal.target-filter.test.tsx` (new) | (none) |

## 18) Definition of feature done

- [ ] All acceptance criteria AC-1 through AC-12 pass in CI.
- [ ] Backend unit/integration/contract tests pass.
- [ ] Frontend vitest passes; `pnpm typecheck`, `pnpm lint`, `pnpm build` all green.
- [ ] `docs/01_architecture/api-conventions.md` updated with BOTH new error-code rows (`JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH`).
- [ ] OpenAPI snapshot contract test updated with the `JudgmentListSummary.target` field and the new `?target=` query param.
- [ ] `ui/src/lib/types.ts` regenerated from live OpenAPI.
- [ ] No open questions remain in §19.
- [ ] PR includes GPT-5.5 final review pass + Gemini Code Assist adjudication.

## 19) Open questions and decision log

### Open questions

(none — all decisions locked. See "Locked decisions" in `idea.md` + the Decision log below.)

### Decision log

- **2026-05-21 (post-GPT-5.5 cycle 3)** — REJECTED cycle-3 finding B.1 (cluster change doesn't cascade-reset query_set_id) with cited counter-evidence at [`create-study-modal.tsx:508`](../../../../ui/src/components/studies/create-study-modal.tsx#L508) — the existing cluster-change `onChange` handler already resets `target`, `query_set_id`, `judgment_list_id`, AND `template_id` to `''`. The reviewer's concern was based on the spec text not citing this existing reset, not on an actual code gap.
- **2026-05-21 (post-GPT-5.5 cycle 3)** — `query_set.cluster_id ↔ body.cluster_id` consistency at POST /studies is OUT OF SCOPE. Queries are plain text strings (no cluster-scoped doc IDs); a query_set.cluster_id mismatch doesn't cause this feature's zero-signal pathology. Cascade reset in the UI already prevents accidental trigger. Captured as a possible follow-up `bug_studies_query_set_cluster_consistency` if a future operator hits the contract inconsistency.
- **2026-05-21 (post-GPT-5.5 cycle 1)** — Add FR-1b cluster_id cross-check + new `JUDGMENT_CLUSTER_MISMATCH` error code. Rationale: cycle-1 reviewer surfaced that without this check, a direct API or chat-agent caller could submit `body.cluster_id = C2` with a judgment_list whose `cluster_id = C1` but matching `target` name, and pass FR-1. Doc IDs are physically scoped to a cluster — same target name on two clusters produces zero overlap. Symmetric with FR-1; one extra string compare, one new error code.
- **2026-05-21 (post-GPT-5.5 cycle 1)** — `?target=` bound `max_length=255` (ES/OpenSearch index-name ceiling), NOT 256. Rationale: cycle-1 reviewer flagged "Text column has implicit 256 limit" as inaccurate (Text has no DB-layer length cap). The only meaningful cap is the ES index-name limit, which is 255 bytes.
- **2026-05-21** — Specific error code `JUDGMENT_TARGET_MISMATCH` (not generic `VALIDATION_ERROR`). Rationale: matches the studies-endpoint specific-code precedent (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`, `TARGETS_FORBIDDEN`); lets the frontend render targeted recovery UI.
- **2026-05-21** — Do NOT rename the existing `VALIDATION_ERROR` returned by the `query_set_id` mismatch check at [`studies.py:242-247`](../../../../backend/app/api/v1/studies.py#L242-L247). Rationale: `api-conventions.md:196` forbids renaming shipped codes; the asymmetry (one specific, one generic) is the lesser evil.
- **2026-05-21** — Add `?target=` as a wire filter on `GET /api/v1/judgment-lists`, not a client-side filter. Rationale: mirrors the established `?cluster_id` / `?query_set_id` pattern from PR #163; keeps `X-Total-Count` consistent with the rendered row count.
- **2026-05-21** — Add `target: str` to `JudgmentListSummary` as a non-nullable additive field. Rationale: underlying column is `Text NOT NULL`; required by the empty-state copy + future ergonomic enhancements (dropdown item subtitle).
- **2026-05-21** — Validator fires only at `POST /studies`; pre-existing mismatched studies are NOT retroactively rejected. Rationale: forward-only fix; mid-flight detection is owned by [feat_orchestrator_zero_streak_abort](../feat_orchestrator_zero_streak_abort/idea.md).
- **2026-05-21** — Frontend modal filter is a UX prefetch, not a contract; the backend 422 is the contract. Rationale: chat-agent `create_study` tool and direct API callers fall through to the same backend gate without needing separate enforcement.
- **2026-05-21** — Adopt `cluster_id` filtering on the modal's `useJudgmentLists` call at the same time as `target` (the call currently passes only `query_set_id`). Rationale: zero marginal cost — the wire param already exists, `clusterId` is already in scope, and the symmetric filter set is cheaper to reason about.
