# Implementation Plan — Contextual Help (Phase 1)

**Date:** 2026-05-14
**Status:** Complete (PR #122, merged 2026-05-15)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`idea.md`](idea.md) (locked decisions), [`CLAUDE.md`](../../../../CLAUDE.md) ("Enumerated Value Contract Discipline" rule)

---

## 0) Planning principles

- Frontend-only feature; no backend, no migration, no API surface.
- Every story traces back to an FR in the spec via §1 traceability.
- Glossary is the single source of truth for tooltip/popover copy — never inline.
- Every wire-value-keyed glossary group cites the backend source file mirroring [`enums.ts`](../../../../ui/src/lib/enums.ts).
- Tests at every layer the feature touches: vitest unit (glossary parity) + vitest component (wrappers) + Playwright E2E (full Phase 1 trigger inventory).
- Phase 1 only. Phases 2 + 3 are tracked separately in [`phase2_idea.md`](phase2_idea.md) and [`phase3_idea.md`](phase3_idea.md); they are explicitly out of scope for this plan.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (Tooltip primitive + motion-reduce) | Epic 1 / Story 1.1 | New shadcn primitive at `ui/src/components/ui/tooltip.tsx`; new npm dep `@radix-ui/react-tooltip` (~1.1.15); `TooltipProvider` wired into `app/layout.tsx`. |
| FR-2 (`InfoTooltip` wrapper, standalone + asChild) | Epic 1 / Story 1.2 | New wrapper at `ui/src/components/common/info-tooltip.tsx`. |
| FR-3 (`HelpPopover` wrapper) | Epic 1 / Story 1.3 | New wrapper at `ui/src/components/common/help-popover.tsx`. |
| FR-4 (Glossary source-of-truth + parity test) | Epic 1 / Story 1.4 | New file `ui/src/lib/glossary.ts` + parity test helper. |
| FR-5 (Entry shape + derived key types) | Epic 1 / Story 1.4 | `ShortGlossaryKey` / `LongGlossaryKey` derived types co-located with the glossary. |
| FR-6 (Create-study modal tooltips) | Epic 2 / Story 2.1 | 11 placements (target, query template, metric, k, direction, max_trials, time_budget_min, parallelism, sampler, pruner, seed). |
| FR-7 (Study-header tooltips) | Epic 2 / Story 2.2 | 3 placements (adjacent-to-badge dynamic key, Best metric, Trials). |
| FR-8 (Trials-table tooltips) | Epic 2 / Story 2.3 | 5 placements (Status, Primary metric, Duration (ms), Params column headers + Sort label). |
| FR-9 (Digest-panel + Open PR + aria-disabled pattern) | Epic 2 / Story 2.4 | 7 placements (5 section headers + 2 Open PR variants via `asChild` wrap). Includes the aria-disabled refactor on the disabled Open PR button. |
| FR-10 (Glossary content + no-backend-refs-in-user-copy) | Epic 1 / Story 1.4 (initial content) + Stories 2.1–2.4 (per-surface review during application) | Final copy converges as the surfaces are wired. AC-12 test asserts user-visible strings contain no backend file paths / symbol names. |

**Deferred-phase tracking:** [`phase2_idea.md`](phase2_idea.md) and [`phase3_idea.md`](phase3_idea.md) already exist in this folder; no FR is silently deferred.

## 2) Delivery structure

Three epics: **Primitives & Glossary** (4 stories), **Phase 1 Surface Application** (4 stories), **Test Coverage & Docs** (2 stories). 10 stories total.

### Conventions (frontend, RelyLoop MVP1)

- All new client components carry `'use client'` directive.
- `<Info />` icon from `lucide-react` at 14×14 px; trigger button hit area 24×24 px (WCAG 2.2 SC 2.5.8).
- Glossary keys are dotted lowercase (`study.metric`, `trial.status.pruned`); never transformed in `data-testid` (use verbatim).
- New tests live at `ui/src/__tests__/` mirroring source tree (verified existing convention; do **not** co-locate `__tests__/` per component).
- New shadcn primitives follow the `React.forwardRef` + `cn(...)` pattern established in [`dialog.tsx`](../../../../ui/src/components/ui/dialog.tsx) and [`popover.tsx`](../../../../ui/src/components/ui/popover.tsx).
- Component test convention: `@testing-library/react` with `userEvent` from `@testing-library/user-event` (already in package.json per the existing component tests at [`ui/src/__tests__/components/`](../../../../ui/src/__tests__/components/)).
- `motion-reduce:animate-none` (or `motion-reduce:transition-none`) on all animation classes added to `TooltipContent` and `PopoverContent`.

### AI Agent Execution Protocol

0. **Load context first**: Read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), and the spec — already known but verify any drift on resumption.
1. **Read scope**: verify each story's New files / Modified files / Endpoints (N/A here) / DoD before starting.
2. **No backend implementation order** — this is frontend-only.
3. **Run frontend gates** (`pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm playwright test`) after each story.
4. **Implement primitives + wrappers first** (Epic 1) so the surface-application stories can import them.
5. **Apply per-surface** (Epic 2) one component at a time.
6. **E2E coverage** (Epic 3 Story 3.1) lands after all four Phase 1 surfaces are wired so the table-driven inventory test references stable triggers.
7. **Update docs** (Epic 3 Story 3.2) at the end.

---

## Epic 1 — Primitives & Glossary infrastructure

### Story 1.1 — Tooltip primitive + provider wiring

**Outcome:** A shadcn-style `Tooltip` primitive exists at `ui/src/components/ui/tooltip.tsx` mirroring the project's other primitives. `TooltipProvider` is mounted in the root layout. `pnpm typecheck` and `pnpm test` pass with no changes elsewhere.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/components/ui/tooltip.tsx`](../../../../ui/src/components/ui/tooltip.tsx) | Re-exports `Tooltip`, `TooltipTrigger`, `TooltipContent`, `TooltipProvider` from `@radix-ui/react-tooltip` with shadcn-styled `TooltipContent` (border, bg-popover, padding, shadow, animation classes with `motion-reduce:animate-none`). |

**Modified files**

| File | Change |
|---|---|
| [`ui/package.json`](../../../../ui/package.json) | Add `"@radix-ui/react-tooltip": "~1.1.15"` to `dependencies` (matches existing Radix tilde-pinning). |
| `ui/pnpm-lock.yaml` | Regenerated by `pnpm install`. |
| [`ui/src/app/layout.tsx`](../../../../ui/src/app/layout.tsx) | Wrap `{children}` (or move outermost) inside a `<TooltipProvider delayDuration={700}>` from `@/components/ui/tooltip`. Place it inside `QueryProvider > ThemeProvider`. |

**UI element inventory**

The primitive itself renders no visible UI in isolation — it's consumed by FR-2 / FR-3 wrappers. The only user-observable wiring is the provider in `layout.tsx`, which adds no DOM but enables tooltip context across the app.

**Key interfaces**

```tsx
// ui/src/components/ui/tooltip.tsx
'use client';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import * as React from 'react';

import { cn } from '@/lib/utils';

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(function TooltipContent({ className, sideOffset = 4, ...props }, ref) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(
          'z-50 max-w-xs rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md outline-none',
          'animate-in fade-in-0 zoom-in-95 motion-reduce:animate-none',
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
});
```

**Tasks**
1. `cd ui && pnpm add @radix-ui/react-tooltip@~1.2.8` (matches existing Radix pinning).
2. Write `ui/src/components/ui/tooltip.tsx` per the Key interfaces above.
3. Modify `ui/src/app/layout.tsx` to wrap children with `<TooltipProvider delayDuration={700}>`. Place it as a child of `<QueryProvider>` so every page renders inside a tooltip context.
4. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm build` — all four must pass with no new errors before completing.

**Definition of Done**
- [ ] `ui/src/components/ui/tooltip.tsx` exists and exports `Tooltip`, `TooltipTrigger`, `TooltipContent`, `TooltipProvider`.
- [ ] `@radix-ui/react-tooltip` is in `ui/package.json` `dependencies`.
- [ ] `ui/src/app/layout.tsx` wraps children in `<TooltipProvider>`.
- [ ] `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm build` green.

---

### Story 1.2 — `InfoTooltip` wrapper (standalone + asChild modes)

**Outcome:** A typed `<InfoTooltip>` wrapper exists at `ui/src/components/common/info-tooltip.tsx` that renders an accessible icon-button trigger in standalone mode and uses Radix `asChild` for wrapping focusable children. Vitest component tests cover both modes plus keyboard / a11y semantics.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx) | The wrapper. Two modes: standalone (renders own `<button>` with `<Info />` icon) and asChild (wraps a focusable child via Radix `asChild`). Glossary-keyed prop typed as `ShortGlossaryKey`. |
| [`ui/src/__tests__/components/common/info-tooltip.test.tsx`](../../../../ui/src/__tests__/components/common/info-tooltip.test.tsx) | Component tests: standalone renders button with `aria-label`; hover/focus reveals body; ESC dismisses; asChild uses child as trigger; `motion-reduce:animate-none` class present. |

**Modified files** — none.

**UI element inventory**

| Element | Type | Source |
|---|---|---|
| Trigger (standalone mode) | `<button type="button" aria-label="...">` with 14×14 `<Info />` icon from `lucide-react`, button hit area 24×24 px via padding | Renders the icon from `lucide-react`, color `text-muted-foreground` |
| Trigger (asChild mode) | The component's `children` — wrapped via Radix `<TooltipTrigger asChild>{children}</TooltipTrigger>` | Caller-supplied (must be focusable) |
| Body | `<TooltipContent>` from Story 1.1 | Renders the glossary entry's `short` field |

**Key interfaces**

```tsx
// ui/src/components/common/info-tooltip.tsx
'use client';
import { Info } from 'lucide-react';
import * as React from 'react';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { glossary, type ShortGlossaryKey } from '@/lib/glossary';

