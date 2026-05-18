# Dropdown primitive + cross-app form-select discipline

**Date:** 2026-05-17
**Status:** Idea — identified during tutorial UX debugging session 2026-05-17.
**Origin:** Operator hit the "type a cluster UUID" form field in [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) while following the [first-study tutorial](../../../08_guides/tutorial-first-study.md) Step 5. Cluster-id text input is the only UUID-paste survivor — every other FK in the UI already uses a `<Select>`. The asymmetry surfaces the absence of a primitive: each `<Select>` is hand-rolled, and the enum/FK source-of-truth discipline that `feat_data_table_primitive` baked into column-configs (per [CLAUDE.md "Enumerated Value Contract Discipline"](../../../../CLAUDE.md)) does not apply to form-level dropdowns.
**Depends on:** None. [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/) (PR #126, merged 2026-05-16) established the pattern this idea generalizes.

## Problem

The DataTable primitive shipped with a lint-enforced source-of-truth discipline — every enum filter cites a backend `Literal[...]` and every FK filter cites a `useX()` hook. Forms didn't get the same treatment, and three concrete consequences are now visible:

1. **One UUID-paste field still ships** at [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) — `<Input placeholder="UUIDv7 of the registered cluster" />`. The tutorial's curl example even uses a `<local-es-id>` placeholder that operators copy-paste literally, leading to a delayed `CLUSTER_NOT_FOUND` and a confusing `QUERY_SET_NOT_FOUND` on the next call. (Documented this session — see chat transcript 2026-05-17.)

2. **FK selects are duplicated, not shared.** Six form components hand-roll the "load entities, render `<Select>`" pattern: [`create-study-modal.tsx:246-340`](../../../../ui/src/components/studies/create-study-modal.tsx) (4 FKs: cluster, query-set, judgment-list, template), [`register-cluster-modal.tsx:218`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) (repo), [`generate-judgments-dialog.tsx:122`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) (template). The closest primitive — [`data-table-fk-select.tsx`](../../../../ui/src/components/common/data-table-fk-select.tsx) — is column-config-coupled and not reusable in forms.

3. **Form-level enum lint is incomplete.** The canonical typed-enum file [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) already exists with ~25 `*_VALUES as const` exports each carrying a `// Values must match backend/...` source-of-truth comment, and a CI grep gate at [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh) enforces enums.ts ↔ backend Literal parity. 15+ components consume the typed arrays — including every enum dropdown in the form modals below. The remaining gap: nothing prevents a *new* form component from inlining `<SelectItem value="completed">` instead of `STUDY_STATUS_VALUES.map(...)`. The DataTable lint at [`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) catches the regression in column-configs but only scans `*.column-config.{ts,tsx}` — form components are unguarded.

## Proposed capabilities

### 1. `<EntitySelect>` primitive

A form-friendly peer of [`DataTableFkSelect`](../../../../ui/src/components/common/data-table-fk-select.tsx) living at `ui/src/components/common/entity-select.tsx`. Note the asymmetry to resolve at primitive-design time: `DataTableFkSelect` is built on a **native `<select>`** (intentional — no Radix dep added at DataTable time), whereas every form-side FK dropdown uses shadcn `<Select>` / `<SelectTrigger>` (Radix). The form-side primitive should stay on shadcn `<Select>` to match the surrounding form ecosystem; the two primitives are kept as peers rather than one extending the other.

Props:

- `useEntities: () => { data: { data: T[] } | undefined, isLoading, isError }` — the TanStack Query hook (e.g., `useClusters({ limit: 200 })`). Must match the existing `apiClient` paginated-list shape returned by [`ui/src/lib/api/clusters.ts`](../../../../ui/src/lib/api/clusters.ts) and peers.
- `value: string | undefined` + `onChange(id: string | undefined): void` — controlled.
- `getId(entity: T): string` + `getLabel(entity: T): string` — required.
- `getStatus?(entity: T): 'green' | 'yellow' | 'red' | 'unknown'` — optional; when provided, renders a `●` indicator before the label and sorts green-first. Uses [`HEALTH_STATUS_VALUES`](../../../../ui/src/lib/enums.ts) from `@/lib/enums` so the lint guard catches drift.
- `emptyState?: { message: string; href?: string; cta?: string }` — rendered when `data.data.length === 0` (e.g., "No clusters registered" with link to `/clusters`).
- `placeholder?: string` — defaults to "Select…".
- `disabledIds?: Set<string>` + `disabledReason?: (entity: T) => string | null` — for archived/soft-deleted entities.
- `inlineWarning?: (entity: T | null) => string | null` — message rendered under the field when the selected entity has a non-green status. Replaces the "Creation will succeed but X will fail" footgun from the cluster case.
- `data-testid?: string` for E2E.

Loading state shows a disabled `<Select>` with "Loading clusters…" placeholder. Error state shows a disabled `<Select>` + inline retry button.

### 2. Form-level enum-import lint guard

Adds a third guard to complement the two already in place:

| Existing guard | Scope |
|---|---|
| [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh) | `ui/src/lib/enums.ts` ↔ backend `Literal[...]` parity |
| [`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) | `*.column-config.{ts,tsx}` files must import enum/sort arrays from `@/lib/enums` |
| **NEW — `form-select-discipline.test.tsx`** | Form components must not inline `<SelectItem value="literal">` for known enums |

Failure modes the new lint catches:

- A form file under `ui/src/components/**/*.tsx` (excluding `__tests__/` and `common/`) contains 2+ adjacent `<SelectItem value="literal">` lines where the values match a known backend enum (cross-reference against `enums.ts` exports), without consuming the typed array via `*_VALUES.map(...)`.
- A form file imports `<SelectItem>` from shadcn and does not import any typed array from `@/lib/enums` — escape hatch comment `// no-enum-import: <reason>` permitted with reviewer ack.

No additions to `enums.ts` are required — every enum the listed migration targets need is **already exported**: `ENGINE_TYPE_VALUES`, `ENVIRONMENT_VALUES`, `AUTH_KIND_VALUES`, `OBJECTIVE_METRIC_VALUES`, `OBJECTIVE_K_VALUES`, `OBJECTIVE_DIRECTION_VALUES`, `SAMPLER_VALUES`, `PRUNER_VALUES`, `RATING_VALUES` (full list in [`enums.ts`](../../../../ui/src/lib/enums.ts)). The discipline this lint enforces is "**don't regress** the existing import convention," not "build the convention."

### 3. Migration list — replace inline `<Input>` and hand-rolled FK selects with the primitive

Audit confirms enum-side discipline is already in place across every listed modal (each already imports from `@/lib/enums`); the migration is FK-side only.

- [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) — replace cluster-id `<Input placeholder="UUIDv7 of the registered cluster">` with `<EntitySelect useEntities={useClusters}>`. **<60min — implement inline in this PR** (per CLAUDE.md implement-over-defer rule). This is the only UUID-paste survivor in the UI.
- [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — replace four hand-rolled FK selects with `<EntitySelect>` instances: `cs-cluster` (line 246), `cs-qs` (line 283), `cs-jl` (line 301), `cs-tpl` (line 326). The five Optuna enum selects (`cs-metric`, `cs-k`, `cs-dir`, `cs-sampler`, `cs-pruner`) **already** consume `OBJECTIVE_METRIC_VALUES` / `OBJECTIVE_K_VALUES` / `OBJECTIVE_DIRECTION_VALUES` / `SAMPLER_VALUES` / `PRUNER_VALUES` from `@/lib/enums` — no change.
- [`register-cluster-modal.tsx:218`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) — repo `<Select>` → `<EntitySelect useEntities={useConfigRepos}>`. Engine/env/auth enums already use `ENGINE_TYPE_VALUES` / `ENVIRONMENT_VALUES` / `AUTH_KIND_VALUES` — no change.
- [`generate-judgments-dialog.tsx:122`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) — template `<Select>` → `<EntitySelect useEntities={useTemplates}>`.
- [`create-template-modal.tsx`](../../../../ui/src/components/templates/create-template-modal.tsx) — engine enum already uses `ENGINE_TYPE_VALUES`. **No migration needed** unless the form gains a new FK select; included here only as a lint-coverage target.
- [`override-popover.tsx`](../../../../ui/src/components/judgments/override-popover.tsx) — rating enum already uses `RATING_VALUES`. **No migration needed**; included only as a lint-coverage target.

### 4. Tutorial doc cleanup

[`tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 currently shows a `<local-es-id>` placeholder that operators paste literally. After the modal switches to a dropdown, the curl example can drop the inline UUID and lead with the `LOCAL_ES_ID=$(curl ... | jq -r ...)` pattern from this session's debug transcript, with the modal as the primary path and curl as the API-equivalent.

## Scope signals

- **Backend:** none.
- **Frontend:**
  - 1 new primitive (`entity-select.tsx`) — ~150 LOC + co-located vitest.
  - 1 new lint guard test (`__tests__/components/common/form-select-discipline.test.tsx`) — ~80 LOC mirroring the DataTable column-discipline pattern.
  - 3 form components migrated FK-side: [`create-query-set-modal.tsx`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) (1 FK), [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) (4 FKs), [`register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) (1 FK), [`generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) (1 FK) — 7 FK sites total, ~20-40 LOC delta per component (deletions dominate).
  - No additions to `ui/src/lib/enums.ts` required — the typed arrays for every form-modal enum dropdown already exist there.
- **Migration:** none (Alembic).
- **Config:** none.
- **Audit events:** none — all reads + form submits that already audit via their existing service calls.
- **Tests:** new vitest suite for `<EntitySelect>` (covers loading/error/empty/status-sort/disabled). Existing modal vitest suites get minor updates as the inner controls change shape; E2E specs in `ui/tests/e2e/` should be unaffected — they target `data-testid` and `role=combobox` which the primitive preserves.
- **Docs:** add a "Dropdown primitive" section to [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) next to the existing "DataTable primitive" section. CLAUDE.md "Enumerated Value Contract Discipline" gains a paragraph noting the lint now covers forms too.

## Why deferred

The tutorial-day workaround (substitute a real UUID) keeps operators unblocked, and every other production form modal already uses a `<Select>` with enum imports from `@/lib/enums` — so the "UUID text input" failure is a one-component bug, not a system-wide regression. The reason to bundle this as a primitive rather than patch one modal:

- The primitive lets the status-dot + inline-warning UX (proposed during the same debug session) ship once and apply uniformly. Otherwise every FK select re-implements it slightly differently as health-coloring requirements show up.
- The enum-import lint guard is the cheap insurance against **future** regression. Enum-side discipline is already in place today — `ui/src/lib/enums.ts` + the verify-source-of-truth grep gate enforce parity to the backend, and 15 components consume the typed arrays. The risk this guard mitigates is the next contributor adding a new form and inlining literals without realizing the convention exists.

Picking it up is a one-PR job once a contributor has the bandwidth — no upstream dependencies, no spec gates, no operator coordination.

## Recommended pipeline path

**Use `/pipeline`** (the full spec → plan → execute → guide flow), not `/impl-execute --ad-hoc` and not `/bug-fix`. Rationale:

- **Design surface to lock in spec-gen:** the `<EntitySelect>` prop API (especially `getStatus` / `inlineWarning` / `emptyState`), the status-dot + inline-warning UX, and the form-vs-DataTable shadcn-vs-native asymmetry are all decisions worth capturing in a `feature_spec.md` that future contributors can reference. `/impl-execute --ad-hoc` skips spec-gen and would bake those decisions into commit messages instead.
- **Multi-component migration with a lint guard:** the new primitive + new CI test + 4 migrated modals is plan-sized work, not a one-PR ad-hoc fix. `/impl-plan-gen` will surface story-level seams (e.g., "ship the primitive + lint, then migrate consumers in a follow-up PR if review is heavy").
- **Not a bug:** the `chore_` prefix is correct — there's no broken behavior. `/bug-fix` is the wrong skill (the user-visible failure is "UX wart," not "regression").

The single `create-query-set-modal.tsx` fix could technically ship inline via `/impl-execute --ad-hoc` and would close the operator-facing footgun in one PR. The idea recommends against this **because** doing so without the primitive forces the next contributor to either re-implement the FK-select pattern from scratch or refactor the one-off when the primitive lands later. Bundling avoids that churn.

**Invocation:** `/pipeline docs/02_product/planned_features/chore_dropdown_primitive/` — runs in default approval-gated mode (spec / plan / execution each pause for review). Use `/pipeline ... --auto` only if you want the stages to chain without per-stage approval; given the spec has UX calls that benefit from a human checkpoint, default-mode is the safer pick here.

## Relationship to other work

- **Parent pattern:** [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/) — same playbook, applied to form-level dropdowns. The lint-guard extension lives in the same test directory as the DataTable guard.
- **Sibling follow-ups:** [`chore_data_table_primitive_followups`](../chore_data_table_primitive_followups/idea.md) — independent (different surface). No ordering constraint.
- **Tutorial impact:** [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 and Step 7 both reference UUID-paste patterns that the modal-via-dropdown path supersedes. Update those examples in the same PR as the modal migration.
- **Future:** when MVP4 adds the multi-tenant `tenants` table, the tenant picker is another `<EntitySelect>` consumer — having the primitive ready means MVP4 doesn't re-invent it.
