# Implementation Plan — Home-page first-run demo nudge

**Date:** 2026-05-21
**Status:** Complete (PR #188, merged 2026-05-22 as squash `21325432`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Deferred-phase tracking:** Originally `phase2_idea.md` in this folder; split out at finalization (2026-05-22) to [`feat_home_demo_reseed_endpoint/idea.md`](../../planned_features/feat_home_demo_reseed_endpoint/idea.md) so the reseed-endpoint work surfaces in `/pipeline --status` as its own planned feature.

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops.
- Fail-loud tests: assert explicit status/shape/errors.
- Keep repository patterns consistent.
- Keep increments narrow enough to verify independently.
- **Phase 1 is frontend-only.** No backend code, no migration, no new endpoint. The plan must NOT introduce any Python file changes outside `scripts/ci/` (for the parity guard) and the GHA workflow.

## 1) Scope traceability (FR → epics/stories)

Per [`feature_spec.md` §17](feature_spec.md), every FR maps to at least one story:

| FR ID | Title | Epic / Story | Notes |
|---|---|---|---|
| FR-1 | Demo-data banner rendering trigger | Epic 2 / Story 2.3, 2.4 | Trigger lives in the banner component (2.3) + page-mount glue (2.4) |
| FR-2 | Banner data source (TanStack Query call) | Epic 2 / Story 2.3 | Uses the existing exported `useClusters({ sort: 'name:asc', limit: 200 })` hook from [`ui/src/lib/api/clusters.ts:55`](../../../../ui/src/lib/api/clusters.ts). Its standard `queryKey` (`['clusters', { sort, limit, ... }]`) provides natural deduplication with any other dashboard query using the same params; no custom key needed. |
| FR-3 | Banner content (plural-aware copy) | Epic 2 / Story 2.2 (helper) + Story 2.3 (banner) | Pure helper `formatDemoClusterPrefix` extracted for unit-test isolation |
| FR-4 | Demo indicator rendering | Epic 3 / Stories 3.1–3.4 | JSX badge on `/clusters` (3.2) + text suffix in 2 pickers (3.3, 3.4) |
| FR-5 | Demo badge tooltip | Epic 3 / Story 3.1 | Tooltip wraps the `<DemoBadge>` JSX surface; suffix surfaces have no tooltip (native `<select>` and shadcn `<SelectItem>` rendering text only) |
| FR-6 | Safe-localStorage wrapper | Epic 2 / Story 2.1 | New shared util `ui/src/lib/safe-local-storage.ts` |
| FR-7 | localStorage dismissal contract | Epic 2 / Story 2.3 (consumer) + Story 2.1 (wrapper) | Consumer enforces `'1'`-only contract; wrapper handles SSR + throws |
| FR-8 | Graceful absence / fetch failure | Epic 2 / Story 2.3 | Banner returns `null` on fetch error or zero demos |
| FR-9 | Single source-of-truth + isDemoClusterName helper + CI guard | Epic 1 / Story 1.1 (constant + helper) + Epic 4 / Story 4.1 (CI guard) | Constant lands first; CI guard lands last |

All 9 FRs covered. No FR is split across epics in a way that breaks linear delivery. No deferred FRs — Phase 1 ships all 9.

**Phase 2 deferred tracking:** [`phase2_idea.md`](phase2_idea.md) exists. Phase 2 covers the reseed endpoint + UI button (capability C from the original idea). Not part of this plan.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** layout (preferred for product-facing work per template guidance). **12 stories across 4 epics** (1 in Epic 1, 4 in Epic 2, 4 in Epic 3, 3 in Epic 4).

### Conventions (Phase 1 — frontend-only)

- All new frontend files live under `ui/src/` (component code) or `ui/src/__tests__/` (vitest). The CI guard lands under `scripts/ci/`.
- Every `<select>`-option array or filter dropdown follows the existing **"// Values must match …"** comment convention from [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts). Demo slugs are NOT wire values, so they live in a separate file (`ui/src/lib/demo-data.ts`) and the CI guard is a sibling of `verify_enum_source_of_truth.sh`.
- `'use client'` directive on every component file that uses hooks (TanStack Query, `useState`, etc.) — established pattern in [`ui/src/app/page.tsx:1`](../../../../ui/src/app/page.tsx).
- localStorage access ALWAYS through the safe-localStorage wrapper (Story 2.1) — no direct `window.localStorage` in component code per FR-6.
- Tooltip pattern uses Radix UI primitives from [`ui/src/components/ui/tooltip.tsx`](../../../../ui/src/components/ui/tooltip.tsx) wrapped in `<TooltipProvider>` (the page-level provider already exists in the app layout).
- Tests follow the existing layout — vitest tests under `ui/src/__tests__/<mirror-of-source-tree>/`, Playwright tests under `ui/tests/e2e/<spec>.spec.ts`.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: Read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), and [`feature_spec.md`](feature_spec.md). The spec is the contract.
1. Read scope: outcome + endpoints + interfaces + DoD.
2. **Phase 1 has no backend stories.** Skip steps 2–3 in the standard protocol.
3. Implement frontend.
4. Run vitest (`cd ui && pnpm test <filter>`) for any test files added or modified.
5. Run Playwright E2E (`cd ui && pnpm test:e2e -- dashboard.spec.ts`) for stories touching the dashboard or cluster pickers.
6. Update docs ([`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md), [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md)) in the same PR per spec §15.
7. Skip migration round-trip — no schema changes.
8. Attach evidence in PR description: commands run, pass/fail, files changed.
9. After the final story, update [`state.md`](../../../../state.md) and [`architecture.md`](../../../../architecture.md) per §4 of this plan.

---

## Epic 1 — Foundation (source-of-truth constant)

### Story 1.1 — `DEMO_CLUSTER_SLUGS` constant + `isDemoClusterName` helper

**Outcome:** A single frontend source-of-truth for the 4 demo cluster slugs, plus a TypeScript-safe membership helper that every consumer (banner, badge, suffix renderers, CI guard) imports.

**Traces to FR-9, FR-2 (indirect — banner consumes the helper).**

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/demo-data.ts` | Exports `DEMO_CLUSTER_SLUGS` (4-element `as const` tuple), `DemoClusterSlug` type, and `isDemoClusterName(name: string): boolean` helper. Carries a top-of-file `// Source: scripts/seed_meaningful_demos.py SCENARIOS slugs (lines 129/245/343/456)` comment per FR-9. |
| `ui/src/__tests__/lib/demo-data.test.ts` | Vitest unit tests asserting (a) the array equals the 4 expected slugs in documented order, (b) `isDemoClusterName` returns true for each demo slug, (c) returns false for plausible non-demo names like `"acme-products-staging"` and the empty string. |

**Modified files**

(none in this story)

**Endpoints**

N/A — pure frontend module.

**Key interfaces**

```ts
// ui/src/lib/demo-data.ts
export const DEMO_CLUSTER_SLUGS = [
  'acme-products-prod',
  'corp-docs-search',
  'news-search-staging',
  'jobs-marketplace-prod',
] as const;
export type DemoClusterSlug = (typeof DEMO_CLUSTER_SLUGS)[number];

// Use a Set built once at module load for O(1) lookup AND `string` widening.
const _SET: ReadonlySet<string> = new Set(DEMO_CLUSTER_SLUGS);
export function isDemoClusterName(name: string): boolean {
  return _SET.has(name);
}
```

**Tasks**
1. Create `ui/src/lib/demo-data.ts` with the constant, the `DemoClusterSlug` type, the `_SET` lookup, and the `isDemoClusterName` helper. Add the source-of-truth comment per FR-9.
2. Create `ui/src/__tests__/lib/demo-data.test.ts` with the three assertions listed above.
3. Run `cd ui && pnpm test src/__tests__/lib/demo-data.test.ts` — must pass.
4. Run `cd ui && pnpm lint && pnpm typecheck` — no new diagnostics.

**Definition of Done**
- [ ] `ui/src/lib/demo-data.ts` exists, exports `DEMO_CLUSTER_SLUGS`, `DemoClusterSlug`, and `isDemoClusterName`.
- [ ] Top-of-file source-of-truth comment is present and cites `scripts/seed_meaningful_demos.py SCENARIOS slugs (lines 129/245/343/456)`.
- [ ] `demo-data.test.ts` asserts the 4 expected slugs, in order, AND happy + non-demo cases for `isDemoClusterName`.
- [ ] All three assertions pass; lint + typecheck clean.

---

## Epic 2 — Demo-data banner

### Story 2.1 — Safe-localStorage wrapper

**Outcome:** A shared `safeLocalStorageGet` / `safeLocalStorageSet` pair that (a) returns `null` on SSR and any read failure, (b) swallows write failures, (c) is consumed by the banner in Story 2.3. Generalizes the SSR-only guard from [`ui/src/components/common/data-table.tsx:123`](../../../../ui/src/components/common/data-table.tsx) into a properly throw-resistant utility.

**Traces to FR-6, FR-7 (storage half).**

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/safe-local-storage.ts` | Exports `safeLocalStorageGet(key: string): string \| null` and `safeLocalStorageSet(key: string, value: string): boolean`. Both guard `typeof window !== 'undefined'` AND wrap the inner `localStorage` call in `try/catch`. Return value of `safeLocalStorageSet` indicates whether the write succeeded (not consumed by callers — present for future audit-style use cases). |
| `ui/src/__tests__/lib/safe-local-storage.test.ts` | Vitest cases: SSR (`typeof window === 'undefined'` simulated via `vi.stubGlobal`) returns `null` / `false`; happy path round-trips a value; throwing `getItem` returns `null`; throwing `setItem` returns `false`. |

**Modified files**

(none — this is a brand-new utility module)

**Endpoints**

N/A.

**Key interfaces**

```ts
// ui/src/lib/safe-local-storage.ts
export function safeLocalStorageGet(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeLocalStorageSet(key: string, value: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}
```

**Tasks**
1. Create `ui/src/lib/safe-local-storage.ts` with the two helpers above.
2. Create `ui/src/__tests__/lib/safe-local-storage.test.ts` with the four cases listed.
3. Run `cd ui && pnpm test src/__tests__/lib/safe-local-storage.test.ts`.
4. Run `cd ui && pnpm lint && pnpm typecheck`.

**Definition of Done**
- [ ] `safe-local-storage.ts` exists with both functions; types match the signatures above.
- [ ] Vitest covers: SSR-undefined, happy path, throwing `getItem`, throwing `setItem`.
- [ ] All cases pass.

### Story 2.2 — `formatDemoClusterPrefix` plural-aware copy helper

**Outcome:** A pure helper that turns an array of present demo slugs into the FR-3 prefix-and-list copy variants (K=1 / K=2-3 / K=4). Extracted from the banner component for unit-test isolation.

**Traces to FR-3.**

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/format-demo-cluster-prefix.ts` | Exports `formatDemoClusterPrefix(slugs: readonly string[]): { prefix: string; slugs: readonly string[]; suffix: string }` — returns the parts so the banner JSX can wrap the slugs in `<code>` tags without re-parsing. The `prefix` is the leading "Four sample clusters — " / "One sample cluster — " / "<N> sample clusters — " variant; `suffix` is " are pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them." (K>=2) or " is pre-loaded …" (K=1). |
| `ui/src/__tests__/lib/format-demo-cluster-prefix.test.ts` | Vitest: K=1, K=2, K=3, K=4 variants each assert the exact prefix string and the singular/plural verb agreement in `suffix`. |

**Modified files**

(none)

**Endpoints**

N/A.

**Key interfaces**

```ts
// ui/src/lib/format-demo-cluster-prefix.ts
export interface DemoClusterCopyParts {
  prefix: string;
  slugs: readonly string[];
  suffix: string;
}

// Spec FR-3 "Ends with" clause is committed verbatim across all K-variants.
// Only the prefix verb agrees (is/are); the final sentence stays plural.
const SHARED_BODY_PLURAL =
  ' are pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them.';
const SHARED_BODY_SINGULAR =
  ' is pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them.';

export function formatDemoClusterPrefix(slugs: readonly string[]): DemoClusterCopyParts {
  if (slugs.length === 1) {
    return { prefix: 'One sample cluster — ', slugs, suffix: ' — ' + SHARED_BODY_SINGULAR.trimStart() };
  }
  if (slugs.length === 4) {
    return { prefix: 'Four sample clusters — ', slugs, suffix: ' — ' + SHARED_BODY_PLURAL.trimStart() };
  }
  // K=2 or K=3
  return { prefix: `${slugs.length} sample clusters — `, slugs, suffix: ' — ' + SHARED_BODY_PLURAL.trimStart() };
}
```

**Tasks**
1. Create `format-demo-cluster-prefix.ts` with the helper.
2. Create vitest with K∈{1,2,3,4} cases. Assert the exact prefix strings AND the singular vs plural suffix.
3. Lint + typecheck.

**Definition of Done**
- [ ] Helper exported with the documented shape.
- [ ] Vitest covers all 4 K-variants with exact-string assertions.
- [ ] AC-2 of the spec ("Plural-aware banner copy") is verifiable via this helper's tests + the banner test that consumes it.

### Story 2.3 — `<DemoDataBanner>` component

**Outcome:** A self-contained dashboard banner that (a) fetches the first 200 clusters via TanStack Query, (b) detects demo presence via `isDemoClusterName`, (c) reads/writes the dismissal localStorage key through `safeLocalStorageGet`/`safeLocalStorageSet`, (d) renders the plural-aware copy from `formatDemoClusterPrefix`, (e) returns `null` on fetch error, zero demos, or dismissal.

**Traces to FR-1, FR-2, FR-3, FR-7, FR-8.**

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/dashboard/demo-data-banner.tsx` | `'use client'` component exporting `<DemoDataBanner />`. Internal state: `dismissed: boolean` (initialized from localStorage on mount). Internal handlers: `handleDismiss()` (sets state + writes localStorage). Renders a shadcn `<Card>` with `info`-toned border + the FR-3 plural-aware body. Includes the FR-3 inline `<Link href="/studies">` CTA and the FR-3 Dismiss `<button>`. |
| `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx` | Vitest cases: (a) renders when demos>0 + not dismissed; (b) returns null when demos=0; (c) returns null when localStorage pre-set to `'1'`; (d) Dismiss click updates state AND writes localStorage; (e) banner survives `safeLocalStorageGet`/`safeLocalStorageSet` returning `null`/`false` (forced via `vi.mock`); (f) returns null when the clusters query errors; (g) **AC-9 coverage** — when the banner is rendered, the CTA element (`getByTestId('demo-data-banner-cta')`) has `href="/studies"` AND clicking the CTA does NOT call `safeLocalStorageSet` (assert via `vi.spyOn` on the wrapper module). |

**Modified files**

(none — Story 2.4 wires this into `page.tsx`)

**Endpoints**

N/A — consumes existing `GET /api/v1/clusters?sort=name:asc&limit=200`. No new endpoint.

**Key interfaces**

The component itself takes no props (it owns its state + queries).

```tsx
// ui/src/components/dashboard/demo-data-banner.tsx
'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useClusters } from '@/lib/api/clusters';
import { isDemoClusterName } from '@/lib/demo-data';
import { formatDemoClusterPrefix } from '@/lib/format-demo-cluster-prefix';
import { safeLocalStorageGet, safeLocalStorageSet } from '@/lib/safe-local-storage';

const DISMISS_KEY = 'relyloop.home-first-run-demo-nudge.dismissed';

export function DemoDataBanner(): React.ReactElement | null {
  // `mounted` gate prevents the FR-1 contract violation: if we initialized
  // `dismissed` to `false`, an already-dismissed user would see the banner
  // flash for one render between SSR/initial-client-render and the post-mount
  // localStorage hydration. By returning null until `mounted === true`, the
  // banner stays hidden on both server and the first client render, then only
  // appears after the effect tick that reads localStorage. Net effect: never
  // renders for dismissed users; mounts cleanly for fresh users.
  const [mounted, setMounted] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (safeLocalStorageGet(DISMISS_KEY) === '1') {
      setDismissed(true);
    }
  }, []);

  // Use the existing useClusters hook — its standard queryKey is
  // ['clusters', { ...filter }] so this call dedupes naturally with any
  // other dashboard consumer using the same params.
  const clusters = useClusters({ sort: 'name:asc', limit: 200 });

  if (!mounted) return null;
  if (dismissed) return null;
  if (clusters.isError) return null;
  if (!clusters.data) return null;

  const presentDemos = clusters.data.data
    .filter((c) => isDemoClusterName(c.name))
    .map((c) => c.name);
  if (presentDemos.length === 0) return null;

  const copy = formatDemoClusterPrefix(presentDemos);

  function handleDismiss() {
    setDismissed(true);
    safeLocalStorageSet(DISMISS_KEY, '1');
  }

  return (
    <Card
      role="region"
      aria-labelledby="demo-banner-heading"
      data-testid="demo-data-banner"
      className="border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20"
    >
      <CardHeader>
        <CardTitle id="demo-banner-heading" className="text-base">
          You&apos;re set up with demo data.
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">
          {copy.prefix}
          {copy.slugs.map((slug, i) => (
            <span key={slug}>
              <code className="rounded bg-blue-100 px-1 py-0.5 text-xs dark:bg-blue-900/40">
                {slug}
              </code>
              {i < copy.slugs.length - 1 ? ', ' : ''}
            </span>
          ))}
          {copy.suffix}
        </p>
        <div className="flex items-center gap-3">
          <Link
            href="/studies"
            data-testid="demo-data-banner-cta"
            className="text-sm font-medium text-blue-600 underline-offset-4 hover:underline"
          >
            Create your first study →
          </Link>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleDismiss}
                aria-label="Dismiss demo data banner"
                data-testid="demo-data-banner-dismiss"
              >
                Dismiss
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              Hide this banner in this browser. Clear browser storage to show it again.
            </TooltipContent>
          </Tooltip>
        </div>
      </CardContent>
    </Card>
  );
}
```

**Tasks**
1. Create the component file with the JSX above. Both `<DemoBadge>` (Story 3.1) and the Dismiss button are wrapped in `<Tooltip>` primitives — a `<TooltipProvider>` must be present at a parent layout level (likely already mounted by shadcn defaults; verify by grep'ing `ui/src/app/layout.tsx` and add it if missing).
2. Create `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx`. Mock `safeLocalStorageGet`/`safeLocalStorageSet` via `vi.mock('@/lib/safe-local-storage', ...)`. Mock `useClusters` via `vi.mock('@/lib/api/clusters', ...)` to return controlled cluster data. Assert each of the 7 cases above. Wrap the rendered component in `<TooltipProvider>` in the test setup if the component test doesn't pick up the app-level provider.
3. Run vitest filter on the new test file.
4. Lint + typecheck.

**Definition of Done**
- [ ] Component file exists with the documented JSX skeleton.
- [ ] Vitest covers all 7 cases (visible / no demos / dismissed / dismiss-click / throwing-localStorage / error-state / CTA href + non-mutation).
- [ ] AC-1, AC-3, AC-6, AC-7, AC-8, AC-9 of the spec are testable via this story's vitest (E2E story 4.1 covers AC-1 + AC-3 against the real backend too).
- [ ] AC-10 (SSR + throwing-localStorage safety) is covered by mocking `safeLocalStorageGet`/`safeLocalStorageSet` to return throw-equivalent values.

### Story 2.4 — Mount banner on the dashboard

**Outcome:** The dashboard page (`ui/src/app/page.tsx`) renders `<DemoDataBanner />` above `<StartHereChecklist />`. The banner's TanStack Query call coexists with the existing 5 dashboard queries (parallel, no blocking).

**Traces to FR-1.**

**New files**

(none)

**Modified files**

| File | Change |
|---|---|
| [`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx) | Import `DemoDataBanner`. Render `<DemoDataBanner />` inside the existing `{allFailed ? ... : <>` fragment, immediately above the `clustersCount.isSuccess && ...` `<StartHereChecklist>` block (currently lines 96–102). The banner is unconditional — it owns its own visibility logic via its internal query + state. No new state in `page.tsx`. |