type InfoTooltipProps =
  | { glossaryKey: ShortGlossaryKey; asChild?: false }
  | { glossaryKey: ShortGlossaryKey; asChild: true; children: React.ReactNode };

export function InfoTooltip(props: InfoTooltipProps) {
  const entry = glossary[props.glossaryKey];
  // Belt-and-braces: type narrowing of ShortGlossaryKey makes both checks
  // unreachable at compile time, but guard against runtime bad keys.
  if (!entry || !('short' in entry)) return null;
  const label = entry.ariaLabel ?? 'More information';
  const bodyTestId = `tooltip-body-${props.glossaryKey}`;

  // Note on `data-testid`:
  // - In standalone mode the wrapper owns the trigger button DOM node and
  //   sets `data-testid="tooltip-trigger-${key}"`.
  // - In asChild mode the child is the trigger and already carries its own
  //   `data-testid` (e.g. `open-pr-link`, `open-pr-disabled`). Setting a
  //   second `data-testid` here would collide on the merged child element
  //   (a DOM node has exactly one `data-testid` attribute). E2E tests
  //   verify the asChild trigger via the child's existing test-id and the
  //   tooltip body via `tooltip-body-${key}`.

  return (
    <Tooltip>
      {props.asChild ? (
        <TooltipTrigger asChild>{props.children}</TooltipTrigger>
      ) : (
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={label}
            data-testid={`tooltip-trigger-${props.glossaryKey}`}
            className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
      )}
      <TooltipContent data-testid={bodyTestId}>{entry.short}</TooltipContent>
    </Tooltip>
  );
}
```

**Tasks**
1. Write `ui/src/components/common/info-tooltip.tsx` per Key interfaces (note: depends on Story 1.4's `glossary` export — Story 1.4 must land first OR the file may be drafted with a minimal stub glossary that Story 1.4 fleshes out).
2. Write `ui/src/__tests__/components/common/info-tooltip.test.tsx` with the following test cases:
   - Standalone mode: renders `<button>` with `aria-label` matching glossary entry's `ariaLabel` (or fallback). Asserts `data-testid="tooltip-trigger-${key}"` on button.
   - Hover reveal: `userEvent.hover(button)` shows tooltip body (after Radix delay; configure provider with `delayDuration={0}` in test wrapper).
   - Focus reveal: `userEvent.tab()` to button shows tooltip body.
   - ESC dismiss: hover/focus to open, then `userEvent.keyboard('{Escape}')` dismisses.
   - asChild mode: pass a focusable `<button>` child; assert the child has `data-testid="tooltip-trigger-${key}"` attached via Radix.
   - Motion-reduce class: assert `TooltipContent` renders with `motion-reduce:animate-none` class token (assert via `expect(content.className).toContain('motion-reduce:animate-none')`).
3. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test` — all green.

**Definition of Done**
- [ ] `info-tooltip.tsx` ships with the two-mode API typed against `ShortGlossaryKey`.
- [ ] All 6 component test cases pass.
- [ ] Linked DoD coverage: **AC-1** (trigger renders, `aria-label` present, `data-testid` matches), **AC-2** (hover reveal), **AC-3** (focus reveal + ESC dismiss), **AC-8** (motion-reduce class), **AC-10** (component-level rendering sanity).

---

### Story 1.3 — `HelpPopover` wrapper

**Outcome:** A typed `<HelpPopover>` wrapper exists at `ui/src/components/common/help-popover.tsx` using Radix `Popover` (click-to-open) with Markdown body rendering and the safety filter. Vitest tests cover click/ESC/outside-click semantics plus the safety filter.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/components/common/help-popover.tsx`](../../../../ui/src/components/common/help-popover.tsx) | The wrapper. Click-to-open popover; body rendered via `react-markdown` with `disallowedElements={['script', 'iframe', 'style']}`. Glossary-keyed prop typed as `LongGlossaryKey`. |
| [`ui/src/__tests__/components/common/help-popover.test.tsx`](../../../../ui/src/__tests__/components/common/help-popover.test.tsx) | Component tests: click opens; ESC closes; outside-click closes; Markdown list renders as `<ul>`; safety filter strips `<script>`; `motion-reduce:animate-none` class present. |

**Modified files** — none.

**UI element inventory**

| Element | Type | Source |
|---|---|---|
| Trigger | `<button type="button" aria-label="...">` identical to InfoTooltip standalone-mode button | Same `<Info />` icon, same 24×24 hit area |
| Body | `<PopoverContent>` (existing primitive from [`popover.tsx`](../../../../ui/src/components/ui/popover.tsx)) | Renders `react-markdown` with safety filter |

**Key interfaces**

```tsx
// ui/src/components/common/help-popover.tsx
'use client';
import { Info } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { glossary, type LongGlossaryKey } from '@/lib/glossary';

interface HelpPopoverProps {
  glossaryKey: LongGlossaryKey;
}

export function HelpPopover({ glossaryKey }: HelpPopoverProps) {
  const entry = glossary[glossaryKey];
  // Defensive: type narrowing of LongGlossaryKey makes both unreachable at
  // compile time, but guard against runtime bad keys.
  if (!entry || !('long' in entry)) return null;
  const label = entry.ariaLabel ?? 'More information';
  const triggerTestId = `popover-trigger-${glossaryKey}`;
  const bodyTestId = `popover-body-${glossaryKey}`;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          data-testid={triggerTestId}
          className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        data-testid={bodyTestId}
        className="prose prose-sm max-w-none motion-reduce:animate-none"
      >
        <ReactMarkdown disallowedElements={['script', 'iframe', 'style']} unwrapDisallowed>
          {entry.long}
        </ReactMarkdown>
      </PopoverContent>
    </Popover>
  );
}
```

**Tasks**
1. Write `ui/src/components/common/help-popover.tsx` per Key interfaces.
2. Write `ui/src/__tests__/components/common/help-popover.test.tsx` with:
   - Click opens body: `userEvent.click(trigger)` reveals popover with body content (using a real glossary entry).
   - ESC closes: `userEvent.keyboard('{Escape}')` after opening dismisses.
   - Outside-click closes: open, then `userEvent.click(document.body)` dismisses (Radix default behavior).
   - Markdown list: a real glossary entry whose `long` includes `- item` Markdown renders as `<ul><li>item</li></ul>`. (`study.metric` is a natural candidate since its `long` body lists the metric definitions.)
   - **Safety filter test mechanism:** the real glossary cannot contain `<script>` content (forbidden by FR-10 + asserted by AC-12 / `glossary.test.ts`). So this test uses `vi.mock('@/lib/glossary', ...)` to inject a test-only `long` entry containing `<script>alert(1)</script>` and a `<style>` tag. Pattern:
     ```ts
     vi.mock('@/lib/glossary', () => ({
       glossary: {
         'test.malicious': {
           long: 'Safe text. <script>alert(1)</script> More text. <style>body{}</style>',
         },
       },
       // Stub the derived types so the import compiles.
       // (TypeScript narrowing of LongGlossaryKey is enforced at the real call sites.)
     }));
     // ... then render <HelpPopover glossaryKey={'test.malicious' as never} />
     ```
     After opening the popover, assert:
     - `container.querySelector('script')` returns `null`
     - `container.querySelector('style')` returns `null`
     - The popover body still renders the safe text portions.
   - Motion-reduce class: assert `PopoverContent` renders with `motion-reduce:animate-none` class token.
3. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test` — all green.

**Definition of Done**
- [ ] `help-popover.tsx` ships with the typed API.
- [ ] All 6 component test cases pass.
- [ ] Linked DoD coverage: **AC-1** (trigger button + `aria-label`), **AC-4** (click opens, ESC + outside-click close), **AC-8** (motion-reduce class).

---

### Story 1.4 — Glossary source-of-truth + parity test

**Outcome:** `ui/src/lib/glossary.ts` ships with all Phase 1 entries (aggregate keys + per-wire-value keys for all 8 enum groups), declared via `as const satisfies Record<string, GlossaryEntry>`, with source-of-truth comments above each enum group mirroring [`enums.ts`](../../../../ui/src/lib/enums.ts). Parity test in `ui/src/__tests__/lib/glossary.test.ts` enforces glossary-enum key parity for all 8 groups.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Glossary object + derived `GlossaryKey` / `ShortGlossaryKey` / `LongGlossaryKey` types + `expectGlossaryGroundedAgainstEnums` test helper. |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | Parity test cases (one per enum group) + short/long length-bound tests + no-backend-refs-in-user-copy test (AC-12). |

**Modified files** — none.

**Key interfaces**

