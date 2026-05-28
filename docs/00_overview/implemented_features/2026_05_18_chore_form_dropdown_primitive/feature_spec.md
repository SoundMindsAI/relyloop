# Feature Specification — Form Dropdown Primitive (`<EntitySelect>`)

**Date:** 2026-05-18
**Status:** Draft
**Owners:** RelyLoop maintainer (Engineering Owner). No external product stakeholder.
**Related docs:**

- Idea: [`docs/00_overview/planned_features/chore_form_dropdown_primitive/idea.md`](idea.md)
- Parent pattern: [`docs/00_overview/implemented_features/2026_05_16_feat_data_table_primitive/feature_spec.md`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/feature_spec.md) (PR #126, merged 2026-05-16)
- UI architecture: [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) §"DataTable primitive" — the canonical sibling pattern this spec extends to forms
- CLAUDE.md §"Enumerated Value Contract Discipline" — codifies the source-of-truth rule that the new lint guard enforces for form-level dropdowns
- Tutorial: [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 — current UUID-paste curl example replaced after the modal migration

---

## 1) Purpose

**Problem.** RelyLoop's UI has one surviving UUID-paste form field — [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) — where operators must copy a cluster UUIDv7 from `/clusters` and paste it into a free-text `<Input>`. The tutorial's curl walkthrough at [`tutorial-first-study.md:182`](../../../08_guides/tutorial-first-study.md) shows a literal `<local-es-id>` placeholder that operators paste verbatim, producing a delayed `CLUSTER_NOT_FOUND` followed by a confusing `QUERY_SET_NOT_FOUND` on the next call. Adjacent to that one survivor, three other form modals (`create-study-modal.tsx`, `register-cluster-modal.tsx`, `generate-judgments-dialog.tsx`) hand-roll six FK `<Select>` instances each with their own load-state, error-state, and empty-state plumbing. The closest existing primitive — [`data-table-fk-select.tsx`](../../../../ui/src/components/common/data-table-fk-select.tsx) — is column-config-coupled (consumes a `useOptions: () => { data: { id, label }[], isLoading }` shape) and not reusable against the form-side TanStack hooks (`useClusters`, `useConfigRepos`, `useTemplates`) which return paginated `UseQueryResult<{ data: T[] }, ApiError>` shapes.

**Outcome.** Ship one form-friendly `<EntitySelect>` primitive that wraps the shadcn `<Select>` family, consumes the existing TanStack listing hooks, and standardizes the load / error / empty / disabled / health-status UX in one place. Migrate the four affected form modals (7 FK sites) onto it. Add a vitest lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` that blocks new form components from inlining `<SelectItem value="literal">` for known backend enum values, mirroring the column-discipline guard at [`data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx). Update the tutorial to lead with the modal walkthrough and demote the UUID-paste curl example to "API-equivalent."

**Non-goal.** This spec does **not** modify the column-config-side primitive (`DataTableFkSelect` stays on native `<select>` per `feat_data_table_primitive` Story 2.3). It does **not** generalize the form-side primitive to support multi-select, async filtering, or virtualized scrolling — every form FK in MVP1 has ≤200 entities and renders fine with shadcn's default `<SelectContent>`. It does **not** add per-FK runtime allowlist enforcement (the existing `verify_enum_source_of_truth.sh` CI gate already enforces enums.ts ↔ backend Literal parity; the new lint catches inline-literal regression in form files specifically).

## 2) Current state audit

### Existing implementations

| File | What it does | Hook / API | Notes |
|---|---|---|---|
| [`ui/src/components/query-sets/create-query-set-modal.tsx:81-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) | New query set form. Cluster ID is a free-text `<Input id="qs-cluster" placeholder="UUIDv7 of the registered cluster">`. | `POST /api/v1/query-sets` via `useCreateQuerySet` | The only UUID-paste survivor in the UI. **No FK dropdown today** — this migration introduces one. |
| [`ui/src/components/studies/create-study-modal.tsx:233-339`](../../../../ui/src/components/studies/create-study-modal.tsx) | 5-step study-creation wizard. Four FK `<Select>` instances: cluster (line 246), query set (line 283), judgment list (line 301), template (line 326). | `useClusters({ limit: 200 })`, `useQuerySets({ cluster_id, limit: 200 })`, `useJudgmentLists({ query_set_id, limit: 200 })`, `useTemplates({ engine_type, limit: 200 })` | The cluster `onValueChange` callback (line 239-244) resets three child fields (`query_set_id`, `judgment_list_id`, `template_id`) — child-reset logic must be preserved post-migration. Selected cluster is derived via `clusters.data?.data.find((c) => c.id === clusterId)` (line 113) for engine_type-filtering downstream selects. |
| [`ui/src/components/clusters/register-cluster-modal.tsx:211-230`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) | New cluster form. Config-repo FK `<Select>` at line 214, wrapped in `{(configRepos.data?.data ?? []).length > 0 && ...}` (the whole field is hidden when no repos exist — no empty-state UI today). | `useConfigRepos({ limit: 100 })` | Three enum `<Select>` instances (engine_type, environment, auth_kind) already iterate `ENGINE_TYPE_VALUES.map(...)` from `@/lib/enums` — no change required. |
| [`ui/src/components/query-sets/generate-judgments-dialog.tsx:116-133`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) | Generate-judgments dialog. Template FK `<Select>` at line 118. | `useTemplates({ limit: 200 })` | Renders `{t.name} (v{t.version})` as label — the primitive's `getLabel` callback must handle entity-shaped label composition. |
| [`ui/src/components/templates/create-template-modal.tsx`](../../../../ui/src/components/templates/create-template-modal.tsx) | New query template form. Only the `engine_type` enum `<Select>` — already imports `ENGINE_TYPE_VALUES` from `@/lib/enums`. | `useCreateTemplate` | **No FK migration needed.** Lint-coverage target only (new lint guard scans this file). |
| [`ui/src/components/judgments/override-popover.tsx`](../../../../ui/src/components/judgments/override-popover.tsx) | Per-row judgment-rating override. Only the `rating` enum `<Select>` — already imports `RATING_VALUES` from `@/lib/enums`. | `usePatchJudgment` (inferred) | **No FK migration needed.** Lint-coverage target only. |
| [`ui/src/components/common/data-table-fk-select.tsx`](../../../../ui/src/components/common/data-table-fk-select.tsx) | Native `<select>` FK dropdown for `<DataTable>` filter slots. Consumes `useOptions: () => { data: { id, label }[]; isLoading: boolean }`. | N/A (caller-provided hook) | **Sibling primitive, NOT the parent class.** Hook shape and rendering family differ; the form-side primitive lives separately. The two primitives are peers — neither extends the other. |
| [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) | 29 `*_VALUES as const` exports each preceded by a `// Values must match backend/...` comment. | — | Already consumed by 18 files across `ui/src/`. No additions required for this feature. |
| [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh) | CI grep gate enforcing `enums.ts` ↔ backend Literal parity (118 LOC). | — | Out of scope to modify. The new lint guard complements rather than extends this gate. |
| [`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) | Story 2.13 vitest guard (327 LOC) scanning `*.column-config.{ts,tsx}` files for required `sourceOfTruth` + non-inline `wireValues`. | — | **Template for the new `form-select-discipline.test.tsx`** — same file-walker structure, same synthetic-regression test pattern, different glob target and different rule. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| [`docs/08_guides/tutorial-first-study.md:182`](../../../08_guides/tutorial-first-study.md) | Hardcoded curl placeholder `<local-es-id>` in query-set creation example | Replace with `LOCAL_ES_ID=$(curl ... \| jq -r '.data[0].id')` shell substitution pattern; lead with the modal walkthrough as the primary path, demote curl to "API-equivalent" code block |

No URL routes, page paths, or component imports change as part of this feature.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx`](../../../../ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx) | `getByPlaceholderText('UUIDv7 of the registered cluster')` or similar (TBD via grep at plan stage) | TBD via grep | Replace with `getByRole('combobox', { name: /cluster/i })` (shadcn `<Select>` renders `role="combobox"`) |
| [`ui/src/__tests__/components/studies/create-study-modal.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx) | DOM assertions tied to hand-rolled `<Select>` markup | TBD via grep | Update fixtures + assertions to match `<EntitySelect>` rendered output. Existing `data-testid` values (`cs-cluster`, `cs-qs`, etc.) MUST be preserved by the migration. |
| [`ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx`](../../../../ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx) | Assertions on the config-repo `<Select>` conditional render | TBD | Update to use `<EntitySelect>`'s empty-state contract (rendered always, with the EmptyState slot when no repos) instead of conditional show/hide. |
| `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` | **Does not exist** — `generate-judgments-dialog.tsx` has E2E coverage via `ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts` but no co-located unit test. Plan stage decides: (a) add a unit test as part of this migration, or (b) rely on the E2E spec + `<EntitySelect>` primitive coverage. | N/A (no file to update) | See Plan-stage decision. |
| [`ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts`](../../../../ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts) | References `gen-template` data-testid for template selection | 1 file (verified by grep at spec time) | **Preserve `gen-template` data-testid** on the `SelectTrigger` rendered by `<EntitySelect>` so the existing real-backend E2E spec continues to pass without modification. |
| Other `ui/tests/e2e/*.spec.ts` | Any test that interacts with the four migrated modals via `data-testid` selectors | TBD via plan-stage grep | Same preservation contract. |

**Audit method:** the Plan stage (`/impl-plan-gen`) will glob the test directories and replace `TBD` with concrete file:line counts. Three of the four migrated modals have co-located unit tests (verified by spec-stage `find`); generate-judgments-dialog only has E2E coverage. The spec-stage commitment is that **no existing test will be deleted** and **all `data-testid` values must round-trip**.

### Existing behaviors affected by scope change

- **Behavior — config-repo field visibility in `register-cluster-modal.tsx`:** Current: the whole `<div>` containing the config-repo `<Select>` is conditionally rendered via `{(configRepos.data?.data ?? []).length > 0 && ...}` (line 211). When no repos exist, the field is hidden entirely. New: the field is always rendered; the empty case shows the `<EntitySelect>`'s empty-state slot ("No config repos registered" + link to `/clusters` or repo registration UI). Decision needed: **no** — the empty-state slot is strictly more discoverable than hiding the field (the current behavior leaves operators wondering whether the field exists at all). The migration changes this in-place.

- **Behavior — UUID-paste in `create-query-set-modal.tsx`:** Current: free-text `<Input>` accepts any string; submission fails with `CLUSTER_NOT_FOUND` if the UUID doesn't match a registered cluster. New: `<EntitySelect>` only allows selecting from registered clusters; submission cannot fail with `CLUSTER_NOT_FOUND` from the form path (operator-level error becomes structurally unreachable). Decision needed: **no** — this is the headline UX improvement.

- **Behavior — child-field reset on cluster change in `create-study-modal.tsx`:** Current: the cluster `onValueChange` callback (line 239-244) explicitly resets `query_set_id`, `judgment_list_id`, `template_id` to empty string when the cluster changes. New: the `<EntitySelect>` exposes a typed `onChange(id: string | undefined)` callback that fires after the value is updated; the consumer wires the same reset logic into that callback. Decision needed: **no** — the primitive does not internalize this concern; consumer remains responsible for cross-field invalidation.

- **Behavior — error-state UX when `useClusters()` fails:** Current: `register-cluster-modal.tsx` and `create-study-modal.tsx` silently render an empty `<SelectContent>` when the TanStack hook errors. New: `<EntitySelect>` renders a disabled trigger with "Failed to load — retry" inline button that invokes the query's `refetch()`. Decision needed: **no** — strictly better than the current silent failure; matches the load-state UX users expect.

---

## 3) Scope

### In scope

1. New primitive `ui/src/components/common/entity-select.tsx` wrapping shadcn `<Select>` family. Generic over entity type `<T>`; consumes a TanStack listing hook + entity→id + entity→label callbacks + optional status/disabled/warning/empty-state slots. Co-located vitest covers loading / error / empty / status-sort / disabled.
2. New vitest lint guard `ui/src/__tests__/components/common/form-select-discipline.test.tsx` mirroring [`data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx). Scans `ui/src/components/**/*.tsx` (excluding `__tests__/`, `common/`, and `*.column-config.{ts,tsx}`) and fails when a form file inlines a `<SelectItem value="<literal>">` whose `<literal>` matches any backend enum wire value defined in `ui/src/lib/enums.ts`.
3. Migrate 4 form components, 7 FK sites:
   - [`create-query-set-modal.tsx`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) — replace lines 86-92 (UUID `<Input>`) with `<EntitySelect useEntities={useClusters} ... />` (1 site).
   - [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — replace 4 hand-rolled `<Select>` blocks at lines 237-256 (cluster), 276-293 (query set), 297-311 (judgment list), 322-336 (template).
   - [`register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) — replace lines 211-230 (config-repo) with always-rendered `<EntitySelect>` carrying the EmptyState slot.
   - [`generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) — replace lines 116-133 (template).
4. Tutorial doc update: [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 reorders to lead with the modal walkthrough; the `<local-es-id>` curl placeholder is replaced with a `LOCAL_ES_ID=$(curl ... | jq -r ...)` shell substitution shown as the API-equivalent code block.
5. Architecture doc update: [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) gains a new "Form dropdown primitive" subsection adjacent to "DataTable primitive" documenting the form-side `<EntitySelect>` and its asymmetry to `DataTableFkSelect`.
6. CLAUDE.md "Enumerated Value Contract Discipline" section gains one paragraph noting the lint now covers form components in addition to column configs.

### Out of scope

- Multi-select, async filter, virtualized rendering — all four MVP1 form modals operate on ≤200-entity slices and don't need them. Revisit at MVP4 if tenant pickers cross 1k+ entries.
- Modifying `DataTableFkSelect` or unifying it with `<EntitySelect>` — different rendering family (native vs Radix), different hook shape, different consumer surface. They remain peers.
- Form-level Zod schema generation from enums — already in place via `enums.ts` (`type EngineType = (typeof ENGINE_TYPE_VALUES)[number]`). The new lint catches inline literals; it doesn't generate schemas.
- Backend changes. This is a frontend-only chore; zero migrations, zero new endpoints, zero new audit events.
- Status-dot + health-aware sorting in `DataTableFkSelect`. Out of scope: that's a column-config concern, captured separately under `chore_data_table_primitive_followups` if pursued.

### API convention check

- **Endpoint prefix convention:** N/A — no new endpoints. Consumes existing `GET /api/v1/clusters`, `GET /api/v1/config-repos`, `GET /api/v1/query-templates`, `GET /api/v1/query-sets`, `GET /api/v1/judgments/lists` via existing TanStack hooks (`useClusters`, `useConfigRepos`, `useTemplates`, `useQuerySets`, `useJudgmentLists`) per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md).
- **Router namespace:** N/A.
- **HTTP methods:** N/A.
- **Non-auth error envelope shape:** N/A (no backend surface added).
- **Auth error shape:** N/A (MVP1, no auth).

### Phase boundaries

**Single phase — no deferral.** The feature is small enough to ship in one PR (~350-500 LOC). No `phase2_idea.md` is created; the implementation plan will sequence stories within the single phase.

---

## 4) Product principles and constraints

- **The form-side primitive consumes existing TanStack hooks unchanged.** No hook signature must be added or modified to support `<EntitySelect>`. Callers pass `useClusters` (or peers) as a value; the primitive calls it inside its own render. This keeps the primitive decoupled from per-resource concerns (filters, pagination cursors) — the caller controls hook invocation parameters.
- **Source-of-truth discipline applies to forms now, not just column configs.** Backend wire values for any enum dropdown MUST flow from `enums.ts` exports; inline string literals in `<SelectItem value="...">` for backend-validated enums are forbidden. The new lint guard catches the regression; the CLAUDE.md rule documents the convention.
- **Data-testid values are part of the contract.** Every `SelectTrigger` rendered by `<EntitySelect>` carries the consumer-provided `data-testid` unchanged. Existing E2E specs and unit tests must continue to find the same DOM hooks.
- **No new runtime dependencies.** `<EntitySelect>` builds entirely on existing shadcn primitives (`Select`, `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem`), existing TanStack Query types, and existing utility classes (Tailwind). Zero `pnpm add` operations.
- **Empty-state CTAs use Next.js `<Link>`, not modal-internal navigation.** When the user clicks the CTA ("Register a cluster"), Next.js routes to `/clusters` (or wherever) and the parent modal unmounts via route change. No special modal-close prop is required.
- **Status indicator only renders when `getStatus` is provided.** A primitive used for non-statusful entities (templates, config repos) renders no dot, no warning, no health-aware sorting. The status feature is opt-in per consumer.

### Anti-patterns

- **Do not** repurpose `DataTableFkSelect` to also serve forms. The native `<select>` rendering family is intentional for the DataTable filter strip; forms use shadcn `<Select>` for visual consistency with the surrounding `<Input>` / `<Textarea>` controls. Keep the two primitives as peers.
- **Do not** add a `multi?: boolean` prop. Multi-select introduces a different controlled-value type (`string[]`) and different empty-state semantics; postpone until a real consumer needs it. Adding it now is YAGNI scaffolding.
- **Do not** internalize child-field reset logic (e.g., reset query_set_id when cluster_id changes). The primitive does not know about cross-field invariants. Consumers wire reset logic in their own `onChange` callback.
- **Do not** add a `loadingPlaceholder` prop that shows skeleton rows in `<SelectContent>`. The shadcn `<Select>` renders a closed trigger by default; the load state is communicated on the trigger ("Loading…"), not inside the dropdown that isn't open yet. Adding skeleton-in-dropdown is a UX regression vs the current closed-and-disabled trigger pattern.
- **Do not** make the lint guard's escape-hatch comment silent. Every `// no-enum-import: <reason>` must include a reason after the colon; the lint rejects the comment if the reason is empty. This prevents drive-by suppression.
- **Do not** mock the TanStack hook inside `<EntitySelect>` tests with anything other than a synchronous fake. Wrapping in `QueryClientProvider` for primitive-level tests adds runtime overhead with no behavioral benefit; the primitive only consumes `{ data, isLoading, isError, refetch }` and doesn't care which library produced it. (Modal-level integration tests will use the real `QueryClientProvider`.)

## 5) Assumptions and dependencies

- **Dependency:** shadcn `<Select>` primitives at `ui/src/components/ui/select.tsx`. Status: present (used by all 5 form modals today). Risk if missing: N/A — they ship with shadcn init and have been stable across all UI features.
- **Dependency:** TanStack Query listing hooks (`useClusters`, `useConfigRepos`, `useTemplates`, `useQuerySets`, `useJudgmentLists`). Status: present (verified in §2 audit). Risk if missing: N/A.
- **Dependency:** Existing `enums.ts` source-of-truth file + CI grep gate. Status: present (29 typed exports; 18 consumer files; 118-LOC CI gate). Risk if missing: N/A.
- **Dependency:** Next.js `<Link>` for empty-state CTAs. Status: present (used throughout the UI). Risk if missing: N/A.

No cross-team, no external service, no third-party dependency.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (interactive UI user) — selects entities from dropdowns when creating studies, query sets, clusters, and judgment generation jobs.
- **Secondary actor:** RelyLoop contributor (adds new form components in the future) — constrained by the lint guard to import enum arrays from `@/lib/enums` rather than inlining literals.
- **Role model:** N/A — RelyLoop is single-tenant + no auth through MVP3 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md). All UI users have full access to all dropdowns.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — audit_log lands at MVP2. This feature is frontend-only and adds no state-mutating endpoints.

---

## 7) Functional requirements

### FR-1: `<EntitySelect>` primitive renders a controlled shadcn `<Select>`

- Requirement:
  - The system **MUST** export a React component `EntitySelect<T>` from `ui/src/components/common/entity-select.tsx` parameterized by entity type `T`.
  - The component **MUST** accept a controlled `value: string | undefined` + `onChange(next: string | undefined): void` pair and render a shadcn `<SelectTrigger>` / `<SelectContent>` / `<SelectItem>` composition.
  - The component **MUST** accept a required `useEntities` prop of shape `() => UseQueryResult<{ data: T[] }, ApiError>` matching the existing TanStack hooks (e.g., `useClusters({ limit: 200 })`).
  - The component **MUST** accept required `getId: (entity: T) => string` and `getLabel: (entity: T) => string` callbacks.
  - The component **MUST** accept an optional `data-testid: string` prop applied to the `SelectTrigger` so existing E2E selectors round-trip.
  - The component **MUST** accept an optional `id?: string` prop applied to the `SelectTrigger` so existing `<Label htmlFor={...}>` associations are preserved (e.g., `id="cs-cluster"`).
  - The component **MUST** accept an optional `placeholder?: string` (defaults to `"Select…"`).
- Notes: The primitive is generic over `T` — `clusters` produces `ClusterSummary` entities, `templates` produces `QueryTemplateSummary`, etc. The `getId` / `getLabel` callbacks let each consumer extract the right fields without the primitive needing knowledge of any specific schema.

### FR-2: Loading state — disabled trigger with "Loading…" placeholder

- Requirement:
  - The system **MUST** render a disabled `<SelectTrigger>` with placeholder text `"Loading…"` (or a caller-supplied `loadingPlaceholder?: string` override) when `useEntities()` returns `isLoading === true`.
  - The system **MUST NOT** open the `<SelectContent>` in the loading state. The shadcn `<Select>`'s native disabled behavior prevents the trigger from opening; no additional guards are required.

### FR-3: Error state — disabled trigger with inline retry

- Requirement:
  - The system **MUST** render a disabled `<SelectTrigger>` with placeholder text `"Failed to load — click retry"` and an adjacent inline `<button type="button" onClick={refetch}>` labeled `"Retry"` when `useEntities()` returns `isError === true`.
  - The retry button **MUST** invoke the TanStack `UseQueryResult.refetch()` function and clear the error state on success.
  - The system **MUST NOT** swallow the underlying error — the `<ApiError>` shape is exposed via TanStack devtools and consumer-side `onError` callbacks unchanged.

### FR-4: Empty state — caller-provided slot rendered inside SelectContent or below trigger

- Requirement:
  - The system **MUST** accept an optional `emptyState?: { message: string; cta?: { label: string; href: string } }` prop.
  - When `useEntities()` returns `data.data.length === 0` and `emptyState` is provided, the system **MUST** render the message text inside a disabled-trigger placeholder slot (e.g., placeholder `"No clusters registered"`) AND render a `<Link href={cta.href}>{cta.label}</Link>` inline below the trigger.
  - When `data.data.length === 0` and `emptyState` is **not** provided, the system **MUST** render the trigger with placeholder text `"No options"` and no CTA.
  - The empty-state CTA **MUST** use Next.js `<Link>` (imported as `import Link from 'next/link'`) — the route change unmounts the parent modal automatically; no `onOpenChange(false)` plumbing is required.

### FR-5: Disabled subset — `disabledIds: Set<string>` + `disabledReason?: (entity: T) => string | null`

- Requirement:
  - The system **MUST** accept an optional `disabledIds?: ReadonlySet<string>` prop. Entities whose `getId(entity)` is in the set **MUST** render with `disabled` on the corresponding `<SelectItem>`.
  - The system **MUST** accept an optional `disabledReason?: (entity: T) => string | null` callback. When the callback returns a non-null string for a given entity, the `<SelectItem>` **MUST** carry a `title` attribute with that string for tooltip-on-hover.
  - Selecting a disabled item **MUST NOT** trigger `onChange`. shadcn's `<SelectItem disabled>` already enforces this.
- Notes: Used for soft-deleted / archived entities (e.g., a cluster with `deleted_at != null` shouldn't be selectable but the user should know why it appears greyed-out).

### FR-6: Status indicator — opt-in dot + sort + warning

- Requirement:
  - The system **MUST** accept an optional `getStatus?: (entity: T) => 'green' | 'yellow' | 'red' | 'unknown'` callback. The accepted strings **MUST** be a subset of the `HEALTH_STATUS_VALUES` array exported from `ui/src/lib/enums.ts` (which is the canonical mapping of `backend/app/api/v1/schemas.py HealthStatusValue`).
  - When `getStatus` is provided, each `<SelectItem>` **MUST** render a small `●` (Unicode bullet) indicator before the label with Tailwind color classes: `green → text-green-600`, `yellow → text-amber-600`, `red → text-red-600`, `unknown → text-muted-foreground`.
  - When `getStatus` is provided, the `data.data` array **MUST** be rendered in stable order sorted by status precedence (green=0, yellow=1, red=2, unknown=3, mapping `'unreachable'` from the backend wire shape to `'unknown'` in the primitive's local API). Within each tier, original insertion order is preserved.
  - The system **MUST** accept an optional `inlineWarning?: (entity: T | undefined) => string | null` callback. When the currently selected entity yields a non-null warning string, the system **MUST** render the warning text below the trigger as `<p className="text-xs text-amber-600 mt-1">{warning}</p>` (matches the existing helper-text styling at [`create-study-modal.tsx:265-267`](../../../../ui/src/components/studies/create-study-modal.tsx)).
- Notes: `getStatus` and `inlineWarning` are independent props — a consumer can use either, both, or neither. When `getStatus` is **not** provided, the primitive renders no dot, no warning, and uses original `data.data` insertion order. The wire→local mapping (`'unreachable'` → `'unknown'`) lets callers pass `(c) => c.health_check.status` directly without a switch statement; the primitive normalizes internally.

### FR-7: Form-select discipline lint guard

- Requirement:
  - The system **MUST** include a vitest test file at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` modeled on [`data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx).
  - The test **MUST** walk `ui/src/components/**/*.tsx` (excluding `__tests__/`, `common/`, and any `*.column-config.{ts,tsx}`) and fail when a form file matches both conditions:
    1. The file imports `SelectItem` from `'@/components/ui/select'`.
    2. The file contains a literal `<SelectItem value="<literal>">` where `<literal>` matches any wire value from any `*_VALUES` array exported by `ui/src/lib/enums.ts`.
  - The test **MUST** offer a per-file escape hatch via a top-of-file comment `// no-enum-import: <reason>` where `<reason>` is non-empty. Files with this comment are excluded from the scan.
  - The test **MUST** include at least four synthetic regression cases (modeled on Story 2.13 patterns):
    1. Inline `<SelectItem value="completed">` matching `STUDY_STATUS_VALUES` fails with a message naming the file and the offending value.
    2. Inline `<SelectItem value="ndcg">` matching `OBJECTIVE_METRIC_VALUES` fails identically.
    3. `<SelectItem value={STUDY_STATUS_VALUES[0]}>` (compile-time indexed) — passes (not an inlined literal).
    4. `// no-enum-import: gradual migration of legacy form` → passes (escape hatch with reason).
    5. `// no-enum-import:` (no reason) → fails with a message saying the escape hatch requires a reason.
- Notes: The lint guard is a vitest test, not an ESLint rule. This matches the parent pattern (Story 2.13 column-discipline guard) and avoids adding a new ESLint plugin or custom rule infrastructure. The test runs in the existing `pnpm test` invocation; CI catches the regression on every PR.

### FR-8: Migrate four form modals onto `<EntitySelect>`

- Requirement:
  - The system **MUST** replace the UUID `<Input>` at [`create-query-set-modal.tsx:86-92`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) with `<EntitySelect useEntities={useClusters} getId={(c) => c.id} getLabel={(c) => c.name} getStatus={(c) => c.health_check.status} ... />`.
  - The system **MUST** replace the four hand-rolled cluster / query-set / judgment-list / template `<Select>` blocks in [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) lines 237-256, 276-293, 297-311, 322-336 with `<EntitySelect>` instances. The cluster instance **MUST** preserve the child-field reset behavior (resetting `query_set_id`, `judgment_list_id`, `template_id` to empty when cluster changes) via consumer `onChange` callback.
  - The system **MUST** replace the config-repo `<Select>` at [`register-cluster-modal.tsx:211-230`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) with `<EntitySelect useEntities={useConfigRepos} ... emptyState={{ message: 'No config repos registered', cta: { label: 'Register a config repo', href: '/clusters' } }} />`. The `{(configRepos.data?.data ?? []).length > 0 && ...}` conditional wrapper **MUST** be removed (always-rendered field).
  - The system **MUST** replace the template `<Select>` at [`generate-judgments-dialog.tsx:116-133`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) with `<EntitySelect useEntities={useTemplates} getLabel={(t) => `${t.name} (v${t.version})`} ... />`.
  - All migrated modals **MUST** preserve their existing `data-testid` values on the `SelectTrigger` (`qs-cluster`, `cs-cluster`, `cs-qs`, `cs-jl`, `cs-tpl`, `cl-repo`, `gen-template`).
  - All migrated modals **MUST** preserve their existing `<Label htmlFor={...}>` associations (which use the same id strings).

### FR-9: Documentation updates

- Requirement:
  - The system **MUST** add a new "Form dropdown primitive" subsection to [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) adjacent to the existing "DataTable primitive" section (currently at line 240). The subsection **MUST** explain the props API, the consumer-supplied `useEntities` shape, the status / warning / empty-state slots, and the explicit asymmetry to `DataTableFkSelect` (shadcn vs native).
  - The system **MUST** add one paragraph to the CLAUDE.md "Enumerated Value Contract Discipline" section noting that the form-select-discipline lint guard now covers form components in addition to column configs.
  - The system **MUST** update [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5 to lead with the modal walkthrough and replace the literal `<local-es-id>` curl placeholder (line 182) with a `LOCAL_ES_ID=$(curl ... | jq -r ...)` shell substitution, demoted to "API-equivalent."

---

## 8) API and data contract baseline

### 7.1 Endpoint surface

N/A — no new endpoints. The migration consumes five existing endpoints unchanged:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/clusters` | Used by `create-query-set-modal.tsx`, `create-study-modal.tsx` cluster dropdown |
| `GET` | `/api/v1/config-repos` | Used by `register-cluster-modal.tsx` config-repo dropdown |
| `GET` | `/api/v1/query-templates` | Used by `create-study-modal.tsx`, `generate-judgments-dialog.tsx` template dropdown |
| `GET` | `/api/v1/query-sets` | Used by `create-study-modal.tsx` query-set dropdown |
| `GET` | `/api/v1/judgments/lists` | Used by `create-study-modal.tsx` judgment-list dropdown |

All five endpoints ship with cursor pagination, `X-Total-Count` header, and the standard error envelope per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md). The `<EntitySelect>` requests `limit: 200` for all consumers (current behavior; no change). MVP4-scale considerations (when tenant pickers might exceed 200) are out of scope.

### 7.2 Contract rules

N/A — no API contract added or modified.

### 7.3 Response examples

N/A — no new API.

### 7.4 Enumerated value contracts

The primitive's `getStatus` prop accepts values from a closed allowlist that must match the backend canonical mapping. Form-side dropdowns continue to consume `enums.ts` exports.

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `EntitySelect.getStatus` return value | `green`, `yellow`, `red`, `unknown` | `ui/src/lib/enums.ts HEALTH_STATUS_VALUES` (mirroring `backend/app/api/v1/schemas.py HealthStatusValue`). Note: backend wire value is `unreachable`; the primitive maps `unreachable → unknown` internally so callers can pass `(c) => c.health_check.status` directly. | `<EntitySelect>` instance in `create-query-set-modal.tsx` (cluster), `create-study-modal.tsx` (cluster) |
| `<SelectItem value="...">` in `create-template-modal.tsx` (engine) | `elasticsearch`, `opensearch` | `ui/src/lib/enums.ts ENGINE_TYPE_VALUES` (mirroring `backend/app/api/v1/schemas.py EngineTypeWire`) | Lint-coverage target only; already using `ENGINE_TYPE_VALUES.map(...)` |
| `<SelectItem value="...">` in `register-cluster-modal.tsx` (engine, env, auth) | `elasticsearch`/`opensearch`; `prod`/`staging`/`dev`; `es_apikey`/`es_basic`/`opensearch_basic`/`opensearch_sigv4` | `ENGINE_TYPE_VALUES`, `ENVIRONMENT_VALUES`, `AUTH_KIND_VALUES` | Already using typed arrays from `@/lib/enums` |
| `<SelectItem value="...">` in `create-study-modal.tsx` (metric, k, direction, sampler, pruner) | `ndcg`/`map`/`precision`/`recall`/`mrr`/`err`; `1`/`3`/`5`/`10`/`20`/`50`/`100`; `maximize`/`minimize`; `tpe`/`random`; `median`/`none` | `OBJECTIVE_METRIC_VALUES`, `OBJECTIVE_K_VALUES`, `OBJECTIVE_DIRECTION_VALUES`, `SAMPLER_VALUES`, `PRUNER_VALUES` | Already using typed arrays from `@/lib/enums` |
| `<SelectItem value="...">` in `override-popover.tsx` (rating) | `0`, `1`, `2`, `3` | `RATING_VALUES` | Already using typed array |

**Audit result:** every existing enum `<Select>` in the listed form modals already consumes the typed array from `@/lib/enums`. The new lint guard's job is to **prevent regression**, not to fix existing drift.

### 7.5 Error code catalog

N/A — no new backend error codes. The primitive surfaces TanStack Query's existing `ApiError` shape via its `refetch()` retry button; no new error envelopes are introduced.

---

## 9) Data model and state transitions

N/A — frontend-only feature. No new tables, no new columns, no migrations.

### Required invariants

- **Invariant 1:** Every `<EntitySelect>` instance whose entity type has a backend-validated wire-value field used as `getStatus` input MUST source the status enum from `ui/src/lib/enums.ts`. Verified at compile time via the TypeScript type narrowing on `'green' | 'yellow' | 'red' | 'unknown'`.
- **Invariant 2:** Every form file under `ui/src/components/**/*.tsx` (excluding `__tests__/`, `common/`, `*.column-config.{ts,tsx}`) that imports `SelectItem` from `'@/components/ui/select'` MUST source enum wire values from `ui/src/lib/enums.ts` rather than inlining string literals. Enforced at CI time by the new vitest lint guard (FR-7).
- **Invariant 3:** Migrated modals MUST preserve their existing `data-testid` and `htmlFor`/`id` values exactly. Verified at compile time by TypeScript (the primitive's props include `data-testid?: string` and `id?: string` that map to the rendered `SelectTrigger`) and at test time by existing test suites continuing to pass.

### State transitions

N/A — `<EntitySelect>` is a controlled component; its state is owned by the consumer's form. No state machine.

### Idempotency/replay behavior

N/A — synchronous UI primitive, no event sourcing.

---

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Stale option list drift** — an inlined `<SelectItem value="invalid_status">` ships, the backend rejects with 422 VALIDATION_ERROR, the user sees a generic error toast. Mitigation: FR-7 lint guard blocks the regression at CI time.
  2. **Cluster id exposure in URL fragments** — N/A; `<EntitySelect>` does not write to URL, no query-param encoding. The selected id only exists in form state until submission.
  3. **CSRF on the consumed list endpoints** — no change; the existing TanStack hooks already include the standard fetch credentials handling; this feature does not add a new request path.
- **Controls:** TypeScript narrowing on the `getStatus` return type; vitest lint guard on inline literals; preserved `data-testid` values for E2E coverage.
- **Secrets/key handling:** N/A — no secrets, no env vars introduced.
- **Auditability:** N/A — frontend-only, no state mutation. The consumed list endpoints already handle their own audit emission post-MVP2.
- **Data retention/deletion/export impact:** N/A.

---

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new routes. `<EntitySelect>` appears inline within four existing modal dialogs (Create Query Set, Create Study, Register Cluster, Generate Judgments) at the same visual position the prior `<Select>` or `<Input>` occupied.
- **Labeling taxonomy:**
  - `qs-cluster` — labeled "Cluster" (replaces "Cluster ID" — drops the "ID" suffix since users no longer type one).
  - `cs-cluster`, `cs-qs`, `cs-jl`, `cs-tpl` — labels unchanged ("Cluster", "Query set", "Judgment list", "Query template").
  - `cl-repo` — label unchanged ("Config repo (optional)").
  - `gen-template` — label unchanged ("Current template").
- **Content hierarchy:** Within each modal, the dropdown order is unchanged. Visual priority is identical to today; only the trigger control's internal markup changes.
- **Progressive disclosure:** Status dots are progressive — they appear only on cluster pickers (the only entity with a `health_check`). Other dropdowns render flat labels.
- **Relationship to existing pages:** N/A — modal-local change; no page restructure.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Status dot (●) in cluster `<EntitySelect>` items | "Cluster health: green/yellow/red/unknown" with the actual status | hover on the dot or item | inline (browser-native tooltip via `title` attribute) |
| Inline warning under cluster `<EntitySelect>` trigger | "Selected cluster is currently <status>. Studies created against this cluster may fail until health recovers." | rendered as a `<p>` below the trigger when `inlineWarning` returns non-null for the selected entity | inline helper text (matches existing pattern at `create-study-modal.tsx:265-267`) |
| Empty-state CTA link | "No config repos registered — register one to enable PR creation." | always visible when `data.data.length === 0` and `emptyState` is provided | inline below the trigger |
| Disabled `<SelectItem>` (e.g., archived entity) | The string returned by `disabledReason(entity)` | hover on the disabled item | inline (browser-native tooltip via `title` attribute) |
| Retry button on error state | "Click to retry loading the list." | hover on the button | inline (browser-native tooltip via `title` attribute) |

**Guidelines applied:** all tooltips are <120 chars; the warning text uses a concrete consequence phrasing ("may fail until health recovers") not just a restated field name. The empty-state CTA copy answers "what should I do next?" with a clear action.

### Primary flows

1. **Flow A — Operator creates a query set from /query-sets:**
   - Click "New query set" → modal opens → cluster field renders `<EntitySelect>` with first 200 registered clusters loaded via `useClusters({ limit: 200 })`.
   - Trigger shows "Loading…" until the query resolves.
   - Click the trigger → dropdown opens → operator sees cluster names with health-status dots (green-first).
   - Operator selects a cluster → trigger collapses to the cluster name → query-set form proceeds.
   - On submit, the form sends the cluster's UUIDv7 as `cluster_id` — same wire shape as before; structurally impossible to misspell.

2. **Flow B — Operator creates a study from /studies:**
   - Click "New study" → 5-step wizard opens.
   - Step 1: cluster dropdown → selecting a cluster fires the consumer-side `onChange` that resets `query_set_id`, `judgment_list_id`, `template_id` to empty and updates `clusterId` form state.
   - Step 2: query-set dropdown is filtered by the chosen `cluster_id`; judgment-list dropdown is filtered by the chosen `query_set_id`. Both dropdowns refetch as the parent value changes — TanStack handles cache invalidation via the query-key params.
   - Step 3: template dropdown is filtered by the chosen cluster's `engine_type`.
   - Wizard proceeds as today.

3. **Flow C — Operator with zero config repos opens Register Cluster:**
   - Click "Register cluster" → modal opens → config-repo field renders an always-visible `<EntitySelect>` with the empty-state slot ("No config repos registered — Register a config repo →").
   - Operator clicks the CTA link → Next.js routes to `/clusters` (or repo registration page) → modal unmounts via route change.
   - (Current behavior hides the field entirely; new behavior makes the optional FK discoverable.)

### Edge/error flows

- **Edge — selected entity goes stale.** If the operator selects a cluster, leaves the modal open, the cluster is deleted in another tab, then the operator submits: the backend rejects with `CLUSTER_NOT_FOUND` (current behavior, unchanged). `<EntitySelect>` doesn't poll for freshness; staleness is bounded by TanStack's default cache window (5 minutes) + the operator's tab dwell time.
- **Edge — `useEntities()` errors after a value is already selected.** The previously selected value remains in form state; the trigger renders the selected entity's label from a memoized last-known-good (if available) or falls back to the raw id with a disabled-trigger error state. Retry button refetches.
- **Edge — disabled item is the currently selected value.** The trigger still renders the selected entity's label (so the user sees what they previously chose); but the disabled `<SelectItem>` in the dropdown carries the `disabledReason` tooltip explaining why it can't be re-selected.
- **Error — backend returns 0 entities even though some exist (transient).** TanStack treats this as a successful empty response; `<EntitySelect>` renders the empty state with the CTA. Operator clicks Retry on the trigger if no CTA is provided. (TanStack's default refetch policies handle the retry; the primitive surfaces the result.)

---

## 12) Given/When/Then acceptance criteria

### AC-1: Cluster picker in create-query-set modal replaces UUID Input

- Given the operator is on `/query-sets` with at least one registered cluster (`POST /api/v1/clusters` 201 returned, cluster appears in `GET /api/v1/clusters`).
- When the operator clicks "New query set" and inspects the Cluster field.
- Then the field renders a shadcn `<SelectTrigger id="qs-cluster" data-testid="qs-cluster">` with the cluster name as a `<SelectItem>` in the dropdown — NOT an `<Input placeholder="UUIDv7 of the registered cluster">`.
- Example values:
  - Setup: register a cluster with `name: "local-es"`, `engine_type: "elasticsearch"`.
  - Expected DOM: `<button role="combobox" id="qs-cluster" data-testid="qs-cluster">…</button>`; opening the dropdown yields `<div role="option" value="<uuidv7>">local-es</div>`.

### AC-2: Loading state renders disabled trigger with placeholder

- Given `useClusters({ limit: 200 })` is in flight (`isLoading: true`, `data: undefined`).
- When the operator opens the create-query-set modal.
- Then the Cluster `<SelectTrigger>` renders with the `disabled` attribute set (shadcn's `<SelectTrigger disabled>` prop, which renders `disabled` on the underlying `<button>`) and placeholder text `"Loading…"`. Clicking the trigger does NOT open the dropdown — the native `disabled` attribute prevents the click handler from firing.

### AC-3: Error state renders disabled trigger with inline retry button

- Given `useClusters({ limit: 200 })` returns `isError: true` (e.g., backend down).
- When the operator opens the create-query-set modal.
- Then the Cluster `<SelectTrigger>` renders disabled with placeholder `"Failed to load — click retry"`; an adjacent `<button type="button">Retry</button>` is visible.
- When the operator clicks Retry.
- Then `refetch()` fires; if the next response succeeds, the trigger transitions back to the loaded state.
- Example values: backend returns 500; the trigger label is `"Failed to load — click retry"`; clicking Retry triggers `GET /api/v1/clusters?limit=200` and the new 200 response repopulates the dropdown.

### AC-4: Empty state renders the configured slot and CTA

- Given `useConfigRepos({ limit: 100 })` returns `data: { data: [], next_cursor: null, has_more: false }`.
- When the operator opens the Register Cluster modal.
- Then the config-repo field is visible (NOT hidden as in current behavior); the `<SelectTrigger id="cl-repo">` placeholder reads `"No config repos registered"`; below the trigger a `<a href="/clusters">Register a config repo</a>` Link is rendered.
- When the operator clicks the link.
- Then Next.js routes to `/clusters` and the modal unmounts.

### AC-5: Status dot renders with correct color for cluster health

- Given the operator has three registered clusters: `local-es` (green), `staging-es` (yellow), `prod-es` (red).
- When the operator opens the create-query-set modal and opens the Cluster dropdown.
- Then the `<SelectItem>`s render in order: `● local-es` (green dot, `text-green-600`), `● staging-es` (yellow, `text-amber-600`), `● prod-es` (red, `text-red-600`). The dots precede the cluster names with a single space separator. Each dot is rendered inside `<span aria-hidden="true">` so the spoken screen-reader label is the cluster name unencumbered; status is conveyed via the `title` attribute on the `<SelectItem>` and the FR-6 inline warning for the selected entity.

### AC-6: Status sort applies green-first stable ordering

- Given a list of five clusters with mixed health: `[clusterA(red), clusterB(green), clusterC(yellow), clusterD(green), clusterE(red)]`.
- When the operator opens the dropdown.
- Then the items render in this order: `clusterB(green), clusterD(green), clusterC(yellow), clusterA(red), clusterE(red)`. (Green-first; within tiers, original order preserved.)

### AC-7: Inline warning renders for non-green selected cluster

- Given a cluster `staging-es` with `health_check.status: "yellow"` is selected in the create-query-set modal.
- When the modal renders the trigger.
- Then a `<p class="text-xs text-amber-600 mt-1">Selected cluster is currently yellow. Studies created against this cluster may fail until health recovers.</p>` appears below the `<SelectTrigger>`.

### AC-8: Disabled subset preserves selection but blocks re-selection

- Given the operator has three clusters: `live-es` (selectable), `archived-es` (in `disabledIds`), `decommissioned-es` (in `disabledIds`).
- When the operator opens the dropdown.
- Then `live-es` is enabled; `archived-es` and `decommissioned-es` render with `data-disabled="true"` (shadcn's default) AND a `title` attribute equal to `disabledReason(entity)` (e.g., `"Cluster archived 2026-04-01"`).
- When the operator clicks a disabled item.
- Then `onChange` does NOT fire; the trigger does NOT collapse.

### AC-9: Child-field reset preserved in create-study-modal

- Given the operator has selected cluster=`cluster-A`, query_set=`qs-A1`, judgment_list=`jl-A1-1`, template=`tpl-A1-x` in the wizard.
- When the operator changes the cluster from `cluster-A` to `cluster-B` via the `<EntitySelect>`.
- Then the `onChange` callback fires; the consumer's handler resets `query_set_id`, `judgment_list_id`, `template_id` to empty strings; the wizard's downstream dropdowns refetch with the new `cluster_id` parameter.

### AC-10: Form-select-discipline lint guard rejects inline literal

- Given a synthetic test file content with `<SelectItem value="completed">Completed</SelectItem>` AND an import `import { SelectItem } from '@/components/ui/select'`.
- When the vitest lint guard runs on the synthetic content.
- Then `validateFormSelect(filePath, content, enumsContent)` returns an error array containing a message naming the file path and the offending literal `"completed"` (which matches `STUDY_STATUS_VALUES`).

### AC-11: Form-select-discipline lint guard accepts mapped-from-enum pattern

- Given a synthetic test file content with `{STUDY_STATUS_VALUES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}` AND `import { STUDY_STATUS_VALUES } from '@/lib/enums';`.
- When the vitest lint guard runs on the synthetic content.
- Then `validateFormSelect` returns an empty error array (no violations).

### AC-12: Form-select-discipline lint guard rejects empty escape-hatch reason

- Given a synthetic test file content with `// no-enum-import:` at the top AND inline `<SelectItem value="completed">`.
- When the vitest lint guard runs.
- Then the result contains an error stating that the escape-hatch comment requires a non-empty reason.

### AC-13: All four migrated modals preserve their data-testid values

- Given the four migrated modals render in a test environment with mocked TanStack hooks.
- When the test queries the DOM via `getByTestId('qs-cluster')`, `getByTestId('cs-cluster')`, `getByTestId('cs-qs')`, `getByTestId('cs-jl')`, `getByTestId('cs-tpl')`, `getByTestId('cl-repo')`, `getByTestId('gen-template')`.
- Then each query returns a `SelectTrigger` element rendered by `<EntitySelect>` (NOT a hand-rolled `<Select>` element from the pre-migration state).

### AC-14: Tutorial Step 5 modal walkthrough leads, curl is demoted

- Given a fresh read of [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 5.
- When the reader scans for the cluster_id input instruction.
- Then the modal walkthrough ("Open /query-sets → click New query set → select cluster from dropdown") appears BEFORE the curl example; the curl example uses `cluster_id":"'$LOCAL_ES_ID'"` (shell substitution) NOT `cluster_id":"<local-es-id>"` (literal placeholder).

### AC-15: ui-architecture.md gains the "Form dropdown primitive" subsection

- Given a fresh read of [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md).
- When the reader scans for the documentation of `<EntitySelect>`.
- Then a "Form dropdown primitive" section appears adjacent to "DataTable primitive" (at or near current line 240). The new section documents the props API, the `useEntities` consumer contract, the status / warning / empty-state slots, and the explicit asymmetry to `DataTableFkSelect` (shadcn vs native).

### AC-16: CLAUDE.md "Enumerated Value Contract Discipline" gains form-coverage paragraph

- Given a fresh read of [`CLAUDE.md`](../../../../CLAUDE.md).
- When the reader scans the "Enumerated Value Contract Discipline" section.
- Then one new paragraph notes the new form-select-discipline lint guard, citing `ui/src/__tests__/components/common/form-select-discipline.test.tsx` and naming the rule (form components must not inline `<SelectItem value="literal">` for known backend enums).

---

## 13) Non-functional requirements

- **Performance:** The primitive adds zero net runtime overhead vs the hand-rolled equivalent — the same shadcn `<Select>` renders, the same TanStack `useQuery()` runs, the same DOM ships. Bundle-size delta is one new ~150 LOC source file (offset by deletions in the four migrated modals); net deletion expected.
- **Reliability:** No new error budget impact. The error and empty states are strictly better than current silent failures.
- **Operability:** No new logs, no new metrics, no new alerts. The lint guard runs in the existing vitest CI step; failure surfaces in the same PR check the column-discipline guard uses.
- **Accessibility/usability:** shadcn `<Select>` is built on Radix `<Select>` which is keyboard-accessible (arrow keys, type-to-search, Enter to select) and screen-reader-friendly (`role="combobox"`, `role="listbox"`, `role="option"`). The new status dot uses a Unicode `●` rendered inside a `<span>` with `aria-hidden="true"` so the dot doesn't pollute the spoken label; the screen-reader-relevant status is conveyed by the `title` attribute on the item and the inline warning text. Color is supplemented by position (green entries always first) so red-green color-blind users still get the priority signal.

---

## 14) Test strategy requirements (spec-level)

| Layer | Coverage |
|---|---|
| **Unit tests** (`ui/src/components/common/entity-select.test.tsx`) | All FR-1 through FR-6 behaviors: rendering with controlled value, loading state (FR-2), error state + retry (FR-3), empty state with + without CTA (FR-4), disabled subset + tooltip (FR-5), status dot rendering + sort + warning (FR-6). Mock `useEntities` with a synchronous fake. ~150-250 LOC of tests. |
| **Lint guard** (`ui/src/__tests__/components/common/form-select-discipline.test.tsx`) | FR-7: a real-glob scan over `ui/src/components/**/*.tsx` (excluding the standard subdirs) PLUS five synthetic regression cases per AC-10/11/12 + two more for the `// no-enum-import: <reason>` escape-hatch happy path and non-form-file-exclusion (e.g., a `*.column-config.tsx` file with inline literals passes this guard, since it's a different file family). Mirrors the structure of `data-table-column-discipline.test.tsx` (~80-100 LOC). |
| **Component integration tests** (`ui/src/__tests__/components/<resource>/<modal>.test.tsx`) | Existing modal test suites (if they exist; spec-stage `TBD` from §2 audit) get updated assertions for `<EntitySelect>`-rendered DOM. New scenarios per AC-13 (data-testid preservation), AC-9 (child-field reset), AC-7 (inline warning render). Real `QueryClientProvider` + mock fetch. |
| **E2E tests** (`ui/tests/e2e/*.spec.ts`) | No new E2E spec required. Existing E2E specs for the four migrated modals continue to pass without modification — preserved `data-testid` values are the contract. Plan-stage audit confirms no E2E spec needs an update; if any does, that's a Plan-stage discovery, not a spec-level commitment. |
| **Contract tests** | N/A — no backend changes. |

**Coverage gate:** the 80% backend Python coverage gate is unaffected (no Python changes). Frontend vitest does not have a coverage gate today; this feature does not add one.

---

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md`: new "Form dropdown primitive" subsection adjacent to "DataTable primitive" (FR-9, AC-15).
- `docs/02_product/`: post-merge, this feature folder moves from `planned_features/chore_form_dropdown_primitive/` to `implemented_features/<YYYY_MM_DD>_chore_form_dropdown_primitive/` per the `/impl-execute` finalization step.
- `docs/03_runbooks/`: no runbook update required (no operator-facing surface added).
- `docs/04_security/`: no security doc update required.
- `docs/05_quality/`: no testing-policy doc update required (the new lint guard is a vitest test, not a new test layer).
- `docs/08_guides/tutorial-first-study.md`: Step 5 reorder + curl pattern update (FR-9, AC-14).
- `CLAUDE.md`: one paragraph added to "Enumerated Value Contract Discipline" (FR-9, AC-16).
- `state.md`: post-merge update via the `/impl-execute` finalization step (add to recent changes; update active priorities).

---

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — frontend refactor with strictly-better UX. Ships in a single PR; no flag.
- **Migration/backfill expectations:** N/A — no schema, no data migration.
- **Operational readiness gates:** standard CI (lint, typecheck, vitest including the new form-select-discipline guard, Next.js build) must pass.
- **Release gate:** PR merge to `main` triggers no remote staging deploy in MVP1 (staging is local-only). Maintainer verifies locally via `cd ui && pnpm dev` and walking the four migrated modals once before merge.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-13 | Story 1.x — implement `<EntitySelect>` primitive | `entity-select.test.tsx` | `ui-architecture.md` |
| FR-2 | AC-2 | Story 1.x | `entity-select.test.tsx` | — |
| FR-3 | AC-3 | Story 1.x | `entity-select.test.tsx` | — |
| FR-4 | AC-4 | Story 1.x | `entity-select.test.tsx` | — |
| FR-5 | AC-8 | Story 1.x | `entity-select.test.tsx` | — |
| FR-6 | AC-5, AC-6, AC-7 | Story 1.x | `entity-select.test.tsx` | — |
| FR-7 | AC-10, AC-11, AC-12 | Story 2.x — lint guard | `form-select-discipline.test.tsx` | `CLAUDE.md` |
| FR-8 | AC-1, AC-4, AC-7, AC-9, AC-13 | Stories 3.x-3.4 — migrate 4 modals | existing modal test suites + `entity-select.test.tsx` | — |
| FR-9 | AC-14, AC-15, AC-16 | Story 4.x — docs | N/A | `ui-architecture.md`, `tutorial-first-study.md`, `CLAUDE.md` |

(Plan stage will assign concrete story IDs; the matrix here is at the FR↔AC↔doc level.)

---

## 18) Definition of feature done

This feature is complete when:

- [ ] `<EntitySelect>` ships at `ui/src/components/common/entity-select.tsx` with co-located vitest covering AC-1 through AC-8.
- [ ] Lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` ships with the synthetic regression cases for AC-10/11/12 and passes the real-glob scan.
- [ ] All four migrated modals (`create-query-set-modal.tsx`, `create-study-modal.tsx`, `register-cluster-modal.tsx`, `generate-judgments-dialog.tsx`) consume `<EntitySelect>` per FR-8; all `data-testid` and `id`/`htmlFor` values preserved.
- [ ] Tutorial Step 5 update lands per AC-14.
- [ ] `ui-architecture.md` + CLAUDE.md updates land per AC-15 + AC-16.
- [ ] CI green: `make lint`, `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all pass.
- [ ] No open questions remain in §19.

---

## 19) Open questions and decision log

### Open questions

(All preflight-stage open questions were locked during spec drafting — see decision log below.)

— None remaining at spec-finalize time.

### Decision log

- **2026-05-18 — Primitive built on shadcn `<Select>` (Radix), not native `<select>`.** Rationale: matches the surrounding form ecosystem; all four migrated modals already use shadcn `<Select>` for their hand-rolled FKs. Keeping the form-side primitive on shadcn means the migration is visually invisible to users; native would require restyling. The peer relationship to `DataTableFkSelect` is intentional and documented in §4 product principles + §11 architecture-doc update.
- **2026-05-18 — `getStatus` returns a 4-value union including `'unknown'`; primitive maps backend `'unreachable'` → `'unknown'` internally.** Rationale: callers can pass `(c) => c.health_check.status` directly without a switch statement; the primitive normalizes the wire variation. Both source-of-truth comments (in the primitive AND in callers' `getStatus` callsites) cite `HEALTH_STATUS_VALUES` per §7.4.
- **2026-05-18 — Status sort is "green-first, stable within tiers" (idea-level "green-first" tightened to precedence green=0, yellow=1, red=2, unknown=3).** Rationale: predictable for operators ("the safest choice is always at the top"); preserves caller-controlled ordering for ties. Alternative ("severity-sorted with red-most-recent first") rejected — would change semantics from "show me safe options first" to "show me dangerous options first," which is the wrong default for a creation flow.
- **2026-05-18 — `inlineWarning` rendered below the trigger as a `<p class="text-xs text-amber-600 mt-1">`.** Rationale: matches the existing helper-text styling at [`create-study-modal.tsx:265-267`](../../../../ui/src/components/studies/create-study-modal.tsx) (`schema.data` fields-discovered hint), so adjacent forms have consistent helper-text appearance. Alternatives (separate alert box, status-dot tooltip) rejected for not matching the existing visual language.
- **2026-05-18 — Disabled subset uses `disabledIds: ReadonlySet<string>`, not callback `isDisabled(entity): boolean`.** Rationale: simpler caller API; consumer pre-computes the set once per render rather than the primitive invoking a callback per item per render. Memory cost is bounded (≤200 entities). Callback flexibility is unnecessary for any MVP1 use case (the only disabled-state is "soft-deleted entity"). If a future use case needs callback flexibility, adding a `disabledFn?` prop later is non-breaking.
- **2026-05-18 — Empty-state CTA uses Next.js `<Link>` (same-tab navigation), no modal-close plumbing.** Rationale: route change unmounts the modal automatically via Next.js App Router. Adding an `onCtaClick` prop or `onClose` plumbing is unnecessary scaffolding.
- **2026-05-18 — Lint guard implemented as a vitest test, not an ESLint plugin or custom rule.** Rationale: mirrors the parent pattern (Story 2.13 `data-table-column-discipline.test.tsx`). Vitest runs in the existing `pnpm test` invocation; CI catches the regression in the same PR check. Adding an ESLint plugin would require new infrastructure (new dependency, new lint script, plugin registration) for zero additional safety vs the vitest approach.
- **2026-05-18 — `register-cluster-modal.tsx` config-repo field changes from conditionally-hidden to always-visible (with empty-state slot when no repos).** Rationale: hiding the field entirely when no repos exist is strictly less discoverable than showing the field with an empty-state CTA; tutorial-day debugging surfaces this regularly. The current behavior is a UX wart, not a deliberate design decision.
