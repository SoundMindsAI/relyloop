# Feature Specification — Side-by-side UBI-vs-LLM study comparison view

**Date:** 2026-05-31
**Status:** Approved
**Owners:** Product — soundminds.ai; Engineering — RelyLoop core
**Related docs:**
- [`idea.md`](idea.md) — this feature's preflighted idea
- [`feat_demo_ubi_study_comparison/feature_spec.md`](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md) — Phase 1 (shipped, PR #320); this is its deferred Phase 2
- [`feat_study_convergence_indicator/feature_spec.md`](../feat_study_convergence_indicator/feature_spec.md) — sibling on the same branch; ships `StudyDetail.convergence.best_so_far_curve` (the curve data this view overlays)
- [`feat_pr_metric_confidence`](../../../implemented_features/) (shipped) — `study_confidence.py` → `StudyDetail.confidence`
- [`chore_cluster_detail_rung_badge/idea.md`](../chore_cluster_detail_rung_badge/idea.md) — the cluster-detail rung-badge work split out of this feature (§3)

---

## 1) Purpose

- **Problem:** A demo operator who wants to compare the **UBI-derived** study against the **LLM-derived** study on the same scenario must open both study-detail pages in two browser tabs and mentally diff the digest narratives, the best-trial parameter values, the best-metric scalar, and the convergence curves. The central value proposition of the synthetic-UBI demo — *"see what changes when you ground judgments in real behavior instead of an LLM's rubric reading"* — is buried behind manual cross-tab labor.
- **Outcome:** A single dedicated route `/studies/compare?a={id}&b={id}` renders the two studies side-by-side with a per-panel diff column: a sentence-level digest-narrative diff, a best-trial parameter table with same/different flags, a best-metric scalar with delta annotation (confidence-aware), and a two-series convergence-curve overlay. Entry points appear on the LLM study-detail page, the UBI study-detail page, and the UBI judgment-list value-delta card — but only when a valid paired study actually exists.
- **Non-goal:** This feature does not seed data, does not generate judgments, does not modify any study/trial/digest, and does not add a rung badge to the cluster-detail page (that work is split out — see §3 and [`chore_cluster_detail_rung_badge`](../chore_cluster_detail_rung_badge/idea.md)). It is a read-only presentation layer over existing endpoints.

## 2) Current state audit

### Existing implementations

- **`GET /api/v1/studies/{study_id}`** ([`backend/app/api/v1/studies.py:549-589`](../../../../backend/app/api/v1/studies.py)) → `StudyDetail` ([`schemas.py:793-824`](../../../../backend/app/api/v1/schemas.py)). Carries `query_set_id`, `judgment_list_id`, `best_metric`, `best_trial_id`, `objective` (holds `direction`), `status`, `trials_summary`, and `confidence: ConfidenceShape | None`. **Does NOT carry judgment-list metadata** (name, `generation_kind`) — the page only knows `judgment_list_id`. The comparison must resolve which study is LLM vs UBI via the judgment list (see below).
- **`GET /api/v1/studies/{study_id}/digest`** ([`backend/app/api/v1/proposals.py:262-318`](../../../../backend/app/api/v1/proposals.py)) → `DigestResponse` ([`schemas.py:1144-1161`](../../../../backend/app/api/v1/schemas.py)). Carries `narrative: str`, `parameter_importance: dict[str, float]`, `recommended_config: dict[str, Any]`, `suggested_followups`, `generated_at`. Returns `404 DIGEST_NOT_READY` (`retryable=true`) when the study isn't completed or the digest row isn't written yet.
- **`GET /api/v1/judgment-lists/{id}`** ([`backend/app/api/v1/judgments.py`](../../../../backend/app/api/v1/judgments.py)) → judgment-list detail. The LLM-vs-UBI discriminator is `generation_params.generation_kind == 'ubi'` (all UBI lists, including hybrid-converter ones — `generation_kind` is `'ubi'` for both) vs NULL/other `generation_params` (LLM lists), per [`backend/app/db/models/judgment_list.py:78-86`](../../../../backend/app/db/models/judgment_list.py).
- **`useStudy` / `useStudyTrials` / `useStudyChildren`** ([`ui/src/lib/api/studies.ts`](../../../../ui/src/lib/api/studies.ts)) — TanStack Query hooks; `useStudy` queryKey is `['studies', id]`; trials queryKey `['studies', id, 'trials', {...}]`.
- **`useStudyDigest`** ([`ui/src/lib/api/digests.ts:30-46`](../../../../ui/src/lib/api/digests.ts)) — queryKey `['studies', id, 'digest']`.
- **`useJudgmentList`** ([`ui/src/lib/api/judgments.ts`](../../../../ui/src/lib/api/judgments.ts)) — already consumed on the study-detail page ([`ui/src/app/studies/[id]/page.tsx:25`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx)).
- **Study-detail page** ([`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx)) — composes `<StudyHeader>`, `<ConfidencePanel>`, `<DigestPanel>`, `<TrialsTable>`, `<StudyActionBar>`. Already imports `isDemoSyntheticUbiClusterName` from `@/lib/demo-data` (line 28) and renders the synthetic-data chip via `<StudyHeader showSyntheticUbiChip>`.
- **`<UbiRungBadge>`** ([`ui/src/components/clusters/ubi-rung-badge.tsx`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx)) — consumed ONLY from the generate-judgments dialog today (needs `query_set_id + target` context the cluster-detail page lacks). **Out of scope here** — see §3.
- **`<ValueDeltaCard>`** ([`ui/src/components/judgments/value-delta-card.tsx`](../../../../ui/src/components/judgments/value-delta-card.tsx)) — rendered on the judgment-list detail page ([`ui/src/app/judgments/[id]/page.tsx:131`](../../../../ui/src/app/judgments/%5Bid%5D/page.tsx)). Gains a "View matched study comparison" affordance (§7 FR-9).
- **`<ParameterImportanceChart>`** ([`ui/src/components/common/parameter-importance-chart.tsx`](../../../../ui/src/components/common/parameter-importance-chart.tsx)) — the only existing Recharts component on the study surface (a vertical `<BarChart>`). **No existing `<LineChart>` overlay** — the two-series convergence overlay is a genuinely new chart variant.
- **`isDemoSyntheticUbiClusterName`** ([`ui/src/lib/demo-data.ts:55`](../../../../ui/src/lib/demo-data.ts)) — three-slug helper; gates the "Synthetic demo data" chip.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| `ui/src/app/studies/[id]/page.tsx` (entry button — new) | n/a | `/studies/compare?a={thisStudyId}&b={pairedStudyId}` |
| `ui/src/app/judgments/[id]/page.tsx` (value-delta affordance — new) | n/a | `/studies/compare?a={llmStudyId}&b={ubiStudyId}` |

No existing routes are moved, renamed, or removed. `/studies/compare` is a net-new route.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/app/studies/...` (study-detail tests) | study-detail DOM assertions | TBD at impl time | No change required — the entry button is additive and hidden when no pair exists. New tests assert the button appears only with a pair. |
| `ui/src/__tests__/components/judgments/value-delta-card.test.tsx` | value-delta card render | ~existing | Extend with the conditional "View matched study comparison" affordance (additive). |

No mocked Playwright (`page.route()`) E2E exists for these surfaces today that would break; new E2E is real-backend (§14).

### Existing behaviors affected by scope change

- **Study-detail entry button visibility.** Current: no compare affordance. New: a "Compare with the {UBI|LLM} study" button appears on the study-detail page **only when** a valid paired study exists (same `query_set_id`, both `completed`, the two judgment lists are one-LLM-one-UBI). Decision needed: no — locked in idea Q-4 (hide entirely when no pair).
- **No `query_set_id` filter on the studies list today.** The studies-list endpoint ([`studies.py:455`](../../../../backend/app/api/v1/studies.py)) supports `?status`, `?cluster_id`, `?target`, `?q`, `?sort` — but **not** `?query_set_id`. Discovering a paired study therefore needs a dedicated lookup, not the list endpoint. This feature's pairing endpoint owns that lookup (FR-2). Decision needed: no.

---

## 3) Scope

### In scope

- **A. Thin pairing endpoint** `GET /api/v1/studies/compare?a={id}&b={id}` (FR-1, FR-2) — validates the pair and returns metadata only (which side is LLM / which is UBI, validity warnings). The page fetches the two `/studies/{id}` + `/studies/{id}/digest` payloads via the existing TanStack Query cache (warm if the operator clicked from a detail page).
- **B. Paired-study discovery helper** (FR-2) — a repo + service capability to find the single valid counterpart study for a given study (same `query_set_id`, opposite judgment-list kind, both `completed`) so the entry-point buttons know whether to render.
- **C. Comparison route + page** `/studies/compare` (FR-3) — `<StudyComparisonPage>` with a two-column responsive grid + per-row diff column.
- **D. Digest-narrative diff panel** (FR-4) — sentence-level diff via the `diff` (jsdiff) library's `diffSentences()`.
- **E. Best-trial parameter-table diff** (FR-5) — column per study, row per parameter, same/different flags.
- **F. Best-metric scalar comparison** (FR-6) — delta annotation, confidence-aware when `StudyDetail.confidence` is present.
- **G. Convergence-curve overlay** (FR-7) — two-series Recharts `<LineChart>` plotting both studies' `best_so_far_curve` (soft-depends on `feat_study_convergence_indicator`; fallback derives the curve from `/studies/{id}/trials`).
- **H. Entry points** (FR-8, FR-9) — study-detail button (both directions) + judgment-list value-delta affordance, each hidden when no valid pair exists.
- **I. Mobile / narrow-viewport stacked layout** (FR-10).
- **J. Tutorial guide subsection** (FR-11) — Step 11 "Compare LLM vs UBI on the same dataset" with screenshots.

### Out of scope

- **Cluster-detail UBI rung badge.** Phase 1's FR-7 surface #3 asked for the synthetic-data chip "adjacent to the `<UbiRungBadge>`" on the cluster-detail page, but `<UbiRungBadge>` does not render there today (it needs `query_set_id + target` the page lacks). Deciding whether to surface a rung badge on `/clusters/[id]` — and the query-set/target picker that would require — is its own UX exercise that shares no design surface with the comparison view. **Split out to [`chore_cluster_detail_rung_badge`](../chore_cluster_detail_rung_badge/idea.md).** This feature's PR stays scoped to the comparison view; the Phase-1 chip stays next to the cluster **name** until that chore lands and relocates it. **Decision: locked — idea Q-1 default (standalone chore).**
- **Phase-1 dashboard studies-table "Compare ↔" affinity badge.** The idea floated a "Compare" badge on the dashboard studies table for same-query-set pairs. Deferred to keep this PR scoped to the comparison view + its two natural entry points (study-detail + value-delta). The badge would need the same paired-study discovery (FR-2) applied per-row across the whole table, which is a list-level concern, not a detail-level one. Captured as a deferred follow-on idea (`phase2_idea.md` is NOT applicable — this is single-phase; see §3 phase boundaries — instead a standalone deferral is noted in §19).
- A new comparison-specific aggregation endpoint that re-serializes both studies' digests + best-trials + curves in one payload. Rejected in favor of the thin pairing endpoint + cache reuse (idea Q-3 default).
- Comparing two LLM studies or two UBI studies, or studies on different `query_set_id`s. The pair MUST be one-LLM-one-UBI on the same `query_set_id` (FR-2 validation; `query_set_id` match IS a hard validity gate).
- Any write path, audit emission, migration, or new env var.
- **Same-cluster as a hard gate.** `query_set_id` match is the hard validity gate; same-cluster is NOT. The entry-point **discovery** helper (FR-2 `find_paired_ubi_llm_study`) restricts to same-cluster so the buttons only surface natural pairs, but a hand-supplied cross-cluster URL with matching `query_set_id` still validates (`200`) and surfaces a non-fatal `CROSS_CLUSTER` warning — it does not 422. (This keeps the validator's hard gates to exactly: both exist, both completed, same query set, one-LLM-one-UBI.)

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints. ✓ Verified at [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py). The new endpoint is `GET /api/v1/studies/compare` (a sub-path of the studies resource, query-param driven).
- **Router namespace for this feature's endpoints:** [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) — the new route is registered on the existing studies router. **Route ordering note:** `/studies/compare` MUST be declared **before** `/studies/{study_id}` in the router so FastAPI's path matcher does not capture `compare` as a `study_id` path param (see FR-1 notes + AC-8).
- **HTTP methods for CRUD:** `GET` (read-only pairing validation). No create/update/delete.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — confirmed via `_err()` at [`backend/app/api/v1/studies.py:80-84`](../../../../backend/app/api/v1/studies.py).
- **Auth error shape:** N/A — single-tenant MVP2, no auth surface.

### Phase boundaries (if multi-phase)

**Single-phase.** This feature ships the comparison view, the pairing endpoint, the discovery helper, both entry points, the four diff panels, the responsive layout, and the tutorial subsection together. There is no deferred Phase N — each piece is small and none delivers operator value alone (an endpoint with no page, or a page with no entry points, ships nothing usable). The cluster-detail rung badge and the dashboard "Compare ↔" badge are **separate features/chores** (not phases of this one) — tracked respectively in [`chore_cluster_detail_rung_badge`](../chore_cluster_detail_rung_badge/idea.md) and as a §19 deferral. No `phase2_idea.md` is created (no deferred phase exists).

## 4) Product principles and constraints

- **Read-only presentation layer.** The feature never writes a study, trial, digest, judgment, or UBI row. Every backend addition is a read path over existing data. Absolute Rule alignment: no adapter bypass, no direct engine calls, no LLM calls.
- **Cache reuse over re-serialization.** The page reuses the existing `useStudy` / `useStudyDigest` TanStack Query caches keyed `['studies', id]` and `['studies', id, 'digest']`. When the operator arrives from a study-detail page, study A's payload is already warm. The pairing endpoint returns only metadata, never duplicating the study-detail or digest serializers (idea Q-3).
- **Honest pairing — never guess.** The "Compare" entry points render ONLY when a valid pair is confirmed by FR-2 discovery. No disabled-with-tooltip affordance (idea Q-4). On clusters with no UBI, the button simply isn't there.
- **Diff via a maintained library.** Sentence-level digest diffing uses the `diff` (jsdiff) npm package's `diffSentences()`. Hand-rolled sentence splitting is forbidden (abbreviations, ellipses, code blocks are edge-case minefields). If `diffSentences` is visually too coarse, fall back to `diffWordsWithSpace` (idea Q-2). `diff-match-patch` is rejected (prose-level word noise).
- **Curve data is borrowed, not recomputed.** The convergence overlay consumes `StudyDetail.convergence.best_so_far_curve` (shipped by the sibling `feat_study_convergence_indicator`). It does NOT re-implement the best-so-far computation when that field is present. A fallback derives the curve client-side from `/studies/{id}/trials` only when `convergence` is absent (sibling unmerged at impl time).
- **Reachability over visual parity on mobile.** Narrow viewports stack study A above study B above the per-row diff annotations rather than hiding the view (idea Q-5).
- **Demo honesty preserved.** The synthetic-data chip surfaces on each study panel via the existing `isDemoSyntheticUbiClusterName(...)` gating and `<StudyHeader showSyntheticUbiChip>` — the comparison view does not invent a new disclosure surface, it reuses the Phase-1 one.

### Anti-patterns

- **Do not** build a fat comparison endpoint that re-serializes both digests + best-trials + curves — it duplicates the study-detail/digest serializers and throws away the warm TanStack Query cache. The pairing endpoint returns metadata only (idea Q-3).
- **Do not** discover the paired study by calling the studies-list endpoint with a client-side filter — that endpoint has **no `?query_set_id` filter** ([`studies.py:455`](../../../../backend/app/api/v1/studies.py)) and listing every study to filter client-side is wasteful and racy. Use the dedicated FR-2 repo helper.
- **Do not** register `/studies/compare` after `/studies/{study_id}` in the router — FastAPI matches top-down and `compare` would be swallowed as a `study_id`, returning `STUDY_NOT_FOUND`. Declare the literal path first (AC-8).
- **Do not** hand-roll sentence segmentation for the digest diff — use `diffSentences()` from `diff`.
- **Do not** re-implement the best-so-far curve when `StudyDetail.convergence` is present — consume `convergence.best_so_far_curve` (`list[{trial_number, best_so_far}]`). Only fall back to deriving from `/studies/{id}/trials` when the field is absent.
- **Do not** assume `StudyDetail` carries the judgment-list name or kind — it carries only `judgment_list_id`. Resolve LLM-vs-UBI via the judgment list's `generation_params.generation_kind` (server-side in the pairing endpoint, so the page receives a resolved `a_kind` / `b_kind`).
- **Do not** show the "Compare" button when only one study exists for the query set, or when both are the same kind, or when either is not `completed`. The pair must be exactly one-LLM-one-UBI, both completed.

## 5) Assumptions and dependencies

- **Dependency:** `feat_demo_ubi_study_comparison` Phase 1 (shipped, PR #320).
  - Why required: provides the dual (LLM)/(UBI) studies per scenario this view compares, plus `isDemoSyntheticUbiClusterName` and the chip.
  - Status: **shipped**.
  - Risk if missing: nothing to compare.
- **Dependency (soft):** `feat_study_convergence_indicator` (spec + plan Approved; **implementation not started** as of 2026-05-31).
  - Why required: ships `StudyDetail.convergence.best_so_far_curve` (`list[CurvePoint{trial_number:int, best_so_far:float}]`), the ideal data source for the convergence overlay (FR-7).
  - Status: **Approved, not implemented.** Same-branch sibling.
  - Risk if missing: FR-7 falls back to deriving the best-so-far curve client-side from `/studies/{id}/trials`. The feature still ships; the overlay is slightly more work and slightly less consistent with the single-study `<ConvergencePanel>` visual. **Soft dependency — not blocking.**
- **Dependency:** `feat_pr_metric_confidence` (shipped) — `StudyDetail.confidence: ConfidenceShape | None`.
  - Why required: FR-6 surfaces bootstrap-CI / runner-up-gap context to make the best-metric delta interpretable beyond a bare scalar.
  - Status: **shipped**.
  - Risk if missing: FR-6 degrades to a plain scalar delta (acceptable, `confidence` is already nullable).
- **Dependency:** `diff` (jsdiff) npm package — new frontend dependency.
  - Why required: `diffSentences()` for FR-4.
  - Status: not yet in `ui/package.json` (confirmed — only `recharts ~3.8.1` present). Permissive (BSD) license, no native module; passes the `license-inventory` gate.
  - Risk if missing: FR-4 has no clean diff path. Adding the dep is the first impl story.

## 6) Actors and roles

- **Primary actor:** Demo operator (anyone running `make up` locally, viewing the dual demo studies). Also any operator with real UBI + LLM studies on the same query set.
- **Role model:** N/A — single-tenant install, no auth surface (MVP2).
- **Permission boundaries:** N/A — single-tenant.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP3 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md). This feature adds **no** state-mutating endpoint or service function — the pairing endpoint is read-only and computes nothing persistent. No audit emission applies.

## 7) Functional requirements

### FR-1: Pairing endpoint — route + contract

- Requirement:
  - The system **MUST** expose `GET /api/v1/studies/compare?a={study_id}&b={study_id}` on the existing studies router ([`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py)), returning a `StudyComparePairing` payload (§8.3).
  - The route **MUST** be declared **before** the `/studies/{study_id}` route in the router module so FastAPI's top-down path matcher resolves `compare` as the literal sub-path, not as a `study_id` path parameter.
  - Both `a` and `b` query params **MUST** be required (`Query(..., min_length=1, max_length=36)`); a **missing / empty / too-long** param yields `422 VALIDATION_ERROR`. **Verified:** FastAPI `RequestValidationError`s are globally converted to the project envelope (`error_code="VALIDATION_ERROR"`) by the `validation_exception_handler` registered in [`backend/app/api/errors.py:89`](../../../../backend/app/api/errors.py) — so the missing-param 422 carries the project `detail.error_code`, not FastAPI's default validation body. A **malformed-but-length-valid** id (e.g. `abc`) is NOT 422 — like the existing `/studies/{study_id}` endpoint (which takes `study_id: str` with no UUID validation, [`studies.py:555`](../../../../backend/app/api/v1/studies.py)), it falls through to the service lookup and returns `404 STUDY_NOT_FOUND`. This matches established repo behavior; no new id-format validator is introduced.
  - The endpoint **MUST** return `200` with the pairing metadata when the pair is valid, and a `4xx` error envelope (per §7.5) when invalid.
- Notes: Read-only. No body. The page consumes this once to resolve `a_kind`/`b_kind` and validity, then fetches the two study + digest payloads via the existing hooks.

### FR-2: Pair validation + paired-study discovery

- Requirement:
  - The system **MUST** add a repo helper (in [`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py)) `find_paired_ubi_llm_study(db, study_id) -> Study | None` that returns the single counterpart study for a given study. The helper **MUST** return `None` unless the **source** study (`study_id`) itself exists AND is `status='completed'` — a still-running source study has no comparable pair, so the entry button must not show. When the source is completed, the counterpart **MUST** match: same `query_set_id`, `status='completed'`, on the **same cluster**, opposite judgment-list kind. When zero or more-than-one counterpart exists, it **MUST** return `None` (ambiguous → no entry point). This keeps `/pair` and `/compare` consistent — anything `/pair` surfaces will validate at `/compare`.
  - The system **MUST** add a service helper (in a new [`backend/app/services/study_comparison.py`](../../../../backend/app/services/study_comparison.py)) `validate_compare_pair(db, a_id, b_id) -> ComparePairing` that:
    - Resolves both studies; missing either → `404 STUDY_NOT_FOUND`.
    - Both **MUST** be `status='completed'`; otherwise `422 COMPARE_STUDY_NOT_COMPLETED`.
    - Both **MUST** share the same `query_set_id`; otherwise `422 COMPARE_QUERY_SET_MISMATCH`.
    - Resolves each study's judgment list and classifies kind via the single shared helper `classify_judgment_kind(generation_params) -> CompareKind` (see below). Exactly one **MUST** be UBI and one **MUST** be LLM; otherwise `422 COMPARE_NOT_LLM_UBI_PAIR`.
    - Returns the resolved `a_kind` / `b_kind` (`"llm"` | `"ubi"`), `query_set_id`, and a typed `warnings: list[CompareWarning]` (§8.3). The validator **MUST** emit these non-fatal warnings, computed from the two already-loaded study rows: `CROSS_CLUSTER` when `a.cluster_id != b.cluster_id`; `TARGET_MISMATCH` when `a.target != b.target`; `OBJECTIVE_MISMATCH` when the two studies' objective metric or direction differ (`a.objective.get("metric") != b.objective.get("metric")` OR `a.objective.get("direction","maximize") != b.objective.get("direction","maximize")`) — because the best-metric delta and convergence overlay assume a shared metric+direction; a same-`query_set_id` pair does NOT guarantee a shared objective outside the demo seed path. None of these change the `200` status. No warning requires loading digests/trials (all read from the `studies` rows already fetched).
  - The system **MUST** centralize kind classification in one helper `classify_judgment_kind(generation_params: dict | None) -> CompareKind` (in [`backend/app/services/study_comparison.py`](../../../../backend/app/services/study_comparison.py)) with the rule: `generation_kind == 'ubi'` → `"ubi"`; everything else (absent `generation_params`, non-dict, or any other `generation_kind`) → `"llm"`. **Verified:** the ONLY persisted `generation_kind` value is `'ubi'` — the UBI dispatcher always injects `"generation_kind": "ubi"` server-side ([`backend/app/services/agent_judgments_dispatch.py:420`](../../../../backend/app/services/agent_judgments_dispatch.py)), including for the **hybrid converter** (`converter='hybrid_ubi_llm'` is a converter choice, NOT a distinct `generation_kind` — hybrid lists still carry `generation_kind='ubi'`). This matches the existing frontend discriminator `generation_params?.generation_kind === 'ubi'` ([`ui/src/app/studies/[id]/page.tsx:211`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx)). There is **no** `'hybrid'` `generation_kind` value to handle.
- Notes: Discovery is symmetric — calling with the LLM study returns the UBI counterpart and vice-versa. The discovery helper restricts to the **same cluster** (demo data always satisfies it). The validation endpoint does NOT treat a cross-cluster pair as fatal — same-cluster is not a hard validity gate (only `query_set_id` match is). When the two studies are on different clusters, `validate_compare_pair` emits a non-fatal `CompareWarning` (code `CROSS_CLUSTER`) so a hand-edited URL is visibly odd rather than silently wrong, but still returns `200`.

### FR-3: Comparison route + page shell

- Requirement:
  - The system **MUST** add a route `/studies/compare` ([`ui/src/app/studies/compare/page.tsx`](../../../../ui/src/app/studies/compare/page.tsx)) reading `a` and `b` from `searchParams`.
  - The page **MUST** call a new `useStudyComparePairing(a, b)` hook (in [`ui/src/lib/api/studies.ts`](../../../../ui/src/lib/api/studies.ts)) hitting `GET /api/v1/studies/compare`, then `useStudy(a)`, `useStudy(b)`, `useStudyDigest(a)`, `useStudyDigest(b)` — reusing the warm cache.
  - On pairing error, the page **MUST** render a clear message keyed off the error code (e.g., "These studies aren't a comparable LLM↔UBI pair") and a link back to `/studies`.
  - The page **MUST** label each column by kind (`LLM judgments` / `UBI judgments`) and render the synthetic-data chip per panel when `isDemoSyntheticUbiClusterName(cluster.name)` is true.
  - **Column-order normalization (F9 fix):** the page **MUST NOT** rely on the URL's `a`/`b` order to decide which column is LLM vs UBI. After the pairing endpoint resolves `a_kind`/`b_kind`, the page **MUST** render the LLM-kind study in the left/A column and the UBI-kind study in the right/B column regardless of which URL param carried which. So a hand-edited/shared `?a={ubi}&b={llm}` URL still renders LLM-left / UBI-right. (The entry-point links already build canonical `a={llm}&b={ubi}`; this requirement guards shared/reversed URLs.)
- Notes: Missing `a`/`b` searchParams → render the same "invalid pair" empty state (do not crash).

### FR-4: Digest-narrative diff panel

- Requirement:
  - The system **MUST** render both studies' `digest.narrative` side-by-side with a sentence-level diff computed via `diffSentences(narrativeA, narrativeB)` from the `diff` package, surfaced in the center diff column (added sentences flagged on B, removed on A) plus a change-count summary above each block.
  - When either digest is `404 DIGEST_NOT_READY`, the panel **MUST** render a graceful "digest not available for this study" placeholder for that side rather than failing the whole page.
  - The diff utility **MUST** live in a dedicated module [`ui/src/lib/diff/narrative-diff.ts`](../../../../ui/src/lib/diff/narrative-diff.ts) wrapping `diffSentences` (so a future swap to `diffWordsWithSpace` is one file).
- Notes: idea Q-2 default — `diffSentences` first, `diffWordsWithSpace` fallback documented in the module.

### FR-5: Best-trial parameter-table diff

- Requirement:
  - The system **MUST** render a parameter table: one column per study, one row per parameter key. The primary source is `digest.recommended_config` (`DigestResponse.recommended_config: dict[str, Any]`, already on the warm digest payload) which holds the winning config.
  - The center column **MUST** flag each row as identical (=) or different (Δ) by comparing the two studies' values for that key.
  - Parameter keys present in only one study's config **MUST** be shown with an em-dash for the missing side and flagged different.
  - When a study's digest is unavailable (`404 DIGEST_NOT_READY`), the panel **MUST** fall back to the study's best trial's `params`. **The trials endpoint has NO `best_trial_id` filter** ([`backend/app/api/v1/studies.py:678-720`](../../../../backend/app/api/v1/studies.py) — only `cursor`/`limit`/`since`/`sort` where sort ∈ `primary_metric_desc`/`primary_metric_asc`/`ended_at_desc`/`ended_at_asc`); the fallback therefore fetches the trials sorted **in the objective's winning direction** (`primary_metric_desc` for `maximize`, `primary_metric_asc` for `minimize`) so the best trial appears on the first page, and selects the row whose `id === study.best_trial_id` from the returned `TrialDetail[]` (`TrialDetail.params`, [`schemas.py:858-872`](../../../../backend/app/api/v1/schemas.py)). If `best_trial_id` is still not found (e.g., budget > page limit), the panel pages forward until found or renders a "best-trial params unavailable" placeholder for that side (acceptable degradation — demo studies cap at `max_trials=12`, well under one page, so this path is exercised only by large real studies missing a digest).
- Notes: `digest.recommended_config` is the winning config the digest worker already computed; it is the canonical best-config source and avoids an extra round trip. The trials fallback exists only for the digest-missing edge case.

### FR-6: Best-metric scalar comparison

- Requirement:
  - The system **MUST** render both studies' `best_metric` and a signed delta computed over the **kind-normalized operands** (`ubi.best_metric - llm.best_metric`), NOT the raw URL `a`/`b` order — so a reversed/shared URL produces the same delta. The "better/worse" framing respects `objective.direction` (for `minimize`, a lower UBI value is the improvement).
  - The metric **label** is derived from `StudyDetail.confidence.headline.metric` when `confidence` is present (the nested `HeadlineShape` carries `metric: str`, [`backend/app/domain/study/confidence.py:141`](../../../../backend/app/domain/study/confidence.py); `ConfidenceShape.headline` at line 231). The underlying `objective["metric"]` key IS validated by the `ObjectiveMetric` `Literal` at create-study time ([`schemas.py:214`](../../../../backend/app/api/v1/schemas.py)), but the panel **SHOULD** read it via `confidence.headline.metric` (the already-projected, validated value) rather than re-reading opaque `objective` JSONB. When `confidence` is absent, the panel renders a neutral "primary metric" label.
  - When `StudyDetail.confidence` is present for a study, the panel **MUST** surface the bootstrap CI / runner-up-gap context (reusing the existing `<ConfidencePanel>` data shape or a compact variant) so the operator can judge whether the LLM-vs-UBI delta exceeds the noise band.
  - When `best_metric` is `null` for either study, the panel **MUST** render an em-dash and suppress the delta.
  - When the pairing endpoint returns an `OBJECTIVE_MISMATCH` warning, the panel **MUST** visibly qualify the delta (e.g., a "metrics differ — delta is not directly comparable" caption) rather than presenting a confident scalar delta.
- Notes: `direction` defaults to `"maximize"` when absent (`objective.get("direction", "maximize")`), matching `_summary()` at [`studies.py:165`](../../../../backend/app/api/v1/studies.py). On the demo pair the two studies share the same objective by construction (a single label suffices), but the `OBJECTIVE_MISMATCH` warning guards hand-supplied pairs that don't.

### FR-7: Convergence-curve overlay

- Requirement:
  - The system **MUST** render a two-series Recharts `<LineChart>` plotting both studies' best-so-far curves (X = `trial_number`, Y = `best_so_far`), alpha-blended/color-distinguished so divergence is visible, with a legend naming each series by kind.
  - When the top-level `StudyDetail.convergence` field is present (sibling `feat_study_convergence_indicator` shipped), the overlay **MUST** consume `convergence.best_so_far_curve` (`list[CurvePoint{trial_number: int, best_so_far: float}]`) directly — no recomputation.
  - **Disambiguation:** do NOT confuse the sibling's top-level `StudyDetail.convergence` (the best-so-far **curve**, what FR-7 needs) with the pre-existing nested `StudyDetail.confidence.convergence` ([`confidence.py:182`](../../../../backend/app/domain/study/confidence.py)) which is `{best_at_trial, total_trials, regime}` — winner-**timing** only, NO curve. FR-7 uses the former.
  - When the top-level `StudyDetail.convergence` is absent (sibling not yet merged), the overlay **MUST** derive each best-so-far curve client-side from `GET /api/v1/studies/{id}/trials`: filter `status === 'complete'` (the `TrialStatusWire` Literal is `"complete" | "failed" | "pruned"` — [`schemas.py:350`](../../../../backend/app/api/v1/schemas.py); note: trial status is `complete`, NOT `completed`) AND `is_baseline === false`, sort by `optuna_trial_number` ASC, running-max (or running-min for `minimize`) over `primary_metric`. The `TrialDetail` wire row exposes `status`, `optuna_trial_number`, `primary_metric`, `is_baseline` ([`schemas.py:858-872`](../../../../backend/app/api/v1/schemas.py)). Because `/studies/{id}/trials` is cursor-paginated (default limit 50, max 200), the fallback **MUST** page through all trials (the demo studies cap at `max_trials=12`, well under one page). This fallback **MUST** live in a dedicated util module so the derived data shape matches the borrowed `best_so_far_curve` exactly.
  - The overlay **MUST** render an empty-state ("no convergence data yet") when neither curve source is available for a study.
- Notes: Different trial budgets across the two studies is fine — both X axes are `optuna_trial_number`; series of different lengths overlay naturally. Soft-dep on `feat_study_convergence_indicator` documented in §5.

### FR-8: Study-detail entry-point button

- Requirement:
  - The system **MUST** add a "Compare with the {UBI|LLM} study" button to the study-detail page ([`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx)), placed in the header/action area.
  - The button **MUST** be rendered **only when** a valid paired study exists — discovered via a new `useStudyPair(studyId)` hook (in `ui/src/lib/api/studies.ts`) backed by `GET /api/v1/studies/{id}/pair` (FR-2's `find_paired_ubi_llm_study`).
  - **`/pair` response contract (locked, F1 fix):** the endpoint **MUST** return `200` in both the found and not-found cases, never `404` for "no counterpart". Found → `200 { "study_id": "<id>", "kind": "ubi"|"llm" }`; no counterpart → `200 { "study_id": null, "kind": null }`. `404 STUDY_NOT_FOUND` is reserved for the case where the **requested** `{id}` study itself does not exist. The UI renders the button only when `study_id !== null`.
  - The button label **MUST** name the *other* kind (if viewing an LLM study, "Compare with the UBI study"; if UBI, "Compare with the LLM study"). It links to `/studies/compare?a={llmId}&b={ubiId}` with `a` always the LLM side and `b` always the UBI side (canonical ordering, so the comparison columns are stable regardless of which detail page the operator came from). The `kind` returned by `/pair` tells the page which of `{thisId, pairedId}` is LLM vs UBI for the link construction.
- Notes: idea Q-4 — hide entirely when no pair (no disabled state). The `/pair` lookup endpoint is the discovery surface; the `/compare` endpoint is the validation surface. Two endpoints, single-purpose each (FR-1 validates a known pair; FR-8's `/pair` discovers an unknown counterpart).

### FR-9: Judgment-list value-delta entry point

- Requirement:
  - The system **MUST** add a "View matched study comparison" affordance to `<ValueDeltaCard>` (or its container on [`ui/src/app/judgments/[id]/page.tsx`](../../../../ui/src/app/judgments/%5Bid%5D/page.tsx)), rendered **only when** the UBI judgment list has a paired LLM study AND a UBI study that form a valid pair.
  - **Discovery path (locked):** the affordance **MUST** resolve the pair in two steps: (1) find the completed study whose `judgment_list_id == this list` via a new repo helper `get_completed_study_for_judgment_list(db, judgment_list_id) -> Study | None` ([`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py)), surfaced through a thin endpoint `GET /api/v1/judgment-lists/{id}/study` returning `{ "study_id": str | None }`; then (2) call FR-8's `GET /api/v1/studies/{ubiStudyId}/pair` to discover the LLM counterpart. **Ambiguity handling:** `studies.judgment_list_id` has **NO uniqueness constraint** (verified — only `optuna_study_name` is unique, [`backend/app/db/models/study.py:80`](../../../../backend/app/db/models/study.py)); multiple studies (re-runs, clones) can reuse a judgment list. The helper therefore **MUST** return `None` when 0 OR >1 completed studies reference the list (mirroring FR-2's ambiguity rule) — never an arbitrary pick. **Rationale for step (1) needing a backend lookup, not a client-side filter:** the studies-**list** response (`StudySummary`, [`schemas.py:827-844`](../../../../backend/app/api/v1/schemas.py)) does **NOT** expose `judgment_list_id` — only `StudyDetail` does — so the value-delta card cannot filter list rows client-side by judgment list. The thin `/judgment-lists/{id}/study` endpoint is the minimal addition.
  - The affordance **MUST** link to `/studies/compare?a={llmStudyId}&b={ubiStudyId}` and be hidden when either resolution step yields no result.
- Notes: This adds exactly one small read endpoint (`/judgment-lists/{id}/study`) plus reuses `/pair`. No `GET /judgment-lists/{id}/comparable-studies` aggregate endpoint is added.

### FR-10: Mobile / narrow-viewport layout

- Requirement:
  - On narrow viewports (below the Tailwind `lg` breakpoint), the page **MUST** stack study A above study B, with the per-row diff rendered as inline annotations beneath each compared element rather than in a center column.
  - The digest-narrative diff **MUST** degrade to two stacked rendered blocks each preceded by its change-count summary.
- Notes: idea Q-5 — reachability over visual parity. Two-column grid at `lg+`, single column below.

### FR-11: Tutorial guide subsection

- Requirement:
  - The system **MUST** add a "Compare LLM vs UBI on the same dataset" subsection to [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) Step 11, with screenshots of the comparison view (captured via the `guide-gen` flow or manually).
- Notes: This closes the Phase-1 deferral noted in `feat_demo_ubi_study_comparison` §3 ("Tutorial guide rewrite ... deferred to Phase 2 once the study-comparison view exists").

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/compare?a={id}&b={id}` | Validate an LLM↔UBI study pair; return resolved kinds + warnings (FR-1/FR-2) | `STUDY_NOT_FOUND` (404), `COMPARE_STUDY_NOT_COMPLETED` (422), `COMPARE_QUERY_SET_MISMATCH` (422), `COMPARE_NOT_LLM_UBI_PAIR` (422), `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/studies/{id}/pair` | Discover the single valid LLM↔UBI counterpart for a study (source must exist + be completed); `200 {study_id:null,kind:null}` when none (FR-8) | `STUDY_NOT_FOUND` (404 only when `{id}` itself missing) |
| `GET` | `/api/v1/judgment-lists/{id}/study` | Resolve the completed study for a judgment list (FR-9 step 1); `200 {study_id:null}` when none | `JUDGMENT_LIST_NOT_FOUND` (404 only when `{id}` itself missing) |

The two studies routes live on the existing studies router; `/judgment-lists/{id}/study` lives on the existing judgments router ([`backend/app/api/v1/judgments.py`](../../../../backend/app/api/v1/judgments.py)). `/studies/compare` and `/studies/{id}/pair` MUST both be registered before the generic `/studies/{study_id}` route (compare is a literal path; `{id}/pair` is more specific and FastAPI handles the `/pair` suffix fine, but list compare first regardless).

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code` inside `detail` (the project envelope).
- Status codes **MUST** be deterministic per scenario (§7.5).
- No cross-tenant concern (single-tenant).

### 8.3 Response examples

**`StudyComparePairing` schema** (new Pydantic model in [`schemas.py`](../../../../backend/app/api/v1/schemas.py)):
- `a_study_id: str`, `b_study_id: str`
- `a_kind: CompareKind`, `b_kind: CompareKind` (`Literal["llm", "ubi"]`)
- `query_set_id: str`
- `warnings: list[CompareWarning]` — each `CompareWarning` is `{ "code": CompareWarningCode, "message": str }` where `CompareWarningCode = Literal["CROSS_CLUSTER", "TARGET_MISMATCH", "OBJECTIVE_MISMATCH"]`. Warnings are computed ONLY from fields already loaded during pair validation (`cluster_id`, `target`, `objective` on the two study rows) — the endpoint stays thin and does NOT load digests or trials to compute warnings (per §4). The earlier "differing best-trial param keys count" warning idea is **dropped** (would require loading best-trial params, violating the thin-endpoint principle).

**`GET /api/v1/studies/compare` — success (`200`):**
```json
{
  "a_study_id": "0190aa...llm",
  "b_study_id": "0190bb...ubi",
  "a_kind": "llm",
  "b_kind": "ubi",
  "query_set_id": "0190qs...",
  "warnings": []
}
```

**`GET /api/v1/studies/compare` — invalid pair (`422`):**
```json
{
  "detail": {
    "error_code": "COMPARE_NOT_LLM_UBI_PAIR",
    "message": "studies must be one LLM-judged and one UBI-judged; both resolved to kind 'llm'",
    "retryable": false
  }
}
```

**`GET /api/v1/studies/compare` — missing study (`404`):**
```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 0190xx... not found",
    "retryable": false
  }
}
```

**`StudyPairResponse` schema** (new, used as `/pair`'s `response_model`): `{ study_id: str | None, kind: CompareKind | None }` — both fields are `None` together (found → both set; no counterpart → both null).

**`GET /api/v1/studies/{id}/pair` — pair found (`200`):**
```json
{ "study_id": "0190bb...ubi", "kind": "ubi" }
```

**`GET /api/v1/studies/{id}/pair` — no pair (`200`):**
```json
{ "study_id": null, "kind": null }
```

**`JudgmentListStudyResponse` schema** (new, used as `/judgment-lists/{id}/study`'s `response_model`): `{ study_id: str | None }` — the completed study whose `judgment_list_id == {id}`, or null.

**`GET /api/v1/judgment-lists/{id}/study` — found (`200`):**
```json
{ "study_id": "0190bb...ubi" }
```

There is no auth error shape (single-tenant).

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `a_kind` / `b_kind` / `kind` (response) | `llm`, `ubi` | New `CompareKind = Literal["llm", "ubi"]` in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py); derived from `judgment_lists.generation_params.generation_kind` — `== 'ubi'` → `ubi`; **everything else** (absent, non-dict, or any other value) → `llm` — per [`backend/app/db/models/judgment_list.py:78-86`](../../../../backend/app/db/models/judgment_list.py). There is no `'hybrid'` `generation_kind` (hybrid is a converter choice; the list still carries `generation_kind='ubi'`). | column kind labels + entry-button label in `ui/src/app/studies/compare/page.tsx` + `ui/src/app/studies/[id]/page.tsx` |
| Study `status` precondition (`completed`) | `completed` (the only acceptable input value; full enum: `queued`, `running`, `completed`, `cancelled`, `failed`) | `StudyStatusWire = Literal["queued","running","completed","cancelled","failed"]` at [`backend/app/api/v1/schemas.py:323`](../../../../backend/app/api/v1/schemas.py) | not user-selectable — server-side precondition only |
| `objective.direction` (delta framing) | `maximize`, `minimize` | `ObjectiveDirection` in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py); defaulted to `maximize` when absent | best-metric delta sign in `ui/src/components/studies/...` comparison panel |

| `warnings[].code` (response) | `CROSS_CLUSTER`, `TARGET_MISMATCH`, `OBJECTIVE_MISMATCH` | New `CompareWarningCode = Literal["CROSS_CLUSTER", "TARGET_MISMATCH", "OBJECTIVE_MISMATCH"]` in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | warning banner on `ui/src/app/studies/compare/page.tsx` |

`a_kind` / `b_kind` / `kind` and `warnings[].code` are response-only (the backend produces them; the frontend renders them) — no user-submitted wire value drifts here. The source-of-truth comment `// Values must match backend CompareKind` MUST sit above any frontend kind-label map, and `// Values must match backend CompareWarningCode` above any warning-code map.

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `STUDY_NOT_FOUND` | 404 | One or both study ids do not resolve (reuses existing code). |
| `COMPARE_STUDY_NOT_COMPLETED` | 422 | One or both studies are not `status='completed'` — comparison needs final metrics + digest. |
| `COMPARE_QUERY_SET_MISMATCH` | 422 | The two studies target different `query_set_id`s — not the same dataset. |
| `COMPARE_NOT_LLM_UBI_PAIR` | 422 | The two studies are not exactly one LLM-judged and one UBI-judged. |
| `JUDGMENT_LIST_NOT_FOUND` | 404 | The `{id}` in `/judgment-lists/{id}/study` does not resolve (reuses existing code). |
| `VALIDATION_ERROR` | 422 | Missing/malformed `a` or `b` query param (reuses existing code). |

## 9) Data model and state transitions

### New/changed entities

**None.** No new tables, no modified tables, no migration. The feature reads existing rows only:
- `studies` (`query_set_id`, `judgment_list_id`, `status`, `best_metric`, `best_trial_id`, `objective`, `cluster_id`).
- `judgment_lists` (`generation_params.generation_kind` for kind classification).
- `digests` (`narrative`, `parameter_importance`, `recommended_config`) via the existing digest endpoint.
- `trials` (`optuna_trial_number`, `primary_metric`, `status`, `is_baseline`) only in the FR-7 fallback path.

### Required invariants

- The pairing endpoint **MUST** be idempotent and side-effect-free (pure read).
- A valid pair is exactly one LLM + one UBI study, both `completed`, same `query_set_id`. The discovery helper returns `None` on ambiguity (0 or >1 counterpart) — the UI then hides the entry point.

### State transitions

None — read-only feature, no state owned.

### Idempotency/replay behavior

N/A — `GET` endpoints, no mutation, no events.

## 10) Security, privacy, and compliance

- **Threats:** (1) Path-param shadowing — `/studies/compare` captured as a `study_id` (mitigated by route ordering, AC-8). (2) Information disclosure via a hand-edited URL pairing two unrelated studies (mitigated — the validator rejects non-pairs with a 422; the page renders the error state, no cross-study data leaks because both are single-tenant-visible anyway). (3) A malformed `generation_params` JSONB crashing kind classification (mitigated — classification reads `generation_params.get("generation_kind")` defensively, treating absent/non-dict as LLM).
- **Controls:** Pure read path; no secrets touched; no LLM/engine/Git calls; reuses existing single-tenant-visible serializers.
- **Secrets/key handling:** None.
- **Auditability:** N/A — MVP2, no `audit_log`; read-only.
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The comparison view is reached via (a) the "Compare with the {UBI|LLM} study" button on a study-detail page header/action area, and (b) the "View matched study comparison" affordance on the UBI judgment-list value-delta card. There is no top-level sidebar entry — the view is contextual to a study/judgment-list pair. The route `/studies/compare` is shareable/linkable (query-param driven).
- **Labeling taxonomy:**
  - Page title: "Study comparison — LLM vs UBI".
  - Column headers: "LLM judgments" (left/A) and "UBI judgments" (right/B).
  - Panel headings: "Digest narrative", "Best-trial parameters", "Best metric", "Convergence".
  - Entry buttons: "Compare with the UBI study" / "Compare with the LLM study" / "View matched study comparison".
  - Diff flags: `=` (identical) / `Δ` (different); change-count summary "N sentences added, M removed".
- **Content hierarchy (top → bottom):** Study header pair (name, status, kind label, synthetic chip) → Best-metric scalar comparison (the headline answer) → Best-trial parameter diff → Digest-narrative diff → Convergence overlay. Headline answer (which path won, by how much, inside/outside the noise band) is primary and first.
- **Progressive disclosure:** The digest-narrative diff and convergence overlay may be collapsible (`<details>`) on narrow viewports; the best-metric + parameter table are always visible. The convergence panel mirrors the single-study `<ConvergencePanel>` collapse semantics where practical.
- **Relationship to existing pages:** Sits alongside the existing study-detail and judgment-list-detail pages; does not replace them. Canonical column ordering (A = LLM, B = UBI) is enforced at the entry-point link construction so the columns are stable.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Best-metric delta | "Difference in nDCG@10 between the UBI-judged and LLM-judged study on the same queries. Inside the confidence band = likely noise." | info icon | top |
| Convergence overlay | "Best metric seen so far at each trial, for both studies. Compare where each path plateaued." | info icon | top |
| `Δ` parameter flag | "These two studies' best trials chose different values for this parameter." | hover | inline |
| Synthetic-data chip | (reuses the existing Phase-1 chip copy — no new key) | hover | inline |

New glossary keys (if added) MUST follow the `short`/`long` pattern in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts). Candidate keys: `study_comparison_delta`, `study_comparison_convergence`. The `Δ` flag may reuse plain `title` text rather than a glossary key (it's self-explanatory in context) — implementer's call, but if a tooltip key is used it MUST be registered in `glossary.ts`.

### Primary flows

1. **Compare from LLM study detail.** Operator opens an LLM study detail → the page's `useStudyPair` finds the UBI counterpart → "Compare with the UBI study" button shows → click → `/studies/compare?a={llm}&b={ubi}` → pairing validates → both panels render from warm cache.
2. **Compare from UBI judgment-list value-delta card.** Operator opens a UBI judgment list → the value-delta card resolves the LLM+UBI study pair → "View matched study comparison" shows → click → same comparison view.

### Edge/error flows

- **No paired study:** entry-point buttons are absent (not disabled). Direct navigation to `/studies/compare` with a non-pair → the page renders the keyed error state + "Back to studies".
- **Digest not ready for one side:** that side's digest-narrative + parameter-from-digest panels render a "digest not available" placeholder; the rest of the comparison still renders.
- **Convergence data absent (sibling unmerged):** fallback derives curves from `/studies/{id}/trials`; if a study has `<` enough complete trials, render "no convergence data yet".
- **Both studies the same kind / different query set / not completed:** 422 with the specific code; page shows the matching message.
- **Path-param shadow:** `/studies/compare` resolves to the compare endpoint, never `STUDY_NOT_FOUND` for a study literally named "compare" (route ordering, AC-8).

## 12) Given/When/Then acceptance criteria

### AC-1: Valid pair validates
- Given an LLM study and a UBI study, both `completed`, same `query_set_id`, on the same cluster
- When `GET /api/v1/studies/compare?a={llm}&b={ubi}`
- Then `200` with `a_kind="llm"`, `b_kind="ubi"`, `query_set_id` set, `warnings=[]`.

### AC-1b: Cross-cluster pair validates with warning (not a 422)
- Given an LLM study and a UBI study, both `completed`, same `query_set_id`, but on **different** clusters
- When `GET /api/v1/studies/compare?a={llm}&b={ubi}`
- Then `200` with `warnings` containing `{ "code": "CROSS_CLUSTER", ... }` (same-cluster is not a hard gate).

### AC-1c: Differing-target pair validates with TARGET_MISMATCH warning
- Given a valid LLM↔UBI pair (same `query_set_id`, both completed) whose two studies have different `target`s
- When `GET /api/v1/studies/compare?a={llm}&b={ubi}`
- Then `200` with `warnings` containing `{ "code": "TARGET_MISMATCH", ... }`.

### AC-2: Two LLM studies rejected
- Given two LLM studies on the same query set
- When `GET /api/v1/studies/compare?a={llm1}&b={llm2}`
- Then `422` with `error_code="COMPARE_NOT_LLM_UBI_PAIR"`.

### AC-3: Different query sets rejected
- Given an LLM and a UBI study on different `query_set_id`s
- When `GET /api/v1/studies/compare?a={llm}&b={ubi}`
- Then `422` with `error_code="COMPARE_QUERY_SET_MISMATCH"`.

### AC-4: Not-completed rejected
- Given a UBI study still `running` paired with a completed LLM study
- When the compare endpoint is called
- Then `422` with `error_code="COMPARE_STUDY_NOT_COMPLETED"`.

### AC-5: Missing study
- Given a non-existent `a`
- When the compare endpoint is called
- Then `404` with `error_code="STUDY_NOT_FOUND"`.

### AC-6: Pair discovery returns counterpart
- Given an LLM study with a valid UBI counterpart
- When `GET /api/v1/studies/{llm_id}/pair`
- Then `200` with `{ "study_id": "<ubi_id>", "kind": "ubi" }`.

### AC-7: No counterpart
- Given an LLM study whose query set has no completed UBI study
- When `GET /api/v1/studies/{llm_id}/pair`
- Then `200` with `{ "study_id": null, "kind": null }`.

### AC-8: Route ordering — no path-param shadow
- Given the studies router
- When `GET /api/v1/studies/compare?a=...&b=...` is requested
- Then it resolves to the compare handler (not the `/studies/{study_id}` detail handler returning `STUDY_NOT_FOUND` for id `"compare"`).
- Example: a contract test asserts `GET /api/v1/studies/compare` without query params returns `422 VALIDATION_ERROR` (compare handler), never `404 STUDY_NOT_FOUND`.

### AC-9: Entry button hidden when no pair
- Given a study with no valid counterpart
- When the operator views its detail page
- Then no "Compare with..." button is rendered (E2E asserts the button is absent).

### AC-10: Entry button shows + navigates with canonical ordering
- Given an LLM study with a UBI counterpart
- When the operator views the LLM study detail page
- Then a "Compare with the UBI study" button is visible, and clicking it navigates to `/studies/compare?a={llm_id}&b={ubi_id}` (LLM as `a`).

### AC-11: Digest narrative diff renders sentence-level changes
- Given two completed studies with differing digest narratives
- When the comparison page renders
- Then the digest panel shows both narratives plus a per-side change-count summary derived from `diffSentences`.

### AC-12: Best-metric delta respects direction
- Given two studies with `objective.direction="minimize"` and `best_metric` A=0.40, B=0.30
- When the best-metric panel renders
- Then B is framed as the better result (lower is better) and the delta sign/labeling reflects that.

### AC-13: Convergence overlay consumes shipped curve when present
- Given both `StudyDetail` payloads carry `convergence.best_so_far_curve`
- When the convergence panel renders
- Then two line series are plotted from those curves with no client-side trials fetch.

### AC-14: Convergence overlay falls back to trials when curve absent
- Given `StudyDetail.convergence` is `null` for both studies (sibling not merged)
- When the convergence panel renders
- Then each curve is derived client-side from `/studies/{id}/trials` (complete, non-baseline, running-max/min over `primary_metric`).

### AC-15: Narrow-viewport stacked layout
- Given a viewport below the `lg` breakpoint
- When the comparison page renders
- Then study A stacks above study B with inline diff annotations (no center column), and the page remains fully reachable.

### AC-16: Parameter diff flags identical vs different
- Given two studies whose `digest.recommended_config` share key `tie_breaker` with equal values but differ on `boost`
- When the parameter-table panel renders
- Then the `tie_breaker` row is flagged `=` and the `boost` row is flagged `Δ`; a key present in only one config shows an em-dash on the missing side and a `Δ` flag.

### AC-17: Value-delta affordance visibility + navigation
- Given a UBI judgment list whose UBI study has a valid LLM counterpart
- When the operator views the judgment-list detail page
- Then a "View matched study comparison" affordance is visible and links to `/studies/compare?a={llmStudyId}&b={ubiStudyId}`.
- And given a UBI judgment list with no LLM counterpart, the affordance is absent.

### AC-18: Reversed-URL column normalization
- Given a shared URL `/studies/compare?a={ubiId}&b={llmId}` (params reversed from canonical)
- When the page renders after pairing validation
- Then the LLM study is still shown in the left/A column and the UBI study in the right/B column (column order derives from resolved kind, not URL order).

### AC-19: Tutorial subsection present
- Given the docs build
- When `docs/08_guides/tutorial-first-study.md` Step 11 is rendered
- Then it contains the "Compare LLM vs UBI on the same dataset" subsection with at least one comparison-view screenshot reference.

## 13) Non-functional requirements

- **Performance:** The pairing endpoint is two indexed PK lookups + two judgment-list lookups + (for `/pair`) one indexed query-set-scoped scan; p95 < 50ms. The page reuses warm caches; cold load fetches 2× study + 2× digest in parallel.
- **Reliability:** Read-only; no SLO impact. Errors degrade per-panel (digest-missing, curve-missing) rather than failing the whole page.
- **Operability:** No new metrics required. Standard request-id logging via existing middleware.
- **Accessibility/usability:** Diff flags carry text equivalents (`=`/`Δ` plus aria-labels); the layout is keyboard-navigable; color is not the sole diff signal (sentence add/remove also carry +/− text markers).

## 14) Test strategy requirements (spec-level)

- **Unit (`backend/tests/unit/`):** `classify_judgment_kind` from `generation_params` — `{generation_kind:'ubi'}` → `ubi`; hybrid-converter list (still `generation_kind:'ubi'`) → `ubi`; `None` / `{}` / non-dict / `{generation_kind:'something_else'}` → `llm` (a literal non-`'ubi'` value classifies as LLM, matching FR-2). `validate_compare_pair` branch coverage (each 422 code + the 404); pure best-so-far helpers if any backend math is added (none expected — curve math is frontend fallback).
- **Unit (frontend, `ui/src/__tests__/`):** `narrative-diff.ts` (`diffSentences` change counts); best-metric direction framing; the trials→best-so-far fallback derivation; kind-label map matches `CompareKind`.
- **Integration (`backend/tests/integration/`):** DB-backed `find_paired_ubi_llm_study` (returns counterpart; returns `None` on 0 / >1 / wrong-kind / not-completed); `validate_compare_pair` against real rows.
- **Contract (`backend/tests/contract/`):** `GET /api/v1/studies/compare` success + each 422/404 error code shape + the `200`-with-`warnings[].code` cases for `CROSS_CLUSTER` / `TARGET_MISMATCH` / `OBJECTIVE_MISMATCH`; `GET /api/v1/studies/{id}/pair` found + null + `404 STUDY_NOT_FOUND` for a missing source; `GET /api/v1/judgment-lists/{id}/study` found + null + `404 JUDGMENT_LIST_NOT_FOUND`; **AC-8 route-ordering assertion** (`/studies/compare` with no params → 422 `VALIDATION_ERROR`, not 404).
- **E2E (`ui/tests/e2e/`):** real-backend Playwright — seed a demo cluster with a dual LLM/UBI pair, navigate from the LLM study detail, assert the "Compare with the UBI study" button, click it, assert both columns render with the four panels; assert the button is **absent** on a study with no counterpart. No `page.route()` mocking.

## 15) Documentation update requirements

- `docs/01_architecture`: note the new `GET /studies/compare` + `GET /studies/{id}/pair` read endpoints in [`api-conventions.md`](../../../../01_architecture/api-conventions.md) or [`ui-architecture.md`](../../../../01_architecture/ui-architecture.md) (the comparison route + two-series overlay variant).
- `docs/02_product`: n/a (no new user story doc required; the tutorial subsection covers it).
- `docs/03_runbooks`: n/a (no new ops procedure).
- `docs/04_security`: n/a (read-only, no new data flow off the cluster).
- `docs/05_quality`: n/a.
- `docs/08_guides`: [`tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) Step 11 "Compare LLM vs UBI on the same dataset" subsection (FR-11).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — the entry points self-gate on pair existence, so the feature is invisible until a valid pair exists (demo data provides one).
- **Migration/backfill expectations:** None — no schema change.
- **Operational readiness gates:** Standard CI (lint, typecheck, unit/integration/contract, frontend, smoke E2E).
- **Release gate:** All AC-* green; `diff` dependency passes the `license-inventory` gate; no new TypeScript/ESLint violations.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-5, AC-8 | endpoint + route ordering | `backend/tests/contract/test_studies_compare.py` | api-conventions.md |
| FR-2 | AC-1, AC-1b, AC-1c, AC-2, AC-3, AC-4, AC-6, AC-7 | repo + service helpers + `classify_judgment_kind` | `backend/tests/unit/services/test_study_comparison.py`, `backend/tests/integration/test_study_pairing.py` | — |
| FR-3 | AC-9, AC-10, AC-11..AC-18 | route + page shell + hooks + column normalization | `ui/.../studies/compare` tests, E2E | ui-architecture.md |
| FR-4 | AC-11 | digest diff panel + `narrative-diff.ts` | `ui/src/__tests__/lib/narrative-diff.test.ts` | — |
| FR-5 | AC-16 | param-table panel | `ui/src/__tests__/.../param-diff.test.tsx` | — |
| FR-6 | AC-12 | best-metric panel | `ui/src/__tests__/.../best-metric.test.tsx` | — |
| FR-7 | AC-13, AC-14 | convergence overlay + fallback util | `ui/src/__tests__/.../convergence-overlay.test.tsx` | — |
| FR-8 | AC-6, AC-7, AC-9, AC-10 | study-detail button + `/pair` + `useStudyPair` | contract + E2E | — |
| FR-9 | AC-17 | judgment-list entry point + `GET /judgment-lists/{id}/study` + `get_completed_study_for_judgment_list` | `ui/src/__tests__/components/judgments/value-delta-card.test.tsx`, `backend/tests/contract/test_judgment_list_study.py`, E2E | — |
| FR-10 | AC-15, AC-18 | responsive layout + column normalization | E2E narrow viewport | — |
| FR-11 | AC-19 | tutorial subsection | guide screenshots | tutorial-first-study.md |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1, AC-1b, AC-1c, AC-2..AC-19) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) green.
- [ ] Documentation updates (api/ui-architecture + tutorial Step 11) merged.
- [ ] `diff` dependency added + license-inventory gate green.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

_None blocking. The two design forks below were resolved during cross-model review and are recorded in the decision log:_

- **FR-9 discovery surface** — RESOLVED: the design uses exactly **one** thin judgment-list-scoped endpoint, `GET /api/v1/judgment-lists/{id}/study` (returns the list's completed study or null), plus reuse of `GET /studies/{ubiId}/pair`. No aggregate `/comparable-studies` endpoint. (See FR-9 + §8.1.) The list-row `StudySummary` does not expose `judgment_list_id`, so the backend lookup is required rather than a client-side filter.
- **Best-trial param source** — RESOLVED: use `digest.recommended_config` (the digest worker's persisted winning config), fall back to the best trial's `params` via `/studies/{id}/trials` (no `best_trial_id` filter — select `id == best_trial_id` from the sorted page) only when the digest is absent. (See FR-5.)

### Decision log
- 2026-05-31 — Cluster-detail rung badge split to standalone `chore_cluster_detail_rung_badge` (idea Q-1). — Keeps this PR scoped to the comparison view; the badge needs its own query-set/target-picker UX exercise.
- 2026-05-31 — Diff library = `diff` (jsdiff) `diffSentences()`, fallback `diffWordsWithSpace`; reject `diff-match-patch` (idea Q-2). — Sentence-level granularity matches the digest-narrative panel without word-level noise.
- 2026-05-31 — Thin pairing endpoint, not a fat re-serialization endpoint (idea Q-3). — Reuses the warm `useStudy`/`useStudyDigest` caches; keeps the new endpoint single-purpose.
- 2026-05-31 — Entry points hidden (not disabled) when no pair (idea Q-4). — Avoids expectation friction on no-UBI clusters.
- 2026-05-31 — Narrow viewport stacks vertically (idea Q-5). — Reachability over visual parity on phones.
- 2026-05-31 — Dashboard "Compare ↔" studies-table affinity badge deferred (not a phase of this feature) — it's a list-level concern needing per-row pair discovery; kept out to scope this PR to the detail-level comparison view.
- 2026-05-31 — Single-phase; no `phase2_idea.md`. — Every piece is small and none ships value alone.
- 2026-05-31 (cross-model review, GPT-5.5 cycle 1) — `/pair` no-counterpart contract = `200 {study_id:null,kind:null}`; `404` reserved for the requested study missing (F1). — Removes an internally inconsistent null/404/200 contract.
- 2026-05-31 (GPT-5.5 cycle 1, F6) — Kind discriminator is `generation_kind == 'ubi'` ONLY; no `'hybrid'` `generation_kind` exists (hybrid is a *converter* choice, list still carries `generation_kind='ubi'`). Centralized in `classify_judgment_kind`. — Verified against `agent_judgments_dispatch.py:420` + the existing frontend discriminator.
- 2026-05-31 (GPT-5.5 cycle 1, F2/F3/F4) — Trial wire status is `complete` (not `completed`); trials endpoint has no `best_trial_id` filter; metric label read from `confidence.headline.metric`, not opaque `objective`. — Corrected against `schemas.py:350`, `studies.py:678-720`, `confidence.py:141`.
- 2026-05-31 (GPT-5.5 cycle 1, F5/F7) — `warnings` is a typed `list[CompareWarning]` computed only from already-loaded fields; same-cluster is a non-fatal `CROSS_CLUSTER` warning, not a hard 422 gate. — Keeps the endpoint thin per §4.
- 2026-05-31 (GPT-5.5 cycle 2) — FR-9 needs a real backend lookup (`GET /judgment-lists/{id}/study`), because the studies-LIST row (`StudySummary`) does NOT expose `judgment_list_id` (only `StudyDetail` does) — client-side filtering is impossible. — Removed the contradictory "MAY add endpoint" escape hatch; locked the one thin endpoint.
- 2026-05-31 (GPT-5.5 cycle 2) — Best-metric delta defined over kind-normalized operands (`ubi - llm`), not URL `a`/`b`; FR-5 fallback sorts in the objective's winning direction so the best trial lands on page 1 (fixes `minimize` studies). DoD gates AC-1..AC-19. Named `StudyPairResponse` / `JudgmentListStudyResponse` schemas added. `/pair` returns null only for a completed source with no counterpart. `TARGET_MISMATCH` warning given an FR rule + AC-1c.
- 2026-05-31 (GPT-5.5 cycle 3 — final) — Added `OBJECTIVE_MISMATCH` warning (same `query_set_id` doesn't guarantee same objective metric+direction; panel qualifies the delta when present). Narrowed FR-1: malformed-but-length-valid id → `404 STUDY_NOT_FOUND` (matches existing `/studies/{id}` `str`-typed param), only missing/empty/too-long → 422. `get_completed_study_for_judgment_list` returns None on 0 OR >1 (no uniqueness constraint on `studies.judgment_list_id` — verified). Fixed §19 wording to acknowledge the one `/judgment-lists/{id}/study` endpoint. DoD + §14 contract tests cover AC-1c, the warning payloads, and the judgment-list-study endpoint. Convergence reached at the 3-cycle ceiling; remaining items were all wording/coverage-completeness, no contract reversals.