```ts
// ui/src/lib/glossary.ts
export interface GlossaryEntryShort {
  short: string;
  ariaLabel?: string;
}
export interface GlossaryEntryLong {
  long: string;
  ariaLabel?: string;
}
export interface GlossaryEntryDual {
  short: string;
  long: string;
  ariaLabel?: string;
}
export type GlossaryEntry = GlossaryEntryShort | GlossaryEntryLong | GlossaryEntryDual;

export const glossary = {
  // --- Create-study modal (FR-6) ---
  'study.target': { short: '…', ariaLabel: 'More information about target index' },
  'study.template': { short: '…', ariaLabel: '…' },

  // Source-of-truth: backend/app/api/v1/schemas.py ObjectiveMetric
  // (mirrored in ui/src/lib/enums.ts OBJECTIVE_METRIC_VALUES).
  // FR-4 parity test enforces key parity against OBJECTIVE_METRIC_VALUES.
  'study.metric': { long: '…', ariaLabel: 'More information about metrics' }, // aggregate, HelpPopover
  'study.metric.ndcg': { short: '…' },
  'study.metric.map': { short: '…' },
  'study.metric.precision': { short: '…' },
  'study.metric.recall': { short: '…' },
  'study.metric.mrr': { short: '…' },
  'study.metric.err': { short: '…' },

  // Source-of-truth: backend/app/api/v1/schemas.py ObjectiveK
  'study.k': { short: '…' }, // aggregate
  'study.k.1': { short: '…' },
  'study.k.3': { short: '…' },
  'study.k.5': { short: '…' },
  'study.k.10': { short: '…' },
  'study.k.20': { short: '…' },
  'study.k.50': { short: '…' },
  'study.k.100': { short: '…' },

  // Source-of-truth: backend/app/api/v1/schemas.py ObjectiveDirection
  'study.direction': { short: '…' }, // aggregate
  'study.direction.maximize': { short: '…' },
  'study.direction.minimize': { short: '…' },

  'study.max_trials': { short: '…' },
  'study.time_budget_min': { short: '…' },
  'study.parallelism': { short: '…' },
  'study.seed': { short: '…' },

  // Source-of-truth: backend/app/eval/types.py SamplerKind
  'study.sampler': { long: '…' }, // aggregate, HelpPopover
  'study.sampler.tpe': { short: '…' },
  'study.sampler.random': { short: '…' },

  // Source-of-truth: backend/app/eval/types.py PrunerKind
  'study.pruner': { long: '…' }, // aggregate, HelpPopover
  'study.pruner.median': { short: '…' },
  'study.pruner.none': { short: '…' },

  // --- Study header (FR-7) ---
  // Source-of-truth: backend/app/api/v1/schemas.py StudyStatusWire
  'study.status.queued': { short: '…' },
  'study.status.running': { short: '…' },
  'study.status.completed': { short: '…' },
  'study.status.cancelled': { short: '…' },
  'study.status.failed': { short: '…' },
  'study.best_metric': { short: '…' },
  'study.trials_summary': { short: '…' },

  // --- Trials table (FR-8) ---
  // Source-of-truth: backend/app/api/v1/schemas.py TrialStatusWire
  'trial.status': { short: '…' }, // aggregate column header
  'trial.status.complete': { short: '…' },
  'trial.status.failed': { short: '…' },
  'trial.status.pruned': { short: '…' },
  'trial.primary_metric': { short: '…' },
  'trial.duration_ms': { short: '…' },
  'trial.params': { short: '…' },

  // Source-of-truth: backend/app/db/repo/trial.py TrialSortKey (re-exported by schemas.py:181)
  'trial.sort_by': { short: '…' }, // aggregate
  'trial.sort.primary_metric_desc': { short: '…' },
  'trial.sort.primary_metric_asc': { short: '…' },
  'trial.sort.ended_at_desc': { short: '…' },
  'trial.sort.ended_at_asc': { short: '…' },
  'trial.sort.optuna_trial_number_asc': { short: '…' },

  // --- Digest panel (FR-9) ---
  'digest.narrative': { short: '…' },
  'digest.parameter_importance': { short: '…' },
  'digest.metric_delta': { short: '…' },
  'digest.recommended_config': { short: '…' },
  'digest.suggested_followups': { short: '…' },
  'digest.open_pr_button': { short: '…' },
  'digest.open_pr_disabled': { short: '…' },
} as const satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof glossary;
export type ShortGlossaryKey = {
  [K in keyof typeof glossary]: (typeof glossary)[K] extends { short: string } ? K : never;
}[keyof typeof glossary];
export type LongGlossaryKey = {
  [K in keyof typeof glossary]: (typeof glossary)[K] extends { long: string } ? K : never;
}[keyof typeof glossary];

// Test helper exposed for the parity unit test (FR-4)
export function listGlossaryKeysWithPrefix(prefix: string): string[] {
  return Object.keys(glossary).filter((k) => k.startsWith(prefix + '.') && k !== prefix);
}

/**
 * Asserts the glossary contains exactly the per-wire-value keys expected
 * for a given enum group (FR-4 / AC-5). Designed to be called from vitest
 * with the readonly tuple from `ui/src/lib/enums.ts`.
 *
 * @param prefix dotted prefix (e.g., 'study.status', 'trial.sort')
 * @param wireValues the canonical readonly array from enums.ts
 * @throws if any wire value lacks a `<prefix>.<value>` key,
 *         or if any `<prefix>.<value>` key exists for a non-allowlisted value
 */
export function expectGlossaryGroundedAgainstEnums(
  prefix: string,
  wireValues: readonly (string | number)[],
): void {
  const present = new Set(listGlossaryKeysWithPrefix(prefix));
  const expected = new Set(wireValues.map((v) => `${prefix}.${String(v)}`));
  // Missing keys
  for (const key of expected) {
    if (!present.has(key)) {
      throw new Error(`glossary parity: missing key ${key}`);
    }
  }
  // Extra keys (per-wire-value keys not in the allowlist)
  for (const key of present) {
    if (!expected.has(key)) {
      throw new Error(`glossary parity: unexpected key ${key} (not in ${prefix} allowlist)`);
    }
  }
}
```

**Note on content:** The `…` placeholders above are filled in during this story. Final copy is captured in the story's PR description and reviewed during Stories 2.1–2.4 when the surfaces are wired (FR-10).

**Tasks**
1. Write `ui/src/lib/glossary.ts` per Key interfaces above. Fill in all `short` and `long` fields with the per-FR-10 rule (≤140 chars short, ≤800 chars long, no backend file paths in user-visible strings).
2. Write `ui/src/__tests__/lib/glossary.test.ts` with these test cases:
   - **Parity tests, one per enum group** (8 total — for `STUDY_STATUS_VALUES`, `TRIAL_STATUS_VALUES`, `TRIAL_SORT_VALUES`, `OBJECTIVE_METRIC_VALUES`, `OBJECTIVE_K_VALUES`, `OBJECTIVE_DIRECTION_VALUES`, `SAMPLER_VALUES`, `PRUNER_VALUES`): for each enum group, invoke `expectGlossaryGroundedAgainstEnums(prefix, wireValues)` from `@/lib/glossary` with the matching `enums.ts` constant. The helper internally validates both directions (no missing wire value, no extra `<prefix>.*` key). Trial-sort uses `('trial.sort', TRIAL_SORT_VALUES)`; metric uses `('study.metric', OBJECTIVE_METRIC_VALUES)`; etc. Aggregates (`study.metric`, `trial.status`, `study.k`, `study.direction`, `study.sampler`, `study.pruner`, `trial.sort_by`) are excluded by the helper because they lack a trailing `.<value>` segment.
   - **Length-bound tests**: every entry's `short` field (if present) is ≤140 chars; every `long` field (if present) is ≤800 chars.
   - **AC-12 — no backend refs in user-visible strings**: for every entry's `short`, `long`, and `ariaLabel` field, assert no field contains the substring `'backend/'`, `'.py'`, or matches a Python-like symbol pattern (e.g., `StudyStatusWire`, `SamplerKind`, `K_REQUIRED`). Forbidden substrings test list: `['backend/', '.py', 'StudyStatusWire', 'TrialStatusWire', 'TrialSortKey', 'ObjectiveMetric', 'ObjectiveK', 'ObjectiveDirection', 'SamplerKind', 'PrunerKind', 'K_REQUIRED']`.
   - **Markdown disallowed elements** (sanity, defense-in-depth): for every `long` entry, assert it does not contain `<script>`, `<iframe>`, or `<style>` raw HTML markers (the safety filter in `HelpPopover` is the runtime guard; this is a content-time check).
3. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test` — all green.

**Definition of Done**
- [ ] `glossary.ts` ships with `glossary` const, `GlossaryKey`, `ShortGlossaryKey`, `LongGlossaryKey` types, and `listGlossaryKeysWithPrefix` helper.
- [ ] All 8 parity tests pass (one per enum group).
- [ ] All length-bound tests pass.
- [ ] AC-12 no-backend-refs test passes.
- [ ] Linked DoD coverage: **AC-5** (glossary parity), **AC-10** (typed glossary lookups), **AC-12** (no backend refs in user copy).

---

## Epic 2 — Phase 1 surface application

### Story 2.1 — Create-study modal tooltips (FR-6)

**Outcome:** All 11 FR-6 placements in [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) render the correct `InfoTooltip` or `HelpPopover` next to the label. Form submission, validation, and step navigation are unchanged.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | Add 11 help affordances next to labels per the FR-6 table. Each is an `InfoTooltip` or `HelpPopover` rendered as a sibling immediately after the `<Label>` text. The `<Label htmlFor=...>` association is preserved; the icon sits to the right with a 4px gap. |

**UI element inventory**

| Step | Label JSX line (current file) | Glossary key | Wrapper | Test-id of trigger |
|---|---|---|---|---|
| 1 | `<Label htmlFor="cs-target">Target index / collection</Label>` (line 257) | `study.target` | `InfoTooltip` | `tooltip-trigger-study.target` |
| 3 | `<Label htmlFor="cs-tpl">Query template (filtered by engine)</Label>` (line 313) | `study.template` | `InfoTooltip` | `tooltip-trigger-study.template` |
| 5 | `<Label htmlFor="cs-metric">Metric</Label>` (line 353) | `study.metric` | `HelpPopover` | `popover-trigger-study.metric` |
| 5 | `<Label htmlFor="cs-k">k</Label>` (line 371) | `study.k` | `InfoTooltip` | `tooltip-trigger-study.k` |
| 5 | `<Label htmlFor="cs-dir">Direction</Label>` (line 391) | `study.direction` | `InfoTooltip` | `tooltip-trigger-study.direction` |
| 5 | `<Label htmlFor="cs-max">Max trials</Label>` (line 411) | `study.max_trials` | `InfoTooltip` | `tooltip-trigger-study.max_trials` |
| 5 | `<Label htmlFor="cs-budget">Time budget (min)</Label>` (line 419) | `study.time_budget_min` | `InfoTooltip` | `tooltip-trigger-study.time_budget_min` |
| 5 | `<Label htmlFor="cs-par">Parallelism</Label>` (line 428) | `study.parallelism` | `InfoTooltip` | `tooltip-trigger-study.parallelism` |
| 5 | `<Label htmlFor="cs-sampler">Sampler</Label>` (line 438) | `study.sampler` | `HelpPopover` | `popover-trigger-study.sampler` |
| 5 | `<Label htmlFor="cs-pruner">Pruner</Label>` (line 456) | `study.pruner` | `HelpPopover` | `popover-trigger-study.pruner` |
| 5 | `<Label htmlFor="cs-seed">Seed</Label>` (line 474) | `study.seed` | `InfoTooltip` | `tooltip-trigger-study.seed` |

**State dependency analysis** — None. The wrappers do not read or modify any form state; they are pure presentation siblings of the `<Label>` elements.

**Analogous markup pattern (insertion point per label)**

Current pattern (e.g., target label, lines 256-264):
```tsx
<div className="space-y-1.5">
  <Label htmlFor="cs-target">Target index / collection</Label>
  <Input id="cs-target" {...form.register('target')} placeholder="products" />
  {schema.data && (
    <p className="text-xs text-muted-foreground">…</p>
  )}
