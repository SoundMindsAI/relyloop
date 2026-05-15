# Feature Specification — Contextual help / tooltips (Phase 1)

**Date:** 2026-05-14
**Status:** Draft
**Owners:** soundminds.ai (product + engineering)
**Related docs:**
- [`idea.md`](idea.md) — origin + locked decisions
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — Next.js / shadcn / Tailwind frontend pattern
- [`docs/05_quality/testing.md`](../../../05_quality/testing.md) — test layer convention + 80% coverage gate

---

## 1) Purpose

RelyLoop's UI is dense with information-retrieval and Optuna concepts (NDCG@K, MAP, MRR, ERR, TPE sampler, median pruner, judgment scale 0–3, trial pruning, parameter importance, study state machine). The MVP1 tutorial walks a user through Study #1, but the moment they step off that scripted path — typically into the create-study modal Step 5 to launch Study #2 — they hit a 9-input form with raw enum values and no per-field guidance, and a study-detail digest panel that surfaces a parameter-importance chart and a `+2.1%` metric delta with no legend or direction indicator.

- **Problem:** the tutorial is currently the only onboarding surface; design partners who explore the UI hit a steep cliff at the first non-tutorial study and the study-detail digest panel.
- **Outcome:** a relevance engineer can launch their second study and interpret its digest without re-reading the tutorial, because every domain-jargon label has a one-click contextual definition grounded in the same allowlist the backend validates against.
- **Non-goal:** this feature does **not** add a glossary editor UI, per-tenant copy configuration, in-app product tours, video tutorials, or a knowledge-base subsystem. Copy is hardcoded TypeScript constants in `ui/src/lib/glossary.ts` and ships with the feature.

## 2) Current state audit

### Existing implementations

Across the entire shipped UI, **zero tooltips, info icons, or HoverCards exist**. Confirmed by `grep -rn "tooltip\|Tooltip" ui/src/components/ui/` returning no matches and by `@radix-ui/react-tooltip` being absent from [`ui/package.json`](../../../../ui/package.json). The only contextual-help affordances today:

- [`ui/src/components/studies/create-study-modal.tsx:483`](../../../../ui/src/components/studies/create-study-modal.tsx) — one inline `<p className="text-xs text-muted-foreground">` note explaining the max-trials / time-budget gate semantics. Phase 1 preserves it.
- [`ui/src/components/clusters/register-cluster-modal.tsx:98`](../../../../ui/src/components/clusters/register-cluster-modal.tsx), [`generate-judgments-dialog.tsx:99`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx), [`calibration-modal.tsx:109`](../../../../ui/src/components/judgments/calibration-modal.tsx) — `DialogDescription` one-liners (Phase 2 + 3 surfaces; out of Phase 1 scope but preserved when those phases land).
- [`ui/src/app/chat/[id]/page.tsx:191-209`](../../../../ui/src/app/chat/[id]/page.tsx) — security warning banner (Phase 3 surface; out of Phase 1 scope).

Two existing Popover consumers establish the project's Radix Popover pattern but use it for input forms rather than help:
- [`ui/src/components/judgments/override-popover.tsx`](../../../../ui/src/components/judgments/override-popover.tsx) — judgment rating override form.
- [`ui/src/components/query-sets/edit-query-popover.tsx`](../../../../ui/src/components/query-sets/edit-query-popover.tsx) — query metadata edit form.

The Phase 1 surface — create-study modal + study-detail page — touches 7 component files. None of them currently use `title=`, `aria-describedby`, or any tooltip primitive; only one `aria-label` exists nearby (in [`study-status-filter-chips.tsx:21`](../../../../ui/src/components/studies/study-status-filter-chips.tsx) on the `role="group"` wrapper).

### Navigation and link impact

None. This feature does not add, remove, or move pages, routes, or links. All work happens **inside** existing component bodies on existing routes (`/studies` and `/studies/[id]`).

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | navigates create-study modal + study-detail page; asserts on `data-testid` attributes (`study-name`, `study-best-metric`, `study-trial-count`, `trials-table`, `digest-narrative`, `digest-metric-delta`, `parameter-importance-chart`, `step-next`, `cs-search-space`, `create-study-submit`) | 1 file | **None required.** Tooltips wrap existing labels without removing or renaming any `data-testid`. Phase 1 adds new `data-testid` attributes for tooltip triggers (`tooltip-trigger-<key>`) and bodies (`tooltip-body-<key>`) so the next E2E pass can assert on them; existing assertions continue to pass unchanged. |

### Existing behaviors affected by scope change

- **Form submission behavior**: unchanged. Adding tooltip wrappers around `<Label>` elements does not alter the form's `react-hook-form` registration, validation, or submit handler.
- **Field validation**: unchanged. The existing `K_REQUIRED` set at [`create-study-modal.tsx:43`](../../../../ui/src/components/studies/create-study-modal.tsx) gating Step 5 validity stays as-is; tooltip copy explains the rule, doesn't enforce it.
- **Polling behavior on `/studies/[id]`**: unchanged. The 3-second TanStack Query refetch interval at [`studies/[id]/page.tsx:21`](../../../../ui/src/app/studies/[id]/page.tsx) is untouched.
- **`StatusBadge` rendering**: unchanged structurally and semantically. Phase 1 adds an adjacent `<InfoTooltip>` info icon immediately to the right of the badge (per FR-7); the badge itself is not the tooltip trigger and remains non-focusable. All existing `data-kind` / `data-value` attributes the badge component emits are preserved.

---

## 3) Scope

### In scope (Phase 1 — this spec)

- New shadcn `Tooltip` primitive at `ui/src/components/ui/tooltip.tsx` (first tooltip in the codebase).
- Two reusable wrappers: `InfoTooltip` and `HelpPopover` in `ui/src/components/common/`.
- Centralized glossary at `ui/src/lib/glossary.ts` — keyed by wire value, source-of-truth comments mirror the existing pattern in [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts).
- Tooltip application to **create-study modal** (Step 1 `target` field + Step 5 all 9 inputs: Metric, K, Direction, Max trials, Time budget, Parallelism, Sampler, Pruner, Seed).
- Tooltip application to **study detail page**: study-header status badge + Best metric + Trials breakdown; trials-table column headers (Status, Primary metric, Duration, Params) + sort-dropdown wire-value disambiguation; digest panel section headers (Parameter importance, Metric delta, Recommended config, Suggested follow-ups) + "Open PR…" button.

### Out of scope (Phase 2 + 3 — future MVP2 idea)

Per the idea's `Locked decisions` section, this spec covers Phase 1 only. The following are documented in [`idea.md`](idea.md) as future scope but are explicitly **not** part of this spec:

- Judgments review page tooltips (Phase 2).
- Calibration modal Cohen's κ help-popover (Phase 2).
- Proposals lifecycle tooltips (Phase 2).
- Cluster registration auth-kind tooltips (Phase 3).
- Chat composer example-prompts strip (Phase 3).
- Home-page first-run "start here" panel (Phase 3 — design-shape decision deferred to future MVP2 idea).

A `phase2_idea.md` and `phase3_idea.md` tracking artifact is created in Step 10 of spec generation so the deferred work is discoverable by future planning sessions.

### API convention check

- **No new endpoints.** This feature is frontend-only.
- **No router changes.** No file under `backend/app/api/` is modified.
- **Error envelope:** N/A — no API surface added.
- **Auth pattern:** N/A — no API surface added. MVP1 is single-tenant, no auth.

### Phase boundaries

- **Phase 1 (MVP1, this spec):** primitives + create-study modal + study-detail surface. Rationale: this is the steepest onboarding cliff per the idea audit — six unlabeled metric/sampler/pruner knobs in one form step, plus a digest panel whose chart and delta percentage have no legend.
- **Phase 2 (MVP2 — separate idea + spec):** judgments + proposals surfaces. Rationale: lower urgency for MVP1 alpha — engineers reach the judgments page only after running a study, by which time they've seen Phase 1's metric tooltips.
- **Phase 3 (MVP2 — separate idea + spec):** chat + cluster registration + home-page onboarding. Rationale: home-page "start here" panel is the only product-design-shaped item in the whole idea and benefits from waiting for design-partner feedback to inform layout (Stripe-style checklist vs. illustration vs. simple ordered list).

**Deferred phase tracking:** `phase2_idea.md` and `phase3_idea.md` will be created in this folder per the spec-gen Step 10 requirement.

---

## 4) Product principles and constraints