(Story 4.1 owns the `dashboard.spec.ts` Playwright extension — NOT this story. Story 2.4 only modifies `page.tsx`.)

**Endpoints**

N/A.

**Key interfaces**

None new — pure JSX wiring.

**Tasks**
1. Edit [`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx) to import `DemoDataBanner` and render it inside the success branch, above the `<StartHereChecklist>` conditional.
2. Run `cd ui && pnpm dev` and visually verify on `http://localhost:3000/` that the banner renders when the auto-seed has run.
3. Run `cd ui && pnpm typecheck && pnpm lint`.

**Definition of Done**
- [ ] `page.tsx` imports + renders `<DemoDataBanner />`.
- [ ] Banner appears above the existing `<StartHereChecklist>` slot.
- [ ] Existing dashboard cards + recent studies still render unchanged on populated states.
- [ ] Lint + typecheck clean.

### Epic 2 gate

Hard stop — do not proceed to Epic 3 until:
- [ ] All 4 stories above complete with their DoDs satisfied.
- [ ] `cd ui && pnpm test src/__tests__/lib/safe-local-storage.test.ts src/__tests__/lib/format-demo-cluster-prefix.test.ts src/__tests__/components/dashboard/demo-data-banner.test.tsx` all green.
- [ ] Local stack via `make up`; the banner is visible on `http://localhost:3000/`; Dismiss persists across reload.

---

## Epic 3 — Demo indicator on cluster surfaces

### Story 3.1 — `<DemoBadge>` component

**Outcome:** A small, tooltip-enabled "Demo" chip rendered next to demo cluster names on `/clusters`. Wraps the existing shadcn `<Badge variant="secondary">` primitive with the FR-5 tooltip and a stable `data-testid`.

**Traces to FR-4 (JSX surface), FR-5.**

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/demo-badge.tsx` | `'use client'` (only if Tooltip pulls in client-only Radix code — verify; the existing tooltip primitive declares `'use client'` already so the badge consumer file may follow suit). Exports `<DemoBadge />` — a `<Tooltip>` wrapping a `<Badge variant="secondary">Demo</Badge>` with the FR-5 tooltip text. |
| `ui/src/__tests__/components/common/demo-badge.test.tsx` | Vitest cases: badge renders with text `"Demo"` + `data-testid="demo-badge"`; tooltip text matches the FR-5 string when triggered (use `userEvent.hover` if jsdom supports it, else assert `aria-label` or `<TooltipContent>` text contents). |

**Modified files**

(none — Story 3.2 mounts the badge into the clusters table)

**Endpoints**

N/A.

**Key interfaces**

```tsx
// ui/src/components/common/demo-badge.tsx
'use client';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

const TOOLTIP_TEXT =
  "Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over.";

export function DemoBadge(): React.ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/*
          tabIndex={0} makes the Badge keyboard-focusable so the tooltip is
          reachable via Tab navigation — required by FR-5 + §11 tooltip
          accessibility contract. role="img" with aria-label gives screen
          readers a semantically correct announcement ("Demo cluster, image")
          without misclassifying the static visual indicator as a button.
        */}
        <Badge
          variant="secondary"
          role="img"
          aria-label="Demo cluster"
          tabIndex={0}
          data-testid="demo-badge"
          className="ml-2 cursor-help focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        >
          Demo
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="top">{TOOLTIP_TEXT}</TooltipContent>
    </Tooltip>
  );
}
```

**Tasks**
1. Create `ui/src/components/common/demo-badge.tsx` with the JSX above.
2. Create vitest covering: (a) text + testid + aria-label render; (b) tooltip text contains the FR-5 string; (c) the badge is keyboard-focusable (assert `tabIndex` is `0` on the rendered element AND a `userEvent.tab()` reaches it from a sibling focusable). For tooltip-content visibility, use the repo's established pattern — see existing tests under [`ui/src/__tests__/components/common/`](../../../../ui/src/__tests__/components/common/) for whether to use `userEvent.hover`/`userEvent.tab` or to assert directly on the portal-rendered `<TooltipContent>` text.
3. Lint + typecheck.

**Definition of Done**
- [ ] `<DemoBadge />` exports correctly, renders text `"Demo"`, has `data-testid="demo-badge"`, `aria-label="Demo cluster"`, `role="img"`, and `tabIndex={0}`.
- [ ] Tooltip text matches the FR-5 string exactly.
- [ ] Badge is reachable via keyboard focus (verified by a vitest `userEvent.tab` assertion).
- [ ] AC-5 of the spec is verifiable via this story's vitest.

### Story 3.2 — Mount DemoBadge in clusters-table

**Outcome:** The `/clusters` list page renders the demo badge inline next to the `<Link>` for any cluster whose name is in `DEMO_CLUSTER_SLUGS`.

**Traces to FR-4 (cluster list surface), AC-4a.**

**New files**

(none)

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/clusters/clusters-table.column-config.tsx`](../../../../ui/src/components/clusters/clusters-table.column-config.tsx) | In the `name` column's `cell` (currently lines 25-34), import `isDemoClusterName` and `<DemoBadge />`, and append `{isDemoClusterName(row.original.name) ? <DemoBadge /> : null}` inside the cell after the `<Link>`. |
| `ui/src/__tests__/components/clusters/clusters-table.column-config.test.tsx` (NEW if missing — check first; existing tests live at `ui/src/__tests__/components/clusters/`) | Add a vitest case asserting the badge renders for a demo-named row and doesn't for non-demo rows. If a column-config-specific test file doesn't exist, extend the closest existing clusters-table vitest. |