</div>
```

New pattern (wrap the Label in a flex row so the icon sits inline):
```tsx
<div className="space-y-1.5">
  <div className="flex items-center gap-1">
    <Label htmlFor="cs-target">Target index / collection</Label>
    <InfoTooltip glossaryKey="study.target" />
  </div>
  <Input id="cs-target" {...form.register('target')} placeholder="products" />
  {schema.data && (
    <p className="text-xs text-muted-foreground">…</p>
  )}
</div>
```

The pattern is identical for every label except Metric/Sampler/Pruner which use `<HelpPopover glossaryKey="..." />` instead.

**Imports to add** (at the top of `create-study-modal.tsx`):
```tsx
import { InfoTooltip } from '@/components/common/info-tooltip';
import { HelpPopover } from '@/components/common/help-popover';
```

**Tasks**
1. Add the two imports to [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx).
2. For each of the 11 labels, wrap the `<Label>` in a `<div className="flex items-center gap-1">` and add the appropriate help wrapper sibling.
3. Verify form submission still produces the same wire payload — open the modal in the dev server, complete all 5 steps, submit, and check the network payload. No `?metric=` / `?k=` / `?sampler=` / `?pruner=` value should change.
4. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm playwright test studies.spec.ts` — all green. (Existing E2E uses `data-testid="cs-…"` IDs that this story doesn't touch.)

**Definition of Done**
- [ ] All 11 help affordances rendered in the modal per the inventory above.
- [ ] No `<Label htmlFor=...>` association broken (`htmlFor` still points at the input id).
- [ ] Existing `studies.spec.ts` E2E suite still passes (regression).
- [ ] Form submission wire payload is byte-identical for a representative test study (manually verified once in dev server before merge).
- [ ] Linked DoD coverage: **AC-1** (11 triggers present), **AC-9** (no triggers on excluded fields — Cluster, Query set, Judgment list, Study name, Search space).

---

### Story 2.2 — Study-header tooltips (FR-7)

**Outcome:** [`study-header.tsx`](../../../../ui/src/components/studies/study-header.tsx) renders 3 help affordances: an InfoTooltip next to the status badge (dynamic key by status value), and InfoTooltips next to the `Best metric` and `Trials` `<dt>` labels.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/study-header.tsx`](../../../../ui/src/components/studies/study-header.tsx) | (1) Add an `InfoTooltip` immediately after the `<StatusBadge>` instance with a dynamic key keyed by `study.status`. (2) Add InfoTooltips after the `Best metric` and `Trials` `<dt>` labels. |

**UI element inventory**

| Element | Current location | Glossary key | Wrapper | Test-id |
|---|---|---|---|---|
| Status badge | Line 16: `<StatusBadge kind="study" value={study.status} />` | Dynamic — `study.status.{value}` resolved via `Record<StudyStatus, ShortGlossaryKey>` | `InfoTooltip` adjacent (Pattern A) | `tooltip-trigger-study.status.{value}` |
| `Best metric` `<dt>` | Line 30: `<dt className="text-xs uppercase text-muted-foreground">Best metric</dt>` | `study.best_metric` | `InfoTooltip` | `tooltip-trigger-study.best_metric` |
| `Trials` `<dt>` | Line 36: `<dt className="text-xs uppercase text-muted-foreground">Trials</dt>` | `study.trials_summary` | `InfoTooltip` | `tooltip-trigger-study.trials_summary` |

**State dependency analysis** — None; pure presentation siblings.

**Analogous markup pattern**

For the status badge (line 14-17 current):
```tsx
<CardTitle className="flex items-center gap-3 text-base">
  <span data-testid="study-name">{study.name}</span>
  <StatusBadge kind="study" value={study.status} />
</CardTitle>
```

New pattern:
```tsx
<CardTitle className="flex items-center gap-3 text-base">
  <span data-testid="study-name">{study.name}</span>
  <div className="flex items-center gap-1">
    <StatusBadge kind="study" value={study.status} />
    <InfoTooltip glossaryKey={STATUS_TO_KEY[study.status]} />
  </div>
</CardTitle>
```

The dynamic-key lookup table is declared at the top of the file:
```tsx
import type { StudyStatus } from '@/lib/enums';
import type { ShortGlossaryKey } from '@/lib/glossary';

const STATUS_TO_KEY = {
  queued: 'study.status.queued',
  running: 'study.status.running',
  completed: 'study.status.completed',
  cancelled: 'study.status.cancelled',
  failed: 'study.status.failed',
} as const satisfies Record<StudyStatus, ShortGlossaryKey>;
```

For the `<dt>` labels (Best metric, Trials):
```tsx
<div>
  <dt className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
    Best metric
    <InfoTooltip glossaryKey="study.best_metric" />
  </dt>
  <dd data-testid="study-best-metric">…</dd>
</div>
```

**Tasks**
1. Add imports for `InfoTooltip`, `StudyStatus`, `ShortGlossaryKey`.
2. Declare the `STATUS_TO_KEY` lookup table.
3. Wrap the status-badge area in a `<div className="flex items-center gap-1">` and add the `InfoTooltip`.
4. Add the `flex items-center gap-1` class to the `Best metric` and `Trials` `<dt>` elements and append the InfoTooltips.
5. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm playwright test studies.spec.ts`.

**Definition of Done**
- [ ] 3 help affordances render in study-header.
- [ ] `STATUS_TO_KEY` typed as `Record<StudyStatus, ShortGlossaryKey>` (compile-time safety per FR-7 spec patch).
- [ ] Existing E2E uses of `data-testid="study-best-metric"` and `data-testid="study-trial-count"` still pass.
- [ ] Linked DoD coverage: **AC-1** (3 triggers present), **AC-7** (dynamic status-key resolves correctly per status).

---

### Story 2.3 — Trials-table tooltips (FR-8)

**Outcome:** [`trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx) renders 5 help affordances: InfoTooltips next to the 4 column headers (Status, Primary metric, Duration (ms), Params) and the Sort label.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx) | Add 5 InfoTooltips next to column headers + sort label. |

**UI element inventory**

| Element | Current location | Glossary key | Test-id |
|---|---|---|---|
| `Sort by` label | Line 31: `<label htmlFor="trial-sort" className="text-muted-foreground">Sort by</label>` | `trial.sort_by` | `tooltip-trigger-trial.sort_by` |
| `Status` column header | Line 56: `<TableHead>Status</TableHead>` | `trial.status` | `tooltip-trigger-trial.status` |
| `Primary metric` column header | Line 57: `<TableHead>Primary metric</TableHead>` | `trial.primary_metric` | `tooltip-trigger-trial.primary_metric` |
| `Duration (ms)` column header | Line 58: `<TableHead>Duration (ms)</TableHead>` | `trial.duration_ms` | `tooltip-trigger-trial.duration_ms` |
| `Params` column header | Line 59: `<TableHead>Params</TableHead>` | `trial.params` | `tooltip-trigger-trial.params` |

**No tooltip on the `#` column** — per FR-8 explicit exclusion.

**Analogous markup pattern**

Current column header:
```tsx
<TableHead>Status</TableHead>
```

New pattern:
```tsx
<TableHead>
  <span className="inline-flex items-center gap-1">
    Status
    <InfoTooltip glossaryKey="trial.status" />
  </span>
</TableHead>
```

For the sort label (line 30-33 current):
```tsx
<label htmlFor="trial-sort" className="text-muted-foreground">
  Sort by
</label>
```

New pattern (sibling wrapper — do NOT nest the `<button>` inside `<label>`; a click on a label activates its associated input, and an interactive button inside would propagate clicks to the select):
```tsx
<div className="flex items-center gap-1">
  <label htmlFor="trial-sort" className="text-muted-foreground">
    Sort by
  </label>
  <InfoTooltip glossaryKey="trial.sort_by" />
</div>
```

**State dependency analysis** — None.

**Tasks**
1. Add `import { InfoTooltip } from '@/components/common/info-tooltip';`.
2. Apply the 5 patterns above.
3. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm playwright test studies.spec.ts`.

**Definition of Done**
- [ ] 5 help affordances render in trials-table.
- [ ] Existing `data-testid="trials-table"` and `data-testid="trial-row-${t.id}"` assertions still pass.
- [ ] Linked DoD coverage: **AC-1** (5 triggers present).

---

### Story 2.4 — Digest-panel tooltips + Open PR aria-disabled refactor (FR-9)

**Outcome:** [`digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx) renders 7 help affordances: 5 InfoTooltips on section headers (Narrative, Parameter importance, Metric delta, Recommended config, Suggested follow-ups) and 2 InfoTooltips in asChild mode wrapping the enabled `Open PR…` button and the new `aria-disabled` variant of the no-pending-proposal button. The disabled button is refactored from native `disabled` to `aria-disabled="true"` per AC-11.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx) | (1) Add InfoTooltips after each of the 5 section labels (`Narrative`, `Parameter importance`, `Metric delta`, `Recommended config`, `Suggested follow-ups`). (2) Refactor the disabled `Open PR (no pending proposal)` `<Button disabled>` (line 92) to use `aria-disabled="true"` + `onClick={(e) => e.preventDefault()}` per AC-11. (3) Wrap both Open PR button variants in `<InfoTooltip asChild glossaryKey="...">`. |