- **Glossary is the single source of truth for tooltip copy.** Every tooltip the feature ships in Phase 1 sources its copy from `ui/src/lib/glossary.ts`. Per-component string literals for tooltip bodies are forbidden — they'd reintroduce the drift risk CLAUDE.md's "Enumerated Value Contract Discipline" rule was written to prevent.
- **Every enum-related tooltip is grounded in a backend allowlist.** Each glossary entry whose key corresponds to a wire value (e.g., `"completed"`, `"tpe"`, `"ndcg"`) carries a `// Values must match <backend/path.py> <Symbol>` comment immediately above the entry, mirroring the established pattern in [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts).
- **Tooltip ≤ 140 chars; longer copy goes in a help-popover.** A single info icon never escalates from tooltip to popover at runtime — the wrapper a component author chooses dictates which.
- **Additive only.** Phase 1 must not change form submission behavior, validation, polling, or routing. Adding tooltips is a pure superset of today's UI.
- **Tooltips are keyboard- and screen-reader-accessible.** Radix's `@radix-ui/react-tooltip` provides the ARIA wiring (`aria-describedby` link from trigger to content; ESC to dismiss; focus-visible reveal). Phase 1 must not bypass these defaults.
- **No tenant-configurable copy.** RelyLoop is single-tenant through MVP3 ([`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)). Glossary copy is ships-with-the-code, not stored in DB.

### Anti-patterns

- **Do not** invent enum values for tooltip examples. Every value mentioned in tooltip copy (e.g., "queued", "completed", "tpe", "median") must exist in the backend allowlist cited in §7.4. Phantom values produce documentation drift that leaks into the next contributor's mental model.
- **Do not** inline tooltip copy in component files. Every tooltip body string lives in `ui/src/lib/glossary.ts`, even one-word copy. Inlining a single string today guarantees a second inline next quarter, then a third — drift compounds.
- **Do not** add `title=` HTML attributes as a tooltip fallback. Browser-native tooltips (a) have inconsistent timing across OSes, (b) cannot be styled to match the design system, (c) are skipped by some screen readers. Use only the Radix-based primitive.
- **Do not** wrap `<Label htmlFor=...>` elements in a way that breaks the label-input association. The `InfoTooltip` wrapper renders an info icon **next to** the label, not around it; the label's `htmlFor` continues to point at the input id.
- **Do not** render tooltips on every form field unconditionally. Tooltips appear only on fields whose meaning is non-obvious to a new user. The "Study name" field at Step 4 does **not** get a tooltip — its meaning is self-evident from the label.
- **Do not** mix glossary copy with UI strings for visible labels. The glossary is for **help text** that appears in tooltips/popovers. The visible field labels (`<Label>` text) stay as-is in the JSX — changing labels would be a separate UX decision out of this scope.
- **Do not** alter `data-testid` attributes on existing elements. The E2E suite at [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) asserts on specific `data-testid` values; any rename breaks the suite. New `data-testid` attributes for tooltip triggers and bodies are additive.

---

## 5) Assumptions and dependencies

- **Dependency:** `@radix-ui/react-tooltip` (new npm dep). **Status:** not yet in `ui/package.json`. **Risk if missing:** N/A — Phase 1 adds it. Match the project's tilde-pinning style; the tooltip package's 1.x track is independent of dialog/popover (their earliest 1.x is 1.2.1, latest 1.2.8 as of 2026-05-14), so pin `~1.2.8`.
- **Dependency:** `lucide-react`'s `Info` icon. **Status:** already in `ui/package.json` and imported by [`ui/src/components/ui/dialog.tsx:3`](../../../../ui/src/components/ui/dialog.tsx) (`X`) + [`ui/src/components/ui/select.tsx:3`](../../../../ui/src/components/ui/select.tsx) (`Check, ChevronDown`).
- **Dependency:** existing `ui/src/lib/enums.ts` source-of-truth file. **Status:** shipped (chore_proposals_source_filter_server_side timeframe). The glossary's source-of-truth comments mirror this file's pattern character-for-character.
- **Dependency:** existing `StatusBadge` component at [`ui/src/components/common/status-badge.tsx`](../../../../ui/src/components/common/status-badge.tsx). **Status:** shipped. Phase 1 wraps `<StatusBadge>` instances in tooltip triggers without modifying the component itself.
- **No backend dependency.** No FastAPI router, no Pydantic schema, no migration, no LLM call, no Arq worker.

---

## 6) Actors and roles

- Primary actor: **Relevance Engineer** (per umbrella spec §6) using the tool to set up and interpret studies.
- Role model: N/A — single-tenant install, no auth surface in MVP1.
- Permission boundaries: N/A — the feature is purely additive UI; no state mutation.

### Authorization

N/A — single-tenant install, no auth surface per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md).

### Audit events

N/A — `audit_log` lands at MVP2. Even when it does, this feature emits no state mutations — tooltips are read-only UI.

---

## 7) Functional requirements

### FR-1: Tooltip primitive

- The system **MUST** ship a shadcn-style `Tooltip` primitive at `ui/src/components/ui/tooltip.tsx` that wraps `@radix-ui/react-tooltip` and exposes `Tooltip`, `TooltipTrigger`, `TooltipContent`, and `TooltipProvider` exports.
- The system **MUST** style `TooltipContent` with Tailwind classes matching the existing shadcn primitives — same border, background, padding, font-size, and shadow as the dialog/popover primitives. Reference: [`ui/src/components/ui/dialog.tsx`](../../../../ui/src/components/ui/dialog.tsx), [`ui/src/components/ui/popover.tsx`](../../../../ui/src/components/ui/popover.tsx).
- The system **MUST** add `@radix-ui/react-tooltip` to `ui/package.json` `dependencies` with the same version pinning style as the existing `@radix-ui/*` deps (tilde-pinned).
- The system **MUST** render the Radix `TooltipProvider` once at the root of the App Router layout (or via the `Providers` wrapper component if one exists) so every `Tooltip` instance has a shared delay context.
- The system **MUST** include `motion-reduce:animate-none` (or equivalent — `motion-reduce:transition-none`) on any animation class applied to `TooltipContent` and `PopoverContent` to satisfy `prefers-reduced-motion: reduce` users. Radix primitives do **not** auto-disable Tailwind animation classes added at the project layer — the spec requires the project CSS itself to honor reduced-motion (AC-8).

### FR-2: `InfoTooltip` wrapper

- The system **MUST** ship `ui/src/components/common/info-tooltip.tsx` exporting `<InfoTooltip>`.
- The component **MUST** support two usage modes via discriminated props:
  - **Standalone mode** (default — used for the 21 label-adjacent Phase 1 placements): `<InfoTooltip glossaryKey="study.k" />`. Renders its own `<button type="button" aria-label="…">` containing the 14×14 `<Info />` icon. Used when the help affordance attaches next to a non-focusable text label (form labels, table column headers, dl labels, section labels).
  - **asChild mode** (used when the target is itself a focusable element): `<InfoTooltip glossaryKey="digest.open_pr_button" asChild><Button>Open PR…</Button></InfoTooltip>`. Does **not** render its own icon; instead uses Radix `TooltipTrigger asChild` so the child element becomes the trigger. Used for FR-9's Open PR button (both enabled and `aria-disabled` variants). The child element **MUST** already be focusable (a `<button>`, a `<Link>`, or have `tabIndex={0}`) — `asChild` mode does not add focus semantics.
- In standalone mode, the trigger button **MUST**:
  - Have `aria-label={glossary[key].ariaLabel ?? "More information"}` (FR-5).
  - Be focusable via Tab key, reveal the tooltip on hover and on keyboard focus.
  - Render the visible icon at 14×14 px in `text-muted-foreground`; the surrounding button hit area **MUST** be 24×24 px (button padding around the icon) per WCAG 2.2 SC 2.5.8 (Target Size — Minimum, AA).
- The wrapper **MUST** render the glossary entry's `short` field as the tooltip body — never `long`. The `short` field is required for any entry usable by `InfoTooltip` (FR-5).
- **`data-testid` rules:**
  - **Standalone mode:** the wrapper **MUST** assign `data-testid={\`tooltip-trigger-${glossaryKey}\`}` to the rendered button trigger and `data-testid={\`tooltip-body-${glossaryKey}\`}` to the tooltip content. Example: `data-testid="tooltip-trigger-study.k"`.
  - **asChild mode:** a single DOM node can carry only one `data-testid` attribute, and the child element typically already carries its own (e.g., `data-testid="open-pr-link"` on the digest-panel Open PR button). The wrapper **MUST NOT** override the child's `data-testid` — Radix `asChild` prop merging on a colliding `data-testid` is fragile. Instead, the wrapper **MUST** rely on the caller's existing testid for trigger-presence assertions and continue to assign `data-testid={\`tooltip-body-${glossaryKey}\`}` to the popover content for body-content assertions. E2E tests verify asChild triggers via the caller's existing testid AND verify the tooltip body via `tooltip-body-${key}`.
  - The glossary key is used **verbatim** (dotted, lowercase) — no transformation — in both the standalone trigger testid and the body testid.
- The wrapper **MUST** prop-type the `glossaryKey` as `ShortGlossaryKey` (FR-5) — TypeScript narrowing prevents `long`-only entries from being passed.
- The wrapper **MUST** silently render nothing (no error, no console warning) if the glossary key is not found — but TypeScript narrowing makes this case unreachable at compile time.

### FR-3: `HelpPopover` wrapper

- The system **MUST** ship `ui/src/components/common/help-popover.tsx` exporting `<HelpPopover glossaryKey="...">`.
- The wrapper **MUST** accept exactly one prop, `glossaryKey: LongGlossaryKey`, where `LongGlossaryKey` is the TypeScript-derived union of glossary keys whose entry has a `long: string` field (defined in FR-5). This narrows the prop type at compile time so `short`-only entries cannot be passed to `HelpPopover`.
- The wrapper **MUST** render the same 14×14 `<Info />` icon trigger inside a 24×24 `<button type="button" aria-label="...">` as `InfoTooltip` (FR-2), but use Radix `Popover` (not `Tooltip`) so click opens, click-outside or ESC closes, and the content body supports multi-line and list content.
- The wrapper **MUST** render the glossary entry's `long` field as the popover body. The `long` field accepts a minimal subset of Markdown (paragraphs, bullet lists, inline code) — render via `react-markdown` (already used by [`digest-panel.tsx:43`](../../../../ui/src/components/studies/digest-panel.tsx)) with the same `disallowedElements={['script', 'iframe', 'style']}` safety filter.
- The wrapper **MUST** assign `data-testid={\`popover-trigger-${glossaryKey}\`}` to the trigger and `data-testid={\`popover-body-${glossaryKey}\`}` to the content body. The glossary key is used verbatim (dotted, lowercase) — matching the FR-2 convention.
- A `HelpPopover` **MUST NOT** be used on a glossary key that has no `long` field; the `LongGlossaryKey` derived type makes this unreachable at compile time.

### FR-4: Glossary single source of truth

- The system **MUST** ship `ui/src/lib/glossary.ts` exporting:
  - A `glossary` object declared as `export const glossary = { ... } as const satisfies Record<string, GlossaryEntry>;` so the object preserves literal key types AND each entry's exact shape (FR-5). Plain `Record<string, GlossaryEntry>` annotation **MUST NOT** be used — it would collapse `keyof typeof glossary` to `string` and break the `ShortGlossaryKey` / `LongGlossaryKey` derivations.
  - A `GlossaryKey` TypeScript type derived as `keyof typeof glossary`.
  - The two narrowed types defined in FR-5: `ShortGlossaryKey` and `LongGlossaryKey`.
- The system **MUST** include a `// Source-of-truth: <backend/path.py> <Symbol>` comment above every group of entries that mirrors a backend enum. The comment cites the same backend symbol that the parallel entry in [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) cites.
- The system **MUST** use the following key-naming convention. Aggregate help keys (e.g., `study.metric`, `trial.status`) and per-wire-value keys (e.g., `study.metric.ndcg`, `trial.status.pruned`) coexist:

| Enum group | Per-wire-value key pattern (parity-required) | Aggregate key (for the column header / label itself) |
|---|---|---|
| Study status | `study.status.{queued\|running\|completed\|cancelled\|failed}` | (none — status appears only via badge; no aggregate label tooltip) |
| Trial status | `trial.status.{complete\|failed\|pruned}` | `trial.status` (column-header tooltip) |
| Trial sort | `trial.sort.{primary_metric_desc\|primary_metric_asc\|ended_at_desc\|ended_at_asc\|optuna_trial_number_asc}` | `trial.sort_by` (sort-label tooltip) |
| Metric | `study.metric.{ndcg\|map\|precision\|recall\|mrr\|err}` | `study.metric` (popover with all 6 definitions) |
| K | `study.k.{1\|3\|5\|10\|20\|50\|100}` | `study.k` (label tooltip — aggregate) |
| Direction | `study.direction.{maximize\|minimize}` | `study.direction` (label tooltip — aggregate) |
| Sampler | `study.sampler.{tpe\|random}` | `study.sampler` (popover with both definitions) |
| Pruner | `study.pruner.{median\|none}` | `study.pruner` (popover with both definitions) |

The per-wire-value entries are **all parity-required** (no group is exempt), even when Phase 1 UI only reads the aggregate key. This keeps the parity test simple (one rule for all enum groups) and pre-positions the glossary for Phase 2/3 to add per-value tooltips without re-running parity-test design.

- The system **MUST** export an `expectGlossaryGroundedAgainstEnums` test helper (in the same file or a sibling `glossary-test-helper.ts`) that asserts:
  - For each enum group above, every wire value in `enums.ts` has a matching `<prefix>.<value>` key in the glossary.
  - No extra `<prefix>.*` keys exist beyond the wire values (e.g., a phantom `study.status.archived` would fail the test).
  - Aggregate help keys (the right column of the table above) are **excluded** from the "no extra keys" check — they exist by design and are not parity-tracked against enum values.
- This unit test (FR-4 + AC-5) runs in `pnpm test` and gates merge.

### FR-5: Glossary entry shape

- A `GlossaryEntry` **MUST** be one of:
  - `{ short: string; ariaLabel?: string }` — tooltip-only entry (used by `InfoTooltip`).
  - `{ long: string; ariaLabel?: string }` — popover-only entry (used by `HelpPopover`).
  - `{ short: string; long: string; ariaLabel?: string }` — dual entry usable by either wrapper.
- `short` text **MUST** be ≤ 140 characters.
- `long` text **MUST** be ≤ 800 characters and **MAY** contain Markdown (paragraphs, bullet lists, inline `code`). It **MUST NOT** contain headings (h1–h6), images, tables, or HTML.
- The optional `ariaLabel` field is used by both wrappers for the button trigger's `aria-label` attribute (FR-2 / FR-3). If omitted, the wrapper falls back to `"More information"`. Concrete labels (e.g., `"More information about Metric"`) are preferred for screen-reader users.
- The glossary **MUST NOT** contain any HTML, raw URLs to internal pages (use Markdown links if needed), or tenant-specific values.
- The glossary **MUST NOT** contain backend file paths, function names, or symbol names in **user-visible** copy (`short`, `long`, `ariaLabel`). Backend grounding citations belong in TypeScript comments immediately above the entry or group, mirroring the [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) pattern (`// Values must match backend/app/api/v1/schemas.py StudyStatusWire.`).
- The system **MUST** export two derived types alongside the glossary:
  - `type ShortGlossaryKey = { [K in keyof typeof glossary]: typeof glossary[K] extends { short: string } ? K : never }[keyof typeof glossary]` — keys whose entry has a `short` field.
  - `type LongGlossaryKey = { [K in keyof typeof glossary]: typeof glossary[K] extends { long: string } ? K : never }[keyof typeof glossary]` — keys whose entry has a `long` field.
  Both unions are computed at compile time so `InfoTooltip` and `HelpPopover` props are correctly narrowed.

### FR-6: Phase 1 create-study modal tooltips

The system **MUST** attach exactly one help affordance (either `InfoTooltip` OR `HelpPopover`, never both on the same icon) immediately to the right of each `<Label>` element listed in the table below, without altering the label's `htmlFor`/`id` association.

| Step | Label text | Glossary key | Wrapper |
|---|---|---|---|
| 1 | `Target index / collection` | `study.target` | `InfoTooltip` |
| 3 | `Query template (filtered by engine)` | `study.template` | `InfoTooltip` |
| 5 | `Metric` | `study.metric` | `HelpPopover` (long body lists one-line definitions of NDCG / MAP / Precision / Recall / MRR / ERR) |
| 5 | `k` | `study.k` | `InfoTooltip` |
| 5 | `Direction` | `study.direction` | `InfoTooltip` |
| 5 | `Max trials` | `study.max_trials` | `InfoTooltip` |
| 5 | `Time budget (min)` | `study.time_budget_min` | `InfoTooltip` |
| 5 | `Parallelism` | `study.parallelism` | `InfoTooltip` |
| 5 | `Sampler` | `study.sampler` | `HelpPopover` (TPE vs random comparison) |
| 5 | `Pruner` | `study.pruner` | `HelpPopover` (median vs none comparison) |
| 5 | `Seed` | `study.seed` | `InfoTooltip` |

The system **MUST NOT** add help affordances to: `Cluster` (Step 1), `Query set` (Step 2), `Judgment list` (Step 2), `Study name` (Step 4), or `Search space (JSON)` (Step 4 textarea).

**Why Search space (JSON) is deferred** (despite the idea listing it): the textarea accepts a parameter-schema JSON object whose **shape varies by query template** — there is no single 140-char (or 800-char) explanation that covers every template's expected parameters without misleading the reader. A correct help affordance here needs either (a) a template-aware tooltip that reads the selected template's parameter schema, or (b) an external doc link with example shapes per template. Both are non-trivial; the future MVP2 idea picks this up after design-partner feedback surfaces whether it matters.

The system **MUST** preserve the existing inline note at [`create-study-modal.tsx:483`](../../../../ui/src/components/studies/create-study-modal.tsx) ("Provide either max trials or a time budget — both gates apply when both are set"). The new tooltips on Max trials and Time budget complement, not replace, this note.

### FR-7: Phase 1 study-header tooltips

- The system **MUST** render an `<InfoTooltip>` (standalone mode — adjacent icon, not asChild wrapping) immediately to the right of the `<StatusBadge kind="study" value={...}>` instance in [`study-header.tsx:16`](../../../../ui/src/components/studies/study-header.tsx). The badge itself remains non-focusable text per its current implementation; the help affordance is the adjacent info icon button.
- The glossary key for the status-badge tooltip resolves dynamically by status value. The dynamic lookup table **MUST** be typed as `Record<StudyStatus, ShortGlossaryKey>` (not `GlossaryKey`) so TypeScript enforces that every `study.status.*` entry has a `short` field (FR-2 requires `ShortGlossaryKey` for `InfoTooltip`). The five entries — `study.status.queued`, `study.status.running`, `study.status.completed`, `study.status.cancelled`, `study.status.failed` — are required by the FR-4 parity test.
- The system **MUST** attach an `InfoTooltip` to each of the following `<dt>` labels in study-header: `Best metric` (key: `study.best_metric`), `Trials` (key: `study.trials_summary`). The `Trials` tooltip explains the complete/failed/pruned breakdown.
- The system **MUST NOT** attach tooltips to: `Cluster`, `Target`, `Created`, `Started`, `Completed`, or `Failed reason` labels. The first four are self-explanatory; the failed-reason copy is dynamic.

### FR-8: Phase 1 trials-table tooltips

- The system **MUST** attach an `InfoTooltip` next to each of the following `<TableHead>` cells in [`trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx):
  - `Status` (key: `trial.status`) — describes complete/failed/pruned
  - `Primary metric` (key: `trial.primary_metric`) — describes "the metric this study optimizes"
  - `Duration (ms)` (key: `trial.duration_ms`) — describes "wall-clock time from enqueue to completion"
  - `Params` (key: `trial.params`) — describes "JSON of search-space parameter values used for this trial"
- The system **MUST** attach an `InfoTooltip` next to the `Sort by` label that explains the wire-value sort-key naming convention (e.g., `primary_metric_desc` = "highest primary metric first"). Key: `trial.sort_by`.
- The system **MUST NOT** attach tooltips to the `#` column header (a trial sequence number is self-evident).

### FR-9: Phase 1 digest-panel tooltips

- The system **MUST** attach an `InfoTooltip` next to each of the following section labels in [`digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx):
  - `Narrative` (key: `digest.narrative`)
  - `Parameter importance` (key: `digest.parameter_importance`) — explains 0–1 importance scores from Optuna's feature selection
  - `Metric delta` (key: `digest.metric_delta`) — explains baseline → best + direction interpretation
  - `Recommended config` (key: `digest.recommended_config`)
  - `Suggested follow-ups` (key: `digest.suggested_followups`)
- The system **MUST** wrap the enabled `Open PR…` button at [`digest-panel.tsx:88`](../../../../ui/src/components/studies/digest-panel.tsx) with `<InfoTooltip glossaryKey="digest.open_pr_button" asChild>` (FR-2 asChild mode). The button itself becomes the tooltip trigger — no extra adjacent icon. Glossary key copy clarifies that the button creates a GitHub PR in the cluster's config repo and that operator merge — not RelyLoop — triggers deployment.
- The system **MUST** wrap the disabled `Open PR (no pending proposal)` variant with `<InfoTooltip glossaryKey="digest.open_pr_disabled" asChild>`. Glossary key copy explains "the digest hasn't created a proposal yet — check back in a minute."
- **Accessibility — disabled button trigger pattern.** Native HTML `disabled` buttons cannot receive focus or pointer events, which breaks tooltip hover/focus reveal for keyboard users. The disabled `Open PR (no pending proposal)` variant **MUST** therefore use the `aria-disabled="true"` pattern instead of native `disabled`:
  - Render as `<Button aria-disabled="true" onClick={(e) => e.preventDefault()}>` — visually styled as disabled (the existing `disabled` Tailwind classes still apply via a conditional), focusable via Tab, with click activation blocked in the handler.
  - The `InfoTooltip asChild` wrap makes the focusable `aria-disabled` button the tooltip trigger, so keyboard users discover *why* it's disabled.
- **Clarifying note (re: scope):** the digest-panel's `Open PR…` button at [`digest-panel.tsx:87-95`](../../../../ui/src/components/studies/digest-panel.tsx) lives on `/studies/[id]` and is **Phase 1 scope** in this spec. A structurally different `Open PR` control rendered by [`proposals/pr-panel.tsx`](../../../../ui/src/components/proposals/pr-panel.tsx) lives on `/proposals/[id]` and is **Phase 2 scope** (deferred). Same button label, two different components, two different routes; tooltips on the proposals-page variant land in the future MVP2 idea.

### FR-10: Tooltip glossary content (Phase 1 scope only)

- The glossary **MUST** include entries for every key referenced by FR-6 through FR-9 above. The exact copy is part of the implementation plan, not this spec — but every entry **MUST** be ≤ 140 chars (short) or ≤ 800 chars (long) and **MUST** be technically accurate against the canonical project documentation (e.g., the metric definitions track [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md) where it exists, otherwise standard IR textbook definitions).
- User-visible copy (`short`, `long`, `ariaLabel` fields) **MUST NOT** contain backend file paths, function names, symbol names, or "see X" implementation references. The audience for tooltip copy is a relevance engineer using the product, not a contributor reading the source.
- Backend grounding citations **MUST** live in TypeScript comments **immediately above each glossary group** in `ui/src/lib/glossary.ts`, mirroring the established pattern in [`ui/src/lib/enums.ts:11-12`](../../../../ui/src/lib/enums.ts) — for example, immediately above the `study.status.*` entries:
  ```typescript
  // Source-of-truth: backend/app/api/v1/schemas.py StudyStatusWire (mirrored in ui/src/lib/enums.ts STUDY_STATUS_VALUES).
  // Copy must remain accurate as the enum evolves; the FR-4 parity test enforces key parity.
  'study.status.queued': { short: '…', ariaLabel: '…' },
  'study.status.running': { short: '…', ariaLabel: '…' },
  // …
  ```
  This keeps grep-traceability for future maintainers while shielding end users from internal references.

---

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — this feature adds no API endpoints.

### 8.2 Contract rules

N/A — no API surface.

### 8.3 Response examples

N/A — no API surface.

### 8.4 Enumerated value contracts

Every glossary entry whose key describes a backend-validated wire value is grounded in a backend allowlist. The feature **does not introduce new wire values**; it adds explanatory copy describing existing values. The following table enumerates every value the Phase 1 glossary describes, with its canonical backend source-of-truth file:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site |
|---|---|---|---|
| Study `status` | `queued`, `running`, `completed`, `cancelled`, `failed` | [`backend/app/api/v1/schemas.py:164`](../../../../backend/app/api/v1/schemas.py) `StudyStatusWire` | [`study-header.tsx:16`](../../../../ui/src/components/studies/study-header.tsx) (status badge) |
| Trial `status` | `complete`, `failed`, `pruned` | [`backend/app/api/v1/schemas.py:190`](../../../../backend/app/api/v1/schemas.py) `TrialStatusWire` | [`trials-table.tsx:67`](../../../../ui/src/components/studies/trials-table.tsx) (status column) |
| Trial sort key (`?sort=`) | `primary_metric_desc`, `primary_metric_asc`, `ended_at_desc`, `ended_at_asc`, `optuna_trial_number_asc` | [`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py) `TrialSortKey` Literal (re-exported by [`schemas.py:181`](../../../../backend/app/api/v1/schemas.py)) | [`trials-table.tsx:34`](../../../../ui/src/components/studies/trials-table.tsx) (sort dropdown) |
| Objective `metric` | `ndcg`, `map`, `precision`, `recall`, `mrr`, `err` | [`backend/app/api/v1/schemas.py:167`](../../../../backend/app/api/v1/schemas.py) `ObjectiveMetric` | [`create-study-modal.tsx:362`](../../../../ui/src/components/studies/create-study-modal.tsx) (Step 5 Metric select) |
| Objective `k` | `1`, `3`, `5`, `10`, `20`, `50`, `100` (integers, not strings) | [`backend/app/api/v1/schemas.py:170`](../../../../backend/app/api/v1/schemas.py) `ObjectiveK` | [`create-study-modal.tsx:382`](../../../../ui/src/components/studies/create-study-modal.tsx) (Step 5 k select) |
| Objective `direction` | `maximize`, `minimize` | [`backend/app/api/v1/schemas.py:172`](../../../../backend/app/api/v1/schemas.py) `ObjectiveDirection` | [`create-study-modal.tsx:400`](../../../../ui/src/components/studies/create-study-modal.tsx) (Step 5 Direction select) |
| `sampler` | `tpe`, `random` | [`backend/app/eval/types.py:30`](../../../../backend/app/eval/types.py) `SamplerKind` | [`create-study-modal.tsx:447`](../../../../ui/src/components/studies/create-study-modal.tsx) (Step 5 Sampler select) |
| `pruner` | `median`, `none` | [`backend/app/eval/types.py:33`](../../../../backend/app/eval/types.py) `PrunerKind` | [`create-study-modal.tsx:465`](../../../../ui/src/components/studies/create-study-modal.tsx) (Step 5 Pruner select) |

**Rules:**
- The glossary **MUST** include an entry for every value in each row above. The unit test from FR-4 (`expectGlossaryGroundedAgainstEnums`) enforces parity with [`enums.ts`](../../../../ui/src/lib/enums.ts).
- The `k` values are integers, not strings — `OBJECTIVE_K_VALUES = [1, 3, 5, 10, 20, 50, 100]` per [`enums.ts:77`](../../../../ui/src/lib/enums.ts). Glossary keys use the integer values stringified (e.g., `study.k.10`).
- **K-required semantics — frontend-only gate.** The backend `ObjectiveCreate` schema at [`backend/app/api/v1/schemas.py:406-408`](../../../../backend/app/api/v1/schemas.py) declares `k: ObjectiveK | None = None`, allowing `null` for any metric. The `K_REQUIRED` set at [`create-study-modal.tsx:43`](../../../../ui/src/components/studies/create-study-modal.tsx) — `new Set(['ndcg', 'precision', 'recall'])` — is a **frontend validation gate**, not a backend invariant. Glossary copy for `study.k` describes the rank-position-aware nature of NDCG/Precision/Recall and explains that the form requires K for those metrics, but **MUST NOT** describe `K_REQUIRED` as a backend rule. A future infrastructure idea may align backend validation with the frontend gate; until then, the gate is UI-side only.

### 8.5 Error code catalog

N/A — no API surface, no new error codes.

---

## 9) Data model and state transitions

N/A — this feature introduces no database tables, no columns, no migrations, no state transitions. It is pure frontend copy + presentation.

---

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Stored XSS via glossary Markdown rendering.** The `long` field of glossary entries is rendered via `react-markdown`. Mitigation: same `disallowedElements={['script', 'iframe', 'style']}` filter the digest narrative already uses ([`digest-panel.tsx:45`](../../../../ui/src/components/studies/digest-panel.tsx)). Since the glossary is hardcoded TypeScript constants (not user-supplied), this is defense-in-depth, not a realistic attack vector.
  2. **Copy drift exposes incorrect mental model.** A glossary entry that misdefines, e.g., what "pruned" means would mislead users. Mitigation: every wire-value entry cites the canonical backend symbol; the FR-4 unit test enforces glossary-enum parity.
  3. **Tooltip content reveals sensitive system internals.** Tooltips intentionally describe internal concepts (TPE sampler, parameter-importance scoring), but do not reveal cluster credentials, PATs, or any tenant data. Mitigation: glossary copy is reviewed in the implementation plan and contains no `${variable}` placeholders.
- **Controls:** standard Radix `aria-describedby` + ESC dismissal; `react-markdown` safety filter for popover bodies; TypeScript compile-time check on glossary keys.
- **Secrets/key handling:** N/A — no secrets touched.
- **Auditability:** N/A — read-only UI.
- **Data retention/deletion/export impact:** N/A — no user data.

---

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** all Phase 1 tooltips appear on existing routes (`/studies` → create-study modal; `/studies/[id]` → study detail). No new routes, no new nav items, no sidebar changes.
- **Labeling taxonomy:** tooltips augment existing labels but do NOT change them. The visible `<Label>` text for "Metric", "k", "Direction", etc. stays as it appears today. The glossary copy provides the *explanation*, not the *label*.
- **Content hierarchy:** info icon triggers sit immediately to the right of their label, vertically center-aligned, with 4px horizontal gap. The visible icon is muted (color `text-muted-foreground`) and 14×14 px; the surrounding `<button>` hit area is 24×24 px (WCAG 2.2 SC 2.5.8 — Target Size Minimum, AA). Small enough not to steal attention from the field, large enough to be a reliable click and keyboard-focus target.
- **Progressive disclosure:** tooltip reveals on hover OR keyboard focus, dismisses on mouseout / blur / ESC. Help-popover opens on click, dismisses on click-outside / ESC. Multi-paragraph guidance lives in popovers; one-line facts live in tooltips.
- **Relationship to existing pages:** purely additive. Phase 1 tooltips never replace or hide existing UI; they sit alongside labels that already render today.

### Tooltips and contextual help

This is the canonical tooltip inventory for Phase 1. Exact body copy is finalized in the implementation plan; the table below specifies placement, trigger, and content intent.

| Element | Tooltip / popover key (in glossary.ts) | Trigger | Placement | Wrapper |
|---|---|---|---|---|
| `Target index / collection` label (Step 1) | `study.target` | hover/focus | right of label | `InfoTooltip` |
| `Query template (filtered by engine)` label (Step 3) | `study.template` | hover/focus | right of label | `InfoTooltip` |
| `Metric` label (Step 5) | `study.metric` | click | right of label | `HelpPopover` (long body includes one-line definitions of NDCG/MAP/Precision/Recall/MRR/ERR) |
| `k` label (Step 5) | `study.k` | hover/focus | right of label | `InfoTooltip` |
| `Direction` label (Step 5) | `study.direction` | hover/focus | right of label | `InfoTooltip` |
| `Max trials` label (Step 5) | `study.max_trials` | hover/focus | right of label | `InfoTooltip` |
| `Time budget (min)` label (Step 5) | `study.time_budget_min` | hover/focus | right of label | `InfoTooltip` |
| `Parallelism` label (Step 5) | `study.parallelism` | hover/focus | right of label | `InfoTooltip` |
| `Sampler` label (Step 5) | `study.sampler` | click | right of label | `HelpPopover` (TPE vs random) |
| `Pruner` label (Step 5) | `study.pruner` | click | right of label | `HelpPopover` (median vs none) |
| `Seed` label (Step 5) | `study.seed` | hover/focus | right of label | `InfoTooltip` |
| Study status badge | `study.status.{value}` (5 keys: queued/running/completed/cancelled/failed) | hover/focus | right of badge | `InfoTooltip` (dynamic key lookup) |
| `Best metric` label (study-header) | `study.best_metric` | hover/focus | right of label | `InfoTooltip` |
| `Trials` label (study-header) | `study.trials_summary` | hover/focus | right of label | `InfoTooltip` |
| `Status` column header (trials-table) | `trial.status` | hover/focus | right of header text | `InfoTooltip` |
| `Primary metric` column header | `trial.primary_metric` | hover/focus | right of header text | `InfoTooltip` |
| `Duration (ms)` column header | `trial.duration_ms` | hover/focus | right of header text | `InfoTooltip` |
| `Params` column header | `trial.params` | hover/focus | right of header text | `InfoTooltip` |
| `Sort by` label (trials-table) | `trial.sort_by` | hover/focus | right of label | `InfoTooltip` |
| `Narrative` section label (digest) | `digest.narrative` | hover/focus | right of label | `InfoTooltip` |
| `Parameter importance` section label | `digest.parameter_importance` | hover/focus | right of label | `InfoTooltip` |
| `Metric delta` section label | `digest.metric_delta` | hover/focus | right of label | `InfoTooltip` |
| `Recommended config` section label | `digest.recommended_config` | hover/focus | right of label | `InfoTooltip` |
| `Suggested follow-ups` section label | `digest.suggested_followups` | hover/focus | right of label | `InfoTooltip` |
| `Open PR…` button (digest) | `digest.open_pr_button` | hover/focus | top of button | `InfoTooltip` |
| `Open PR (no pending proposal)` button (digest disabled state) | `digest.open_pr_disabled` | hover/focus | top of button | `InfoTooltip` |

**Guidelines for tooltip content (applied in the implementation plan):**
- Tooltip copy answers "what does this do?" or "why would I pick this value?" — not just the field name restated.
- Limits/thresholds are stated with consequences. The Max trials tooltip notes "300–500 is typical for a search-space of ~3 parameters; larger spaces need more."
- The Open PR button tooltips state the consequence (creates a GitHub PR; operator merge triggers deployment) — not what the click handler does technically.
- Tooltip copy under 140 chars; popover copy under 800 chars; the rest defers to docs/tutorial links.

### Primary flows

1. **Create-study modal flow.** User opens the modal, navigates Steps 1–5, encounters info icons next to dense fields, hovers/focuses to read the short copy, clicks the help-popover icons on Metric/Sampler/Pruner for longer guidance, submits the study. No flow change — only added affordances.
2. **Study detail interpretation flow.** User opens `/studies/[id]`, sees status badge + best-metric + trial-summary; hovers info icons to learn what each means; scrolls to the digest panel; reads the parameter-importance chart and metric-delta with their respective tooltips; clicks Open PR with the explanatory tooltip on the button.

### Edge/error flows

- **Tooltip on the disabled Open PR variant.** Native HTML `disabled` buttons cannot receive focus or pointer events, which would break tooltip hover/focus reveal for keyboard users. Phase 1 uses the **`aria-disabled="true"` pattern** (FR-9): the button is rendered without the native `disabled` attribute, stays focusable, has its click handler short-circuit with `e.preventDefault()`, and is visually styled as disabled via conditional Tailwind classes. The `InfoTooltip asChild` wrap then makes the focusable `aria-disabled` button the tooltip trigger. AC-11 asserts this.
- **Tooltip on the Step 5 "Next" button when validation fails.** Out of scope for Phase 1 — the Next button does not get a tooltip (per FR-6 exclusion list). Validation feedback already comes from the existing form state.
- **User toggles between hover and focus rapidly.** Radix's `TooltipProvider` `delayDuration` prop sets the open delay; default 700ms. Phase 1 uses the default — fast enough to feel responsive, slow enough to avoid flicker.
- **Glossary key typo at compile time.** TypeScript's `ShortGlossaryKey` / `LongGlossaryKey` (FR-5) catch typos at build time. The CI lint job (`pnpm typecheck` per CLAUDE.md "Build, Test, and Lint Commands") fails on a typo before merge.
- **Glossary entry referencing a wire value that no longer exists in `enums.ts`.** The FR-4 unit test (`expectGlossaryGroundedAgainstEnums`) fails. This is caught in `pnpm test` before merge.

---

## 12) Given/When/Then acceptance criteria

### AC-1: Help-trigger button renders next to every Phase 1 label
- **Given** a user opens the create-study modal and navigates through Steps 1, 3, and 5
- **When** the modal renders
- **Then** a `<button type="button">` containing an `<Info />` icon is present immediately to the right of each label in the FR-6 table (Step 1: Target; Step 3: Query template; Step 5: Metric, k, Direction, Max trials, Time budget, Parallelism, Sampler, Pruner, Seed — 11 buttons total)
- **And** each standalone-mode button has `data-testid={\`tooltip-trigger-${key}\`}` or `data-testid={\`popover-trigger-${key}\`}` matching the FR-6 mapping, with the key value used verbatim (dotted, lowercase, e.g., `tooltip-trigger-study.k`, `popover-trigger-study.metric`). asChild-mode triggers (FR-9 Open PR variants) keep their caller-supplied testid per FR-2 — verified via the caller's existing `open-pr-link` / `open-pr-disabled` selectors.
- **And** each button has a non-empty `aria-label` attribute
- **And** opening or dismissing a tooltip does not submit the create-study form or change the modal's open state (the tooltip's outside-click dismissal is local to the tooltip, not the modal — Radix default)

### AC-2: Hover reveals tooltip body
- **Given** a user has the create-study modal open at Step 5
- **When** the user hovers the info icon next to the `k` label for ≥ 700 ms (Radix default)
- **Then** the tooltip body appears with `data-testid="tooltip-body-study.k"` rendering the glossary entry's `short` text
- **And** the tooltip dismisses within ≤ 200 ms of mouseout

### AC-3: Keyboard accessibility (InfoTooltip)
- **Given** a user is navigating the create-study modal Step 5 with the keyboard
- **When** the user Tabs to the info icon next to the `k` label (an `InfoTooltip` per FR-6)
- **Then** the button receives focus (`:focus-visible` ring renders)
- **When** focus stays on the button
- **Then** the tooltip body appears (Radix opens-on-focus for keyboard users — `InfoTooltip` opens on hover OR focus)
- **When** the user presses ESC
- **Then** the tooltip dismisses and focus stays on the button
- Note: `HelpPopover` keyboard activation (click / Enter / Space) is covered by AC-4. `InfoTooltip` and `HelpPopover` have different keyboard reveal semantics by design.

### AC-4: Help-popover opens on click and closes on ESC / outside-click
- **Given** the create-study modal is at Step 5
- **When** the user clicks the info icon next to the Metric label (HelpPopover, per FR-6)
- **Then** the popover body opens with `data-testid="popover-body-study.metric"` rendering Markdown-formatted definitions of all 6 metrics
- **When** the user presses ESC
- **Then** the popover closes and focus returns to the trigger
- **When** the user clicks anywhere outside the popover
- **Then** the popover closes

### AC-5: Glossary parity with enums (unit test)
- **Given** the glossary at `ui/src/lib/glossary.ts` defines entries for the study-status group
- **When** `vitest run` executes the FR-4 `expectGlossaryGroundedAgainstEnums` test for `study.status.*`
- **Then** the test asserts the glossary keys `study.status.queued`, `study.status.running`, `study.status.completed`, `study.status.cancelled`, `study.status.failed` exist (one per value in `STUDY_STATUS_VALUES`)
- **And** no extra `study.status.*` keys exist
- **And** the same parity holds for trial status, trial sort, metric, k, direction, sampler, pruner

### AC-6: Phase 1 does not regress existing behavior
- **Given** an operator runs the existing Playwright suite `pnpm playwright test` against the Phase 1 build
- **When** [`studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) executes
- **Then** every assertion that passed before Phase 1 still passes
- **And** create-study form submission still produces a study with the same wire payload
- **And** the trials-table sort dropdown still emits the same `?sort=` query parameter values

### AC-7: Dynamic glossary key lookup for status badges
- **Given** a study has status `completed`
- **When** the study-header renders
- **Then** the InfoTooltip wrapping the status badge resolves `study.status.completed` from the glossary
- **And** the tooltip body contains the completed-status explanation

### AC-8: Reduced motion respected via project CSS
- **Given** the user has `prefers-reduced-motion: reduce` set
- **When** any tooltip or popover opens
- **Then** the appearance animation is instantaneous or bypassed
- **And** the `TooltipContent` className includes `motion-reduce:animate-none` (or `motion-reduce:transition-none`) — Radix primitives do NOT auto-disable Tailwind animation classes added at the project layer, so the project CSS itself must respect `prefers-reduced-motion`
- **And** the same `motion-reduce:*` class is applied to `PopoverContent`
- **And** a vitest component test asserts these className tokens are present on the rendered content (or that no animation classes are applied at all)

### AC-9: No tooltip on out-of-scope labels
- **Given** the create-study modal is at Step 4 (Search space)
- **When** the modal renders
- **Then** no info icons appear next to `Study name` or `Search space (JSON)` labels (per FR-6)
- **And** no info icons appear anywhere outside the Phase 1 surfaces listed in FR-6 through FR-9

### AC-10: Component-level rendering sanity (vitest)
- **Given** the `InfoTooltip` component is rendered in isolation in a vitest component test
- **When** the test provides `glossaryKey="study.k"`
- **Then** the rendered output contains a `<button>` element with the `<Info />` icon SVG inside
- **And** after the test fires a focus event, the `short` text appears (Radix opens on focus)
- **And** the button has a non-empty `aria-label` attribute

### AC-11: Disabled "Open PR" tooltip remains reachable
- **Given** a completed study has no pending proposal yet
- **When** the study-detail page renders the disabled `Open PR (no pending proposal)` button
- **Then** the button has `aria-disabled="true"` (not the native `disabled` attribute)
- **And** the button is focusable via Tab key
- **And** the InfoTooltip wrapper around the button reveals the `digest.open_pr_disabled` body on hover or focus
- **And** clicking the button does not navigate or fire the click handler

### AC-12: Glossary copy contains no backend references
- **Given** the glossary at `ui/src/lib/glossary.ts`
- **When** a unit test scans every entry's `short`, `long`, and `ariaLabel` string fields
- **Then** no field contains a path matching `/backend\//`, no field contains `.py` as a substring, and no field contains a Python symbol pattern (e.g., `StudyStatusWire`, `SamplerKind`, `K_REQUIRED`)
- **And** the TypeScript comments above each glossary group (in the file source, not in the user-visible strings) DO cite backend symbols per FR-10

---

## 13) Non-functional requirements

- **Performance:**
  - Tooltip primitives add < 5KB gzipped to the client bundle. `@radix-ui/react-tooltip` is comparable to `@radix-ui/react-popover` (~3KB gz) which already ships.
  - No SSR penalty — tooltips are client-only (`'use client'` directive on the wrapper file) and never render content on the server.
  - No layout-shift on tooltip open: Radix portals the content above the page rather than reflowing inline.
  - Glossary lookup is O(1) — a TypeScript-typed object literal access, no runtime parsing.
- **Reliability:** N/A — no backend impact, no SLO change.
- **Operability:** no new logs, no new metrics, no new alerts. The feature is invisible to ops.
- **Accessibility (WCAG 2.1 AA):**
  - **Button semantics, not raw icons.** The trigger is a `<button type="button" aria-label="...">` element (FR-2 / FR-3), not a focusable `<span>` or `<svg>`. This satisfies WCAG 4.1.2 (Name, Role, Value): screen readers announce "Button: More information about Metric" rather than an unnamed graphic.
  - **Accessible name.** Each glossary entry's optional `ariaLabel` field provides the button's accessible name. Concrete labels (e.g., `"More information about NDCG"`) are preferred over generic `"More information"`.
  - **Color contrast.** The info icon uses `text-muted-foreground` against the Card background. Verified to meet 4.5:1 contrast in the existing design system (the same color is used by `DialogDescription` and section labels that have shipped with passing axe scans).
  - **Keyboard reachable.** The button is in the natural tab order. Tooltip reveals on `:focus-visible`; popover opens on click/Enter/Space. ESC dismisses both. Radix wires these defaults.
  - **Screen reader friendly.** `aria-describedby` link from trigger to content (Radix default). The popover body is an ARIA-labelled region so screen readers read the long copy.
  - **Touch target size.** 24×24 button hit area satisfies **WCAG 2.2 SC 2.5.8 — Target Size (Minimum)**, Level AA (24×24 minimum). Note: WCAG 2.1 SC 2.5.5 is the AAA criterion at 44×44 and is intentionally not claimed here; raising to 44×44 would make the help-icon button visually dominate the labels it sits next to.
  - **Reduced motion.** All animation classes on tooltip/popover content carry `motion-reduce:animate-none` (or omit animation entirely) per FR-1. AC-8 asserts this.
  - **Disabled-button reachability.** The disabled "Open PR" variant uses `aria-disabled="true"` (not `disabled`) so the tooltip trigger remains focusable for keyboard users (FR-9).

---

## 14) Test strategy requirements (spec-level)

| Layer | Path | What to cover |
|---|---|---|
| Unit / component (vitest) | [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) (new) | `expectGlossaryGroundedAgainstEnums` parity check (AC-5); short/long length bounds (FR-5); no-backend-refs assertion on user-visible copy (AC-12); Markdown safety filter on `long` bodies (FR-3). |
| Component (vitest + Testing Library) | [`ui/src/__tests__/components/common/info-tooltip.test.tsx`](../../../../ui/src/__tests__/components/common/info-tooltip.test.tsx) (new) | Standalone mode renders `<button>` trigger with `aria-label` (AC-1, AC-10); hover reveals body (AC-2); focus reveals body (AC-3); ESC dismisses (AC-3); asChild mode uses the child as trigger (FR-2); `motion-reduce:animate-none` class present on content (AC-8). |
| Component (vitest + Testing Library) | [`ui/src/__tests__/components/common/help-popover.test.tsx`](../../../../ui/src/__tests__/components/common/help-popover.test.tsx) (new) | Click opens body (AC-4); ESC closes; outside-click closes; Markdown-list renders as semantic `<ul>`; safety filter strips `<script>` in a malicious-input test; `motion-reduce:animate-none` class present on content (AC-8). |
| Integration / hook | N/A | No backend, no service-layer hooks. |
| Contract | N/A | No API surface. |
| E2E (Playwright) | [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) (extend) | (1) **Table-driven trigger-inventory assertion** — declare the full Phase 1 expected-trigger inventory as a `data-testid` list (the 11 create-study modal triggers from FR-6 + the 3 study-header triggers from FR-7 + the 5 trials-table triggers from FR-8 + the 7 digest-panel triggers from FR-9 = 26 triggers) and assert each one is present on its respective rendered surface. (2) **Sampled interaction assertions** — hover/focus reveals body for at least one `InfoTooltip` and one `HelpPopover` (AC-2, AC-4); ESC dismisses both (AC-3, AC-4); disabled Open PR variant is focusable and reveals its tooltip on focus (AC-11). (3) **Regression** — existing flow assertions in `studies.spec.ts` still pass (AC-6). The E2E run hits the real backend per CLAUDE.md (no `page.route()` mocking). |

Coverage gate per CLAUDE.md: backend coverage gate (80%) is unaffected; UI tests counted via the vitest run that already happens in CI (`pnpm test`). Phase 1 adds ~15–20 new test cases.

E2E mocking policy reminder (CLAUDE.md): Playwright tests **must use the real backend** via `page` (no `page.route()` mocking). The Phase 1 E2E additions only assert on DOM elements that render statically — they require no backend mocking and don't add new backend dependencies.

---

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` — append a paragraph under the existing UI primitives section noting the new `Tooltip` primitive and the `InfoTooltip` + `HelpPopover` wrapper convention.
- `docs/02_product/planned_features/feat_contextual_help/` — this `feature_spec.md`, plus `phase2_idea.md` and `phase3_idea.md` deferred-phase trackers.
- `docs/05_quality/testing.md` — no change (the existing test layer convention already covers vitest unit/component + Playwright E2E).
- `state.md` — add a "Recent meaningful changes" entry when the feature ships; update the "Most recent meaningful changes" and any backlog-summary line.
- `CLAUDE.md` — no change. The existing "Enumerated Value Contract Discipline" rule already governs how the glossary entries are sourced.
- Tutorial ([`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md)) — no change for Phase 1. The tutorial keeps its current detail level; the tooltips reduce dependence on the tutorial but don't make it stale.

---

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. The feature is additive UI; no flag is warranted. Tooltips appear immediately on the next deploy after merge.
- **Migration/backfill:** N/A — no schema.
- **Operational readiness gates:** `pnpm test` (vitest) green, `pnpm playwright test` green, `pnpm typecheck` green, `pnpm lint` green. No runbook changes.
- **Release gate:** all gates above, plus CI pipeline (`.github/workflows/pr.yml`) green on the PR. No new gates introduced.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories (per implementation plan) | Test files |
|---|---|---|---|
| FR-1 (Tooltip primitive + motion-reduce) | AC-1, AC-2, AC-3, AC-8 | Story 1.1 (primitive + provider wiring) | info-tooltip.test.tsx |
| FR-2 (InfoTooltip wrapper, button + aria-label) | AC-1, AC-2, AC-3, AC-7, AC-10 | Story 1.2 (wrapper + tests) | info-tooltip.test.tsx |
| FR-3 (HelpPopover wrapper, button + aria-label) | AC-1, AC-4 | Story 1.3 (wrapper + tests) | help-popover.test.tsx |
| FR-4 (Glossary source-of-truth + parity test) | AC-5, AC-12 | Story 1.4 (glossary file + parity test) | glossary.test.ts |
| FR-5 (Entry shape + derived key types) | AC-5 | Story 1.4 (TS types in glossary) | glossary.test.ts |
| FR-6 (Create-study modal tooltips) | AC-1, AC-2, AC-3, AC-4, AC-9 | Story 2.1 (modal wiring) | studies.spec.ts |
| FR-7 (Study-header tooltips) | AC-1, AC-7 | Story 2.2 (header wiring) | studies.spec.ts |
| FR-8 (Trials-table tooltips) | AC-1 | Story 2.3 (table wiring) | studies.spec.ts |
| FR-9 (Digest-panel + Open PR + disabled aria-disabled) | AC-1, AC-11 | Story 2.4 (digest wiring) | studies.spec.ts |
| FR-10 (Glossary content + no backend refs in user copy) | AC-5, AC-10, AC-12 | Story 1.4 (initial copy) + reviewed in 2.1–2.4 | glossary.test.ts, info-tooltip.test.tsx |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-12) pass in CI.
- [ ] Vitest unit + component tests green; Playwright E2E green.
- [ ] `pnpm typecheck` clean (no glossary key typos).
- [ ] `pnpm lint` clean.
- [ ] Glossary parity test (AC-5) green for all 8 backend-enum-grounded groups in §8.4.
- [ ] `docs/01_architecture/ui-architecture.md` updated to mention the new Tooltip primitive and wrappers.
- [ ] `phase2_idea.md` and `phase3_idea.md` exist in this folder so deferred work is tracked.
- [ ] No open questions remain in §19.
- [ ] Gemini Code Assist review on the PR adjudicated per the four-quadrant rubric (CLAUDE.md).
- [ ] Final GPT-5.5 review per `/impl-execute` Step 6 returns no unresolved High findings.

## 19) Open questions and decision log

### Open questions

None. The idea was preflighted twice and all open forks were resolved:
- MVP scope → MVP1 Phase 1 only (locked in idea Locked Decisions §1).
- Glossary centralization → `ui/src/lib/glossary.ts` from day one (idea Locked Decisions §2).
- Icon source → `lucide-react`'s `Info` (idea Locked Decisions §3).
- Tooltip vs popover usage rule → length-based (idea Locked Decisions §4).
- Phase 3 "start here" panel design → deferred to future MVP2 idea, not locked here.

### Decision log

- 2026-05-14 — Folder name stays `feat_contextual_help` (not `_mvp2` suffix) because Phase 1 ships in MVP1. Phases 2 + 3 get their own folder in MVP2.
- 2026-05-14 — Glossary key naming uses dotted lowercase (`study.metric.ndcg`, `trial.status.pruned`) to mirror the wire-value path and stay greppable.
- 2026-05-14 — Search-space JSON textarea (Step 4 of create-study modal) is **not** tooltipped in Phase 1. Its content is too domain-specific (the JSON schema varies by template) to be summarized in a 140-char tooltip; if user feedback surfaces it as a need, the future MVP2 idea picks it up.
- 2026-05-14 — `trial_timeout_s` is in the `FormValues` type at `create-study-modal.tsx:64` but is **not** rendered as a UI input today; the idea originally listed it as a tooltip target but it has no on-screen label to attach to. Dropped from the FR-6 inventory.
- 2026-05-14 — Cross-model review cycle 1 (GPT-5.5): 12 findings (9 High, 2 Medium, 1 Medium-disagreed). Accepted 11, rejected 1 with cited counter-evidence. Applied: stronger TypeScript narrowing via `ShortGlossaryKey` / `LongGlossaryKey` derived types (FR-2, FR-3, FR-5); `<button>` + `aria-label` semantics on the trigger (FR-2, FR-3, §13); `aria-disabled` pattern for the disabled Open PR button (FR-9, AC-11); `motion-reduce:animate-none` requirement (FR-1, AC-8); restored `Query template` tooltip (FR-6); explicit deferral rationale for Search space JSON (FR-6); moved backend citations out of user-visible glossary copy into TS comments above each group (FR-10, AC-12); reframed `K_REQUIRED` as a frontend gate (§8.4 K-required rule); extended E2E coverage to all four Phase 1 subsurfaces (§14); rewrote FR-6 as a clean per-label wrapper-mapping table; standardized `data-testid` on the verbatim dotted glossary key (FR-2, FR-3, AC-1). Rejected: GPT-5.5 flagged Open PR tooltip as Phase 2 scope drift — counter-evidence at [`digest-panel.tsx:87-95`](../../../../ui/src/components/studies/digest-panel.tsx) vs. [`proposals/pr-panel.tsx`](../../../../ui/src/components/proposals/pr-panel.tsx) shows two structurally different Open PR controls on two routes; the digest-panel variant is correctly Phase 1, the proposals-page variant is correctly Phase 2 (clarifying note added to FR-9).
- 2026-05-14 — Cross-model review cycle 2 (GPT-5.5, post-patch): 7 findings (2 High, 4 Medium, 1 Low). Accepted all 7; no repeats from cycle 1. Applied: `asChild` discriminated-prop mode on `InfoTooltip` so existing buttons/badges can be tooltip triggers without an extra adjacent icon (FR-2, FR-9 Open PR wrapping); `as const satisfies Record<string, GlossaryEntry>` declaration pattern + glossary key parity-prefix table (FR-4); reframed AC-1's outside-click clause as "opening/dismissing a tooltip doesn't submit the form or close the modal"; table-driven E2E trigger-inventory assertion over the full 26-trigger Phase 1 set (§14); aligned AC-8 with FR-1's motion-reduce requirement (dropped "Radix handles this by default"); corrected WCAG SC citation from 2.1 SC 2.5.5 (44×44 AAA) to 2.2 SC 2.5.8 (24×24 Minimum, AA) for the touch-target claim (§11, §13).
- 2026-05-14 — Cross-model review cycle 3 (GPT-5.5, convergence check): 5 findings (3 High, 2 Medium). Accepted all 5; no repeats from cycles 1 or 2. Applied: tightened FR-7's dynamic status-badge lookup type from `Record<StudyStatus, GlossaryKey>` to `Record<StudyStatus, ShortGlossaryKey>`; dropped the "optional" marking on `study.k.*` and `study.direction.*` per-wire-value entries (now uniformly parity-required across all 8 enum groups, FR-4 table); changed AC-3 keyboard-focus target from Metric (a `HelpPopover` that opens on click) to `k` (an `InfoTooltip` that opens on focus); rewrote §11 Edge/error flows to use the FR-9 `aria-disabled` pattern (dropped stale span-wrapper guidance); standardized §2 + FR-7 on adjacent-icon (Pattern A) for the non-focusable StatusBadge. **Convergence reached** — 3 cycles per protocol; cycle 3 surfaced only patch-induced drift from prior cycles, no new architectural issues. The spec is internally consistent.
- 2026-05-14 — Spec FR-2 + AC-1 patched during plan-gen cycle 2 review (GPT-5.5): clarified the `data-testid` rules to handle the asChild DOM-collision constraint. Standalone mode keeps `tooltip-trigger-${key}` on the wrapper-rendered button; asChild mode (only the 2 Open PR variants in FR-9) relies on the caller's existing testid (`open-pr-link` / `open-pr-disabled`) and continues to assign `tooltip-body-${key}` on the popover content. A DOM node can carry only one `data-testid`; Radix `asChild` prop merging on a colliding `data-testid` is fragile. Body testid is unchanged in both modes. Rationale: this is the only viable resolution; making the asChild wrapper override the child's testid would force a breaking E2E update for unrelated assertions in `studies.spec.ts` that reference `open-pr-link` / `open-pr-disabled`.