**Endpoints**

N/A.

**Key interfaces**

```tsx
// in clusters-table.column-config.tsx, name column cell:
cell: ({ row }) => (
  <span className="inline-flex items-center">
    <Link
      href={`/clusters/${row.original.id}`}
      className="text-blue-600 underline-offset-4 hover:underline"
    >
      {row.original.name}
    </Link>
    {isDemoClusterName(row.original.name) ? <DemoBadge /> : null}
  </span>
),
```

**Tasks**
1. Edit [`ui/src/components/clusters/clusters-table.column-config.tsx`](../../../../ui/src/components/clusters/clusters-table.column-config.tsx) to add the imports and append the conditional `<DemoBadge />`.
2. Verify or extend the corresponding vitest under `ui/src/__tests__/components/clusters/`.
3. Lint + typecheck.

**Definition of Done**
- [ ] Demo-named rows render `<DemoBadge>` next to their name link.
- [ ] Non-demo rows render no badge.
- [ ] Vitest covers both branches.
- [ ] AC-4a of the spec is satisfied.

### Story 3.3 — `" (Demo)"` suffix in create-study modal cluster picker

**Outcome:** The create-study modal's cluster `<EntitySelect>` labels demo clusters with `"<name> (<engine_type>) (Demo)"`. The text suffix appears inside the shadcn `<SelectItem>` rendered by `<EntitySelect>`.

**Traces to FR-4 (modal surface), AC-4b.**

**New files**