**UI element inventory**

| Element | Current location | Glossary key | Wrapper | Test-id |
|---|---|---|---|---|
| `Narrative` label | Line 41 | `digest.narrative` | `InfoTooltip` (adjacent) | `tooltip-trigger-digest.narrative` |
| `Parameter importance` label | Line 54 | `digest.parameter_importance` | `InfoTooltip` (adjacent) | `tooltip-trigger-digest.parameter_importance` |
| `Metric delta` label | Line 61 | `digest.metric_delta` | `InfoTooltip` (adjacent) | `tooltip-trigger-digest.metric_delta` |
| `Recommended config` label | Line 69 | `digest.recommended_config` | `InfoTooltip` (adjacent) | `tooltip-trigger-digest.recommended_config` |
| `Suggested follow-ups` label | Line 78 | `digest.suggested_followups` | `InfoTooltip` (adjacent) | `tooltip-trigger-digest.suggested_followups` |
| `Open PR…` enabled button | Lines 87-90 | `digest.open_pr_button` | `InfoTooltip asChild` (Pattern B) | `tooltip-trigger-digest.open_pr_button` |
| `Open PR (no pending proposal)` disabled button | Lines 91-94 | `digest.open_pr_disabled` | `InfoTooltip asChild` (Pattern B); button refactored to `aria-disabled` | `tooltip-trigger-digest.open_pr_disabled` |

**Analogous markup pattern — section labels**

Current pattern (Narrative section, lines 40-51):
```tsx
<section>
  <p className="text-xs uppercase text-muted-foreground">Narrative</p>
  <div className="prose prose-sm mt-1 max-w-none" data-testid="digest-narrative">
    <ReactMarkdown …>{digest.narrative}</ReactMarkdown>
  </div>
</section>
```

New pattern:
```tsx
<section>
  <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
    Narrative
    <InfoTooltip glossaryKey="digest.narrative" />
  </p>
  <div className="prose prose-sm mt-1 max-w-none" data-testid="digest-narrative">
    <ReactMarkdown …>{digest.narrative}</ReactMarkdown>
  </div>
</section>
```

The four other section labels (`Parameter importance`, `Metric delta`, `Recommended config`, `Suggested follow-ups`) follow the identical pattern.

**Analogous markup pattern — Open PR buttons (the load-bearing refactor)**

Current pattern (lines 86-96):
```tsx
<section className="flex items-center gap-3">
  {pendingProposal ? (
    <Button asChild data-testid="open-pr-link">
      <Link href={`/proposals/${pendingProposal.id}?action=open_pr`}>Open PR…</Link>
    </Button>
  ) : (
    <Button disabled data-testid="open-pr-disabled">
      Open PR (no pending proposal)
    </Button>
  )}
</section>
```

New pattern:
```tsx
<section className="flex items-center gap-3">
  {pendingProposal ? (
    <InfoTooltip asChild glossaryKey="digest.open_pr_button">
      <Button asChild data-testid="open-pr-link">
        <Link href={`/proposals/${pendingProposal.id}?action=open_pr`}>Open PR…</Link>
      </Button>
    </InfoTooltip>
  ) : (
    <InfoTooltip asChild glossaryKey="digest.open_pr_disabled">
      <Button
        aria-disabled="true"
        onClick={(e) => e.preventDefault()}
        data-testid="open-pr-disabled"
        className="cursor-not-allowed opacity-50"
      >
        Open PR (no pending proposal)
      </Button>
    </InfoTooltip>
  )}
</section>
```

The Tailwind `cursor-not-allowed opacity-50` reproduces the visual disabled state since the native `disabled` attribute is no longer present. The button stays focusable via Tab. Click activation is prevented via the inline `onClick` handler.

**State dependency analysis** — None for the section headers. For the disabled Open PR refactor: the parent component does not read the button's `disabled` state from React — `pendingProposal` is the only branch condition (truthy → enabled link variant; falsy → disabled variant). The refactor is local to `digest-panel.tsx`.

**Legacy behavior parity** — **N/A**. No component is being deleted or replaced; `digest-panel.tsx` (100 LOC pre-change) gains additive markup. The Open PR button refactor is a behavior-preserving migration (native `disabled` → `aria-disabled` with click-prevention) per AC-11; the user-observable disabled-state visual is preserved via Tailwind utilities. The only behavior CHANGE is that the disabled button is now Tab-focusable — which is the explicit AC-11 requirement.

