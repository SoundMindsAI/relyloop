# Feature Specification — Clone study from a previous study

**Date:** 2026-05-24
**Status:** Draft (pending GPT-5.5 cycle 1)
**Owners:** soundminds.ai (engineering)
**Related docs:**
- [idea.md](idea.md) — preflighted 2026-05-24
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — wizard / modal patterns
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope + cursor pagination
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — `studies` table

**Depends on (shipped):**
- [`feat_studies_ui`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/) — the create-study modal
- [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/) — `studies.parent_study_id` column
- [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/) — `CreateStudyModal` `initialValues: PrefillValues` prefill plumbing (Story 5.2)
- [`feat_auto_followup_studies`](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/) — first existing producer of `studies.parent_study_id` writes

---

## 1) Purpose

- **Problem:** A relevance engineer's iterative tuning loop after a study completes is "read digest → narrow params → re-run." Step 3 today means re-entering the cluster, target, query set, judgment list, template, search space (JSON paste), objective, and config from scratch in [`CreateStudyModal`](../../../../ui/src/components/studies/create-study-modal.tsx). ~2–5 minutes/iteration + invites JSON copy-paste errors. The umbrella spec ([`relyloop-spec.md`](../../../00_overview/relyloop-spec.md) §6) frames RelyLoop as an iterative loop; the create-study surface treats every study as green-field.

- **Outcome:** A "Clone study" button on the study-detail page opens `CreateStudyModal` pre-filled with the source study's fields (cluster, target, query set, judgment list, template, search space, objective, config). The POST carries a new optional `parent_study_id` field; the server validates it and writes it into the existing `studies.parent_study_id` column. Lineage is preserved alongside `auto_followup`'s existing writes to the same column. Manual iteration time drops to "click → tweak the one field that changed → submit."

- **Non-goal:** The "narrow bounds" smart-rewrite of cloned `search_space` is **deferred** to a separate idea folder (`feat_study_clone_narrow_bounds`) per locked D-3. This spec ships only verbatim-copy + editable-fields. No new ORM tables, no migration, no schema CHECK constraints, no audit-event emission (pre-MVP2 per [CLAUDE.md](../../../../CLAUDE.md) "Activates at MVP2"). No frontend visual diff between source and clone. No clone from the proposal-detail page or from the digest panel (per FR-1 / D-7).

---

## 2) Current state audit

### Existing implementations to extend