(none)

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | At line 511, change `getLabel={(c) => \`${c.name} (${c.engine_type})\`}` to compute the suffix: `getLabel={(c) => \`${c.name} (${c.engine_type})${isDemoClusterName(c.name) ? ' (Demo)' : ''}\`}`. Import `isDemoClusterName` from `@/lib/demo-data`. |
| One of `ui/src/__tests__/components/studies/create-study-modal.*.test.tsx` (extend the closest existing test file — likely `create-study-modal.test.tsx`) | Add a vitest case: render the modal with a cluster query result that includes `{ id: 'x', name: 'acme-products-prod', engine_type: 'elasticsearch', ... }` plus a non-demo cluster; open the `<Select>`; assert the demo option's text contains `"acme-products-prod (elasticsearch) (Demo)"` AND the non-demo option's text does NOT contain `" (Demo)"`. |

**Endpoints**

N/A.

**Key interfaces**

The change is a single `getLabel` callback edit. No new function signatures.

**Tasks**
1. Edit [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) to add the `isDemoClusterName` import and the suffix-aware `getLabel`.
2. Extend the closest existing `create-study-modal.*.test.tsx` with the new vitest assertion. (Picking `create-study-modal.test.tsx` for the broad path — if the test patterns there don't cover the cluster picker, use `create-study-modal.builder-rendering.test.tsx` instead.)
3. Lint + typecheck.

**Definition of Done**
- [ ] `getLabel` callback appends `" (Demo)"` for cluster names in `DEMO_CLUSTER_SLUGS`.
- [ ] New vitest assertion proves the suffix appears for demo names and does not for non-demo names.
- [ ] AC-4b of the spec is satisfied.

### Story 3.4 — `" (Demo)"` suffix in proposals-table cluster fk-select

**Outcome:** The proposals page cluster filter dropdown shows `"<name> (Demo)"` for demo-named clusters in its options.

**Traces to FR-4 (proposals filter surface), AC-4c.**

**New files**

(none)

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/proposals/proposals-table.column-config.tsx`](../../../../ui/src/components/proposals/proposals-table.column-config.tsx) | In the `useClustersForFilter` hook adapter (currently lines 40-46), change `label: c.name` to `label: c.name + (isDemoClusterName(c.name) ? ' (Demo)' : '')`. Import `isDemoClusterName` from `@/lib/demo-data`. |
| `ui/src/__tests__/components/proposals/proposals-table.test.tsx` | Extend (or split into a sibling test file `proposals-table.column-config.test.tsx` if cleaner) to assert that the `useClustersForFilter` adapter returns labels with the `" (Demo)"` suffix for demo names. Likely strategy: import the adapter function (it's not currently exported — Story 3.4 task includes a small refactor to export it for testability, OR use `useClusters` mock + render `<ProposalsTable>` and assert against the dropdown options). |

**Endpoints**

N/A.

**Key interfaces**

```ts
// Before:
function useClustersForFilter(): { data: { id: string; label: string }[]; isLoading: boolean } {
  const q = useClusters({ limit: 200 });
  return {
    data: (q.data?.data ?? []).map((c) => ({ id: c.id, label: c.name })),
    isLoading: q.isPending,
  };
}

// After:
function useClustersForFilter(): { data: { id: string; label: string }[]; isLoading: boolean } {
  const q = useClusters({ limit: 200 });
  return {
    data: (q.data?.data ?? []).map((c) => ({
      id: c.id,
      label: c.name + (isDemoClusterName(c.name) ? ' (Demo)' : ''),
    })),
    isLoading: q.isPending,
  };
}
```

**Tasks**
1. Edit the adapter hook to append the suffix.
2. Add a vitest assertion proving the suffix appears for demo names. If the adapter is not currently testable in isolation, render `<ProposalsTable>` with a mocked `useClusters` result and assert against the rendered `<option>` text.
3. Lint + typecheck.

**Definition of Done**
- [ ] `useClustersForFilter` returns suffixed labels for demo names.
- [ ] Vitest proves the suffix.
- [ ] AC-4c of the spec is satisfied.

### Epic 3 gate

- [ ] All 4 stories above complete with DoDs satisfied.
- [ ] `cd ui && pnpm test src/__tests__/components/common/demo-badge.test.tsx src/__tests__/components/clusters` and the create-study + proposals test additions all green.
- [ ] Visual smoke check on `/clusters`, the create-study modal cluster picker, and the proposals page cluster filter dropdown all show the demo indicator.

---

## Epic 4 — CI parity guard + E2E + docs

### Story 4.1 — Playwright E2E coverage in `dashboard.spec.ts`

**Outcome:** The existing Playwright spec for `/` is extended with 3 new test blocks proving the banner's behavior against the real backend.

**Traces to FR-1, FR-3, FR-7 (real-backend verification). Covers AC-1, AC-3, AC-6.**

**New files**

(none — extends existing file per spec §14)

**Modified files**

| File | Change |
|---|---|
| [`ui/tests/e2e/dashboard.spec.ts`](../../../../ui/tests/e2e/dashboard.spec.ts) | Append a new `test.describe('/ dashboard demo-data banner', ...)` block with 3 tests: (1) banner is visible when seeded demos are present, regardless of seeded study count; (2) clicking Dismiss persists across reload; (3) `page.addInitScript` pre-sets localStorage and the banner is not shown. All against the real backend at `localhost:8000` — NO `page.route()` mocking of `/api/v1/clusters` per CLAUDE.md E2E rules. Test setup relies on the CI environment's seeded demo state (the canonical CI run includes `make up` which auto-seeds). |

**Endpoints**

N/A.

**Key interfaces**

```ts
// Append to ui/tests/e2e/dashboard.spec.ts:
test.describe('/ dashboard demo-data banner', () => {
  test('banner renders on a seeded stack with demo clusters present', async ({ page }) => {
    await page.goto('/');
    const banner = page.getByTestId('demo-data-banner');
    await expect(banner).toBeVisible({ timeout: 5_000 });
    await expect(banner.getByRole('heading')).toHaveText("You're set up with demo data.");
  });

  test('Dismiss persists across reload', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('demo-data-banner-dismiss').click();
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
    await page.reload();
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
  });

  test('Pre-set localStorage hides the banner from initial render', async ({ page, context }) => {
    await context.addInitScript(() => {
      window.localStorage.setItem('relyloop.home-first-run-demo-nudge.dismissed', '1');
    });
    await page.goto('/');
    // Wait for the dashboard to load so we know the banner had a chance to render.
    await expect(page.getByTestId('card-open-proposals')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
  });
});
```

**Tasks**
1. Append the new `test.describe` block to [`ui/tests/e2e/dashboard.spec.ts`](../../../../ui/tests/e2e/dashboard.spec.ts).
2. Run locally: `cd ui && pnpm test:e2e -- dashboard.spec.ts`. Three new tests green; existing two tests still green.
3. **Cleanup contract:** the dismiss test mutates localStorage on the test browser; Playwright defaults to per-test browser contexts so the mutation does not bleed. Verify by running the suite twice in a row — both runs should report all 5 tests passing (no flake from leaked state).

**Definition of Done**
- [ ] 3 new tests added to `dashboard.spec.ts`.
- [ ] All 5 tests in the file green locally (2 existing + 3 new).
- [ ] Tests use `page` / `context.addInitScript` for browser-layer assertions; ZERO `page.route()` mocking of `/api/v1/clusters`.
- [ ] AC-1, AC-3, AC-6 of the spec verified against the real backend.

### Story 4.2 — `scripts/ci/verify_demo_slug_parity.sh` + wire into pr.yml

**Outcome:** A CI guard fails the build if the 4 slugs in `ui/src/lib/demo-data.ts` `DEMO_CLUSTER_SLUGS` and the 4 `"slug":` literals in `scripts/seed_meaningful_demos.py SCENARIOS` ever drift apart.

**Traces to FR-9 (CI guard half), AC-11.**

**New files**

| File | Purpose |
|---|---|
| `scripts/ci/verify_demo_slug_parity.sh` | Bash script. Parses `DEMO_CLUSTER_SLUGS` from `ui/src/lib/demo-data.ts` via a regex; parses `"slug": "<slug>"` lines from `scripts/seed_meaningful_demos.py`. Compares the two sets. Exits 0 on match, non-zero with a diagnostic on mismatch. Modeled on [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh). |

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | Add a small step (in the `frontend` or a new lightweight job) that runs `bash scripts/ci/verify_demo_slug_parity.sh`. Place it adjacent to the existing `verify_enum_source_of_truth.sh` step (if one exists) or as a standalone `verify-demo-slug-parity` job similar to `secrets-files-guard`. Job runs in <10s; no service containers needed. |

**Endpoints**

N/A.

**Key interfaces**

```bash
#!/usr/bin/env bash
# scripts/ci/verify_demo_slug_parity.sh
#
# Verifies DEMO_CLUSTER_SLUGS (frontend) matches SCENARIOS[*]["slug"] (CLI script).
# Modeled on verify_enum_source_of_truth.sh — same exit-code contract.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FE_FILE="${REPO_ROOT}/ui/src/lib/demo-data.ts"
PY_FILE="${REPO_ROOT}/scripts/seed_meaningful_demos.py"

# Extract the frontend slugs from the `as const` tuple in demo-data.ts.
# Pattern: lines between `DEMO_CLUSTER_SLUGS = [` and `] as const;`, each
# bearing a single 'slug-string', stripped of quotes and trailing comma.
fe_slugs=$(awk '/^export const DEMO_CLUSTER_SLUGS = \[/,/\] as const;/' "${FE_FILE}" \
  | grep -oE "'[a-z0-9-]+'" | tr -d "'" | sort)

# Extract the Python slugs from the SCENARIOS list literals.
# Pattern: lines like `"slug": "acme-products-prod",`
py_slugs=$(grep -oE '"slug":\s*"[a-z0-9-]+"' "${PY_FILE}" \
  | grep -oE '"[a-z0-9-]+"$' | tr -d '"' | sort)

if [[ -z "${fe_slugs}" ]]; then
  echo "verify_demo_slug_parity: failed to parse frontend slugs from ${FE_FILE}" >&2
  exit 2
fi
if [[ -z "${py_slugs}" ]]; then
  echo "verify_demo_slug_parity: failed to parse python slugs from ${PY_FILE}" >&2
  exit 2
fi
if [[ "${fe_slugs}" != "${py_slugs}" ]]; then
  echo "verify_demo_slug_parity: drift between frontend and seed script" >&2
  echo "  frontend (${FE_FILE}):" >&2
  echo "${fe_slugs}" | sed 's/^/    /' >&2
  echo "  python   (${PY_FILE}):" >&2
  echo "${py_slugs}" | sed 's/^/    /' >&2
  exit 1
fi

count=$(echo "${fe_slugs}" | wc -l | tr -d ' ')
echo "verify_demo_slug_parity: ${count} demo slugs verified — clean"
```

**Tasks**
1. Create `scripts/ci/verify_demo_slug_parity.sh` with the contents above; `chmod +x`.
2. Run locally: `bash scripts/ci/verify_demo_slug_parity.sh` — must exit 0 against the current files. Then temporarily edit one slug in `ui/src/lib/demo-data.ts` to verify the guard exits non-zero with the diagnostic. Revert the edit.
3. Edit `.github/workflows/pr.yml` to add the step. Match the existing job structure (use the `secrets-files-guard` workflow at `.github/workflows/secrets-defense.yml` as a precedent for adding a small standalone job, OR add a step under `frontend` if that job is the right shared lane). **Decision point during implementation:** if pr.yml has a `lint`-style frontend job, add the step there; otherwise add a new `verify-demo-slug-parity` job that runs in parallel with the others. Verify pr.yml passes `gh workflow run` syntax-check or local actionlint.
4. Push a temporary commit deliberately introducing a slug mismatch (e.g., rename one slug to `acme-products-staging` in the frontend) and confirm CI fails. Revert before merging.

**Definition of Done**
- [ ] `scripts/ci/verify_demo_slug_parity.sh` exists, executable, runs in <2s.
- [ ] Wired into `pr.yml` and runs on every PR.
- [ ] Verified locally to fail loudly on drift (tested by temporary edit, then reverted).
- [ ] AC-11 of the spec satisfied.

### Story 4.3 — Documentation updates

**Outcome:** [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) gains a "Demo data nudge" subsection; [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) gains a "Resetting demo state" paragraph; [`state.md`](../../../../state.md) records the completed feature.

**Traces to spec §15 + the standard finalization step.**

**New files**

(none)

**Modified files**

| File | Change |
|---|---|
| [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) | Add a "Demo data nudge" subsection under "Dashboard" (or wherever the existing dashboard architecture text lives — read the file first to find the right anchor). Describe: the banner trigger, the `DEMO_CLUSTER_SLUGS` + `isDemoClusterName` source-of-truth pattern, and the CI parity guard. Link to this spec. |
| [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) | Append a "Resetting demo state" paragraph documenting `make seed-demo FORCE=1`, the fact that the dismissal localStorage key is NOT cleared by reseeding (manual clear via dev tools required), and the link to Phase 2 ([`phase2_idea.md`](phase2_idea.md)) for the eventual reseed-UI affordance. |
| [`state.md`](../../../../state.md) | Add an entry under "Recent changes" describing the merged PR. Update the active-branch section as needed. |

**Endpoints**

N/A.

**Tasks**
1. Read [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md), find the dashboard section, append the new subsection.
2. Read [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md), append the new paragraph at the appropriate seam.
3. Edit [`state.md`](../../../../state.md) to record the merged feature.
4. Run `cd ui && pnpm lint` (no docs lint exists, but a sanity pass on the repo).

**Definition of Done**
- [ ] All 3 doc files updated.
- [ ] References to this feature link back to [`feature_spec.md`](feature_spec.md).
- [ ] `state.md` reflects the merged state of Phase 1.

### Epic 4 gate

- [ ] All 3 stories above complete.
- [ ] CI runs `verify_demo_slug_parity.sh` and passes.
- [ ] Playwright E2E adds 3 new tests, all green.
- [ ] Docs reflect shipped behavior.

---

## UI Guidance

### Reference: current component structure

**[`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx)** (137 lines)
- Sections, top-to-bottom:
  - Lines 1-14: imports
  - Lines 15-19: `SEVEN_DAYS_MS` constant + `sevenDaysAgoIso()` helper
  - Lines 21-72: `DashboardPage` component
    - Lines 22-49: 3 TanStack Query calls for the count cards (recent, openProposals, completedRecently)
    - Lines 51-71: 2 additional queries for clustersCount + judgmentListsCount used by `<StartHereChecklist>`
  - Lines 73-136: render
    - Lines 76-82: heading block
    - Lines 83-87: `allFailed` empty state
    - Lines 88-133: success branch
      - Lines 96-102: `<StartHereChecklist>` conditional render (only when all 3 count queries succeed)
      - Lines 103-118: `<section>` with `<CountCard>` × 2
      - Lines 119-132: Recent studies `<Card>`