**Tasks**
1. Add `import { InfoTooltip } from '@/components/common/info-tooltip';`.
2. Apply the 5 section-label patterns.
3. Apply the Open PR refactor: wrap both branches with `<InfoTooltip asChild>`; convert the disabled branch to `aria-disabled="true"` + `onClick={(e) => e.preventDefault()}` + Tailwind visual-disabled classes.
4. Verify the enabled branch's `<Button asChild><Link …>` interaction still navigates on click (manual test in dev server).
5. Verify the disabled branch is focusable via Tab AND that clicking it does not navigate (manual test in dev server).
6. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm playwright test studies.spec.ts`.

**Definition of Done**
- [ ] All 7 help affordances render in digest-panel.
- [ ] Disabled Open PR button has `aria-disabled="true"` (not native `disabled`); is Tab-focusable; click does not navigate.
- [ ] Enabled Open PR button still navigates to `/proposals/${id}?action=open_pr` on click.
- [ ] Existing `data-testid="open-pr-link"` and `data-testid="open-pr-disabled"` E2E selectors still resolve to the correct elements.
- [ ] Linked DoD coverage: **AC-1** (7 triggers present), **AC-11** (disabled button uses aria-disabled, focusable, tooltip reveals on focus).

---

## Epic 3 — Test coverage & docs

### Story 3.1 — Extend `studies.spec.ts` E2E with full trigger inventory

**Outcome:** [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) gains a new test block that asserts every Phase 1 trigger (26 in total — 11 in the create-study modal + 15 on study-detail) is present on its respective rendered surface, plus sampled interaction tests for hover/focus/click/ESC/aria-disabled-focusability.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | Add a new `test.describe('contextual help — Phase 1', …)` block with 4 tests (see Tasks). The existing 3 tests in the spec are preserved unchanged (regression). |

**UI element inventory** — see Stories 2.1–2.4 for the per-trigger inventory. Story 3.1's test block iterates that inventory.

**Analogous markup pattern (test setup)**

Existing setup pattern (lines 25-49 of `studies.spec.ts`):
```tsx
const chain = await seedFullChain(3);
const study = await seedStudy({ … });
await page.goto(`/studies/${study.id}`);
await expect(page.getByTestId('study-name')).toContainText(study.name);
```

New test block follows the same pattern — seed via API helpers, navigate via `page.goto`, assert via `page.getByTestId` (no `page.route()` mocking).

**Tasks**

Add this block at the end of `studies.spec.ts` (preserve the existing `test.describe('/studies', …)` block as-is):

```ts
test.describe('contextual help — Phase 1', () => {
  test('create-study modal renders all FR-6 help triggers', async ({ page }) => {
    await page.goto('/studies');
    await page.getByRole('button', { name: /create study/i }).click();
    // Step 1
    await expect(page.getByTestId('tooltip-trigger-study.target')).toBeVisible();
    // Navigate Steps 2 → 5 by clicking Next; the modal data-testid="step-next" advances
    // through Cluster+Target → QuerySet+Judgments → Template → Search space → Objective.
    // For trigger-presence we need to drive the form to Step 3 (template) and Step 5 (objective).
    // Use API-seeded chain so the dropdowns populate.
    // … per-step trigger assertions for the 11 FR-6 triggers
  });

  test('study-detail page renders FR-7/8/9 triggers (15 triggers)', async ({ page }) => {
    const chain = await seedFullChain(3);
    const study = await seedStudy({ … });
    // Seed the study to completed status with a digest + pending proposal so all surfaces render.
    // Helper: seedStudyCompletedWithDigest(...) — to be added if not already in helpers/seed.ts.
    await page.goto(`/studies/${study.id}`);
    // Study-header (3): status badge dynamic key, Best metric, Trials
    await expect(
      page.getByTestId(/^tooltip-trigger-study\.status\.(queued|running|completed|cancelled|failed)$/),
    ).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-study.best_metric')).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-study.trials_summary')).toBeVisible();
    // Trials-table (5)
    await expect(page.getByTestId('tooltip-trigger-trial.sort_by')).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-trial.status')).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-trial.primary_metric')).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-trial.duration_ms')).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-trial.params')).toBeVisible();
    // Digest-panel section headers (5) + Open PR variants (2)
    for (const key of [
      'digest.narrative',
      'digest.parameter_importance',
      'digest.metric_delta',
      'digest.recommended_config',
      'digest.suggested_followups',
    ]) {
      await expect(page.getByTestId(`tooltip-trigger-${key}`)).toBeVisible();
    }
    // Open PR — either enabled or disabled variant must be present
    const openPrAny = page.getByTestId(/^tooltip-trigger-digest\.open_pr_(button|disabled)$/);
    await expect(openPrAny).toBeVisible();
  });

  test('hover reveals InfoTooltip body and ESC dismisses', async ({ page }) => {
    await page.goto('/studies');
    await page.getByRole('button', { name: /create study/i }).click();
    const trigger = page.getByTestId('tooltip-trigger-study.target');
    await trigger.hover();
    await expect(page.getByTestId('tooltip-body-study.target')).toBeVisible({ timeout: 2_000 });
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('tooltip-body-study.target')).not.toBeVisible();
  });

  test('click opens HelpPopover body; both ESC and outside-click close it', async ({ page }) => {
    await page.goto('/studies');
    await page.getByRole('button', { name: /create study/i }).click();
    // Navigate to Step 5 via seeded chain
    // … (seed setup + step navigation)
    const trigger = page.getByTestId('popover-trigger-study.metric');
    // Round 1: ESC closes
    await trigger.click();
    await expect(page.getByTestId('popover-body-study.metric')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('popover-body-study.metric')).not.toBeVisible();
    // Round 2: outside-click closes (click a stable non-popover element).
    await trigger.click();
    await expect(page.getByTestId('popover-body-study.metric')).toBeVisible();
    // The dialog title is a stable click target that isn't inside the popover portal.
    await page.getByText(/Create study/i).first().click({ force: true });
    await expect(page.getByTestId('popover-body-study.metric')).not.toBeVisible();
  });

  test('disabled Open PR button is focusable and tooltip reveals on focus', async ({ page }) => {
    // Seed a completed study with no pending proposal so the disabled variant renders.
    const chain = await seedFullChain(3);
    const study = await seedStudyCompletedWithoutProposal({ … });
    await page.goto(`/studies/${study.id}`);
    const disabledButton = page.getByTestId('open-pr-disabled');
    await expect(disabledButton).toBeVisible();
    await expect(disabledButton).toHaveAttribute('aria-disabled', 'true');
    await disabledButton.focus();
    // The tooltip-body uses the glossary key (the trigger itself keeps its
    // existing `open-pr-disabled` test-id per the asChild data-testid rule).
    await expect(page.getByTestId('tooltip-body-digest.open_pr_disabled')).toBeVisible();
  });

  test('AC-7: completed-status tooltip body contains the completed-status copy', async ({ page }) => {
    // Seed a study that reaches `status='completed'` so the dynamic
    // status-badge tooltip resolves to study.status.completed.
    const chain = await seedFullChain(3);
    const study = await seedStudyCompletedWithDigest({ … });
    await page.goto(`/studies/${study.id}`);
    const trigger = page.getByTestId('tooltip-trigger-study.status.completed');
    await expect(trigger).toBeVisible();
    await trigger.focus();
    const body = page.getByTestId('tooltip-body-study.status.completed');
    await expect(body).toBeVisible({ timeout: 2_000 });
    // Assert the body actually contains the canonical completed-status copy.
    // Match a substring that is stable in the glossary (e.g., "completed" + a
    // distinguishing phrase) without coupling to the exact phrasing — the
    // glossary owns the copy.
    await expect(body).toContainText(/complet/i);
  });

  test('AC-9: no help triggers next to out-of-scope create-study labels', async ({ page }) => {
    await page.goto('/studies');
    await page.getByRole('button', { name: /create study/i }).click();
    // Drive to Step 4 (Search space) — Cluster Step 1 + QuerySet Step 2 + Template Step 3 are advanced via seeded chain.
    // … (seed setup + step navigation to step-4)
    // Out-of-scope labels: Study name, Search space (JSON).
    // These have no help affordance per FR-6 exclusion list.
    const studyNameLabel = page.getByLabel('Study name');
    await expect(studyNameLabel).toBeVisible();
    // No info-icon sibling near the Study name label.
    await expect(
      studyNameLabel.locator('..').getByRole('button', { name: /more information/i }),
    ).toHaveCount(0);
    // No info-icon sibling near the Search space textarea.
    const searchSpaceTextarea = page.getByTestId('cs-search-space');
    await expect(searchSpaceTextarea).toBeVisible();
    await expect(
      searchSpaceTextarea.locator('..').getByRole('button', { name: /more information/i }),
    ).toHaveCount(0);
    // Also assert no tooltip-trigger-* test-ids beyond the FR-6 inventory.
    // The expected Phase 1 keys in the modal Step 4 are: none. So:
    for (const forbiddenKey of [
      'study.name',
      'study.search_space',
      'study.cluster',
      'study.query_set',
      'study.judgment_list',
    ]) {
      await expect(page.getByTestId(`tooltip-trigger-${forbiddenKey}`)).toHaveCount(0);
      await expect(page.getByTestId(`popover-trigger-${forbiddenKey}`)).toHaveCount(0);
    }
  });
});
```

A seed helper for a completed study with digest may need to be added to [`helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts). If `seedFullChain` + `seedStudy` already supports advancing a study to `completed` status with a digest, reuse them; otherwise add `seedStudyCompletedWithDigest({...})` that mirrors the existing helpers' shape.

