# Dropdown primitive + cross-app form-select discipline

**Date:** 2026-05-17
**Status:** Idea — identified during tutorial UX debugging session 2026-05-17.
**Origin:** Operator hit the "type a cluster UUID" form field in [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) while following the [first-study tutorial](../../../08_guides/tutorial-first-study.md) Step 5. Cluster-id text input is the only UUID-paste survivor — every other FK in the UI already uses a `<Select>`. The asymmetry surfaces the absence of a primitive: each `<Select>` is hand-rolled, and the enum/FK source-of-truth discipline that `feat_data_table_primitive` baked into column-configs (per [CLAUDE.md "Enumerated Value Contract Discipline"](../../../../CLAUDE.md)) does not apply to form-level dropdowns.
**Depends on:** None. [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/) (PR #126, merged 2026-05-16) established the pattern this idea generalizes.

## Problem

The DataTable primitive shipped with a lint-enforced source-of-truth discipline — every enum filter cites a backend `Literal[...]` and every FK filter cites a `useX()` hook. Forms didn't get the same treatment, and three concrete consequences are now visible:

1. **One UUID-paste field still ships** at [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) — `<Input placeholder="UUIDv7 of the registered cluster" />`. The tutorial's curl example even uses a `<local-es-id>` placeholder that operators copy-paste literally, leading to a delayed `CLUSTER_NOT_FOUND` and a confusing `QUERY_SET_NOT_FOUND` on the next call. (Documented this session — see chat transcript 2026-05-17.)

2. **FK selects are duplicated, not shared.** Six form components hand-roll the "load entities, render `<Select>`" pattern: [`create-study-modal.tsx:246-340`](../../../../ui/src/components/studies/create-study-modal.tsx) (4 FKs: cluster, query-set, judgment-list, template), [`register-cluster-modal.tsx:218`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) (repo), [`generate-judgments-dialog.tsx:122`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) (template). The closest primitive — [`data-table-fk-select.tsx`](../../../../ui/src/components/common/data-table-fk-select.tsx) — is column-config-coupled and not reusable in forms.

3. **Enum dropdowns drift silently.** Hardcoded `<SelectItem>` blocks for engine type, environment, auth type, metric, k, direction, sampler, pruner, rating, etc. None carry a `sourceOfTruth` comment or `wireValues` import from `@/lib/enums`. The DataTable lint guard at [`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) only scans `*.column-config.{ts,tsx}` — form components are unguarded. A copy-paste from an out-of-date enum array would 422 at the backend with no CI signal.

## Proposed capabilities

### 1. `<EntitySelect>` primitive

A form-friendly peer of `DataTableFkSelect` living at `ui/src/components/common/entity-select.tsx`. Props:

- `useEntities: () => { data: { data: T[] } | undefined, isLoading, isError }` — the TanStack Query hook (e.g., `useClusters({ limit: 200 })`). Must match the existing `apiClient` paginated-list shape.
- `value: string | undefined` + `onChange(id: string | undefined): void` — controlled.
- `getId(entity: T): string` + `getLabel(entity: T): string` — required.
- `getStatus?(entity: T): 'green' | 'yellow' | 'red' | 'unknown'` — optional; when provided, renders a `●` indicator before the label and sorts green-first.
- `emptyState?: { message: string; href?: string; cta?: string }` — rendered when `data.data.length === 0` (e.g., "No clusters registered" with link to `/clusters`).
- `placeholder?: string` — defaults to "Select…".
- `disabledIds?: Set<string>` + `disabledReason?: (entity: T) => string | null` — for archived/soft-deleted entities.
- `inlineWarning?: (entity: T | null) => string | null` — message rendered under the field when the selected entity has a non-green status. Replaces the "Creation will succeed but X will fail" footgun from the cluster case.
- `data-testid?: string` for E2E.

Loading state shows a disabled `<Select>` with "Loading clusters…" placeholder. Error state shows a disabled `<Select>` + inline retry button.

### 2. Form-level `sourceOfTruth` lint for enum dropdowns

Extend the DataTable column-discipline lint guard to scan form components for inline `<SelectItem value="...">` arrays. Failure modes the lint catches:

- A form file contains 2+ adjacent `<SelectItem value="...">` lines without a `// Values must match backend/...` comment within 5 lines above, OR
- A form file imports `<SelectItem>` and does not import from `@/lib/enums`.

Granularity: scan `ui/src/components/**/*.tsx` excluding `__tests__/` and `common/`. The `common/` exception is for the primitive itself — once enums move to `@/lib/enums`, primitive consumers prove discipline via the import, not the comment.

Pair with a one-time refactor to create `ui/src/lib/enums/` containing typed exports for each backend `Literal[...]`:

- `cluster_engine_type` → `'elasticsearch' | 'opensearch'`
- `cluster_environment` → `'development' | 'staging' | 'production'`
- `study_status` → ... (already partially modeled in column-configs)
- `metric_kind`, `optimization_direction`, `sampler`, `pruner` — Optuna controls
- `judgment_rating` — 0-3 integer literals
- Plus the existing column-config consumers re-importing from `@/lib/enums` (single source).

Each export carries `sourceOfTruth: 'backend/app/db/models/<file>.py'` as a top-of-file comment or a co-located `*.source.md` pointer.

### 3. Migration list — replace inline `<Input>` and `<Select>` with primitives

- [`create-query-set-modal.tsx`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) — replace cluster-id `<Input>` with `<EntitySelect useEntities={useClusters}>`. **<60min — implement inline in this PR** (per CLAUDE.md implement-over-defer rule).
- [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — replace four hand-rolled FK selects with `<EntitySelect>` instances. Enum selects (metric, k, direction, sampler, pruner) move to `@/lib/enums` imports.
- [`register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) — repo `<Select>` → `<EntitySelect useEntities={useConfigRepos}>`. Engine, env, auth-type enums → `@/lib/enums`.
- [`generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) — template `<Select>` → `<EntitySelect useEntities={useTemplates}>`.
- [`create-template-modal.tsx`](../../../../ui/src/components/templates/create-template-modal.tsx) — engine enum → `@/lib/enums`.
- [`override-popover.tsx`](../../../../ui/src/components/judgments/override-popover.tsx) — rating enum → `@/lib/enums`.

### 4. Tutorial doc cleanup

[`tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 currently shows a `<local-es-id>` placeholder that operators paste literally. After the modal switches to a dropdown, the curl example can drop the inline UUID and lead with the `LOCAL_ES_ID=$(curl ... | jq -r ...)` pattern from this session's debug transcript, with the modal as the primary path and curl as the API-equivalent.

## Scope signals

- **Backend:** none.
- **Frontend:**
  - 1 new primitive (`entity-select.tsx`) — ~150 LOC + co-located test.
  - 1 new directory (`lib/enums/`) — ~50 LOC total across ~6 enum files.
  - 1 lint guard test extension — ~80 LOC in `__tests__/components/common/form-select-discipline.test.tsx` (new file, mirrors the DataTable pattern).
  - 6 form components migrated — ~30-60 LOC delta per component (mostly deletions; the inline `<Select>` blocks shrink to one-liners).
  - 1 column-config file refactor as enums move into `@/lib/enums` — proposals/studies/etc. column-configs gain an import, drop their inline `wireValues` constant.
- **Migration:** none (Alembic).
- **Config:** none.
- **Audit events:** none — all reads + form submits that already audit via their existing service calls.
- **Tests:** new vitest suite for `<EntitySelect>` (covers loading/error/empty/status-sort/disabled). Existing modal vitest suites get minor updates as the inner controls change shape; E2E specs in `ui/tests/e2e/` should be unaffected — they target `data-testid` and `role=combobox` which the primitive preserves.
- **Docs:** add a "Dropdown primitive" section to [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) next to the existing "DataTable primitive" section. CLAUDE.md "Enumerated Value Contract Discipline" gains a paragraph noting the lint now covers forms too.

## Why deferred

The tutorial-day workaround (substitute a real UUID) keeps operators unblocked, and three of the four production form modals already use a `<Select>` — so the "UUID text input" failure is a one-component bug, not a system-wide regression. The reason to bundle this as a primitive rather than patch one modal:

- The primitive lets the status-dot + inline-warning UX (proposed during the same debug session) ship once and apply uniformly. Otherwise every modal re-implements it slightly differently.
- The enum-discipline lint extension is the cheap insurance — without it, enum drift is a known-and-documented failure mode that the codebase has not yet been bitten by, but only because every enum has stayed small. The first time someone adds a new `study_status` value, the inline `<SelectItem>` blocks across 3 components will silently miss it.

Picking it up is a one-PR job once a contributor has the bandwidth — no upstream dependencies, no spec gates, no operator coordination.

## Relationship to other work

- **Parent pattern:** [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/) — same playbook, applied to form-level dropdowns. The lint-guard extension lives in the same test directory as the DataTable guard.
- **Sibling follow-ups:** [`chore_data_table_primitive_followups`](../chore_data_table_primitive_followups/idea.md) — independent (different surface). No ordering constraint.
- **Tutorial impact:** [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 and Step 7 both reference UUID-paste patterns that the modal-via-dropdown path supersedes. Update those examples in the same PR as the modal migration.
- **Future:** when MVP4 adds the multi-tenant `tenants` table, the tenant picker is another `<EntitySelect>` consumer — having the primitive ready means MVP4 doesn't re-invent it.