- **`backend/app/api/v1/schemas.py`** — `CreateStudyRequest` at [line 633](../../../../backend/app/api/v1/schemas.py#L633). Currently has `parent: ParentFollowupRef | None = None` (added by `feat_digest_executable_followups` Story 4.2 for proposal-followup lineage). Will gain optional `parent_study_id: str | None`.
- **`backend/app/api/v1/studies.py`** — `_create_study` handler starts at line 200; FK validation block (cluster, template, query set, judgment list) at lines 207–240; parent-followup validation block at lines 333–379; `repo.create_study()` call at line 386 accepts `**fields` so adding `parent_study_id=…` requires no helper signature change.
- **`backend/app/db/repo/study.py`** — `create_study(db, **fields)` at line 47 (variadic); `get_study(db, study_id)` at line 61 (used to look up the parent for validation).
- **`backend/app/db/models/study.py`** — `parent_study_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("studies.id"), nullable=True)` at lines 78–81. The model docstring (line 19) calls it "for forks (MVP2)." `auto_followup` worker already writes the column ([`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py)).
- **`ui/src/components/studies/create-study-modal.tsx`** — `CreateStudyModal` accepts `initialValues?: PrefillValues` at [line 198](../../../../ui/src/components/studies/create-study-modal.tsx#L198). `PrefillValues` is defined at lines 165–187 with a **required** `parent: { proposal_id, followup_index }` field — this spec extends the type to support study-clone lineage (see §8 "PrefillValues extension").
- **`ui/src/components/studies/study-action-bar.tsx`** — current header action bar; only renders "Cancel study". Will gain "Clone study" button alongside.
- **`ui/src/app/studies/[id]/page.tsx`** — wraps the study detail; will route the "Clone study" click to a navigation to `/studies/new?clone_from=<id>` (or to `/studies` if no dedicated `/new` route exists — see §11 routing decision below).
- **`ui/src/app/studies/page.tsx`** — currently renders `<CreateStudyModal open={createOpen} onOpenChange={setCreateOpen} />` (line 47) on the studies list. Will read the `?clone_from` query param and pass `initialValues` when present.
- **`ui/src/lib/api/studies.ts`** — `CreateStudyRequest` TS type is auto-generated from the OpenAPI schema (`components['schemas']['CreateStudyRequest']`); adding the Pydantic field surfaces the TS field automatically. `useCreateStudy` mutation hook at line 108 takes the typed payload as-is — no hook change.
- **`ui/src/app/proposals/[id]/page.tsx`** — assembles `PrefillValues` for the proposal-followup path at lines 181–215. Reference pattern for the study-detail clone handler.

### Existing tests to extend

| Test file | Purpose | Change needed |
|---|---|---|
| `backend/tests/contract/test_create_study_parent.py` | Asserts current `parent: ParentFollowupRef` wire shape | Add cases for `parent_study_id` |
| `backend/tests/contract/test_studies_api_contract.py` | CreateStudyRequest response shape + error envelope | Verify `parent_study_id` optional on request; `StudyDetail` already returns the column |
| `backend/tests/contract/test_studies_error_codes.py` | Error envelope shape per error code | Add `PARENT_STUDY_NOT_FOUND`, `PARENT_STUDY_WRONG_CLUSTER` |
| `backend/tests/integration/test_studies_api.py` | DB-backed POST flows | Add: happy-path clone; missing parent → 404; wrong-cluster parent → 422 |
| `ui/src/components/studies/__tests__/create-study-modal.test.tsx` | Vitest for the modal | Add: when `initialValues.parent_study_id` is set, the POST body carries it |
| `ui/src/app/studies/__tests__/page.test.tsx` (or new) | Studies list reading `?clone_from` | Add: with `?clone_from=X`, modal opens with prefill |
| `ui/tests/e2e/study-clone.spec.ts` (new) | Real-backend Playwright | Seed a `completed` study; click "Clone study"; assert prefill + POST → `parent_study_id` resolves on `GET /api/v1/studies/{new_id}` |

### Downstream consumers of `studies.parent_study_id` (must not regress)

- [`backend/app/db/repo/study.py:167-188`](../../../../backend/app/db/repo/study.py#L167-L188) — `list_children_of_study(db, parent_study_id)` repo helper used by `auto_followup`'s "in-flight child" detection ([`backend/workers/auto_followup.py:87`](../../../../backend/workers/auto_followup.py#L87)). Clone-spawned children will appear in this list. Verified safe: the helper is FK-equality based; no auto_followup-only filter.
- [`backend/app/services/study_state.py:285,291,299`](../../../../backend/app/services/study_state.py) — cascade-cancel logic uses `parent_study_id` to find chain children. A clone is a chain child of its parent for cancel-cascade purposes. **Coordination decision**: clones SHOULD participate in cancel-cascade chains. The cascade radio in [`study-action-bar.tsx:43-51`](../../../../ui/src/components/studies/study-action-bar.tsx#L43-L51) reads `chainChildren` for `queued`/`running` children — clones inherit the existing behavior with no additional logic (see D-6 in §19).
- [`backend/app/api/v1/schemas.py:684`](../../../../backend/app/api/v1/schemas.py#L684) — `StudyDetail.parent_study_id` already exposed; no response shape change.
- [`backend/tests/integration/test_auto_followup.py:220,425`](../../../../backend/tests/integration/test_auto_followup.py) — assertions on `parent_study_id`; not regressed (auto_followup write path is untouched).
- **Frontend reads:** `grep -rn parent_study_id ui/src/` returns zero hits today (the field is on `StudyDetail` but unused by any UI). This spec adds the first read (a "Cloned from study {name}" banner in the wizard).

### Navigation and link impact

- New optional query param `?clone_from=<study_id>` on `/studies` (the page that owns the create modal). The studies list page reads it on mount and seeds the modal.
- No new route, no nav-menu change, no breadcrumb change. The `/studies/[id]` study-detail page gains a button.

### Information architecture

- **Button placement:** in the existing [`StudyActionBar`](../../../../ui/src/components/studies/study-action-bar.tsx) component, to the left of "Cancel study". Visible regardless of status (per locked D-2; running clones get a confirmation modal).
- **Cloned-from banner:** sits above Step 1 in `CreateStudyModal` when `initialValues.cloneSource` is present (NOT `parent_study_id` — see D-12 / FR-12). One line: "Cloned from study **{cloneSource.name}** · [view source](/studies/{cloneSource.id})". Dismissable? No — the banner is informational, not gating; it disappears after submit since the modal closes. If `parent_study_id` is set but `cloneSource` is absent (synthetic / hand-constructed `initialValues`), the banner does NOT render — there is no fallback that reads from form state.
- **No new top-nav entry.**

### Tooltips and contextual help

- New glossary key: `study.clone_button` → "Open the create-study form pre-filled with this study's settings. Useful for iterating with narrowed bounds or a different objective." Story owns adding the key to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts).
- New glossary key: `study.cloned_from_banner` → "This study will be created as a fork of the linked source. The lineage is recorded for future reference."
- Tooltip pattern: existing `InfoTooltip` component (see [`backend/tests/unit/.../info-tooltip*`](../../../../ui/src/components/common/info-tooltip.tsx) for the convention). Both tooltips use the existing `<InfoTooltip glossaryKey="..." />` pattern; no new tooltip primitive.

### Enumerated value contracts

This spec adds two new error codes (`PARENT_STUDY_NOT_FOUND`, `PARENT_STUDY_WRONG_CLUSTER`) whose wire values are surfaced in the error envelope. Per [`docs/01_architecture/api-conventions.md` §"Error envelope"](../../../01_architecture/api-conventions.md) the error codes are not enumerated in a backend `frozenset` / `Literal[...]` — the contract is each error string. Both codes are tested in `backend/tests/contract/test_studies_error_codes.py` (see §14 test strategy). No new frontend `<select>`/dropdown values introduced.

---

## 3) Scope

### In scope (single phase — no phase split)

- Backend: `CreateStudyRequest.parent_study_id: str | None = None` field; `_create_study` validation (exists? same cluster?); `repo.create_study(... parent_study_id=...)` write; two new error codes.
- Frontend: "Clone study" button in `StudyActionBar`; `?clone_from=<id>` deep link on `/studies`; `PrefillValues` extension with `parent_study_id?: string`; modal `parent` field made optional; "Cloned from" banner; confirmation modal when source is `running`; vitest + Playwright coverage.
- Tests: contract (2 new error codes + 1 new field on request), integration (3 new cases on `_create_study`), vitest (modal prefill + POST body), Playwright (one real-backend e2e).
- Docs: glossary entries; brief note in [`ui-architecture.md`](../../../01_architecture/ui-architecture.md) on the `?clone_from` deep-link pattern.

### Out of scope (deferred / cross-feature)

- **"Narrow bounds" smart action** — deferred to `feat_study_clone_narrow_bounds` (per D-3). The follow-up idea folder gets created in §15 doc-update step.
  - **Update (2026-05-25):** the narrow-bounds smart action shipped via [`feat_study_clone_narrow_bounds`](../../../00_overview/planned_features/feat_study_clone_narrow_bounds/feature_spec.md). See its FR-1 through FR-14 for the implemented surface — Step-4 opt-in checkbox + reference panel; pure-frontend rewrite via the `narrowBoundsAroundWinner` helper at `ui/src/lib/narrow-bounds.ts`; gated on `cloneSource` + `useStudyDigest` success + non-empty `recommended_config`.
- **Read-only "best trial params" reference panel** in the modal — OQ-1 default = no; deferred to the narrow-bounds follow-up that owns the smart-rewrite UX.
- **Lineage telemetry event** (Langfuse / SigNoz) — OQ-2 default = no; captured as MVP2 follow-up.
- **`study.cloned` audit event** — MVP2 (audit_log table doesn't exist in MVP1).
- **Fork-tree UI** (`/studies/{id}/lineage`) — MVP2 follow-up, documented in idea relationship section.
- **Schema CHECK constraint** that `parent_study_id` and `parent_proposal_id` are mutually exclusive — per D-5, both are allowed simultaneously.
- **Clone-from-proposal-detail-page entry point** — per D-7, only the study-detail page exposes Clone. The proposal-detail page already has the "Run this followup" CTA which is the dedicated proposal→study spawn surface.
- **Clone button hidden when status=`queued` or visual differentiation per status** — per D-2, always visible; only `running` adds a confirmation step.

---

## 4) Product principles and constraints

- **Forward-only, no compat shim.** The new optional field on `CreateStudyRequest` is additive; existing clients (the studies list page POSTing without `parent_study_id`) keep working unchanged. No deprecation path.
- **Validation at the API edge.** The two new errors are 4xx, non-retryable. Per CLAUDE.md "Bug Fix Protocol" + spec discipline, the fix lives at the layer that owns the contract: API handler validates; service layer persists; UI surfaces the toast.
- **No schema migration.** The column already exists; the spec ships pure code.
- **Lineage equivalence.** A clone-spawned child must be indistinguishable from an auto_followup-spawned child for any cross-cutting concern (cancel-cascade, list-children, MVP2 fork-tree rendering). Different production sites, same DB state.

---

## 5) Assumptions and dependencies

- **Hard dependencies (shipped):**
  - `feat_studies_ui` — `CreateStudyModal` exists with `initialValues` plumbing.
  - `feat_study_lifecycle` — `studies.parent_study_id` column exists.
  - `feat_digest_executable_followups` — `PrefillValues` interface exists; `CreateStudyModal` accepts it.
- **Soft coordinations (shipped, must not regress):**
  - `feat_auto_followup_studies` — same column, identical semantics. Clone's writes must round-trip through every consumer the auto_followup path round-trips through.
- **Test infrastructure:** Playwright real-backend pattern is established (see `ui/tests/e2e/dashboard-reseed.spec.ts` from `feat_home_demo_reseed_endpoint` for the seed-via-API + assert-via-browser pattern).
- **Operator environment:** no new env vars, no new secrets, no new compose services.

---

## 6) Actors and roles

- **Relevance Engineer (primary):** clicks "Clone study" on study-detail, tweaks one or more fields in the modal, submits. Sees the new study in `/studies` list with a `parent_study_id` populated.
- **Approver / Viewer:** unaffected — no permission model change, no new entitlement, no auth surface.
- **`auto_followup` worker:** unaffected — uses the same column; no interaction.

---

## 7) Functional requirements

- **FR-1 — "Clone study" button placement.** A button labeled "Clone study" appears in [`StudyActionBar`](../../../../ui/src/components/studies/study-action-bar.tsx), positioned to the left of the existing "Cancel study" button. Visible on every study regardless of `status`. Carries `data-testid="clone-study"`.

- **FR-2 — Clone visibility on the digest panel.** The button is **NOT** added to `digest-panel.tsx`. (Locked D-7: avoid two competing iterate-from-here CTAs on one page; the proposal-detail "Run this followup" is the dedicated proposal→study flow; clone is the manual-iterate flow anchored at study-detail.)

- **FR-3 — Click handler navigates to the create-study route with deep link.** Clicking "Clone study" navigates to `/studies?clone_from=<source_study_id>` via Next.js `router.push`. The studies list page receives the param.

- **FR-4 — `?clone_from` deep-link is honored on first paint.** The read MUST happen inside [`StudiesPageInner`](../../../../ui/src/app/studies/page.tsx#L12) (already rendered under the `<Suspense>` boundary at the default export — Next 16 App Router requires `useSearchParams` consumers to be Suspense-wrapped, see [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)). The inner component **distinguishes "param absent" from "param present but empty/invalid"** via explicit presence + value normalization:

  ```typescript
  const hasCloneFrom = searchParams.has('clone_from');
  const cloneFromId = searchParams.get('clone_from')?.trim() || null;
  // Three states:
  //   !hasCloneFrom                          → normal list page, no clone behavior at all
  //   hasCloneFrom && cloneFromId === null   → invalid (empty or whitespace) → invalid-param path
  //   hasCloneFrom && cloneFromId !== null && cloneFromId.length === 36 → valid → fetch
  //   hasCloneFrom && cloneFromId !== null && cloneFromId.length !== 36 → invalid-length → invalid-param path
  ```

  The fetch is enabled only when `cloneFromId !== null` AND `cloneFromId.length === 36` (matches the UUIDv7 length contract — guards against `?clone_from=` empty-string, `?clone_from=garbage` non-UUID, and other malformed inputs that would otherwise hit `/api/v1/studies/<bad>` or the list endpoint). For valid IDs, fetch `GET /api/v1/studies/{cloneFromId}` via `useStudy(cloneFromId, { enabled: true })`; once resolved, build the prefill payload (see FR-5) and open `CreateStudyModal` with `initialValues={prefill}`. **Deep-link consumption lifecycle:** once `initialValues` has been seeded into the modal (one-shot), the page calls `router.replace('/studies')` to clear the query param so a re-render, refresh, or back-navigation does not reopen the clone modal. **All invalid / error paths** (`hasCloneFrom && invalid-format` OR 404 from the source fetch OR network error) — show a toast ("Source study {cloneFromId} not found" / "could not load source study" / "invalid clone-from id"), clear the `?clone_from` param via `router.replace('/studies')`, and open the modal empty. **`!hasCloneFrom` path is a no-op** — the page renders as the bare studies list with no toast, no fetch, no modal auto-open.

- **FR-5 — Prefill helper builds `PrefillValues` from `StudyDetail`.** A new helper `buildPrefillFromStudy(source: StudyDetail): PrefillValues` (location: `ui/src/components/studies/prefill-from-study.ts`) maps every field. Mapping rules:
  - `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id` → copied verbatim
  - `name` → `"{source.name} (clone)"`, with the **source name truncated to 200 chars** before suffix concatenation so the result fits in the 256-char `CreateStudyRequest.name` bound (mirrors the 200-char defensive truncation pattern in [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/%5Bid%5D/page.tsx) introduced by PR #225 Gemini feedback)
  - `search_space_text` → `JSON.stringify(source.search_space, null, 2)`
  - `metric`, `k`, `direction` → from `source.objective`
  - `max_trials`, `time_budget_min`, `parallelism`, `trial_timeout_s`, `sampler`, `pruner`, `seed` → from `source.config` (missing keys map to `undefined` so the form defaults stand)
  - `parent_study_id` → `source.id`
  - `parent` → `undefined` (clone path does not carry proposal-followup lineage)
  - **`cloneSource`** → `{ id: source.id, name: source.name }` — UI-only metadata, NOT included in the POST body. Powers the banner (FR-12) so the rendered "Cloned from {name}" text is stable across user edits to the prefilled `name` field and is not affected by the 200-char truncation. See §8 "PrefillValues extension" for the type declaration.

- **FR-6 — `CreateStudyModal` POST carries `parent_study_id` when prefilled with clone lineage.** When the form is submitted and `initialValues.parent_study_id` was set, the POST body includes `parent_study_id: <id>` alongside the form-derived fields. When `initialValues.parent` (proposal-followup) was set, the POST body includes `parent: {proposal_id, followup_index}` instead (the existing path, unchanged). When both are present in `initialValues` (impossible via normal UX but legal), both are sent.

- **FR-7 — `CreateStudyRequest` schema additive change.** `backend/app/api/v1/schemas.py:CreateStudyRequest` gains `parent_study_id: str | None = Field(default=None, min_length=36, max_length=36, description="...")`. The exact-length bound matches `ParentFollowupRef.proposal_id` discipline ([schemas.py:629](../../../../backend/app/api/v1/schemas.py#L629)) and forces malformed strings to surface as 422 `VALIDATION_ERROR` before the FK check.

- **FR-8 — Backend validates `parent_study_id` exists.** In `_create_study`, **immediately after cluster FK resolution (after line 210), and BEFORE template / query-set / judgment-list FK resolution**, add a parent-study resolution block. If `body.parent_study_id is not None`:
  - `parent_study = await repo.get_study(db, body.parent_study_id)`
  - If `parent_study is None`: `raise _err(404, "PARENT_STUDY_NOT_FOUND", f"parent study {body.parent_study_id} not found", False)`
  - If `parent_study.cluster_id != body.cluster_id`: `raise _err(422, "PARENT_STUDY_WRONG_CLUSTER", f"parent study {body.parent_study_id} is on cluster {parent_study.cluster_id!r}; clone target cluster is {body.cluster_id!r}", False)`

  **Placement rationale (locked D-9):** the early placement ensures clone-flow errors surface BEFORE the downstream judgment-list↔cluster check ([studies.py:255](../../../../backend/app/api/v1/studies.py#L255)), which would otherwise mask a `PARENT_STUDY_WRONG_CLUSTER` failure with a `JUDGMENT_CLUSTER_MISMATCH` error in the wrong-cluster edge case (engineer clones source A on cluster X, manually changes Step-1 cluster to Y in the modal). Cluster-axis errors should attribute to the cluster-mutation site that caused them.

- **FR-9 — Persisted parent lineage.** The `repo.create_study(...)` call in `_create_study` adds `parent_study_id=body.parent_study_id`. No other repo or service change. `StudyDetail` already returns `parent_study_id`; no response-shape edit.

- **FR-10 — `parent_study_id` is independent of `parent: ParentFollowupRef`.** Both may be set on the same request; both are persisted (`parent_study_id` writes to `studies.parent_study_id`; `parent` writes to `parent_proposal_id` + `parent_proposal_followup_index`). No mutual-exclusion check at schema or DB layer (locked D-5).

- **FR-11 — Confirmation modal for cloning a `running` study.** When the source study has `status="running"`, clicking "Clone study" first opens an `AlertDialog` with copy: "Clone an in-progress study? '{source.name}' is still running. The clone will use the current configuration but its trials are still being tuned." Buttons: "Clone anyway" (proceeds to navigate) / "Cancel". Per D-2 the confirm is shown only for `running` status — `queued`, `completed`, `failed`, `cancelled` skip straight to navigation. `data-testid="clone-running-confirm"` on the dialog; `data-testid="clone-confirm-proceed"` on the action button.

- **FR-12 — "Cloned from study {name}" banner above the wizard.** When `initialValues.cloneSource` is set, `CreateStudyModal` renders a non-dismissable banner immediately above the Step-1 content: "Cloned from study **{cloneSource.name}** · [view source](/studies/{cloneSource.id})". Tooltip key `study.cloned_from_banner`. The banner reads from the dedicated UI-only `cloneSource` metadata (FR-5), NOT from the editable `name` form value — so user edits to the prefilled name do not corrupt the banner, and 200-char source-name truncation is irrelevant to display. The banner disappears when the modal closes.

- **FR-13 — Glossary entries.** Two entries are added to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts): `study.clone_button` and `study.cloned_from_banner`. Both use the existing `InfoTooltip` consumer pattern.

- **FR-14 — Cancel-cascade chain participation.** Clones inherit auto_followup's chain semantics for cancellation. No new logic — the existing `chainChildren` query in [`study-action-bar.tsx`](../../../../ui/src/components/studies/study-action-bar.tsx#L43-L51) and the cascade handler in [`backend/app/services/study_state.py`](../../../../backend/app/services/study_state.py) discover clones via `parent_study_id` equality just as they discover auto_followup children. Verified safe: `list_children_of_study` is FK-equality based with no auto_followup-only filter.

- **FR-15 — Manual clone suppresses auto_followup auto-spawn (locked D-10).** [`backend/workers/auto_followup.py:87`](../../../../backend/workers/auto_followup.py#L87) drops a duplicate enqueue when `list_children_of_study(parent_study_id)` returns any rows ("LAYER-2 IDEMPOTENCY BACKSTOP", log event `auto_followup_enqueued_duplicate_dropped`). A manual clone is a child by that FK-equality check, so cloning a `running` study with `auto_followup_depth > 0` BEFORE the parent completes will cause the auto_followup worker to self-suppress when the parent later finishes. **This is the intended behavior:** the operator has already manually started the iteration; auto_followup standing down is correct. No new code; no filter is added. Documented here so future readers know the interaction is deliberate, not a bug. Surfaced in the runbook via the existing `auto_followup_enqueued_duplicate_dropped` log line (no new event_type needed).

---

## 8) API and data contract baseline

### Endpoint: `POST /api/v1/studies` (existing; additive fields only)

**Request body — added fields (Pydantic model `CreateStudyRequest`):**

```jsonc
{
  // ...all existing fields unchanged: name, cluster_id, target, template_id,
  //    query_set_id, judgment_list_id, search_space, objective, config, parent
  "parent_study_id": "0190d4b0-1234-7abc-9def-0123456789ab"  // NEW: optional, 36-char string
}
```

Pydantic field declaration:

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

**Response shape — unchanged.** `StudyDetail` already includes `parent_study_id: str | None` ([schemas.py:684](../../../../backend/app/api/v1/schemas.py#L684)). No response model edits.

**New error codes** (envelope per [`backend/app/api/v1/studies.py:_err`](../../../../backend/app/api/v1/studies.py#L76)):

| HTTP | `error_code` | `retryable` | Message template |
|---|---|---|---|
| 404 | `PARENT_STUDY_NOT_FOUND` | `false` | `parent study {body.parent_study_id} not found` |
| 422 | `PARENT_STUDY_WRONG_CLUSTER` | `false` | `parent study {id} is on cluster {parent.cluster_id!r}; clone target cluster is {body.cluster_id!r}` |

**Pre-existing error codes** that the clone path can also surface: `INVALID_SEARCH_SPACE` (400), `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `VALIDATION_ERROR` (422 — pydantic-derived), `JUDGMENT_CLUSTER_MISMATCH` (422), `JUDGMENT_TARGET_MISMATCH` (422), `INSUFFICIENT_JUDGMENT_OVERLAP` (422), `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400). All these continue to fire on the standard validation chain even when `parent_study_id` is set — clone does not bypass validation.

**Validation order** (in `_create_study`):

1. `SearchSpace.model_validate` (existing — line 203)
2. Cluster FK resolution (existing — line 208)
3. **Parent-study lineage validation (NEW — FR-8).** Inserted here, immediately after cluster FK and BEFORE template/query-set/judgment-list resolution. See FR-8 "Placement rationale (D-9)".
4. Template FK + search-space-vs-template validation (existing — lines 211–228)
5. Query set FK (existing — line 230)
6. Judgment list FK (existing — line 233)
7. judgment_list ↔ query_set consistency (existing — line 243)
8. judgment_list ↔ cluster consistency (existing — line 255)
9. judgment_list ↔ target consistency (existing — line 273)
10. Preflight overlap probe (existing — line 292)
11. Parent-followup lineage validation (existing — line 333)
12. Config serialization + INSERT (existing — line 381)

Order rationale: the parent-study check belongs immediately after cluster FK (so `body.cluster_id` is resolved) and before any other FK / consistency check so a wrong-cluster clone surfaces as `PARENT_STUDY_WRONG_CLUSTER` rather than as a downstream `JUDGMENT_CLUSTER_MISMATCH`. Parent-study and parent-followup remain independent axes (either block can fail without the other firing).

### TypeScript schema (auto-generated)

`ui/src/lib/api/studies.ts` imports `CreateStudyRequest` from `components['schemas']['CreateStudyRequest']` (auto-generated from the OpenAPI schema). Adding the Pydantic field surfaces `parent_study_id?: string | null` in TS automatically. No manual TS type edit.

### `PrefillValues` extension

`ui/src/components/studies/create-study-modal.tsx:PrefillValues` is widened:

```typescript
export interface PrefillValues {
  // ...all existing fields unchanged: cluster_id, target, template_id, ...
  parent?: {                  // CHANGED: now optional (was required)
    proposal_id: string;
    followup_index: number;
  };
  parent_study_id?: string;   // NEW: set by the clone path; sent on POST as request.parent_study_id
  cloneSource?: {             // NEW: UI-only metadata; NEVER serialized into the POST body
    id: string;               // matches parent_study_id when set together — but conceptually independent
    name: string;             // raw, un-truncated source name for the FR-12 banner
  };
}
```

**Why `cloneSource` is separate from `parent_study_id`:** `parent_study_id` is the wire-protocol field that flows into the POST body and the DB column. `cloneSource` is a UI-display helper that powers the banner without coupling display text to the editable `name` field. Conceptually `cloneSource.id === parent_study_id` whenever both are set, but keeping them as separate optional fields means the modal's submit serializer can mechanically ignore `cloneSource` without a special filter, and a future caller could in principle set `cloneSource` without `parent_study_id` (e.g., a "view source attribution without lineage" mode) without re-modeling the type.

**Existing callers (proposals page) must continue compiling.** [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/%5Bid%5D/page.tsx) always sets `parent` and never sets `parent_study_id`; making `parent` optional and adding `parent_study_id` is purely additive at the type level (existing callers pass a superset of the new minimum shape). Verified: no caller destructures `parent` without an `if (parent)` guard.

### `useCreateStudy` mutation

No hook change. The hook ([`ui/src/lib/api/studies.ts:108`](../../../../ui/src/lib/api/studies.ts#L108)) accepts the generated `CreateStudyRequest` type as-is; once the schema regen includes `parent_study_id`, callers can pass it.

---

## 9) Data model and state transitions

**No schema migration.** `studies.parent_study_id` already exists ([model line 78-81](../../../../backend/app/db/models/study.py#L78-L81); migration [0003 line 183](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183)). This spec adds a second producer of writes to that column.

**Per-row state after a clone POST:**

```
studies row {
  id: <new uuid7>,
  parent_study_id: <source study id>,    // ← NEW write path
  parent_proposal_id: NULL,              // (unless caller also set `parent`)
  parent_proposal_followup_index: NULL,  // (unless caller also set `parent`)
  ...all other fields copied from source via UI prefill
}
```

**State transitions:** none. No new study `status` value, no new column. The clone produces a `status='queued'` study via the existing INSERT path; the Arq enqueue at line 406 fires unchanged.

**Lineage axis coordination** (documents the three-axis matrix referenced in idea §"Coordination with existing parent fields"):

| Lineage axis | Wire field on `CreateStudyRequest` | DB column(s) | Producer |
|---|---|---|---|
| Proposal-followup | `parent: ParentFollowupRef` | `parent_proposal_id` + `parent_proposal_followup_index` | "Run this followup" on proposal-detail |
| Auto-followup | (none — direct repo write) | `parent_study_id` | `backend/workers/auto_followup.py` |
| Manual clone (this spec) | `parent_study_id: str \| None` | `parent_study_id` | "Clone study" on study-detail |

---

## 10) Security, privacy, and compliance

- **No new auth surface.** `POST /api/v1/studies` is unauthenticated in MVP1 single-tenant (per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)). Clone inherits.
- **No PII in error messages.** The two new error messages quote `parent_study_id` (a UUIDv7) and `cluster_id` (a UUIDv7 or operator-set string). No user data exposed.
- **No new secret, no new env var.**
- **Logging:** validation errors log at INFO via FastAPI's standard chain. The new error codes follow the existing `_err` pattern; no new log statements required.

---

## 11) UX flows and edge cases

### Happy path (status=`completed`)

1. Engineer is on `/studies/{id}` for a completed study.
2. Clicks "Clone study" in `StudyActionBar`.
3. Navigates to `/studies?clone_from={id}`.
4. The studies list page fetches `GET /api/v1/studies/{clone_from}`; once data is in, opens `CreateStudyModal` with `initialValues = buildPrefillFromStudy(source)`.
5. Modal opens at Step 1 with all fields populated; "Cloned from study **{source.name}**" banner is visible.
6. Engineer edits Step 4 (search space) to narrow bounds, leaves other steps untouched, clicks Submit.
7. POST body carries `parent_study_id: <source.id>`. Server validates → 201 with new `StudyDetail`.
8. Modal closes; engineer is on `/studies` showing the new row.

### Confirm path (status=`running`)

1. Engineer clicks "Clone study" on a `running` source.
2. `AlertDialog` opens: "Clone an in-progress study? ..."
3. Engineer clicks "Clone anyway" → proceeds with happy-path flow from step 3.
4. Or clicks "Cancel" → dialog closes; no navigation.

### Edge: source study deleted between page load and clone click

- Click navigates to `/studies?clone_from=<gone_id>`.
- The studies-list page's `useStudy` fetch returns 404.
- Toast: "Source study not found — opening empty create form".
- Modal opens with no prefill; engineer fills it from scratch (no error envelope surfaced to UI; just the toast).

### Edge: parent and target cluster mismatch

- Engineer clones source A (cluster X), then in the modal manually changes Step-1 cluster to Y.
- POST sends `cluster_id: Y, parent_study_id: A.id`, judgment-list also still cluster-X.
- Server FR-8 check (placed early per D-9): `parent.cluster_id (X) != body.cluster_id (Y)` → 422 `PARENT_STUDY_WRONG_CLUSTER`. Fires BEFORE the existing judgment-list↔cluster check would have produced `JUDGMENT_CLUSTER_MISMATCH`.
- Toast: error envelope `message` ("parent study {id} is on cluster ..."); modal stays open at the failed step.
- Covered by AC-7 + AC-13.

### Edge: cloning a `running` parent that would have auto-spawned a followup

- Engineer's source A is `running` with `auto_followup_depth=1`.
- Engineer clones A → B is created with `parent_study_id=A.id`.
- A completes; auto_followup worker fires.
- Worker calls `list_children_of_study(A.id)` → returns `[B]`.
- LAYER-2 IDEMPOTENCY check ([auto_followup.py:87](../../../../backend/workers/auto_followup.py#L87)) fires → logs `auto_followup_enqueued_duplicate_dropped` → returns. No auto-spawn.
- Documented behavior (FR-15 / D-10). Operator's manual clone takes precedence over auto-followup.
- Covered by AC-12 + integration test (g).

### Edge: clone of a clone

- Source itself has `parent_study_id: X`. Cloning produces a new row with `parent_study_id: <source.id>`. The new row does NOT inherit `source.parent_study_id` — each clone link is one hop. (The future MVP2 fork-tree view walks the chain.)

### Edge: clone of a study spawned from a proposal followup

- Source has `parent_proposal_id: P, parent_proposal_followup_index: i`. The cloned row has `parent_study_id: <source.id>` and `parent_proposal_id: NULL` (the prefill helper sets only the study lineage; the modal doesn't carry the source's proposal lineage forward — that's a one-time lineage event, not a transitive property).

### Edge: malformed `?clone_from` query param (not a UUIDv7, including empty string)

- Per FR-4, the page normalizes the param with `searchParams.get('clone_from')?.trim() || null` and the `useStudy` fetch is enabled only when the value is non-null AND length===36 (UUIDv7 contract). This rejects all of:
  - `/studies?clone_from=` → `''` → `|| null` → `null` → fetch disabled → toast + clear + open empty
  - `/studies?clone_from=garbage` (length ≠ 36) → fetch disabled → toast + clear + open empty
  - `/studies?clone_from=<valid-length-but-deleted-id>` → fetch fires → server returns 404 via existing `STUDY_NOT_FOUND` handler at [studies.py:511](../../../../backend/app/api/v1/studies.py#L511) → toast + clear + open empty
- All three paths converge on the same UX: toast + clear `?clone_from` + open empty modal. Covered by AC-17.

### Edge: cloning while a chain-cancel is in flight

- Source is `running` with auto_followup children. Engineer clicks "Clone study" → confirm dialog → proceed.
- POST creates the new study; it's `parent_study_id == source.id`.
- If the parent is then cancelled with cascade=true, the new clone is in the chain and gets cancelled too. Documented behavior (per FR-14); covered by existing cascade integration tests.

---

## 12) Given/When/Then acceptance criteria

- **AC-1 (FR-1, FR-3):** GIVEN a `completed` source study at `/studies/{id}`, WHEN the engineer clicks the "Clone study" button, THEN the browser navigates to `/studies?clone_from={id}` AND no confirmation dialog appears.

- **AC-2 (FR-11):** GIVEN a `running` source study, WHEN the engineer clicks "Clone study", THEN an `AlertDialog` with `data-testid="clone-running-confirm"` appears AND no navigation occurs until the engineer clicks "Clone anyway" (which navigates) or "Cancel" (which dismisses without navigation).

- **AC-3 (FR-4, FR-5):** GIVEN navigation to `/studies?clone_from=X` where X is a valid completed study id, WHEN the page loads, THEN `CreateStudyModal` opens with `initialValues.parent_study_id == X` AND every form field (cluster, target, query set, judgment list, template, search space text, objective metric/k/direction, config max_trials/time_budget_min/parallelism/trial_timeout_s/sampler/pruner/seed) matches the source study's value AND the name field shows `"{source.name} (clone)"` (truncated to ≤256 chars).

- **AC-4 (FR-12):** GIVEN the modal is open in clone mode, WHEN the engineer is on any step, THEN a banner with text containing "Cloned from study {source.name}" is visible above the wizard content AND the source name is hyperlinked to `/studies/{source.id}`.

- **AC-5 (FR-6, FR-9):** GIVEN the modal is open in clone mode, WHEN the engineer submits the form (no edits), THEN the POST body includes `parent_study_id: X` AND on 201, `GET /api/v1/studies/{new_id}` returns `parent_study_id: X`.

- **AC-6 (FR-7, FR-8 — missing parent):** GIVEN a POST to `/api/v1/studies` with `parent_study_id: <nonexistent_uuid>`, WHEN the server processes the request, THEN the response is `404 {"detail": {"error_code": "PARENT_STUDY_NOT_FOUND", "message": "parent study <id> not found", "retryable": false}}`.

- **AC-7 (FR-8 — wrong cluster):** GIVEN a POST with `parent_study_id: A.id` and `cluster_id: Y` where source A is on cluster X (X ≠ Y), WHEN the server processes the request, THEN the response is `422 {"detail": {"error_code": "PARENT_STUDY_WRONG_CLUSTER", "message": "parent study <A.id> is on cluster 'X'; clone target cluster is 'Y'", "retryable": false}}`.

- **AC-8 (FR-7 — malformed length):** GIVEN a POST with `parent_study_id: "short"` (length < 36), WHEN the server processes the request, THEN the response is `422 {"detail": {"error_code": "VALIDATION_ERROR", ...}}` from the Pydantic validator (NOT `PARENT_STUDY_NOT_FOUND` — the length check fires first).

- **AC-9 (FR-2):** GIVEN the study-detail page is rendered for any study, WHEN the engineer inspects `digest-panel.tsx`, THEN no "Clone study" button or `data-testid="clone-study"` element exists inside the digest panel DOM.

- **AC-10 (FR-10):** GIVEN a POST with both `parent_study_id: A.id` AND `parent: {proposal_id: P.id, followup_index: 0}` set (and all validations pass), WHEN the server processes the request, THEN the created study row has BOTH `parent_study_id == A.id` AND `parent_proposal_id == P.id` AND `parent_proposal_followup_index == 0`.

- **AC-11 (FR-14):** GIVEN a `running` source study has an in-flight clone child (created via `POST /api/v1/studies` with `parent_study_id`), WHEN the engineer cancels the source with `cascade: true`, THEN the existing cascade logic in [`study_state.py`](../../../../backend/app/services/study_state.py) finds the clone via `list_children_of_study(parent_study_id=source.id)` AND transitions both the source and the clone to `cancelled`. Backed by a new integration test (§14 row "f") that exercises the create→clone→cancel sequence via the API path, not just by direct DB seed.

- **AC-12 (FR-15 / D-10 — auto_followup suppression):** GIVEN a `running` source A with `config.auto_followup_depth = 1` AND a clone B created via `POST /api/v1/studies` with `parent_study_id = A.id`, WHEN A transitions to `completed` AND the `auto_followup` worker is invoked on A, THEN the worker logs `event_type=auto_followup_enqueued_duplicate_dropped` with `existing_child_ids=[B.id]` AND no additional child is created. Backed by a new integration test (§14 row "g").

- **AC-13 (D-9 — validation ordering):** GIVEN a POST with `cluster_id: Y`, `parent_study_id: A.id` (where source A is on cluster X), AND a `judgment_list_id` whose `cluster_id` is X (so judgment-list↔cluster would mismatch too), WHEN the server processes the request, THEN the response is `422 PARENT_STUDY_WRONG_CLUSTER` — NOT `422 JUDGMENT_CLUSTER_MISMATCH`. Backed by §14 integration test row "e".

- **AC-14 (D-11 — deep-link consumption):** GIVEN navigation to `/studies?clone_from=X`, WHEN the source fetch resolves AND the modal opens with `initialValues`, THEN the browser URL is rewritten via `router.replace` to `/studies` (no `?clone_from`) so refresh / back-navigation does not reopen the clone modal. Same behavior on the source-fetch-error path (param is cleared regardless of outcome).

- **AC-15 (D-12 — banner sourced from `cloneSource`):** GIVEN the modal is open in clone mode AND the engineer edits the prefilled `name` field (e.g., deletes the `" (clone)"` suffix or rewrites it entirely), WHEN the engineer inspects the banner, THEN the banner still reads the original source name from `initialValues.cloneSource.name` — unaffected by the form-state edit.

- **AC-16 (D-12 / serializer hygiene — `cloneSource` does NOT leak into POST):** GIVEN the modal is open in clone mode AND the engineer clicks Submit, WHEN the network request is inspected, THEN the POST body to `/api/v1/studies` includes `parent_study_id` AND DOES NOT include a `cloneSource` key. Backed by §14 vitest case (a) request-body assertion.

- **AC-17 (FR-4 — empty / garbage `?clone_from` is rejected client-side):** GIVEN navigation to `/studies?clone_from=` (empty), `/studies?clone_from=garbage` (non-UUID), or `/studies?clone_from={short}` (length ≠ 36), WHEN the page loads, THEN NO source-study fetch is issued (the `enabled` gate fails on length-36 check), a toast surfaces explaining the bad input, the `?clone_from` param is cleared via `router.replace('/studies')`, AND the modal opens empty. Covered by vitest test in `studies/__tests__/page.test.tsx`.

---

## 13) Non-functional requirements

- **Latency:** the new parent-study FK check adds one indexed SELECT to the create path; negligible (<5ms p95 against local Postgres). Total create_study latency budget unchanged.
- **Type safety:** UI uses the auto-generated `CreateStudyRequest` type from the OpenAPI schema; manual TS-side drift is impossible by construction.
- **Backwards compatibility:** the new request field is optional with default `None`; existing POST clients (the bare "New study" button, the proposals-page "Run this followup" path, any operator-side curl scripts) are unchanged.
- **Idempotency:** POST `/api/v1/studies` is not idempotent today (no `Idempotency-Key`); clone inherits. Double-click risk on the Clone button is mitigated by the `submitting` flag in `CreateStudyModal` (existing).

---

## 14) Test strategy requirements (spec-level)

**Required new tests:**

| Layer | File | Cases |
|---|---|---|
| Contract | `backend/tests/contract/test_create_study_parent.py` | (a) request body accepts optional `parent_study_id: str \| null`; (b) request body rejects `parent_study_id` with length < 36 or > 36 (Pydantic VALIDATION_ERROR) |
| Contract | `backend/tests/contract/test_studies_error_codes.py` | (a) `PARENT_STUDY_NOT_FOUND` envelope shape; (b) `PARENT_STUDY_WRONG_CLUSTER` envelope shape |
| Integration | `backend/tests/integration/test_studies_api.py` | (a) happy clone: POST with valid `parent_study_id` → 201 + `GET` returns `parent_study_id`; (b) missing parent → 404 `PARENT_STUDY_NOT_FOUND`; (c) wrong-cluster parent → 422 `PARENT_STUDY_WRONG_CLUSTER`; (d) both `parent_study_id` and `parent: ParentFollowupRef` set → 201 + both DB columns populated (FR-10 round-trip); (e) **validation order** — POST with `parent_study_id` pointing at cluster-X source AND `cluster_id=Y` AND a judgment-list-on-X attached → first error is `PARENT_STUDY_WRONG_CLUSTER` (NOT `JUDGMENT_CLUSTER_MISMATCH`), proving FR-8's early placement; (f) **cascade-of-clone via API** — create parent A via POST; create clone B via POST with `parent_study_id=A.id`; cancel A with `cascade=true`; assert both A and B end in `cancelled` status (proves FR-14 via the new write path); (g) **auto_followup self-suppression** — create A with `auto_followup_depth=1`, status=`running`; create clone B via POST with `parent_study_id=A.id`; transition A to `completed`; run the auto_followup worker on A; assert log event `auto_followup_enqueued_duplicate_dropped` fires AND no new child is created (proves FR-15 / D-10). |
| Vitest | `ui/src/components/studies/__tests__/prefill-from-study.test.ts` (new) | Pure-function unit tests for `buildPrefillFromStudy`: every field mapped, name suffix + truncation, undefined-config-keys handling |
| Vitest | `ui/src/components/studies/__tests__/create-study-modal.test.tsx` (extend existing) | (a) `initialValues.parent_study_id` set → POST body includes `parent_study_id` AND **excludes `cloneSource`** (regression guard against the banner-metadata leaking into the wire payload — Pydantic v2 would silently drop it server-side, masking the bug; verified at the request-body assertion level); (b) banner renders when `initialValues.cloneSource` is present; (c) banner absent when `cloneSource` is absent — including the synthetic case where `parent_study_id` is present but `cloneSource` is not (no form-state fallback); (d) modal still works when neither `parent` nor `parent_study_id` nor `cloneSource` is set (regression on existing "New study" flow); (e) **payload serializer shape:** the create-study POST body is constructed from `initialValues` via explicit field selection (destructure-and-omit-cloneSource OR field-by-field assembly) — not via spread of `initialValues` into the request — so future `PrefillValues` additions don't accidentally pass through to the wire. |
| Vitest | `ui/src/components/studies/__tests__/study-action-bar.test.tsx` (extend existing or new) | (a) Clone button renders for every `status`; (b) Clone click on `completed` source navigates without dialog; (c) Clone click on `running` source opens dialog; dialog's "Clone anyway" navigates; "Cancel" dismisses |
| E2E (Playwright, real backend) | `ui/tests/e2e/study-clone.spec.ts` (new) | (1) Seed a `completed` study via the existing test-only endpoint `POST /_test/studies/seed-completed` (used by [`scripts/seed_meaningful_demos.py:672-684`](../../../../scripts/seed_meaningful_demos.py#L672-L684) to bootstrap the demo's completed-study scenario). The same `request` fixture pattern as [`ui/tests/e2e/dashboard-reseed.spec.ts`](../../../../ui/tests/e2e/dashboard-reseed.spec.ts) governs setup-vs-assertion split (setup via `request`, all user-facing assertions via `page`). (2) Navigate to `/studies/{id}`. (3) Click "Clone study". (4) Assert **stable outcomes only** (avoid asserting on the transient `?clone_from=` URL — with a fast real backend the replace can fire before Playwright observes the intermediate state, producing flake; the intermediate navigation is covered deterministically at the vitest layer for `study-action-bar`): final URL is `/studies` (no `?clone_from=`), modal is open with banner visible and source name shown, every form field matches source. (5) Submit. (6) Assert success toast; navigate to the new study's `/studies/{new_id}`. (7) Assert response body of `GET /api/v1/studies/{new_id}` has `parent_study_id == source.id`. **No `page.route()` mocking** — must use real backend per [CLAUDE.md "E2E Testing Rules"](../../../../CLAUDE.md). |

**Coverage:** 80% backend gate per CLAUDE.md; the contract + integration cases above are sufficient for the new code paths.

**Existing tests to verify pass unchanged:**

- `backend/tests/integration/test_auto_followup.py` — auto_followup write path unaffected.
- `backend/tests/integration/test_studies_with_parent_followup.py` — proposal-followup path unaffected.
- `backend/tests/integration/test_studies_parent_proposal_check.py` + `..._on_delete.py` — proposal-FK constraint logic unaffected.
- `backend/tests/integration/test_study_cancel.py` — cascade behavior unaffected (FR-14).
- `ui/tests/e2e/study-clone-from-proposal-followup.spec.ts` (or whatever the executable-followups e2e is named) — proposal-followup flow unaffected.

---

## 15) Documentation update requirements

- **`docs/01_architecture/ui-architecture.md`** — add a brief paragraph in the wizard/modal section noting the `?clone_from=<id>` deep-link pattern. Location: under the existing `CreateStudyModal.initialValues` section.
- **`ui/src/lib/glossary.ts`** — add `study.clone_button` + `study.cloned_from_banner` entries (per FR-13).
- **`docs/00_overview/planned_features/feat_study_clone_narrow_bounds/idea.md`** — new file. Drafts the deferred "narrow bounds smart action" follow-up (per D-3, OQ-1). Captured here so the deferral is durable, not lost in conversation.
- **No CLAUDE.md update** — no new rule, no new convention.
- **No state.md update during spec phase** — `state.md` will be updated by `/impl-execute` finalization, not by spec-gen.
- **No runbook update** — no new operational concern.

---

## 16) Rollout and migration readiness

- **Migration:** none. The column already exists. No DDL; no Alembic round-trip required.
- **Backwards compat:** new request field is optional. Old POST clients (no `parent_study_id`) keep working unchanged because the field defaults to `None`.
- **Feature flag:** none. Simple additive UX feature; no toggle gate needed.
- **Deploy order:** **backend-first or simultaneous; frontend-first is unsafe.** Pydantic v2's default behavior is to drop unknown fields silently — a frontend deploy that includes `parent_study_id` against an older backend without the field would create studies WITHOUT lineage, with no error surfaced. RelyLoop's CI deploys backend + frontend together from a single PR, so simultaneous deploy is the default; an explicit guard or version check is not required, but the rollout order must NOT be reversed in any future hotfix scenario.
- **Rollback:** revert the PR. No data state to clean up (the column existed before this spec; the only effect of rollback is that previously-cloned studies retain their `parent_study_id` value, which is harmless and indistinguishable from auto_followup-spawned rows). A partial rollback (frontend without backend) would create the silent-drop scenario from "Deploy order" — do not perform.

---

## 17) Traceability matrix

| FR | Tests | Code locations |
|---|---|---|
| FR-1 (Clone button placement) | Vitest study-action-bar.test.tsx (a); Playwright study-clone.spec.ts (3) | `ui/src/components/studies/study-action-bar.tsx` |
| FR-2 (No clone on digest panel) | AC-9 vitest | `ui/src/components/studies/digest-panel.tsx` (verified unchanged) |
| FR-3 (Navigate to `?clone_from`) | Vitest study-action-bar.test.tsx (b,c); Playwright (4) | `ui/src/components/studies/study-action-bar.tsx` |
| FR-4 (Deep link honored) | Playwright (5); Vitest studies/page.test.tsx | `ui/src/app/studies/page.tsx` |
| FR-5 (Prefill helper) | Vitest prefill-from-study.test.ts | `ui/src/components/studies/prefill-from-study.ts` (new) |
| FR-6 (POST carries `parent_study_id`) | Vitest create-study-modal.test.tsx (a); Integration (a) | `ui/src/components/studies/create-study-modal.tsx` |
| FR-7 (Pydantic field) | Contract test_create_study_parent.py | `backend/app/api/v1/schemas.py:CreateStudyRequest` |
| FR-8 (Validation) | Integration (b,c); Contract test_studies_error_codes.py | `backend/app/api/v1/studies.py:_create_study` |
| FR-9 (Persist) | Integration (a); Playwright (8) | `backend/app/api/v1/studies.py:_create_study` (repo call) |
| FR-10 (Independent of `parent`) | Integration (d) | `backend/app/api/v1/studies.py:_create_study` (no exclusion check) |
| FR-11 (Running confirm) | Vitest study-action-bar.test.tsx (c); AC-2 | `ui/src/components/studies/study-action-bar.tsx` |
| FR-12 (Banner) | Vitest create-study-modal.test.tsx (b,c); AC-4 | `ui/src/components/studies/create-study-modal.tsx` |
| FR-13 (Glossary) | (covered by tooltip rendering tests) | `ui/src/lib/glossary.ts` |
| FR-14 (Cascade participation) | AC-11 + integration test (f) in `test_studies_api.py` (create→clone→cascade-cancel via API) | `backend/app/services/study_state.py` (verified unchanged) |
| FR-15 (auto_followup suppression) | AC-12 + integration test (g) in `test_studies_api.py` (clone before parent completes; assert log + no-spawn) | `backend/workers/auto_followup.py` (verified unchanged — behavior emerges from existing LAYER-2 check) |

---

## 18) Definition of feature done

- All 15 FRs (FR-1 through FR-15) implemented and all 17 AC scenarios (AC-1 through AC-17) pass.
- New backend tests (contract + integration) green.
- New frontend tests (vitest + Playwright) green.
- `make test` (unit + integration + contract) green; `make lint` + `make typecheck` clean.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` clean.
- 80% backend coverage gate green.
- PR opened against `main`; CI green; Gemini Code Assist findings adjudicated; one cross-model review pass clean.
- Glossary entries added; `ui-architecture.md` paragraph added; `feat_study_clone_narrow_bounds/idea.md` drafted as follow-up.
- Feature folder moved to `docs/00_overview/implemented_features/YYYY_MM_DD_feat_study_clone_from_previous/` after PR merge; `state.md` updated.

---

## 19) Open questions and decision log

### Locked decisions

- **D-1 (wire shape):** `parent_study_id` is a separate top-level optional field on `CreateStudyRequest`, not a reshape of `parent: ParentFollowupRef`. Rationale: orthogonal lineage axes; ParentFollowupRef is a 2-field tuple that doesn't unify cleanly with a 1-field study reference; reshaping the proposal-followup wire shape requires a coordinated frontend rewrite for zero benefit. (From idea preflight; reaffirmed here.)

- **D-2 (cloning a `running` study):** allowed, with `AlertDialog` confirmation. Hiding the button on `running` would force the operator to wait or back-cancel just to start a follow-up, defeating the iteration-speed gain. (From idea preflight.)

- **D-3 ("narrow bounds" smart action):** split to a separate follow-up idea (`feat_study_clone_narrow_bounds`). Clone v1 ships only verbatim-copy + editable-fields. (From idea preflight.)

- **D-4 (template edited/deleted after source study completed):** clone the search_space as-is. Existing FK validation catches deleted template; runtime-drift on an edited-but-existing template is the same surface non-cloned studies have today. No new wizard validation introduced. (From idea preflight.)

- **D-5 (mutual exclusion with `parent: ParentFollowupRef`):** not enforced at schema or DB layer. Both signals can coexist; both columns get populated. Frontend sets one in practice but server is permissive. (From idea preflight.)

- **D-6 (cancel-cascade participation):** clones inherit auto_followup's chain semantics with no new code. `list_children_of_study(parent_study_id)` discovers clones because the FK column is the same. Captured here because the locking happens at spec time even though no new code is required. (From spec-gen Pass 2 — invariant write-path audit.)

- **D-7 (entry-point scope):** Clone is exposed ONLY on the study-detail page (header action bar). NOT on the digest panel ("Suggested follow-ups" is the LLM-prescribed proposal-followup CTA's sibling space; adding Clone there creates two competing iterate-from-here CTAs in one place). NOT on the proposal-detail page ("Run this followup" already covers that path; clone-from-proposal would be redundant). (From idea preflight + spec-gen IA review.)

- **D-8 (auto-generated TS type for `parent_study_id`):** rely on the OpenAPI codegen pipeline; do NOT hand-write the field in TS. Matches all existing `CreateStudyRequest` field additions across the repo (e.g., `parent: ParentFollowupRef` from `feat_digest_executable_followups`). (From spec-gen Pass 1.)

- **D-9 (parent-study validation placement):** the FR-8 check fires immediately after cluster FK resolution and BEFORE the template / query-set / judgment-list FK resolution and the downstream judgment-list↔cluster consistency check. Rationale: in the wrong-cluster edge case (engineer clones source A on cluster X and manually changes Step-1 cluster to Y in the modal), the existing `JUDGMENT_CLUSTER_MISMATCH` check at [studies.py:255](../../../../backend/app/api/v1/studies.py#L255) would otherwise mask `PARENT_STUDY_WRONG_CLUSTER` with a less informative error. Cluster-axis errors should attribute to the cluster-mutation site that triggered them. (From GPT-5.5 cycle 1 finding A1; accepted.)

- **D-10 (manual clone suppresses auto_followup):** when a user clones a `running` study that has `auto_followup_depth > 0`, the auto_followup worker's LAYER-2 IDEMPOTENCY check at [`auto_followup.py:87`](../../../../backend/workers/auto_followup.py#L87) treats the clone as an existing child (FK-equality on `parent_study_id`) and self-suppresses with `auto_followup_enqueued_duplicate_dropped`. This is the intended behavior — the operator has manually initiated the followup; the worker standing down is correct. NOT a bug; NO discriminator column added; NO filter introduced. Documented as FR-15 and covered by integration test (g) in §14. (From GPT-5.5 cycle 1 finding B3; accepted with intended-behavior framing.)

- **D-11 (`?clone_from` deep-link consumption lifecycle):** the studies page calls `router.replace('/studies')` to clear the query param once `initialValues` has been seeded into the modal (one-shot). This prevents re-renders, refreshes, and back-navigation from reopening the modal. Both the success path and the source-fetch-error path clear the param. (From GPT-5.5 cycle 1 finding B4; accepted.)

- **D-12 (`cloneSource` UI-only metadata):** `PrefillValues` carries a new `cloneSource?: { id: string; name: string }` field for the banner display. UI-only — never serialized into the POST body. Separating display data from the editable `name` form value protects the banner from user edits and from the 200-char source-name truncation. (From GPT-5.5 cycle 1 finding B5; accepted.)

### Open questions (recommended defaults included; final answers due before plan-gen)

- **OQ-1 (read-only best-trial reference panel):** Should the modal show the source's best-trial params anywhere as a read-only reference? **Recommended: no for v1.** Deferred to `feat_study_clone_narrow_bounds` follow-up. (From idea preflight.)

- **OQ-2 (lineage telemetry event):** Should `POST /api/v1/studies` emit a structured event distinguishing clone / followup / organic / auto creation? **Recommended: no for MVP1.** Capture as an MVP2 follow-up alongside the audit_log work. (From idea preflight.)

- **OQ-3 (clone name suffix):** the spec uses `"{source.name} (clone)"`. Alternatives considered: `"{source.name} v2"`, `"{source.name} — followup"`, `"clone of {source.name}"`. **Recommended: `(clone)`** — explicit, sortable alongside the source in name-ordered lists, and the only variant that doesn't pretend to know what the engineer is iterating *toward*. (From spec-gen UX review.)

- **OQ-4 (running-source confirmation copy):** the spec proposes "Clone an in-progress study? '{source.name}' is still running. The clone will use the current configuration but its trials are still being tuned." **Recommended: ship as-drafted**; if operator feedback complains during dogfood, iterate post-merge. (From spec-gen UX review.)