**Tasks**
1. Read [`helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) and verify whether a "completed study with digest" seeder exists. If not, add one that creates the upstream chain, seeds a study with `status='completed'`, manually inserts a Digest + Proposal row via API helpers.
2. Append the `test.describe('contextual help — Phase 1', …)` block to `studies.spec.ts` with the 4–5 tests above.
3. Run `pnpm playwright test studies.spec.ts --headed=false` against a running local backend (`make up`). All tests (old + new) must pass.

**Definition of Done**
- [ ] New `test.describe` block ships with 6–7 tests covering trigger-inventory presence + interaction sampling + the disabled-button focus pattern + AC-7 body-content + AC-9 absence assertions.
- [ ] Existing 3 tests in `studies.spec.ts` still pass.
- [ ] Linked DoD coverage: **AC-1** (full inventory presence), **AC-2** (hover reveal sampled), **AC-3** (ESC dismiss sampled), **AC-4** (popover click + outside-click sampled), **AC-6** (regression), **AC-7** (completed-status body content), **AC-9** (no triggers on excluded fields), **AC-11** (disabled-button focus pattern).

---

### Story 3.2 — Update `docs/01_architecture/ui-architecture.md`

**Outcome:** The UI architecture doc gains a short section documenting the new Tooltip primitive + the `InfoTooltip` / `HelpPopover` wrappers + the glossary convention, so future contributors discover the pattern.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) | Append a "Contextual help (tooltips and popovers)" section: lists the primitive at `ui/src/components/ui/tooltip.tsx`, the two wrappers at `ui/src/components/common/`, the glossary at `ui/src/lib/glossary.ts`, the source-of-truth comment convention mirroring `enums.ts`, and the `InfoTooltip` standalone vs. asChild modes. |
| [`state.md`](../../../../state.md) | Update the "Active feature" line and "Most recent meaningful changes" with the feat_contextual_help Phase 1 entry. To be applied at PR merge time, not now. |

**Tasks**
1. Append a ~30-line section to `ui-architecture.md` documenting the convention. Cross-reference the feature spec.
2. (Deferred to merge): Update `state.md` per the spec's §15 documentation requirements.

**Definition of Done**
- [ ] `ui-architecture.md` has a "Contextual help" section.
- [ ] State.md update is staged for the PR-merge commit.

---

## UI Guidance (plan-level, frontend-only feature)

### Reference: current component structure

| File | LOC | Key state | Insertion points |
|---|---|---|---|
| [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | 521 | `useForm`, `step` (useState), `submitting` (useState) | 11 `<Label>` elements at the lines specified in Story 2.1's inventory |
| [`study-header.tsx`](../../../../ui/src/components/studies/study-header.tsx) | 69 | Stateless; props-driven from `StudyDetail` | Line 16 (StatusBadge), line 30 (Best metric `<dt>`), line 36 (Trials `<dt>`) |
| [`trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx) | 82 | Stateless; props-driven with `sort` controlled by parent | Lines 31, 55-59 |
| [`digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx) | 100 | Stateless; props-driven | Lines 41, 54, 61, 69, 78, 86-96 (Open PR section) |
| [`app/layout.tsx`](../../../../ui/src/app/layout.tsx) | 33 | Server component; renders providers | Inside `<QueryProvider>` (Story 1.1) |

### Analogous markup patterns

See per-story sections above for copy-pasteable JSX. Key patterns:

- **Label + adjacent InfoTooltip** (used in 19 of 26 placements): wrap `<Label>` in `<div className="flex items-center gap-1">` and append `<InfoTooltip glossaryKey="..." />` as sibling.
- **Status badge + adjacent InfoTooltip** (1 placement, Story 2.2): wrap `<StatusBadge>` in `<div className="flex items-center gap-1">` with a dynamic-key lookup table.
- **Column header + inline InfoTooltip** (4 placements, Story 2.3): wrap the header text in `<span className="inline-flex items-center gap-1">` inside the `<TableHead>`.
- **asChild button wrap** (2 placements, Story 2.4): wrap `<Button>` in `<InfoTooltip asChild glossaryKey="...">`.

### Layout and structure

- Info icons sit immediately to the right of their target label or element, 4px gap (`gap-1` Tailwind class).
- Icon button is 24×24 px (6×6 in Tailwind h/w units), visible icon is 14×14 px (3.5×3.5 in Tailwind units).
- All animations carry `motion-reduce:animate-none`.

### Interaction behavior

| Wrapper | Open trigger | Close trigger | Body content |
|---|---|---|---|
| `InfoTooltip` (standalone) | Hover OR focus on icon button | Mouseout / blur / ESC | Glossary entry's `short` string (≤140 chars) |
| `InfoTooltip` (asChild) | Hover OR focus on the wrapped child | Mouseout / blur / ESC | Glossary entry's `short` string |
| `HelpPopover` | Click OR Enter/Space on icon button | Click outside / ESC | Glossary entry's `long` string (rendered as Markdown, ≤800 chars) |

### Visual consistency

Match the existing shadcn primitives: `border bg-popover text-popover-foreground shadow-md rounded-md` on the body. Trigger button uses `text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring`.

### Component composition

- New components (`Tooltip` primitive, `InfoTooltip` wrapper, `HelpPopover` wrapper): standalone, no shared state with consumers. Pure props-driven.
- Glossary: import-only; no React state.
- Consumers import the wrappers and the glossary types directly; never compose against the underlying Radix primitives in the surface components.

### Information architecture placement

- No nav changes; no new routes; no new pages.
- Help affordances sit adjacent to the labels they describe, on existing surfaces (`/studies/[id]`, the create-study modal opened from `/studies`).

### Tooltips and contextual help

The full Phase 1 tooltip inventory is in the [`feature_spec.md`](feature_spec.md) §11 table and is replicated in per-story inventories above. The implementation plan does not deviate from the spec inventory.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** Phase 1 is purely additive: tooltips wrap or sit adjacent to existing labels. The one near-edge case is Story 2.4's Open PR button refactor (native `disabled` → `aria-disabled`), which is documented inline in Story 2.4 as a behavior-preserving change (visual disabled state preserved via Tailwind; click activation prevented via `onClick` handler; new behavior: Tab focusability, which is the explicit AC-11 requirement).

### Client-side persistence

N/A — no `localStorage` / `sessionStorage` usage. All tooltip state is in-memory React state (Radix-managed).

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `ui/src/__tests__/lib/`
- Scope: glossary parity against enums; length-bound enforcement; no-backend-refs in user-visible strings.
- Tasks:
  - [ ] Story 1.4: `ui/src/__tests__/lib/glossary.test.ts` — 8 parity tests + length-bound tests + AC-12 test + Markdown safety sanity.
- DoD:
  - [ ] All 8 enum groups (study status, trial status, trial sort, metric, k, direction, sampler, pruner) have parity coverage.

### 3.2 Integration tests

- N/A — no backend, no DB-backed workflows.

### 3.3 Contract tests

- N/A — no API surface.

### 3.4 Component tests (vitest)

- Location: `ui/src/__tests__/components/common/`
- Scope: `InfoTooltip` standalone + asChild + a11y; `HelpPopover` click + ESC + outside-click + Markdown safety filter.
- Tasks:
  - [ ] Story 1.2: `info-tooltip.test.tsx` (6 cases)
  - [ ] Story 1.3: `help-popover.test.tsx` (6 cases)
- DoD:
  - [ ] All AC-1, AC-2, AC-3, AC-4, AC-8, AC-10 component-level scenarios pass.

### 3.5 E2E tests

- Location: `ui/tests/e2e/`
- Scope: full Phase 1 trigger inventory (26 triggers) + sampled interactions + disabled-button focus pattern + regression.
- **Rule: real backend, no `page.route()` mocking** — Story 3.1 extends `studies.spec.ts` with `seedFullChain` / `seedStudy` API helpers plus a new `seedStudyCompletedWithDigest` helper if needed.
- Tasks:
  - [ ] Story 3.1: extend `studies.spec.ts` with the new `test.describe('contextual help — Phase 1', …)` block.
- DoD:
  - [ ] All 4–5 new tests pass against a local backend.
  - [ ] Existing 3 tests still pass (regression).

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | `data-testid="study-name"`, `data-testid="trials-table"`, `data-testid="open-pr-disabled"`, `data-testid="open-pr-link"`, `data-testid="cs-search-space"`, `data-testid="step-next"`, `data-testid="create-study-submit"` etc. | 8+ in 3 tests | **No change to existing assertions** — Phase 1 adds new `tooltip-trigger-*` / `popover-trigger-*` test-ids; does not rename existing ones. Story 3.1 extends the file with a new describe block. |
| [`ui/src/__tests__/components/studies/`](../../../../ui/src/__tests__/components/studies/) (any) | Tests against `StudyHeader`, `TrialsTable`, `DigestPanel` rendering | If present | Verify Story 2.x changes don't break component-level snapshots. Existing structure is preserved (labels stay, badges stay, columns stay); only siblings are added. |

### 3.6 Migration verification

N/A — no schema changes.

### 3.7 CI gates

- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm test` (vitest)
- [ ] `cd ui && pnpm playwright test studies.spec.ts` (against a local `make up` stack)
- [ ] `cd ui && pnpm build` (Next.js production build)

Backend gates (`make test-unit`, `make test-integration`, `make test-contract`) are **not** in scope — this feature ships zero backend changes.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update at PR merge:
- [ ] Active feature: `none in flight` → `none in flight (feat_contextual_help Phase 1 merged)`
- [ ] Most recent meaningful changes: add an entry for feat_contextual_help PR
- [ ] Backlog: drop `feat_contextual_help` from the actionable items list

**`architecture.md`** — no update needed (pointer file; the `ui-architecture.md` topical doc is where the convention lives).

**`CLAUDE.md`** — no update needed; no new project-wide rule.

### 4.1 Architecture docs

- [ ] Story 3.2: append "Contextual help (tooltips and popovers)" section to [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md).

### 4.2 Product docs

- [ ] Mark feat_contextual_help Phase 1 as implemented in `state.md` and move the folder to `docs/00_overview/implemented_features/2026_05_14_feat_contextual_help/` at finalization (per CLAUDE.md release pattern). `phase2_idea.md` and `phase3_idea.md` move with the folder; they remain `_mvp2`-tagged deferred work.

### 4.3 Runbooks

- N/A — no operational behavior change.

### 4.4 Security docs

- N/A — no secrets, no data flow change.

### 4.5 Quality docs

- N/A — testing.md convention is already followed.

---

## 5) Lean refactor workstream

### 5.1 Goals

- Establish the **first tooltip primitive** in the codebase as a sharable, reusable pattern.
- Establish the **glossary source-of-truth file** as a future home for tenant-facing UI copy that mirrors backend wire values.

### 5.2 Planned refactor tasks

- [ ] (Story 2.4) Refactor the disabled Open PR button to use `aria-disabled` instead of native `disabled` (a11y improvement; preserves visual disabled state). This is the only behavior-touching refactor.
- [ ] (Story 3.2) Update `docs/01_architecture/ui-architecture.md` to document the new primitive + wrapper convention so it's discoverable.

### 5.3 Refactor guardrails

- [ ] All existing E2E assertions in `studies.spec.ts` still pass (regression).
- [ ] No `data-testid` rename on any existing element.
- [ ] No `<Label htmlFor=...>` association broken.
- [ ] Form submission wire payload identical for a representative study create (manually verified).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `@radix-ui/react-tooltip` ~1.2.8 | Story 1.1 | Planned (Story 1.1 adds it) | None — Story 1.1 fails fast if `pnpm add` fails |
| `lucide-react` `Info` icon | Stories 1.2, 1.3 | Installed (verified at `ui/package.json`) | None |
| `react-markdown` | Story 1.3 | Installed (~9.0.3) | None |
| Story 1.1 (primitive) | Stories 1.2, 1.3 | Sequential | Hard sequence: **1.1 → 1.4 → 1.2 + 1.3 → 2.x → 3.x** (1.4 lands before wrappers so they import a real glossary file — no stub interim) |
| Story 1.4 (glossary) | Stories 1.2, 1.3, 2.1–2.4 | Sequential | Lands after 1.1 and before the wrappers per the hard sequence above |
| `seedStudyCompletedWithDigest` E2E helper | Story 3.1 | Either exists or needs adding | Audit `helpers/seed.ts` in Story 3.1 — add if missing |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `pnpm add @radix-ui/react-tooltip` conflicts with another Radix version | L | L | Match the tilde-pin to existing Radix deps (~1.1.15) — same version family |
| `TooltipProvider` in `layout.tsx` causes hydration warning | L | L | Wrap with `'use client'` (`tooltip.tsx` already has it); layout.tsx is a server component so the provider mounts inside the existing client boundary |
| Form submission breaks due to label-wrapper restructure | L | H | Manual smoke test after Story 2.1; existing `data-testid="create-study-submit"` E2E assertion catches major regressions |
| Disabled Open PR aria-disabled refactor breaks the existing E2E `data-testid="open-pr-disabled"` selector | L | M | Selector preserved; only the underlying `disabled` attribute changes to `aria-disabled` |
| Glossary copy contains a backend-symbol substring incidentally (false positive on AC-12 test) | M | L | Substring list in AC-12 test is specific (`backend/`, `.py`, named symbols); review copy if a false positive surfaces and tighten the regex |
| Radix Tooltip hover behavior misbehaves under Playwright headless | L | M | Use `userEvent` in component tests (proven path); for Playwright use `page.hover()` (the existing E2E does not rely on hover timing) |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| User has JS disabled | Browser config | Tooltips fail to open; labels still readable (graceful degradation — visible text is unchanged) | None needed; tooltips are not load-bearing |
| Glossary key referenced in component code is removed from `glossary.ts` | Bad merge | `pnpm typecheck` fails (typed keys) | Fix typing error before merge |
| Glossary parity test catches a missing wire value | New backend enum value lands without glossary update | `pnpm test` fails | Add the glossary entry in the same PR that adds the backend value |
| Radix CDN issue (none — Radix is bundled, not CDN) | N/A | N/A | N/A |

---

## 7) Sequencing and parallelization

### Suggested sequence (strict order — no parallelism for the AI-agent run)

1. **Story 1.1** — Tooltip primitive + provider wiring. Establishes `@radix-ui/react-tooltip` dep and `tooltip.tsx` primitive.
2. **Story 1.4** — Glossary source-of-truth + parity test. **Lands before wrappers** so Stories 1.2 and 1.3 can import `glossary`, `ShortGlossaryKey`, `LongGlossaryKey` from a real file (no stub interim). Story 1.4 covers the structural skeleton; final copy may be iterated during 2.1–2.4 as the surfaces wire up, but the keys themselves are stable from 1.4 onward.
3. **Story 1.2** — `InfoTooltip` wrapper (standalone + asChild). Imports `glossary` + `ShortGlossaryKey` from 1.4.
4. **Story 1.3** — `HelpPopover` wrapper. Imports `glossary` + `LongGlossaryKey` from 1.4.
5. **Stories 2.1 → 2.2 → 2.3 → 2.4** — Phase 1 surface application, one component at a time.
6. **Story 3.1** — Extend `studies.spec.ts` E2E with the 26-trigger inventory + AC-specific assertions.
7. **Story 3.2** — Doc update for `ui-architecture.md`.

### Parallelization opportunities

- For an AI-agent run via `/impl-execute --all`: **no parallelism** — execute strictly in the order above. Each story's verification gates (typecheck/lint/test) must pass before the next starts.
- For a human-team run: Stories 2.1, 2.2, 2.3, 2.4 are file-independent and can be parallelized after Epic 1 lands. Stories 1.2 and 1.3 are file-independent and can be parallelized after 1.1 + 1.4 land.

---

## 8) Rollout and cutover plan

- **Rollout stages:** none. Additive UI; ships on next deploy.
- **Feature flag strategy:** none. The tooltips are unconditional; no kill switch needed.
- **Migration/cutover steps:** none.
- **Reconciliation/repair strategy:** none.

---

## 9) Execution tracker

### Current sprint (execute strictly in this order)

- [x] Story 1.1 — Tooltip primitive + provider wiring (commit `615fc93`)
- [x] Story 1.4 — Glossary source-of-truth + parity test (commit `34ad869`)
- [x] Story 1.2 — `InfoTooltip` wrapper (standalone + asChild) (commit `2e16c5a`)
- [x] Story 1.3 — `HelpPopover` wrapper (commit `2e16c5a`)
- [x] Story 2.1 — Create-study modal tooltips (FR-6) (commit `bac31d0`)
- [x] Story 2.2 — Study-header tooltips (FR-7) (commit `34d89ab`)
- [x] Story 2.3 — Trials-table tooltips (FR-8) (commit `1445ca1`)
- [x] Story 2.4 — Digest-panel tooltips + Open PR aria-disabled refactor (FR-9) (commit `7d68654`)
- [x] Story 3.1 — Extend `studies.spec.ts` E2E (commit `9a22a0d`)
- [x] Story 3.2 — Update `docs/01_architecture/ui-architecture.md` (commit `693f479`)

### Post-merge (PR #122 squash-merged into main 2026-05-15)

- 5 CI jobs green (frontend, backend × 2, docker buildx, smoke E2E)
- Gemini Code Assist: 1 Medium accepted (commit `227c37e` added `type="button"` to aria-disabled Open PR), 1 Medium rejected with cited counter-evidence
- Final GPT-5.5 review: 1 Medium accepted-framing-but-deferred — `infra_e2e_seed_completed_study` idea tracks the cross-subsystem E2E coverage gap (component-level coverage IS in place)

### Blocked items

- None.

### Done this sprint

- (none yet)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (New files / Modified files tables).
- [ ] No `<Label htmlFor=...>` association broken.
- [ ] No `data-testid` rename on existing element.
- [ ] Commands executed and passed:
  - [ ] `cd ui && pnpm typecheck`
  - [ ] `cd ui && pnpm lint`
  - [ ] `cd ui && pnpm test`
  - [ ] `cd ui && pnpm build`
  - [ ] `cd ui && pnpm playwright test studies.spec.ts` (Stories 2.x onward + Story 3.1)
- [ ] Related docs updated in same PR when behavior/contract changed (Story 3.2 only).

---

## 11) Plan consistency review (required before execution)

| Check | Verdict |
|---|---|
| 1. Spec ↔ plan endpoint count | **N/A** — feature has 0 endpoints; spec §8.1 says "this feature adds no API endpoints"; plan adds 0 endpoint rows. |
| 2. Spec ↔ plan error code coverage | **N/A** — feature has 0 new error codes per spec §8.5. |
| 3. Spec ↔ plan FR coverage | **Verified** — all 10 FRs traced in §1 table; each FR assigned to ≥1 story. |
| 4. Story internal consistency | **Verified** — every story has Outcome, New/Modified files, UI element inventory, Tasks, DoD; no file is owned by two stories. |
| 5. Test file count and assignment | **Verified** — 3 new test files: `glossary.test.ts` (Story 1.4), `info-tooltip.test.tsx` (Story 1.2), `help-popover.test.tsx` (Story 1.3). Story 3.1 extends `studies.spec.ts` (existing). No orphaned test files. |
| 6. Gate arithmetic | **Verified** — Epic 1 has 4 stories; Epic 2 has 4 stories; Epic 3 has 2 stories; total 10. |
| 7. Open questions resolved | **Verified** — spec §19 has no open questions; idea has no open questions. |
| 8. Frontend UI Guidance completeness | **Verified** — plan-level UI Guidance section present with all required subsections (Insertion points / Analogous markup / Layout / Interaction / Visual consistency / Component composition / IA placement / Tooltips / Legacy parity (N/A justified) / Persistence (N/A)). |
| 9. Plan ↔ codebase verification | See ledger below. |
| 10. Infrastructure path verification | **Verified** — vitest test convention is `ui/src/__tests__/` mirroring source tree (confirmed via `find` on existing tests); E2E path is `ui/tests/e2e/`; `@radix-ui/react-tooltip` is NOT in package.json (confirmed via `grep`). |
| 11. Frontend data plumbing | **Verified** — all wrappers are pure props-driven; no parent component needs to fetch additional data. |
| 12. Persistence scope | **N/A** — no localStorage/sessionStorage usage. |
| 13. Enumerated value contract audit | **Verified** — spec §8.4 enumerates all 8 enum groups with backend source-of-truth citations; Story 1.4's glossary mirrors the convention with source-of-truth comments above each group; AC-5 parity test enforces wire-value parity. |
| 14. Audit-event coverage audit | **N/A** — pre-MVP2 (`audit_log` lands at MVP2); no state mutations. |

### Verification ledger

| Claim | Verified by | Status |
|---|---|---|
| Vitest test dir convention is `ui/src/__tests__/` mirroring source tree | `find /Users/ericstarr/relyloop/ui/src -name __tests__ -type d` → returns `/Users/ericstarr/relyloop/ui/src/__tests__` only | Verified |
| `@radix-ui/react-tooltip` NOT in `ui/package.json` | `grep '@radix-ui/react-tooltip' ui/package.json` returns no match | Verified |
| `lucide-react` Info icon available; already used by shadcn primitives | `grep "from 'lucide-react'" ui/src/` → matches at `dialog.tsx:3` (`X`), `select.tsx:3` (`Check, ChevronDown`), `guides/markdown-doc.tsx:3`, `guides/guide-viewer.tsx:4` | Verified |
| `react-markdown` ~9.0.3 installed | `grep react-markdown ui/package.json` | Verified |
| Existing `studies.spec.ts` uses `seedFullChain` + `seedStudy` API helpers | Read `studies.spec.ts:23` import + lines 28-32 | Verified |
| Backend enum source files exist at cited line numbers | Cycle-3-validated grep on schemas.py:164/167/170/172/190 + eval/types.py:30/33 | Verified |
| `create-study-modal.tsx` Step 5 has 9 inputs + Step 1 has 1 input + Step 3 has 1 input = 11 FR-6 placements | Read `create-study-modal.tsx` lines 230-486 | Verified |
| `study-header.tsx` is 69 LOC with 3 FR-7 placements | Read `study-header.tsx` (69 lines) | Verified |
| `trials-table.tsx` is 82 LOC with 5 FR-8 placements (status, primary metric, duration, params columns + sort label) | Read `trials-table.tsx` (82 lines) | Verified |
| `digest-panel.tsx` is 100 LOC with 5 section labels + 2 Open PR buttons | Read `digest-panel.tsx` (100 lines) | Verified |
| `layout.tsx` already wraps in `ThemeProvider > QueryProvider`; TooltipProvider needs adding inside this stack | Read `layout.tsx` lines 1-33 | Verified |
| `ui/src/lib/enums.ts` source-of-truth pattern uses `// Values must match …` comments above each group | Read `enums.ts` lines 11-12 (study status comment + array) | Verified — glossary will mirror exactly |

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs updates (§1 traceability complete).
- [x] Every story includes Outcome, New/Modified files, UI element inventory, Tasks, DoD.
- [x] Test layers (unit / component / E2E) are explicitly scoped (no integration / contract layers needed for this feature).
- [x] Documentation updates planned and owned (Story 3.2).
- [x] Refactor scope is explicit and bounded (one aria-disabled refactor in Story 2.4).
- [x] Epic gates are measurable.
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) performed with no unresolved findings.

Cross-model review of this plan: **deferred to spec-gen's cross-model loop (already converged at cycle 3)** — the plan is a direct projection of the spec onto the stories with no design decisions that weren't already locked in the spec. If GPT-5.5 review of this plan surfaces findings, they will be applied via Review & Patch mode before execution.