- State variables: none (all data lives in TanStack Query).
- Props: none — top-level page.
- Insertion point: line 95 (immediately before the `<StartHereChecklist>` conditional). The banner renders unconditionally; it owns its own visibility.

**[`ui/src/components/dashboard/start-here-checklist.tsx`](../../../../ui/src/components/dashboard/start-here-checklist.tsx)** (153 lines)
- Pure prop-driven component (`hasClusters: boolean`, `hasQuerySetsWithJudgments: boolean`, `hasStudies: boolean`).
- Returns `null` on line 51 when all three props are true (the auto-hide).
- **No modification to this file** — the new banner is independent.

**[`ui/src/components/clusters/clusters-table.column-config.tsx`](../../../../ui/src/components/clusters/clusters-table.column-config.tsx)** (existing)
- 6 columns; the first one (`name`) is the insertion point for the badge. See Story 3.2 key interface.

**[`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)** (~700 lines)
- The cluster `<EntitySelect>` lives at lines 506-528. The `getLabel` callback is at line 511. See Story 3.3 key interface.

**[`ui/src/components/proposals/proposals-table.column-config.tsx`](../../../../ui/src/components/proposals/proposals-table.column-config.tsx)** (177 lines)
- The `useClustersForFilter` adapter is at lines 40-46. See Story 3.4 key interface.

### Analogous markup patterns

**Card outer structure (analogous to `<StartHereChecklist>`'s `<Card>` shell)**

```tsx
{/* From: ui/src/components/dashboard/start-here-checklist.tsx:87-94 — STRUCTURE only,
    no accent classes on this <Card>. The accent comes from a sibling pattern below. */}
<Card data-testid="start-here-checklist">
  <CardHeader>
    <CardTitle className="text-base">Get started</CardTitle>
    <p className="text-sm text-muted-foreground">
      Three steps to your first relevance proposal. Each one unlocks the next.
    </p>
  </CardHeader>
  <CardContent>
    {/* body */}
  </CardContent>
</Card>
```

**Accent-color pattern (analogous to `start-here-checklist.tsx:108` — the emerald "step done" treatment)**

```tsx
{/* From: ui/src/components/dashboard/start-here-checklist.tsx:106-112 */}
className={`flex items-start gap-3 rounded-md border p-3 ${
  step.done
    ? 'border-emerald-200 bg-emerald-50/50 dark:border-emerald-900/40 dark:bg-emerald-950/20'
    : isCurrent
      ? 'border-foreground/20 bg-background'
      : 'border-muted bg-muted/30 opacity-70'
}`}
```

The banner combines (a) the structural `<Card>` shell from lines 87-94 with (b) a NEW blue/info accent color choice modeled on the emerald pattern at line 108 but swapped to blue: `border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20`. The blue/info treatment is intentionally new — it differentiates the informational banner from the checklist's emerald "completion" states without inventing a new design token.

**Dismiss button (analogous to the Tooltip-trigger badge approach in `<DemoBadge>`)**

The Dismiss button uses the existing shadcn `<Button variant="outline" size="sm">` from [`ui/src/components/ui/button.tsx`](../../../../ui/src/components/ui/button.tsx). No new primitive needed.

**Inline `<Link>` CTA (analogous to `<StartHereChecklist>` step CTAs at line 137)**

```tsx
{/* From: ui/src/components/dashboard/start-here-checklist.tsx:136-142 */}
<Link
  href={step.href}
  data-testid={`start-here-cta-${step.key}`}
  className="inline-block text-xs font-medium text-blue-600 underline-offset-4 hover:underline"
>
  {step.ctaLabel} →
</Link>
```

The banner's "Create your first study →" CTA reuses this exact style (`text-blue-600 underline-offset-4 hover:underline`). Size bumped to `text-sm` to match the banner's overall body size.

**Tooltip on a small interactive element (analogous to existing tooltip usage in shadcn)**

```tsx
{/* From: ui/src/components/ui/tooltip.tsx — primitive structure */}
<Tooltip>
  <TooltipTrigger asChild>
    <Badge>...</Badge>
  </TooltipTrigger>
  <TooltipContent side="top">...</TooltipContent>
</Tooltip>
```

The dashboard layout must be wrapped in `<TooltipProvider>` — this is already provided at the app-layout level by shadcn defaults; verify by grep'ing for `<TooltipProvider>` in `ui/src/app/layout.tsx` before writing the test. If not present, Story 3.1 must add it to the page or layout.

### Layout and structure

- The banner is a single `<Card>` with `border-blue-200 bg-blue-50/50` (dark variants on `dark:` prefix).
- Inside: `<CardHeader>` with `<CardTitle>`, then `<CardContent>` with two children stacked vertically (`space-y-3`): a `<p>` with the body copy, and a `<div className="flex items-center gap-3">` containing the inline `<Link>` CTA and the Dismiss `<Button>`.
- No responsive collapse — the banner uses the dashboard's max-w-7xl page width and stacks naturally on narrower viewports.
- The demo badge in cluster tables uses `ml-2` to separate from the cluster link; no other layout change.

### Confirmation/modal dialog pattern

N/A — Phase 1 has no confirmation dialogs. Phase 2's reseed button will need one (see [`phase2_idea.md`](phase2_idea.md)).

### Visual consistency table

| New element | CSS class / pattern | Source |
|---|---|---|
| Banner card | `border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20` | analogous to `<StartHereChecklist>`'s `border-emerald-200 bg-emerald-50/50 …` at [`start-here-checklist.tsx:108`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) (color swapped to blue/info tone) |
| Banner heading | `text-base` via `<CardTitle>` | [`start-here-checklist.tsx:90`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) |
| Banner body text | `text-sm` | [`start-here-checklist.tsx:91`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) |
| Slug code chips | `rounded bg-blue-100 px-1 py-0.5 text-xs dark:bg-blue-900/40` | new — derived from shadcn's chip/code-inline patterns |
| Inline CTA | `text-sm font-medium text-blue-600 underline-offset-4 hover:underline` | [`start-here-checklist.tsx:139`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) (`text-xs` bumped to `text-sm` for the banner) |
| Dismiss button | `<Button variant="outline" size="sm">` | shadcn primitive at [`ui/src/components/ui/button.tsx`](../../../../ui/src/components/ui/button.tsx) |
| Demo badge | `<Badge variant="secondary" className="ml-2 cursor-help">` | shadcn primitive at [`ui/src/components/ui/badge.tsx`](../../../../ui/src/components/ui/badge.tsx) |
| Tooltip | `<Tooltip><TooltipTrigger asChild><Badge … /></TooltipTrigger><TooltipContent side="top">…</TooltipContent></Tooltip>` | [`ui/src/components/ui/tooltip.tsx`](../../../../ui/src/components/ui/tooltip.tsx) |

### Component composition

- `<DemoDataBanner>` is **self-contained**: own state, own query, own helpers. Page renders it as `<DemoDataBanner />` with no props. Rationale: the banner has zero parent dependencies; making it self-contained avoids polluting `page.tsx` with another query + state.
- `<DemoBadge>` is **stateless**: pure JSX with the tooltip wrapper. Composed inline next to cluster names in the clusters-table cell.
- `safeLocalStorageGet` / `safeLocalStorageSet` are **module-level utilities** in `ui/src/lib/safe-local-storage.ts`. Imported by `<DemoDataBanner>` directly. Available to any future feature.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Visit `/` for the first time on a seeded stack | `<DemoDataBanner>` mounts, issues `GET /api/v1/clusters?sort=name:asc&limit=200`, detects demos, renders banner | `GET /api/v1/clusters?sort=name:asc&limit=200` (existing endpoint) |
| Click Dismiss | `setDismissed(true)` (immediate unmount via state), `safeLocalStorageSet('relyloop.home-first-run-demo-nudge.dismissed', '1')` (best-effort write) | none |
| Reload after Dismiss | useEffect reads localStorage via `safeLocalStorageGet`; if `'1'`, sets `dismissed = true` on first render after mount; banner stays hidden | `GET /api/v1/clusters?sort=name:asc&limit=200` still fires (TanStack Query cache hit if within window) but banner returns `null` immediately so the query result is unused for rendering |
| Click "Create your first study →" CTA | Standard Next.js `<Link>` navigation to `/studies` | none (route change only) |
| Click a cluster name on `/clusters` | (Unchanged from today.) Navigates to `/clusters/[id]`. Badge is purely decorative; not clickable. | none |
| Hover the Demo badge | Radix UI tooltip opens after the default 700ms hover delay, shows FR-5 text | none |
| Open the create-study modal on the cluster picker | Existing `<EntitySelect>` flow. Demo options render with `" (Demo)"` suffix in the option label. | (existing `useClusters` query — unchanged) |

### Handler function patterns

**`handleDismiss` (inside `<DemoDataBanner>`):**

```tsx
function handleDismiss() {
  // 1. Update state synchronously so the banner unmounts on the next React commit
  //    regardless of localStorage success.
  setDismissed(true);
  // 2. Best-effort persistence. Failure returns false but we don't surface it —
  //    the banner is already hidden in this tab; future visits will simply re-show
  //    until the operator dismisses again.
  safeLocalStorageSet('relyloop.home-first-run-demo-nudge.dismissed', '1');
}
```

**Mount + hydration (inside `<DemoDataBanner>`):**

```tsx
const [mounted, setMounted] = useState(false);
const [dismissed, setDismissed] = useState(false);

useEffect(() => {
  setMounted(true);
  if (safeLocalStorageGet('relyloop.home-first-run-demo-nudge.dismissed') === '1') {
    setDismissed(true);
  }
}, []);

// later in render:
if (!mounted) return null;  // gate prevents the dismissed-user flash
if (dismissed) return null;
// ... rest of the checks
```

Why a `mounted` gate: reading localStorage during initial render would cause an SSR/CSR hydration mismatch on Next.js (server can't see localStorage; client can). Without the gate, a `dismissed === false` initial state would cause the banner to flash visible for one render before the post-mount effect reads localStorage and unmounts it — violating FR-1's MUST NOT render contract for pre-dismissed users. The gate returns `null` from both the server and the very first client render, then the effect sets `mounted = true` AND reads `dismissed` in the same tick, so dismissed users never see the banner at all. New users see the banner only after the effect completes — acceptable because no localStorage is set for them, so `dismissed` stays `false` and the banner renders on the second commit.

Alternative considered: `useSyncExternalStore` — overkill for this scope; the mount-gate pattern is well-established in the React ecosystem.

### Information architecture placement

- Dashboard root `/` (existing).
- Renders above `<StartHereChecklist />`'s slot; the checklist's auto-hide logic is independent.
- No new top-level navigation entry; no new tab; no settings entry.
- Discovery: the banner IS the discovery affordance — operators see it on first visit. Demo badges on `/clusters` reinforce the seed-vs-self distinction in the directory listing.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | JSX pattern |
|---|---|---|---|---|
| `<DemoBadge>` | `"Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over."` | hover / focus (Radix default) | top | See Story 3.1 key interface. |
| Banner "Dismiss" button | `"Hide this banner in this browser. Clear browser storage to show it again."` | hover / focus | bottom | Wrap the `<Button>` in `<Tooltip><TooltipTrigger asChild>…</TooltipTrigger><TooltipContent side="bottom">…</TooltipContent></Tooltip>` per the same pattern as `<DemoBadge>`. |

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** The largest modification (Story 3.3) changes a single `getLabel` callback line in `create-study-modal.tsx`; no behaviors are dropped. Story 2.4 adds a render line to `page.tsx` (no deletions). Stories 3.2 and 3.4 add JSX/text inside existing column-config cells; no existing behavior is removed.

### Client-side persistence

- **`localStorage`** — banner dismissal. Persists indefinitely across browser sessions. Per-browser, not per-user (no auth yet).
- The DoD wording matches: AC-3 says "on a subsequent `window.location.reload()` … the banner does NOT render" — i.e., persists across sessions. No `sessionStorage` is used in this plan.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `ui/src/__tests__/lib/` + `ui/src/__tests__/components/dashboard/` + `ui/src/__tests__/components/common/`
- Scope: pure helpers (`demo-data`, `safe-local-storage`, `format-demo-cluster-prefix`); banner component branches; badge component.
- Tasks:
  - [ ] `ui/src/__tests__/lib/demo-data.test.ts` (Story 1.1) — DEMO_CLUSTER_SLUGS shape + `isDemoClusterName` happy/non-demo cases.
  - [ ] `ui/src/__tests__/lib/safe-local-storage.test.ts` (Story 2.1) — SSR, happy, throwing-get, throwing-set.
  - [ ] `ui/src/__tests__/lib/format-demo-cluster-prefix.test.ts` (Story 2.2) — K=1, K=2, K=3, K=4 variants.
  - [ ] `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx` (Story 2.3) — 6 branches.
  - [ ] `ui/src/__tests__/components/common/demo-badge.test.tsx` (Story 3.1) — render + tooltip.
  - [ ] Extension to an existing `create-study-modal.*.test.tsx` (Story 3.3) — `" (Demo)"` suffix in modal cluster picker.
  - [ ] Extension to `proposals-table.test.tsx` (Story 3.4) — `" (Demo)"` suffix in proposals cluster fk-select.
- DoD:
  - [ ] All 7 test files (5 new + 2 extensions) pass under `cd ui && pnpm test`.
  - [ ] Each FR with a vitest-level acceptance criterion (AC-1, AC-2, AC-3, AC-4a/b/c, AC-5, AC-6, AC-7, AC-8, AC-10) has at least one assertion.

### 3.2 Integration tests

N/A in Phase 1 — no backend integration changes. Phase 2 will need integration tests for the reseed endpoint.

### 3.3 Contract tests

N/A in Phase 1 — no new endpoints. The error catalog (§8.5 of the spec) introduces no new codes.

### 3.4 E2E tests

- Location: `ui/tests/e2e/dashboard.spec.ts`
- Scope: banner renders against a real-backend seeded stack; dismiss persists; pre-set dismissal hides banner.
- **Rule:** real browser interactions only — `page` for assertions, `context.addInitScript` for pre-seeding localStorage. NO `page.route()` mocking of `/api/v1/clusters` (Story 4.1 DoD).
- Tasks:
  - [ ] Story 4.1 appends 3 new tests to `dashboard.spec.ts`.
- DoD:
  - [ ] All 5 tests in `dashboard.spec.ts` green (2 existing + 3 new) on `cd ui && pnpm test:e2e -- dashboard.spec.ts`.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`ui/tests/e2e/dashboard.spec.ts`](../../../../ui/tests/e2e/dashboard.spec.ts) | `getByTestId('card-open-proposals')`, `card-completed-recent` | 4 occurrences | No change to existing assertions — the 2 existing tests are unaffected by the banner. Story 4.1 APPENDS 3 new tests. |
| [`ui/src/__tests__/components/dashboard/`](../../../../ui/src/__tests__/components/dashboard/) | (folder does not exist yet) | 0 | Story 2.3 creates it. |
| Existing clusters / studies / proposals tests | references to cluster names, picker labels | varied | No assertions currently match `" (Demo)"` literal text, so existing tests are safe. Stories 3.3 + 3.4 ADD new assertions; do not change existing ones. |
| `ui/src/__tests__/lib/enums.test.ts` | enum-source-of-truth coverage | 1 file | No change — demo slugs deliberately live in `demo-data.ts`, not `enums.ts`, so the existing CI guard (`verify_enum_source_of_truth.sh`) is unaffected. |

### 3.5 Migration verification

N/A — no schema changes.

### 3.6 CI gates

- [ ] `cd ui && pnpm lint` — clean.
- [ ] `cd ui && pnpm typecheck` — clean.
- [ ] `cd ui && pnpm test` — all vitest green.
- [ ] `cd ui && pnpm test:e2e -- dashboard.spec.ts` — all 5 tests green.
- [ ] `bash scripts/ci/verify_demo_slug_parity.sh` — exits 0.

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] [`state.md`](../../../../state.md) — record the merged PR + the new fact that the dashboard renders a demo-data banner.
- [ ] [`architecture.md`](../../../../architecture.md) — no top-level layer change; the `ui/src/lib/demo-data.ts` source-of-truth file is documented as part of [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) below.
- [ ] [`CLAUDE.md`](../../../../CLAUDE.md) — no new conventions; the existing localStorage namespace + frontend source-of-truth discipline already cover this feature.

### 4.1 Architecture docs

- [ ] [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — add a "Demo data nudge" subsection.

### 4.2 Product docs

- [ ] No changes — [`feature_spec.md`](feature_spec.md) IS the product doc.

### 4.3 Runbooks

- [ ] [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) — append a "Resetting demo state" paragraph.

### 4.4 Security docs

- [ ] No changes — no new secrets, no PII, no auth.

### 4.5 Quality docs

- [ ] No changes — test layers unchanged.

**Documentation DoD**

- [ ] All 3 file updates above complete.
- [ ] Cross-references between the spec, plan, and ui-architecture doc are reciprocal.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Generalize the existing SSR-only localStorage guard from `data-table.tsx:123` into a shared utility (Story 2.1). This is a small, scoped extraction — not a rewrite.

### 5.2 Planned refactor tasks

- [ ] Story 2.1 creates `safe-local-storage.ts` as a new shared utility. Existing consumers (`data-table.tsx`, `guide-viewer.tsx`, `markdown-doc.tsx`) MAY be migrated to use the wrapper in a follow-up, but this plan does NOT modify them — out of scope for Phase 1.
- [ ] No frontend refactors beyond the new utility.

### 5.3 Refactor guardrails

- [ ] No behavioral changes to existing components (data-table, guide-viewer) in this PR. They continue to use `window.localStorage` directly per their current implementations.
- [ ] Lint + typecheck remain green.
- [ ] No expansion of product scope — the helper is the minimum new code needed for FR-6.
- [ ] If a future cleanup migrates existing consumers to the new wrapper, that work is captured as a separate idea file (`chore_safe_local_storage_migration` — file at the operator's discretion, not part of this plan).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| PR #182 auto-seed | Banner visibility on first-run | Implemented (merged 2026-05-21) | Banner silently hides (graceful degradation per FR-8 — no error state) |
| Existing `GET /api/v1/clusters` with `sort=name:asc&limit=200` | Story 2.3 banner query | Implemented (`backend/app/api/v1/clusters.py:191`) | Banner cannot fetch demo data; FR-8 fallback to hidden state |
| `<StartHereChecklist>` | Banner sits above its slot | Implemented (`feat_contextual_help_mvp2` Phase 3) | Cosmetic only — banner still renders independently |
| shadcn `<Card>`, `<Button>`, `<Badge>`, `<Tooltip>` primitives | All UI stories | Implemented | Blocker — but all primitives are in the repo already |
| `<TooltipProvider>` mounted in app layout | Story 3.1 badge tooltip | TBD — must verify at Story 3.1 start | If missing, Story 3.1 must add it; small additional change (1 line in `layout.tsx`) |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Operator renames a demo cluster slug, drift between frontend constant and seed script | Medium | High (badge silently disappears for that cluster, banner may underreport) | CI guard `verify_demo_slug_parity.sh` (Story 4.2) — fails CI on drift. |
| TanStack Query's default `gcTime` causes the banner's `/api/v1/clusters` payload to evict between renders, triggering re-fetches | Low | Low (network noise on dashboard mounts) | If observed in practice, add `staleTime: 60_000` to the banner query — documented as a follow-up option in spec §13. |
| jsdom doesn't render Radix Portal-based tooltips, so `<DemoBadge>` tooltip vitest is hard to assert directly | Medium | Low (tooltip text is still verifiable on the rendered `<TooltipContent>` element) | Story 3.1 vitest uses `screen.getByText(TOOLTIP_TEXT)` after triggering hover — fall back to asserting the `TooltipContent` rendered text without exercising the open animation. Match the pattern already established in the codebase (check existing tooltip tests under `ui/src/__tests__/components/common/`). |
| Hydration mismatch on the banner's initial render (server-rendered "not dismissed" vs. client-side "dismissed") causes a console warning OR a visible flash for pre-dismissed users | Low | Medium (visible flash would violate FR-1's MUST NOT render contract) | Story 2.3 uses a `mounted` gate: the banner returns `null` from both the server and the very first client render, then the post-mount effect both sets `mounted = true` AND reads localStorage in the same tick. Pre-dismissed users never see the banner; fresh users see it on the second commit. No flash. |
| Playwright E2E flakes on CI's seeded-state setup if `make up` partially fails | Medium | Medium (false negatives) | The existing `dashboard.spec.ts` already runs against the same seeded state; if the seed is broken, those tests also fail. No additional fragility introduced. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cluster fetch 5xx | Backend down or transient error | Banner returns `null` (FR-8); dashboard's existing `allFailed` empty-state still works | TanStack Query auto-retries per app defaults; user reload also retries |
| `window.localStorage` throws on read | Safari private mode, disabled storage | `safeLocalStorageGet` returns `null`; banner treats as "not dismissed"; renders | None needed — visible state is correct |
| `window.localStorage` throws on write | Same | `safeLocalStorageSet` returns `false`; banner state still updates so banner unmounts in this tab | On next visit, banner re-renders (write failed); operator can dismiss again |
| Demo cluster renamed in DB but not in frontend constant | Operator manual rename | Badge disappears for the renamed cluster; banner reports fewer slugs but still renders if any other demo remains | Update both files OR re-run the seed script |
| Frontend constant lists a slug the seed script doesn't | Drift | CI guard fails; PR is blocked | Reconcile both files |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Story 1.1) — must come first; everything depends on `DEMO_CLUSTER_SLUGS` + `isDemoClusterName`.
2. **Epic 2** (Stories 2.1, 2.2, 2.3, 2.4) — banner stack. Story 2.1 (safe-localStorage) and Story 2.2 (plural-aware copy helper) can run in parallel. Story 2.3 depends on both. Story 2.4 depends on 2.3.
3. **Epic 3** (Stories 3.1, 3.2, 3.3, 3.4) — demo indicator stack. Story 3.1 (badge) must come before Story 3.2 (mount in cluster list). Stories 3.3 + 3.4 (text suffix in pickers) depend only on Story 1.1 and can run in parallel with Story 3.1 + 3.2.
4. **Epic 4** (Stories 4.1, 4.2, 4.3) — E2E + CI guard + docs. Story 4.1 needs the banner deployed (Story 2.4). Story 4.2 needs the demo-data file (Story 1.1). Story 4.3 can come last.

### Parallelization opportunities

- After Story 1.1 lands: Stories 2.1, 2.2, 3.1, 3.3, 3.4 can all start in parallel.
- Stories 4.2 (CI guard) and 4.3 (docs) can be done in parallel with Epics 2–3.

## 8) Rollout and cutover plan

- **Rollout stages:** internal-only — single-tenant MVP1, no staged rollout. Feature is gated by data (demo slug presence) + localStorage. No feature flag.
- **Migration / cutover steps:** none — no schema changes.
- **Reconciliation:** N/A — no external systems involved.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — DEMO_CLUSTER_SLUGS constant + isDemoClusterName helper
- [ ] Story 2.1 — safe-localStorage wrapper
- [ ] Story 2.2 — formatDemoClusterPrefix helper
- [ ] Story 2.3 — DemoDataBanner component
- [ ] Story 2.4 — Mount banner on dashboard
- [ ] Story 3.1 — DemoBadge component
- [ ] Story 3.2 — Mount DemoBadge in clusters-table
- [ ] Story 3.3 — " (Demo)" suffix in create-study modal
- [ ] Story 3.4 — " (Demo)" suffix in proposals-table cluster fk-select
- [ ] Story 4.1 — Playwright E2E extensions
- [ ] Story 4.2 — CI parity guard + pr.yml wiring
- [ ] Story 4.3 — Documentation updates

### Blocked items
(none at plan time)

### Done this sprint
(empty — plan just approved)

## 10) Story-by-Story Verification Gate

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Endpoints — N/A in Phase 1 (no new endpoints)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated:
    - [ ] vitest for any new/modified component or helper
    - [ ] Playwright E2E for stories touching the dashboard (Story 4.1 covers all)
- [ ] Commands executed and passed:
    - [ ] `cd ui && pnpm lint`
    - [ ] `cd ui && pnpm typecheck`
    - [ ] `cd ui && pnpm test <filter>`
    - [ ] `cd ui && pnpm test:e2e -- dashboard.spec.ts` (if banner touched)
    - [ ] `bash scripts/ci/verify_demo_slug_parity.sh` (Story 4.2 onward)
- [ ] Migration round-trip — N/A
- [ ] Related docs/checklists updated in same PR when behavior/contract changed

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** spec §8.1 declares 0 new endpoints. Plan declares 0 new endpoints. ✓
2. **Spec ↔ plan error code coverage:** spec §8.5 declares 0 new error codes. Plan declares 0. ✓
3. **Spec ↔ plan FR coverage:** All 9 FRs (FR-1 through FR-9) are mapped in §1 traceability above. Every FR is assigned to at least one story. ✓
4. **Story internal consistency:**
   - No endpoint tables (Phase 1 frontend-only). No Pydantic schemas.
   - DoD assertions reference the spec's AC IDs explicitly.
   - New files: `ui/src/lib/demo-data.ts` (1.1), `ui/src/lib/safe-local-storage.ts` (2.1), `ui/src/lib/format-demo-cluster-prefix.ts` (2.2), `ui/src/components/dashboard/demo-data-banner.tsx` (2.3), `ui/src/components/common/demo-badge.tsx` (3.1), `scripts/ci/verify_demo_slug_parity.sh` (4.2). 6 unique new files, no ownership conflict. ✓
   - Modified files (across all stories): `ui/src/app/page.tsx` (2.4), `ui/src/components/clusters/clusters-table.column-config.tsx` (3.2), `ui/src/components/studies/create-study-modal.tsx` (3.3), `ui/src/components/proposals/proposals-table.column-config.tsx` (3.4), `ui/tests/e2e/dashboard.spec.ts` (4.1), `.github/workflows/pr.yml` (4.2), 3 doc files (4.3). All exist (verified). ✓
5. **Test file count:** 5 new vitest files + 2 vitest extensions + 1 Playwright extension + 1 CI guard. All assigned: demo-data.test.ts→1.1, safe-local-storage.test.ts→2.1, format-demo-cluster-prefix.test.ts→2.2, demo-data-banner.test.tsx→2.3, demo-badge.test.tsx→3.1, create-study-modal extension→3.3, proposals-table extension→3.4, dashboard.spec.ts extension→4.1, verify_demo_slug_parity.sh→4.2. ✓
6. **Gate arithmetic:** Epic 2 gate names 4 stories; Epic 3 names 4; Epic 4 names 3; Epic 1 names 1. Total 12 stories cited across gates vs 10 story DoDs above. Discrepancy — let me re-count the story headers… Story 1.1, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3 = 12 stories. The execution tracker in §9 also lists 12. ✓
7. **Open questions:** spec §19 lists none. ✓
8. **UI Guidance completeness:** all required subsections present (Insertion point ✓, Analogous markup ✓, Layout ✓, Confirmation/modal — N/A documented ✓, Visual consistency table ✓, Component composition ✓, Interaction behavior table ✓, Handler function patterns ✓, IA placement ✓, Tooltips ✓, Legacy behavior parity — N/A documented ✓). ✓
9. **Codebase verification ledger:**

| Claim | Verified by | Status |
|---|---|---|
| `ui/src/app/page.tsx` is 137 lines, has `<StartHereChecklist>` at lines 96-102 | Read file directly during planning | Verified |
| `ui/src/components/dashboard/start-here-checklist.tsx` line 51 is the early-return | Read file | Verified |
| `ui/src/components/studies/create-study-modal.tsx` `<EntitySelect>` at lines 506-528 with `getLabel` at line 511 | Read file | Verified |
| `ui/src/components/proposals/proposals-table.column-config.tsx` has `useClustersForFilter` adapter at lines 40-46 | Read file | Verified |
| `ui/src/components/clusters/clusters-table.column-config.tsx` `name` column cell at lines 25-34 | Read file | Verified |
| `MAX_PAGE_LIMIT = 200` in `backend/app/api/v1/clusters.py` line 83 | grep | Verified |
| `sort=name:asc` is in `CLUSTER_SORT_VALUES` allowlist | Read `ui/src/lib/enums.ts:144-152` | Verified |
| 4 demo slugs at `scripts/seed_meaningful_demos.py` lines 129, 245, 343, 456 | grep | Verified |
| `verify_enum_source_of_truth.sh` exists at `scripts/ci/verify_enum_source_of_truth.sh` | ls | Verified |
| shadcn `<Badge variant="secondary">` exists at `ui/src/components/ui/badge.tsx` | read | Verified |
| Radix Tooltip primitives at `ui/src/components/ui/tooltip.tsx` | read | Verified |
| `<TooltipProvider>` is mounted in app layout | TBD at Story 3.1 — risk noted in §6 | Pending |
| `localStorage` namespacing `relyloop.<feature>.<key>` is the convention | Read `guide-viewer.tsx:28-29` | Verified |
| `dashboard.spec.ts` has 2 existing tests | Read file | Verified |

10. **Enumerated value contract audit:** No new wire-value allowlists. Demo slugs are NOT wire values (the backend validates `cluster.name` against a regex pattern, not an allowlist). The CI guard in Story 4.2 covers source-to-frontend parity for the demo slugs separately, but they do not need an `enums.ts` entry. ✓

11. **Audit-event coverage:** N/A — no state mutations in Phase 1. ✓

12. **Persistence scope consistency:** localStorage used in Stories 2.1 + 2.3. DoD for both stories matches: "persists across browser sessions" / "sticky-dismissed." ✓

13. **Frontend data plumbing:** `<DemoDataBanner>` is self-contained (no props); no parent-data dependency. Stories 3.2, 3.3, 3.4 use `c.name` from already-fetched cluster summaries — verified to be available in those scopes. ✓

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New/Modified files, Key interfaces (where applicable), Tasks, and DoD.
- [x] Test layers explicit (vitest, Playwright E2E, CI guard).
- [x] Documentation updates across docs/01-05 planned (1 architecture doc + 1 runbook + state.md).
- [x] Lean refactor scope bounded (safe-localStorage helper).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review performed with no unresolved findings.
