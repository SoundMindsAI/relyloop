# Implementation Plan — Overnight final solution Phase 2 (morning summary card + strategy line)

**Date:** 2026-06-03
**Status:** Draft
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) (frontend conventions, Enumerated Value Contract Discipline, form-select-discipline rule, E2E rules), [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability: every story maps to one or more FRs from the spec (FR-1 through FR-9). The mount-predicate, hook-ordering, and child-component patterns from spec D-11 / D-18 / D-19 are hard contracts — stories must implement them exactly as documented to avoid Rules-of-Hooks violations that ESLint catches at lint-time.
- Phase 2 is **single-PR, frontend-only**. No backend code, no migration, no schema change.
- Two existing components are touched: `<LinkedEntitiesRow>` (Story 5) and `<AutoFollowupChainPanel>` (Story 1, mechanical refactor — `CHAIN_STOP_REASON_PHRASE` extracted, behavior identical). The new `<OvernightResultCard>` is additive.
- `<DigestPanel>` gains a one-line `id="digest"` addition (Story 4) so the card's "View full digest →" anchor works.
- Hook-order invariance (spec D-19) means both `useStudyChain` and `useStudyDigest` are called at the TOP of `<OvernightResultCard>` before any early return; the FR-7 mount predicate gates the rendered output, not the hook calls.

## 1) Scope traceability (FR → epics/stories)

Phase 2 has **one epic** ("Morning summary card + strategy line — single-PR delivery"). All FRs map within it.

| FR ID | Story | Notes |
|---|---|---|
| FR-1 | Story 3 (`<OvernightResultCard>` shell) + Story 4 (narrative section) | Hook-order block lands in Story 3; narrative excerpt lands in Story 4. The component's other sections (headline, path render, best-config matrix, stop reason) all land in Story 3. |
| FR-2 | Story 5 (`<StrategyLine>` inside `<LinkedEntitiesRow>`) | Standalone read-only line; no dependency on `<OvernightResultCard>`. |
| FR-3 | Story 2 (`pathTokenForLink` pure helper) + Story 3 (`<PathToken>` child component + parent stitcher) | Pure helper unit-tested independently; child component is the Rules-of-Hooks-safe wrapper per D-11. |
| FR-4 | Story 4 (`<WinningLinkConvergenceChip>` child component) | Parent-gates-mount pattern per D-18. |
| FR-5 | Story 4 (`truncateNarrative` helper + narrative section) + adds `id="digest"` to `<DigestPanel>` | Hook-call shape for `useStudyDigest` aligns with FR-1's invariant-hook-order block per D-22. |
| FR-6 | Story 1 (two glossary keys + lock-test extension — colocated with foundation work) | `overnight_result` + `auto_followup_strategy_line`. **Moved from Story 6 to Story 1** per cycle-1 finding C1-1 — `<InfoTooltip>`'s `glossaryKey` prop is type-locked to `ShortGlossaryKey` (`ui/src/components/common/info-tooltip.tsx:14-16` + `ui/src/lib/glossary.ts:987`); stories 3 + 5 that use the new keys would fail `pnpm typecheck` if the keys didn't exist yet. |
| FR-7 | Story 3 (`shouldShowOvernightResultCard` colocated with the card component) | Pure boolean → unit-testable without React. Helper lives in `overnight-result-card.tsx` (exported). **Note (cycle-1 finding C1-6):** the helper is OWNED by Story 3, not Story 2 — Story 2 ships ONLY the path-token helper. |
| FR-8 | Story 1 (extract `CHAIN_STOP_REASON_PHRASE` + `formatSignedLift` into shared modules) | Mechanical refactor — chain panel keeps passing existing tests unchanged. |
| FR-9 | Story 6 (tutorial guide update + screenshot regen + ui-architecture doc) | Step 12 of `tutorial-first-study.md`. Per spec FR-9, the populated-stack screenshot is a documentation deliverable — E2E downgrade per spec D-17 does NOT waive it. |

All 9 FRs covered by 6 stories within 1 epic. No FRs are deferred.

**Phase boundary check:** Phase 2 is single-phase. Per the spec §3 "Phase boundaries" sub-section, there is no Phase 3+ deferred from Phase 2 itself. Cap 2 (index-page surface) was delegated to sibling `feat_overnight_studies_summary_card` per D-4 — not a deferred phase of THIS plan. No `phase<N>_idea.md` tracking artifact required.

## 2) Delivery structure

### Conventions (project-specific)

- **All new components** are TypeScript + React 19 functional with explicit `React.ReactNode` return types.
- **All new tests** live alongside the source they cover: vitest tests under `ui/src/__tests__/` mirroring the source path; E2E specs under `ui/tests/e2e/`.
- **Source-of-truth comments** are mandatory on any frontend code that mirrors a backend allowlist (per CLAUDE.md "Enumerated Value Contract Discipline"). The new `<StrategyLine>` (Story 5) and the path-token mapper (Story 2) BOTH import their enum values from `ui/src/lib/enums.ts` rather than declaring inline literals.
- **Form-select-discipline:** Story 5's `<StrategyLine>` does NOT use `<Select>` — it's a read-only display, not an editable form control — so the lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` does not apply. The value lookup still goes through `OVERNIGHT_STRATEGY_VALUES` to satisfy the source-of-truth discipline.
- **Child-component pattern for variable-arity hooks** (per spec D-11 / D-18): NEVER call `useX(...)` inside a `.map(...)` loop or in a conditional branch within the same component. Always extract a child component with the hook at its top level.
- **Hook-order invariance** (per spec D-19): the top-level component (`<OvernightResultCard>`) calls all hooks (`useStudyChain`, `useStudyDigest`) at the top in stable order, computes the predicate, then conditionally returns `null` — never the reverse.

### AI Agent Execution Protocol

0. **Load context:** Read [`architecture.md`](../../../../architecture.md) and [`state.md`](../../../../state.md). Phase 2 ships into MVP2 (in-flight); no backend changes touch the Alembic head (stays at `0022_solr_engine_auth_check`).
1. **Read scope:** Story outcome + new/modified files + key interfaces + DoD.
2. **Backend:** N/A — Phase 2 has no backend code.
3. **Run backend tests:** N/A — no backend changes. (CI still runs them; they must remain green.)
4. **Frontend:** Implement per story. Mechanical Story 1 first (refactor with no behavior change), then Story 2 (pure helpers, no UI), then Story 3 (the card shell), then Story 4 (narrative + chip), then Story 5 (strategy line), then Story 6 (glossary + guide).
5. **Run frontend tests:**
   - `cd ui && pnpm lint` — must be clean.
   - `cd ui && pnpm typecheck` — must be clean.
   - `cd ui && pnpm test` — vitest unit + component tests pass.
   - `cd ui && pnpm test:e2e` — gated; run after Story 6.
   - `cd ui && pnpm build` — Next.js production build green (catches SSR issues if `<OvernightResultCard>` accidentally uses non-client APIs — though it's already a `'use client'` file like the chain panel).
6. **Doc updates** in same PR: ui-architecture.md (Story 6's task list), tutorial-first-study.md Step 12 (Story 6).
7. **No migration verification** — no schema change.
8. **PR evidence:** command outputs from step 5 attached; affected test counts; final GPT-5.5 review attached per `/impl-execute` Step 7.
9. **After Story 6** (final story): update `state.md` (move from "queued" to "merged" once PR ships) and `architecture.md` (Story 6's task — note the new shared module + the morning card surface).

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Morning summary card + strategy line

### Story 1 — Foundation: extract shared helpers + add glossary keys

**Outcome:** Two helpers used by both the existing chain panel and the new card live in shared modules (FR-8); two new glossary keys (`overnight_result`, `auto_followup_strategy_line`) land BEFORE any consuming component is written (FR-6) so subsequent stories can reference them through the type-locked `<InfoTooltip glossaryKey={...}>` prop without breaking `pnpm typecheck`. The chain panel's behavior is byte-identically preserved.

**Why this story is the foundation:** `<InfoTooltip>`'s `glossaryKey` is typed against `ShortGlossaryKey` ([`ui/src/components/common/info-tooltip.tsx:14-16`](../../../../ui/src/components/common/info-tooltip.tsx#L14-L16)), itself derived from `keyof typeof glossary` at [`ui/src/lib/glossary.ts:987`](../../../../ui/src/lib/glossary.ts#L987). Stories 3 + 5 use `glossaryKey="overnight_result"` and `glossaryKey="auto_followup_strategy_line"` — those values MUST be valid keys of `glossary` at the time of typecheck. Moving glossary additions into Story 1 makes Stories 3 + 5 typecheck-clean by construction.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/chain-stop-reason.ts` | Exports `CHAIN_STOP_REASON_PHRASE: Record<ChainStopReason, string>` (the six-entry map currently inline in the chain panel). Carries source-of-truth comment `// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS`. |
| `ui/src/lib/format-lift.ts` | Exports `formatSignedLift(value: number \| null \| undefined): string` (the helper currently inline in the chain panel at [auto-followup-chain-panel.tsx:49-52](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L49-L52)). Returns `+0.NNNN` / `-0.NNNN` / `—` (4-decimal signed, no percent). |
| `ui/src/__tests__/lib/chain-stop-reason.test.ts` | Vitest unit test — asserts the six expected keys (`in_flight`, `no_lift`, `depth_exhausted`, `budget`, `parent_failed`, `cancelled`), non-empty phrase values, and the source-of-truth comment is present. |
| `ui/src/__tests__/lib/format-lift.test.ts` | Vitest unit test — `formatSignedLift(null) === '—'`, `formatSignedLift(undefined) === '—'`, `formatSignedLift(0.1245) === '+0.1245'`, `formatSignedLift(-0.05) === '-0.0500'`, `formatSignedLift(0) === '+0.0000'`. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/auto-followup-chain-panel.tsx` | Remove the inline `CHAIN_STOP_REASON_PHRASE` (currently at [lines 33-41](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L33-L41)) and `formatSignedLift` (currently at [lines 49-52](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L49-L52)). Add imports from the two new modules. No other change. |
| `ui/src/lib/glossary.ts` | Add two new entries (FR-6): `overnight_result` (`short` + `long`) and `auto_followup_strategy_line` (`short` + `long`). Locate the existing `overnight_strategy` entry (Phase 1) and place the new entries adjacent in the same logical block (likely the `feat_overnight_autopilot Story 3.1` block). |
| `ui/src/__tests__/lib/glossary.test.ts` (or `glossary-discipline.test.ts` if separate — verify at impl-time) | Extend the value-lock test with assertions for `overnight_result` and `auto_followup_strategy_line` (non-empty `short` AND `long`), mirroring the Phase 1 `overnight_strategy` lock pattern. Per the file's policy at [`glossary.ts:6-15`](../../../../ui/src/lib/glossary.ts#L6-L15): `short` ≤ 140 chars, `long` ≤ 800 chars. |

**Endpoints:** None — pure refactor.

**Key interfaces**

```typescript
// ui/src/lib/chain-stop-reason.ts
import type { StudyChainResponse } from '@/lib/api/studies';

type ChainStopReason = NonNullable<StudyChainResponse['stop_reason']>;

// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS
export const CHAIN_STOP_REASON_PHRASE: Record<ChainStopReason, string> = {
  depth_exhausted: 'depth budget exhausted',
  no_lift: 'no further improvement',
  budget: 'daily LLM budget reached',
  parent_failed: 'parent study failed or was cancelled',
  cancelled: 'operator cancelled the chain',
  in_flight: 'chain still running',
};
```

```typescript
// ui/src/lib/format-lift.ts
/**
 * Format a signed lift/delta value with a leading `+`/`-` and 4 decimals.
 * Returns '—' for null/undefined (matches the chain panel + overnight result
 * card empty-cell convention). Used by both `<AutoFollowupChainPanel>` and
 * `<OvernightResultCard>` so the same lift number never appears in two
 * different formats on the same page (spec D-12).
 */
export function formatSignedLift(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}
```

**Pydantic schemas:** None.

**Tasks**

1. Create `ui/src/lib/chain-stop-reason.ts` with the export above (copy verbatim from the chain panel's existing inline definition). Add the source-of-truth comment.
2. Create `ui/src/lib/format-lift.ts` with the export above (copy verbatim from the chain panel's existing inline definition).
3. Edit `auto-followup-chain-panel.tsx`: remove the inline declarations at lines 33-41 and 49-52; add the two imports near the top of the file (next to existing `@/lib/...` imports).
4. Create `ui/src/__tests__/lib/chain-stop-reason.test.ts` with the assertions in the New Files table.
5. Create `ui/src/__tests__/lib/format-lift.test.ts` with the assertions in the New Files table.
6. Edit `ui/src/lib/glossary.ts`: add the two new entries (`overnight_result` and `auto_followup_strategy_line`) per the FR-6 content block. Both entries follow the `short` (≤ 140 chars) + `long` (≤ 800 chars) + optional `ariaLabel` shape. Place them adjacent to the existing `overnight_strategy` entry in the same logical block.
7. Extend the existing glossary value-lock test with assertions for the two new keys (non-empty `short` AND `long` per the lock pattern).
8. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test` and confirm:
   - All existing chain-panel tests pass unchanged (this proves the refactor is mechanical-only).
   - The four new test contexts pass (chain-stop-reason + format-lift + two glossary entries via the lock test extension).

**Definition of Done (DoD)**

- New helper files exist at the paths above with the expected exports.
- `auto-followup-chain-panel.tsx` no longer carries the inline declarations; imports the shared modules.
- `ui/src/lib/glossary.ts` carries the two new entries (`overnight_result`, `auto_followup_strategy_line`) with `short` + `long`.
- Vitest: `ui/src/__tests__/lib/chain-stop-reason.test.ts` + `ui/src/__tests__/lib/format-lift.test.ts` pass.
- Vitest: glossary lock test passes with the two new key assertions added.
- Vitest: `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` passes UNCHANGED (no test edits — the refactor is internal).
- `cd ui && pnpm lint && pnpm typecheck` clean.
- `cd ui && pnpm build` succeeds (no SSR breakage from the import restructuring).
- **Foundation gate:** Stories 3 and 5 can now reference `glossaryKey="overnight_result"` / `glossaryKey="auto_followup_strategy_line"` and typecheck cleanly.

---

### Story 2 — Pure-domain helper (`pathTokenForLink`)

**Outcome:** One pure function used by the card is added in unit-testable form, independent of React. Story owns ONLY `pathTokenForLink`; `shouldShowOvernightResultCard` (FR-7) is owned by Story 3 (colocated with the card), and `truncateNarrative` (FR-5) is owned by Story 4 (colocated with the narrative section). Cycle-1 finding C1-6 clarified ownership.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/chain-path-tokens.ts` | Exports `pathTokenForLink(link: StudyChainLink, templateName: string \| null): string \| null` per FR-3. Pure data → data; no hooks; no React. **Implementation pattern (cycle-1 finding C1-7 accept):** uses `Record<SelectedFollowupKind, ...>` exhaustiveness so the build breaks if a new value lands in `SELECTED_FOLLOWUP_KIND_VALUES` without a corresponding token mapping. Mirrors Phase 1's `CHAIN_STOP_REASON_PHRASE: Record<ChainStopReason, string>` pattern. |
| `ui/src/__tests__/lib/chain-path-tokens.test.ts` | Vitest unit test — asserts the five mapping cases (null → null, narrow_default → "refined", narrow → "narrow", widen → "widen", swap_template with templateName → "swap to {truncated}", swap_template with null templateName → "swap to {first 6 of template_id}"). Asserts 24-char truncation + ellipsis. |

**Modified files:** None.

**Endpoints:** None.

**Key interfaces**

```typescript
// ui/src/lib/chain-path-tokens.ts
import type { StudyChainResponse } from '@/lib/api/studies';
import { type SelectedFollowupKind } from '@/lib/enums';

type StudyChainLink = StudyChainResponse['links'][number];

const SWAP_TEMPLATE_NAME_MAX_LEN = 24;

/**
 * Per-kind token rendering. Source-of-truth: the SELECTED_FOLLOWUP_KIND_VALUES
 * tuple exported by ui/src/lib/enums.ts (which mirrors
 * backend/app/domain/study/auto_followup_strategy.py SELECTED_FOLLOWUP_KIND_VALUES).
 *
 * The Record<SelectedFollowupKind, ...> type forces exhaustiveness — adding a
 * new value to SELECTED_FOLLOWUP_KIND_VALUES breaks the build until the map is
 * extended (mirrors the Phase 1 CHAIN_STOP_REASON_PHRASE pattern).
 */
const TOKEN_RENDERERS: Record<
  SelectedFollowupKind,
  (link: StudyChainLink, templateName: string | null) => string
> = {
  narrow_default: () => 'refined',
  narrow: () => 'narrow',
  widen: () => 'widen',
  swap_template: (link, templateName) => {
    if (templateName !== null) {
      const truncated =
        templateName.length > SWAP_TEMPLATE_NAME_MAX_LEN
          ? `${templateName.slice(0, SWAP_TEMPLATE_NAME_MAX_LEN)}…`
          : templateName;
      return `swap to ${truncated}`;
    }
    return `swap to ${link.template_id.slice(0, 6)}`;
  },
};

/**
 * Map a chain link's `selected_followup_kind` to a short token for the
 * "Explored: …" line on the Overnight result card (spec FR-3).
 *
 * Returns null for:
 *   - the anchor link (selected_followup_kind === null by Phase 1 D-12),
 *   - any link in a legacy "narrow" chain (every link's value is null).
 *
 * Callers MUST filter null-token links BEFORE rendering child components
 * (per cycle-1 finding C1-3 — rendering null-token children would emit
 * dangling " → " separators).
 */
export function pathTokenForLink(
  link: StudyChainLink,
  templateName: string | null,
): string | null {
  const kind = link.selected_followup_kind;
  if (kind === null || kind === undefined) return null;
  return TOKEN_RENDERERS[kind](link, templateName);
}
```

**Pydantic schemas:** None.

**Tasks**

1. Create `ui/src/lib/chain-path-tokens.ts` with the export above.
2. Create `ui/src/__tests__/lib/chain-path-tokens.test.ts` covering:
   - `pathTokenForLink({ selected_followup_kind: null, template_id: '...' }, null) === null`
   - `pathTokenForLink({ selected_followup_kind: 'narrow_default', ... }, null) === 'refined'`
   - `pathTokenForLink({ selected_followup_kind: 'narrow', ... }, null) === 'narrow'`
   - `pathTokenForLink({ selected_followup_kind: 'widen', ... }, null) === 'widen'`
   - `pathTokenForLink({ selected_followup_kind: 'swap_template', template_id: '...' }, 'function-score-v1') === 'swap to function-score-v1'`
   - `pathTokenForLink({ selected_followup_kind: 'swap_template', template_id: '...' }, 'this-is-a-very-long-template-name-exceeding-the-limit') === 'swap to this-is-a-very-long-temp…'` (24-char truncation + ellipsis).
   - `pathTokenForLink({ selected_followup_kind: 'swap_template', template_id: 'abc123def456...' }, null) === 'swap to abc123'` (first 6 chars fallback).
3. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done (DoD)**

- `ui/src/lib/chain-path-tokens.ts` exists with `pathTokenForLink` exported.
- Vitest: `ui/src/__tests__/lib/chain-path-tokens.test.ts` covers all six cases above.
- `cd ui && pnpm lint && pnpm typecheck` clean.

---

### Story 3 — `<OvernightResultCard>` shell + headline + path + stop reason + best config + narrative excerpt

**Outcome:** The morning summary card mounts above `<LinkedEntitiesRow>` on `/studies/{id}` when the chain has terminated and has ≥ 2 links. Renders headline + path summary + best-config CTA + stop-reason line (with conditional `<InfoTooltip>` for `depth_exhausted`/`budget` per spec §11) + narrative excerpt with "View full digest →" link. Convergence chip + the `id="digest"` anchor on `<DigestPanel>` land in Story 4. Story 3 must consume the `digestQ` hook it declares for invariant-hook-order compliance per spec D-19; consuming it means rendering the narrative section here (per cycle-2 finding C2-4).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/overnight-result-card.tsx` | The morning card component. Contains: (a) the top-level `<OvernightResultCard>` component with FR-1's invariant hook ordering, (b) the colocated pure predicate `shouldShowOvernightResultCard`, (c) the colocated pure helper `truncateNarrative` (FR-5), (d) the child component `<PathTokenChip>` per FR-3, (e) a placeholder mount-point for `<WinningLinkConvergenceChip>` per FR-4 (Story 4 implements the chip). |
| `ui/src/__tests__/components/studies/overnight-result-card.test.tsx` | Vitest component tests using `@testing-library/react` + a TanStack-Query test provider. Covers AC-1 partial (sans chip), AC-2, AC-3, AC-4, AC-5, AC-11, three best-config cases, mixed-token-chain, `shouldShowOvernightResultCard` direct unit tests, `truncateNarrative` direct unit tests. Story 4 extends with AC-1 full (with chip), AC-6, AC-10. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/studies/[id]/page.tsx` | Add `import { OvernightResultCard } from '@/components/studies/overnight-result-card';` (next to existing imports at lines 14-18). Insert `<OvernightResultCard study={study} />` between `<StudyHeaderWithSyntheticChip>` ([line 95](../../../../ui/src/app/studies/[id]/page.tsx#L95)) and `<LinkedEntitiesRow>` ([line 96](../../../../ui/src/app/studies/[id]/page.tsx#L96)). |

**Endpoints:** None — pure frontend.

**Key interfaces**

```typescript
// ui/src/components/studies/overnight-result-card.tsx
'use client';

import { useStudyChain, type StudyChainResponse, type StudyDetail } from '@/lib/api/studies';
import { useStudyDigest } from '@/lib/api/digests';
import { useTemplate } from '@/lib/api/query-templates';
import { CHAIN_STOP_REASON_PHRASE } from '@/lib/chain-stop-reason';
import { formatSignedLift } from '@/lib/format-lift';
import { pathTokenForLink } from '@/lib/chain-path-tokens';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import type React from 'react';

interface OvernightResultCardProps {
  study: StudyDetail;
}

// FR-7 — pure predicate, exported for unit testing.
export function shouldShowOvernightResultCard(
  chain: StudyChainResponse | undefined,
): boolean {
  if (!chain) return false;
  if (chain.stop_reason === 'in_flight') return false;
  return chain.links.length >= 2;
}

export function OvernightResultCard({ study }: OvernightResultCardProps): React.ReactNode {
  // Hook order is invariant across every render per spec D-19:
  //   1. useStudyChain (always — drives the predicate)
  //   2. useStudyDigest (always — enabled flag gates the network call)
  //   3. derive predicate
  //   4. early return AFTER both hooks have been called.
  const chainQ = useStudyChain(study.id);
  const chain = chainQ.data;
  // FR-5 / D-22 hook-call shape: passes `undefined` when no winner so the
  // hook's `enabled` gate skips the fetch; the call itself still happens.
  const digestQ = useStudyDigest(
    chain?.best_link_id ?? undefined,
    {
      enabled:
        chain?.best_link_id !== null && shouldShowOvernightResultCard(chain),
    },
  );
  const show = shouldShowOvernightResultCard(chain);

  if (!show || !chain) return null;

  const bestLink =
    chain.best_link_id !== null
      ? (chain.links.find((l) => l.id === chain.best_link_id) ?? null)
      : null;

  // FR-3: filter out null-token links BEFORE mounting child components per
  // cycle-1 finding C1-3. The filter is purely a function of the link's
  // `selected_followup_kind` (a wire-data field — no hook needed to read it),
  // so it's safe to apply before mounting children. The resulting
  // `tokenLinks` array length determines isLast correctly.
  const tokenLinks = chain.links
    .slice(1) // drop anchor (always null kind)
    .filter((l) => l.selected_followup_kind !== null);

  return (
    <Card data-testid="overnight-result-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {/* Story 3: headline; Story 4 injects the <WinningLinkConvergenceChip> here, gated on chain.best_link_id !== null. */}
          {`Overnight exploration complete — ${chain.links.length} ${chain.links.length === 1 ? 'study' : 'studies'}${
            chain.cumulative_lift !== null ? `, ${formatSignedLift(chain.cumulative_lift)} lift` : ''
          }`}
          <InfoTooltip glossaryKey="overnight_result" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {tokenLinks.length > 0 && (
          <p data-testid="overnight-result-path">
            Explored:{' '}
            {tokenLinks.map((link, i) => (
              <PathTokenChip
                key={link.id}
                link={link}
                isLast={i === tokenLinks.length - 1}
              />
            ))}
          </p>
        )}
        <p data-testid="overnight-result-best-config">
          {/* FR-1 three-case render matrix per D-13. */}
          {chain.best_link_id === null || bestLink === null ? (
            <>Best config: —</>
          ) : chain.proposal_id_for_best_link === null ? (
            <>Best config: {bestLink.name} (Awaiting proposal)</>
          ) : (
            <>
              Best config:{' '}
              <Link
                href={`/proposals/${chain.proposal_id_for_best_link}`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                {bestLink.name}
              </Link>
            </>
          )}
        </p>
        <p data-testid="overnight-result-stop-reason">
          Stop reason: {CHAIN_STOP_REASON_PHRASE[chain.stop_reason]}
          {/* Reuse the chain-panel's conditional tooltip pattern per spec §11. */}
          {chain.stop_reason === 'depth_exhausted' && (
            <span className="ml-2 inline-flex">
              <InfoTooltip glossaryKey="auto_followup_depth" />
            </span>
          )}
          {chain.stop_reason === 'budget' && (
            <span className="ml-2 inline-flex">
              <InfoTooltip glossaryKey="auto_followup_budget_skip" />
            </span>
          )}
        </p>
        {digestQ.data && !digestQ.isError && chain.best_link_id !== null && (
          <div data-testid="overnight-result-narrative" className="border-t pt-2">
            <p className="text-xs font-medium text-muted-foreground">Summary</p>
            <p className="mt-1">{truncateNarrative(digestQ.data.narrative)}</p>
            <p className="mt-1">
              <Link
                href={`/studies/${chain.best_link_id}#digest`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                View full digest →
              </Link>
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// FR-5 — pure helper, exported for unit testing. Per spec D-15 the hard
// fallback walks back to the nearest whitespace before the limit; only the
// pathological single-token-no-whitespace case cuts mid-word.
export function truncateNarrative(text: string, maxChars: number = 240): string {
  if (text.length <= maxChars) return text;
  const slice = text.slice(0, maxChars + 1);
  const lastTerminator = Math.max(
    slice.lastIndexOf('.'),
    slice.lastIndexOf('!'),
    slice.lastIndexOf('?'),
  );
  if (lastTerminator > 0 && lastTerminator <= maxChars) {
    return text.slice(0, lastTerminator + 1);
  }
  const lastSpace = text.lastIndexOf(' ', maxChars);
  if (lastSpace > 0) {
    return `${text.slice(0, lastSpace)}…`;
  }
  return `${text.slice(0, maxChars)}…`;
}

// FR-3 — child component per Rules-of-Hooks discipline (D-11).
// The hook is at the TOP of this child; never inside a parent loop.
// Parent guarantees `link.selected_followup_kind !== null` via the
// `tokenLinks.filter(...)` above, so the token will never be null here.
function PathTokenChip({
  link,
  isLast,
}: {
  link: StudyChainResponse['links'][number];
  isLast: boolean;
}): React.ReactNode {
  // Hook always runs; the parameter is non-null only for swap_template links,
  // so the hook's `enabled` gate skips the request for the other kinds.
  const templateQ = useTemplate(
    link.selected_followup_kind === 'swap_template' ? link.template_id : null,
  );
  const token = pathTokenForLink(link, templateQ.data?.name ?? null);
  // Defensive: token is non-null by the parent's filter, but guard anyway.
  if (token === null) return null;
  return (
    <span data-testid={`overnight-result-path-token-${link.id}`}>
      {token}
      {!isLast ? ' → ' : ''}
    </span>
  );
}
```

**Pydantic schemas:** None.

**Tasks**

1. Create `ui/src/components/studies/overnight-result-card.tsx` with the structure above — implementing the FULL card surface EXCEPT the convergence chip. Concretely: headline, conditional-tooltip stop reason, path render (via `<PathTokenChip>` children with the null-filter), best-config three-case matrix, NARRATIVE SECTION (renders `truncateNarrative(digestQ.data.narrative)` + "View full digest →" link when `digestQ.data && !digestQ.isError`), `shouldShowOvernightResultCard` predicate helper (exported for direct testing), AND `truncateNarrative` helper (exported for direct testing — implements the FR-5 / D-15 sentence-boundary → whitespace → hard-fallback algorithm). The only commented placeholder is the chip mount-point inside `<CardTitle>`; Story 4 fills that.
2. Insert `<OvernightResultCard study={study} />` between `<StudyHeaderWithSyntheticChip>` and `<LinkedEntitiesRow>` in `ui/src/app/studies/[id]/page.tsx`. Add the import.
3. Create `ui/src/__tests__/components/studies/overnight-result-card.test.tsx`. Test fixtures:
   - **Helper:** wrap `<OvernightResultCard>` in a `<QueryClientProvider>` with a fresh `QueryClient` per test; pre-populate the cache with `queryClient.setQueryData(['studies', studyId, 'chain'], <fixture>)` to skip network.
   - **Direct unit tests for `shouldShowOvernightResultCard` (FR-7 + cycle-2 finding C2-6 accept):** import the helper directly and call it with `undefined`, `{ stop_reason: 'in_flight', links: [...] }`, `{ stop_reason: 'no_lift', links: [anchor_only] }`, `{ stop_reason: 'no_lift', links: [anchor, child] }`. Assert false / false / false / true respectively. Tests run with no React rendering — pure function.
   - **Direct unit tests for `truncateNarrative` (FR-5):** import the helper directly and assert: text ≤ 240 chars → unchanged; sentence boundary at 230 → cut at terminator; no terminator but whitespace at 200 → cut at whitespace + `…`; no whitespace, 250-char single token → hard cut at 240 + `…`.
   - **AC-1 partial (path + best config + stop reason + narrative):** terminated 3-link chain (anchor + 2 descendants, all with non-null `selected_followup_kind`); seed `useStudyDigest` cache with a fake digest narrative; assert `data-testid="overnight-result-card"` present, headline matches `Overnight exploration complete — 3 studies, +0.1245 lift`, **path renders with two tokens** (anchor is dropped per FR-3; only B and C contribute tokens), best-config link points at `/proposals/{id}`, stop-reason text matches `no further improvement`, narrative section renders with "View full digest →" link to `/studies/{best_link_id}#digest`. (AC-1's chip portion lands in Story 4.)
   - **AC-2:** `stop_reason: 'in_flight'` → `data-testid="overnight-result-card"` not present (returns null).
   - **AC-3:** `links.length === 1` → not present.
   - **AC-4:** 3-link chain where every link's `selected_followup_kind === null` → card present, headline present (with `+0.0500 lift`), best-config + stop-reason present, BUT `data-testid="overnight-result-path"` is NOT in the document.
   - **AC-5 (narrative hide-on-error)** — moved into Story 3 with the narrative section: seed `useStudyDigest` to return `isError: true` (mock the underlying `apiClient.get` to return 404 `DIGEST_NOT_READY`). Assert `data-testid="overnight-result-narrative"` is NOT in document; the rest of the card still renders.
   - **AC-11 (cache dedup):** render TWO `useStudyDigest(C.id)` consumers within the same `<QueryClientProvider>` (the page-level hook stub + the card's own hook); use a spied `apiClient.get` and assert exactly ONE call for `GET /api/v1/studies/{C.id}/digest`. Pre-populating the cache is the alternative — in that case assert ZERO additional `apiClient.get` calls (cycle-2 finding C2-5 accept — the test pattern must match the dedup semantics, not just the result count).
   - **Best-config three cases:** test the matrix from FR-1 → `Best config: —`, `(Awaiting proposal)`, link-rendered.
   - **Mixed-token-chain (path filter):** 4-link chain where link 1 has kind `narrow`, link 2 has kind `null`, link 3 has kind `widen` → path renders exactly `narrow → widen` (the null-kind link is filtered out; no dangling separator). Asserts cycle-1 C1-3 fix.
   - **Stop-reason tooltip (cycle-2 finding C2-3 accept):** seed `stop_reason: 'depth_exhausted'` → assert an `<InfoTooltip glossaryKey="auto_followup_depth" />` is rendered next to the stop-reason phrase. (Seed `stop_reason: 'budget'` → similar assertion for `auto_followup_budget_skip`.)
4. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test` and `pnpm build`. All green.

**UI Element Inventory (Story 3 — new UI)**

| Element type | Label / data-testid | Data source | User interactions |
|---|---|---|---|
| Card | `data-testid="overnight-result-card"` | `useStudyChain(study.id)` | None (read-only surface) |
| Card title | `Overnight exploration complete — N studies, ±X.XXXX lift` | `chain.links.length`, `chain.cumulative_lift` via `formatSignedLift` | None |
| InfoTooltip | `<InfoTooltip glossaryKey="overnight_result" />` (Story 6 adds the key) | Glossary lookup | hover/focus |
| Path line | `data-testid="overnight-result-path"` (hidden when all tokens null) | `chain.links.slice(1)` → child `<PathTokenChip>` per link | Hover the per-link tooltips if any (no clicks) |
| Path token chip | `data-testid="overnight-result-path-token-{link.id}"` | `useTemplate(link.template_id)` (only when `swap_template`) + `pathTokenForLink` | None |
| Best-config line | `data-testid="overnight-result-best-config"` | `chain.best_link_id` + `chain.proposal_id_for_best_link` + `bestLink.name` | Click link → navigate to `/proposals/{id}` (when both ids set) |
| Stop-reason line | `data-testid="overnight-result-stop-reason"` | `chain.stop_reason` → `CHAIN_STOP_REASON_PHRASE` | hover the conditional `<InfoTooltip>` for `depth_exhausted`/`budget` (matches chain-panel pattern at [`auto-followup-chain-panel.tsx:297-307`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L297-L307)) |
| Narrative section | `data-testid="overnight-result-narrative"` | `useStudyDigest(best_link_id)` → `digest.narrative` → `truncateNarrative` | hover/click the "View full digest →" link |

**Definition of Done (DoD)**

- `<OvernightResultCard>` component file exists with the structure above — including `truncateNarrative`, the narrative section, and the stop-reason tooltip.
- Page-level integration: `<OvernightResultCard study={study} />` mounted at the documented position in `page.tsx`.
- Vitest `overnight-result-card.test.tsx` covers: AC-1 partial (sans chip), AC-2, AC-3, AC-4, AC-5 (narrative hide-on-error), AC-11, three best-config cases, mixed-token-chain, stop-reason tooltip for `depth_exhausted` + `budget`, and DIRECT unit tests for `shouldShowOvernightResultCard` + `truncateNarrative` (no React render). AC-10 is OWNED by Story 4 (where `<WinningLinkConvergenceChip>` and the cross-study `useStudy` lands).
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all green. `digestQ` is consumed by the narrative section so no unused-variable lint failure.
- Hook-order invariance manually verified: ESLint's `react-hooks/rules-of-hooks` is clean on the new file. The component calls `useStudyChain` first, `useStudyDigest` second, then derives the predicate, then early-returns.

---

### Story 4 — Convergence chip + `<DigestPanel>` anchor

**Outcome:** The card's convergence chip renders correctly with graceful-degrade on null verdict. `<DigestPanel>` gains an `id="digest"` anchor so the "View full digest →" link (Story 3's narrative section) lands on the right page anchor. (Story 3 already owns the narrative section + `truncateNarrative` after cycle-2 restructure C2-4.)

**New files:** None (extends Story 3's component file).

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/overnight-result-card.tsx` | (a) Add the `<WinningLinkConvergenceChip>` child component definition (parent-gates-mount per D-18). (b) Mount it inside `<CardTitle>` immediately after the headline text + before the `<InfoTooltip>` per the parent-gates-mount rule (D-18). |
| `ui/src/components/studies/digest-panel.tsx` | Add `id="digest"` to the outer wrapper element (FR-5 / D-22 — cross-story dependency: Story 3's narrative section in the card links to `/studies/{best_link_id}#digest`, which requires this anchor). Today the panel renders `<div className="prose prose-sm mt-1 max-w-none" data-testid="digest-narrative">` at [line 50](../../../../ui/src/components/studies/digest-panel.tsx#L50) — locate the appropriate outer wrapper (likely a `<Card>` ancestor) and add `id="digest"`. If no semantic wrapper exists, add `id="digest"` to the existing `<Card>` element. No behavior change. |
| `ui/src/__tests__/components/studies/overnight-result-card.test.tsx` | Extend with: AC-1 full (with chip — seed `useStudy(best_link_id)` cache with `convergence: { verdict: 'converged' }`, assert chip renders "Converged" via `<Badge variant="secondary">`); AC-6 (null convergence → chip hidden); AC-10 (no double-fetch on winner's own page — when `study.id === chain.best_link_id`, assert the cross-study `useStudy(best_link_id)` is NOT called via spying on `apiClient.get`). |

**Endpoints:** None.

**Key interfaces** (additions to Story 3's file)

```typescript
// ui/src/components/studies/overnight-result-card.tsx (additions)

// FR-4 — child component per parent-gates-mount pattern (D-18).
// Imports added in Story 4: `useStudy` from '@/lib/api/studies';
// `Badge` from '@/components/ui/badge'.
import { useStudy } from '@/lib/api/studies';
import { Badge } from '@/components/ui/badge';

const VERDICT_LABEL: Record<NonNullable<StudyDetail['convergence']>['verdict'], string> = {
  converged: 'Converged',
  still_improving: 'Still improving',
  too_few_trials: 'Too few trials',
};

function WinningLinkConvergenceChip({
  linkId,
  viewedStudy,
}: {
  linkId: string;  // non-null per parent gate
  viewedStudy: StudyDetail;
}): React.ReactNode {
  // Hook ALWAYS runs; enabled only for cross-study lookups.
  const studyQ = useStudy(linkId, { enabled: linkId !== viewedStudy.id });
  const verdict =
    linkId === viewedStudy.id
      ? (viewedStudy.convergence?.verdict ?? null)
      : (studyQ.data?.convergence?.verdict ?? null);
  if (verdict === null) return null;
  // FR-4: use the existing <Badge> primitive with variant="secondary"
  // (cycle-1 finding C1-4 accept — matches convergence-panel.tsx precedent).
  return (
    <Badge variant="secondary" data-testid="overnight-result-convergence-chip" className="ml-2">
      {VERDICT_LABEL[verdict]}
    </Badge>
  );
}
```

In the main `<OvernightResultCard>` body, after Story 3's headline text and before the `<InfoTooltip>`:

```tsx
{chain.best_link_id !== null && (
  <WinningLinkConvergenceChip linkId={chain.best_link_id} viewedStudy={study} />
)}
```

**Pydantic schemas:** None.

**Tasks**

1. Add the `<WinningLinkConvergenceChip>` child component definition to `overnight-result-card.tsx` per the snippet above.
2. Mount the chip in the `<CardTitle>` (between headline text and `<InfoTooltip>`) gated on `chain.best_link_id !== null`.
3. Edit `digest-panel.tsx`: find the outer-most wrapper element (the `<Card>` returned by the component) and add `id="digest"`. Verify no behavior change.
4. Extend `overnight-result-card.test.tsx` with:
   - **AC-1 full chip portion:** seed `useStudy(best_link_id)` cache with `convergence: { verdict: 'converged' }`. Assert chip renders "Converged" via the `<Badge variant="secondary">` primitive. (Narrative + path + best-config portions are covered by Story 3 tests.)
   - **AC-6** (null convergence): seed `useStudy(best_link_id)` cache with `convergence: null`. Assert `data-testid="overnight-result-convergence-chip"` is NOT in document.
   - **AC-10** (no double-fetch on winner's own page) — MOVED from Story 3 per cycle-1 finding C1-5 accept: when `study.id === chain.best_link_id`, assert that the cross-study `useStudy(best_link_id)` is NOT called (proxy via spying on `apiClient.get` mock — the chain-anchor view shouldn't issue a second `GET /api/v1/studies/{best_link_id}`; the verdict is read from `viewedStudy.convergence` directly per the `<WinningLinkConvergenceChip>` branch).
5. Verify `<DigestPanel>` tests still pass after `id="digest"` addition.
6. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`. All green.

**UI Element Inventory (Story 4 — additions)**

| Element type | Label / data-testid | Data source | User interactions |
|---|---|---|---|
| Convergence chip | `data-testid="overnight-result-convergence-chip"` | `<WinningLinkConvergenceChip>` reading `study.convergence.verdict` (via `<Badge variant="secondary">`) | None |

(Narrative section + "View full digest →" link are in Story 3's inventory — moved per cycle-2 C2-4.)

**Definition of Done (DoD)**

- `<WinningLinkConvergenceChip>` child component lives in the card file; mounted conditionally on `chain.best_link_id !== null`; reads verdict from `viewedStudy.convergence` or `studyQ.data?.convergence`; renders as `<Badge variant="secondary">` per cycle-1 C1-4.
- `<DigestPanel>` outer wrapper carries `id="digest"` so Story 3's "View full digest →" link anchors correctly.
- Vitest `overnight-result-card.test.tsx` extensions pass: AC-1 full chip portion, AC-6, AC-10.
- Existing `<DigestPanel>` tests still pass.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all green.

---

### Story 5 — `<StrategyLine>` inside `<LinkedEntitiesRow>`

**Outcome:** A read-only "Strategy: …" line appears as a fifth item inside `<LinkedEntitiesRow>` whenever `study.config.auto_followup_strategy` is set to `"narrow"` or `"follow_suggestions"`. Hidden for null / missing / unknown values.

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/linked-entities-row.tsx` | Add a `<StrategyLine>` block (inline or extracted helper) AFTER the existing four `<Entry>` chips. Render conditionally on `OVERNIGHT_STRATEGY_VALUES.includes(study.config?.auto_followup_strategy)`. Include `<InfoTooltip glossaryKey="auto_followup_strategy_line" />` (Story 6 adds the key). |
| `ui/src/__tests__/components/studies/linked-entities-row.test.tsx` | Extend with AC-7 (`follow_suggestions` → line visible with "Try suggested follow-ups" text), AC-8 (missing key → no line), AC-9 (`narrow` → "Refine same knobs" text; both wire values render correctly). |

**Endpoints:** None.

**Key interfaces** (inline addition to `linked-entities-row.tsx`)

```typescript
import { OVERNIGHT_STRATEGY_VALUES, type OvernightStrategy } from '@/lib/enums';
import { InfoTooltip } from '@/components/common/info-tooltip';

// Source-of-truth: ui/src/lib/enums.ts OVERNIGHT_STRATEGY_VALUES (mirrors
// backend/app/api/v1/schemas.py AUTO_FOLLOWUP_STRATEGY_VALUES).
const STRATEGY_DISPLAY: Record<OvernightStrategy, string> = {
  narrow: 'Refine same knobs',
  follow_suggestions: 'Try suggested follow-ups',
};

function StrategyLine({ study }: { study: StudyDetail }): React.ReactNode {
  // study.config is StudyDetail['config'] — JSONB record on the API; safe-narrow.
  const raw = study.config?.auto_followup_strategy;
  if (typeof raw !== 'string') return null;
  if (!(OVERNIGHT_STRATEGY_VALUES as readonly string[]).includes(raw)) return null;
  const strategy = raw as OvernightStrategy;
  return (
    <span data-testid="study-strategy-line">
      <span className="text-muted-foreground">Strategy:</span> {STRATEGY_DISPLAY[strategy]}
      <span className="ml-1 inline-flex">
        <InfoTooltip glossaryKey="auto_followup_strategy_line" />
      </span>
    </span>
  );
}
```

Inside the existing `<LinkedEntitiesRow>` JSX (after the four `<Entry>` calls):

```tsx
<StrategyLine study={study} />
```

**Pydantic schemas:** None.

**Tasks**

1. Edit `linked-entities-row.tsx`:
   - Add the imports for `OVERNIGHT_STRATEGY_VALUES`, `OvernightStrategy`, and `InfoTooltip` (the latter is likely already imported via siblings; verify).
   - Define the `STRATEGY_DISPLAY` mapping + the `StrategyLine` inline component.
   - Mount `<StrategyLine study={study} />` after the four existing `<Entry>` calls.
2. Extend `linked-entities-row.test.tsx`:
   - **AC-7**: `study.config.auto_followup_strategy = 'follow_suggestions'` → assert `data-testid="study-strategy-line"` present, text contains `Strategy:` + `Try suggested follow-ups`, `<InfoTooltip>` icon present.
   - **AC-8**: no `auto_followup_strategy` key in `config` → assert `data-testid="study-strategy-line"` NOT present.
   - **AC-9**: both `narrow` and `follow_suggestions` render with their respective display strings.
   - Additional defensive test: `study.config.auto_followup_strategy = 'unknown_value'` → line hidden (defensive coercion).
3. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`. All green.

**UI Element Inventory (Story 5 — new UI)**

| Element type | Label / data-testid | Data source | User interactions |
|---|---|---|---|
| Strategy line | `data-testid="study-strategy-line"` | `study.config?.auto_followup_strategy` (string `narrow`/`follow_suggestions`) → `STRATEGY_DISPLAY` mapping | None (read-only) |
| InfoTooltip | `<InfoTooltip glossaryKey="auto_followup_strategy_line" />` | Glossary lookup (Story 6 adds the key) | hover/focus |

**Definition of Done (DoD)**

- `<StrategyLine>` block added to `<LinkedEntitiesRow>` after the four existing chips.
- Vitest `linked-entities-row.test.tsx` covers AC-7, AC-8, AC-9 + defensive unknown-value case.
- Strategy values + display mapping reference `OVERNIGHT_STRATEGY_VALUES` from `@/lib/enums.ts`. No inline string literals.
- Source-of-truth comment present above `STRATEGY_DISPLAY`.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all green.

---

### Story 6 — Tutorial guide + ui-architecture doc + screenshot

**Outcome:** The first-study tutorial guide Step 12 documents the morning card with a populated-stack screenshot (FR-9 — required). `docs/01_architecture/ui-architecture.md` mentions the shared `CHAIN_STOP_REASON_PHRASE` module + the morning card surface. (Glossary keys + lock-test extension moved to Story 1 — see cycle-1 finding C1-1.)

**Note on FR-9 screenshot requirement (cycle-1 finding C1-9 accept):** Spec D-17 sanctions an E2E click-through downgrade if the demo seed can't produce a terminated multi-link chain — but it does NOT waive FR-9's screenshot deliverable. The screenshot is a documentation contract; if `pnpm capture-guides` against the demo seed can't capture a chain-anchor card automatically, the impl-execute author MUST either (a) hand-craft a deterministic seed locally (via API helpers + direct DB INSERTs against the local stack) for the screenshot capture session, or (b) file a follow-up `chore_*` idea that BLOCKS this PR's merge until the screenshot lands. The E2E downgrade and the screenshot downgrade are independent decisions.

**New files**

| File | Purpose |
|---|---|
| `ui/public/docs/tutorial-first-study.md` (regenerated) | Copied from `docs/08_guides/tutorial-first-study.md` by `scripts/copy-docs.mjs` post-edit. NOT manually authored — the source-of-truth is the docs source file. |
| `docs/08_guides/images/12-overnight-result-card.png` (or similar; placement per existing convention) | Populated-stack screenshot of the morning card showing all rendered sections. Generated by `pnpm capture-guides` OR a manual local capture per the FR-9 note above. |
| `ui/tests/e2e/overnight-result-card.spec.ts` | Real-backend Playwright spec per spec §14 + §18 (cycle-2 finding C2-2 accept — was previously listed in §3.5 but absent from any story's task list). Required negative-predicate assertion + best-effort AC-12 click-through per spec D-17. Pattern from existing real-backend specs (e.g., `auto-followup.spec.ts`). |

**Modified files**

| File | Change |
|---|---|
| `docs/08_guides/tutorial-first-study.md` | Step 12 ("Run the loop overnight") sub-section *"In the morning — read the overnight result card"*: 2-3 short paragraphs + the populated-stack screenshot showing card with headline, path, best config, stop reason, narrative excerpt. |
| `docs/01_architecture/ui-architecture.md` | Add a paragraph under the existing "Study detail page" section describing: (a) the morning card mount point above `<LinkedEntitiesRow>` with the predicate, (b) the new shared `CHAIN_STOP_REASON_PHRASE` + `formatSignedLift` modules (FR-8) for future cross-surface consumers, (c) the read-only strategy line inside `<LinkedEntitiesRow>`. |

**Endpoints:** None.

**Key interfaces**

(Glossary entries moved to Story 1. Story 6 has no key-interface block beyond the prose changes documented in Tasks.)

**Pydantic schemas:** None.

**Tasks**

1. Edit `docs/08_guides/tutorial-first-study.md`:
   - Locate Step 12 ("Run the loop overnight") — verify section heading exists.
   - Add a sub-section *"In the morning — read the overnight result card"* with the prose described above.
   - Add the screenshot reference `![Overnight result card](images/12-overnight-result-card.png)` (or matching the existing image-path convention).
2. Edit `docs/01_architecture/ui-architecture.md`:
   - Locate the existing "Study detail page" section.
   - Add a paragraph (3-5 sentences) describing the new morning card surface + the shared `CHAIN_STOP_REASON_PHRASE` / `formatSignedLift` modules + the strategy line.
3. Capture the populated-stack screenshot:
   - **First try:** Run `pnpm capture-guides` against the demo seed and check whether the auto-captured guide includes a terminated multi-link chain anchor with the card rendered.
   - **If the auto-capture doesn't produce the precondition:** boot the local stack (`make up && make seed-demo`), manually create a chained study via the UI wizard with `auto_followup_depth >= 2` + `auto_followup_strategy = "follow_suggestions"`, wait for the chain to terminate, then re-run `pnpm capture-guides` against the now-populated state. Commit the resulting screenshot.
   - **Hard fallback (not preferred):** if neither path produces a working screenshot before merge, file a `chore_overnight_result_card_screenshot` idea that BLOCKS this PR's merge until the screenshot lands. Do NOT merge without the screenshot — spec D-17 covers E2E coverage, not the FR-9 documentation deliverable.
4. Create `ui/tests/e2e/overnight-result-card.spec.ts` (cycle-2 finding C2-2 accept):
   - **Required negative case:** Set up via API helpers (or via the existing global setup) a single-link or in-flight study; navigate to its `/studies/{id}` page; assert `data-testid="overnight-result-card"` is NOT present.
   - **Best-effort positive case (AC-12):** Check whether `make seed-demo` (or the existing E2E global setup) produces a study whose `/api/v1/studies/{id}/chain` response satisfies `stop_reason !== 'in_flight'` AND `links.length >= 2` AND `best_link_id !== null` AND `proposal_id_for_best_link !== null`. If yes, navigate to that study, assert the card is present + click the "Best config: …" link, assert browser navigates to `/proposals/{proposal_id_for_best_link}` (verify via `page.url()`). If no, document the gap in the PR body per spec D-17.
   - Pattern: real backend (no `page.route()`); seed via API helpers; navigate via `page.goto`; assert via `page.locator` per CLAUDE.md "E2E Testing Rules".
5. Run `cd ui && pnpm prebuild` (the `copy-docs.mjs` step) → confirm the regenerated `ui/public/docs/tutorial-first-study.md` is updated.
6. Verify `generated-artifacts-fresh` would pass (per [CLAUDE.md "Generated artifacts" section](../../../../CLAUDE.md)): the regeneration script copies the docs source into `ui/public/docs/`. The freshness gate fails if `git status --porcelain` shows drift between source and copy.
7. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e && pnpm build`. All green.

**Definition of Done (DoD)**

- `docs/08_guides/tutorial-first-study.md` Step 12 has the new sub-section AND the populated-stack screenshot is committed (per cycle-1 finding C1-9 accept — screenshot is required, not waived by the E2E downgrade).
- `ui/public/docs/tutorial-first-study.md` regenerated (or freshness gate would catch the drift).
- `docs/01_architecture/ui-architecture.md` mentions the morning card + shared modules + strategy line.
- `ui/tests/e2e/overnight-result-card.spec.ts` exists with at minimum the negative-predicate assertion. Best-effort positive-case assertion lands when the seed precondition holds (per spec D-17 + cycle-2 C2-2).
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e && pnpm build` all green.

---

## UI Guidance (required for frontend-facing work)

### Reference: current component structure

#### `ui/src/components/studies/auto-followup-chain-panel.tsx` (Story 1 — refactor target)

- **Total line count:** ~314 lines (verified via `wc -l` at plan time).
- **Section structure:** imports (1-19) → `CHAIN_STOP_REASON_PHRASE` constant (33-41) → `TERMINAL_STUDY_STATUSES` (43) → `formatSignedLift` helper (49-52) → `formatDelta` helper (54-58) → `<ChainLinkStrategyBadge>` child component (80-117) → `<AutoFollowupChainPanel>` main component (133-313) → trailing newline (314).
- **State variables:** None directly — the panel consumes hooks (`useStudyChain`, `useQueryClient`, `useRef`) and derives render state.
- **Props:** `{ study: StudyDetail; chainChildren: StudySummary[] }` per [line 20-30](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L20-L30).
- **Insertion points (Story 1):**
  - Remove lines 33-41 (`CHAIN_STOP_REASON_PHRASE`) and 49-52 (`formatSignedLift`).
  - Add two imports near the existing `@/lib/...` imports (around lines 10-19).

#### `ui/src/components/studies/linked-entities-row.tsx` (Story 5 — extend)

- **Total line count:** ~95 lines.
- **Section structure:** imports (1-12) → `Entry` helper (24-46) → `LinkedEntitiesRow` main component (48-95).
- **State variables:** None — consumes `useCluster`, `useQuerySet`, `useJudgmentList`, `useTemplate` hooks at lines 49-52.
- **Props:** `{ study: StudyDetail }` per [line 48](../../../../ui/src/components/studies/linked-entities-row.tsx#L48).
- **Insertion point (Story 5):** After the four existing `<Entry>` calls inside the `<div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">` wrapper (around the closing `</div>` near line 95). Add `<StrategyLine study={study} />` as a fifth child.

#### `ui/src/app/studies/[id]/page.tsx` (Story 3 — extend with card mount)

- **Insertion point:** Between `<StudyHeaderWithSyntheticChip>` ([line 95](../../../../ui/src/app/studies/[id]/page.tsx#L95)) and `<LinkedEntitiesRow>` ([line 96](../../../../ui/src/app/studies/[id]/page.tsx#L96)).
- Insert `<OvernightResultCard study={study} />`. The component returns `null` when its predicate is false, so unconditional mount is correct — no parent-side gating.

#### `ui/src/components/studies/digest-panel.tsx` (Story 4 — anchor addition)

- **Insertion point:** The outer-most JSX element (likely a `<Card>` from `@/components/ui/card`). Add `id="digest"` to it.
- **Verify before edit:** open the file, find the outer return JSX (probably around lines 35-95), confirm the outer element. If it's not a `<Card>`, wrap appropriately OR add the id to whatever the outer wrapper is.

### Analogous markup patterns

#### Pattern 1 — Card structure (Story 3 / 4)

Copy from `<AutoFollowupChainPanel>` at [auto-followup-chain-panel.tsx:179-313](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L179-L313):

```tsx
{/* Pattern — Card with title + InfoTooltip + content body, from auto-followup-chain-panel.tsx:179-188 */}
<Card data-testid="overnight-result-card">
  <CardHeader>
    <CardTitle className="flex items-center gap-2 text-base">
      Overnight result {/* headline text + dynamic content */}
      <InfoTooltip glossaryKey="overnight_result" />
    </CardTitle>
  </CardHeader>
  <CardContent className="space-y-2 text-sm">
    {/* card body sections — match the chain panel's space-y-2 / text-sm rhythm */}
  </CardContent>
</Card>
```

#### Pattern 2 — Child component with hook-at-top per Rules of Hooks (Story 3 PathTokenChip / Story 4 WinningLinkConvergenceChip)

Copy from `<ChainLinkStrategyBadge>` at [auto-followup-chain-panel.tsx:80-117](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L80-L117):

```tsx
/* Pattern — child component that calls a hook unconditionally,
 * gated by `enabled`, then renders based on the result.
 * From auto-followup-chain-panel.tsx:80-117. */
function ChainLinkStrategyBadge({
  link,
}: {
  link: StudyChainResponse['links'][number];
}): React.ReactNode {
  const kind = link.selected_followup_kind;
  // Hooks must run unconditionally; ALWAYS call useTemplate but pass
  // null for non-swap links so it stays disabled (the hook's `enabled`
  // gate handles the null id).
  const templateQ = useTemplate(kind === 'swap_template' ? link.template_id : null);
  if (!kind) return null;
  // ... render based on (kind, templateQ.data)
  return (
    <span
      data-testid={`chain-link-strategy-${link.id}`}
      className="ml-2 inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
    >
      {label}
    </span>
  );
}
```

#### Pattern 3 — Link to a proposal (Story 3 best-config CTA)

Copy from `<AutoFollowupChainPanel>` at [auto-followup-chain-panel.tsx:278-294](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L278-L294):

```tsx
{/* Pattern — Best-config link to proposal page, from auto-followup-chain-panel.tsx:278-294 */}
<p data-testid="chain-summary-best-config">
  {chain.proposal_id_for_best_link !== null && bestLink ? (
    <>
      Best config:{' '}
      <Link
        href={`/proposals/${chain.proposal_id_for_best_link}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        {bestLink.name}
      </Link>
    </>
  ) : chain.best_link_id !== null && bestLink ? (
    <>Best config: {bestLink.name} (Awaiting proposal)</>
  ) : (
    <>Best config: —</>
  )}
</p>
```

#### Pattern 4 — `<Entry>` row inside `<LinkedEntitiesRow>` (Story 5 reference — strategy line replaces the `<Entry>` Link wrapper since it's not linkable)

The strategy line is NOT a clickable `<Entry>` — it's a label + value without a destination. Pattern reference for the `text-muted-foreground` label prefix style is at [linked-entities-row.tsx:38-45](../../../../ui/src/components/studies/linked-entities-row.tsx#L38-L45):

```tsx
{/* Pattern — Label + value row inside LinkedEntitiesRow, from linked-entities-row.tsx:38-45.
 * The strategy line uses the same `<span className="text-muted-foreground">Label:</span>` prefix
 * but renders plain text instead of a Link. */}
<span data-testid="study-strategy-line">
  <span className="text-muted-foreground">Strategy:</span> {STRATEGY_DISPLAY[strategy]}
  <span className="ml-1 inline-flex">
    <InfoTooltip glossaryKey="auto_followup_strategy_line" />
  </span>
</span>
```

### Layout and structure

- **Card position:** between `<StudyHeaderWithSyntheticChip>` and `<LinkedEntitiesRow>` per spec D-6. The page's vertical stack pattern is `space-y-6` at the `<main>` level ([page.tsx:74](../../../../ui/src/app/studies/[id]/page.tsx#L74)); the new card fits into that rhythm.
- **Card internal spacing:** mirror the existing chain panel's `<CardContent className="space-y-3 text-sm">` ([line 187](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L187)). Use `space-y-2 text-sm` for the morning card so it's slightly tighter (it has fewer sections than the chain panel).
- **Headline + chip:** `flex items-center gap-2` so the convergence chip sits inline with the headline text.
- **Strategy line:** lives INSIDE the existing `flex flex-wrap gap-x-6 gap-y-1` container of `<LinkedEntitiesRow>` ([line 55](../../../../ui/src/components/studies/linked-entities-row.tsx#L55)). The `flex-wrap` means it wraps to a new line on narrow viewports — no extra responsive handling needed.

### Interaction behavior

| Action | Behavior | API call |
|---|---|---|
| Operator navigates to `/studies/{id}` | Page mounts; `useStudyChain` + `useStudyDigest` + (conditional) `useStudy(best_link_id)` + (conditional) `useTemplate(...)` fire | `GET /api/v1/studies/{id}/chain` (always); `GET /api/v1/studies/{best_link_id}/digest` (when chain predicate passes); `GET /api/v1/studies/{best_link_id}` (when `best_link_id !== study.id`); `GET /api/v1/query-templates/{id}` per swap-template link (cached) |
| Operator clicks "Best config: {name}" link | Browser navigates to `/proposals/{proposal_id_for_best_link}` | (Next.js client-side nav; no extra API call) |
| Operator clicks "View full digest →" link | Browser navigates to `/studies/{best_link_id}#digest` (in-page anchor on the same study when `best_link_id === study.id`; otherwise cross-page nav with hash anchor) | (Next.js nav) |
| Operator hovers `<InfoTooltip>` icon (card title or strategy line) | Tooltip opens with the glossary entry's `short` text | (No API call) |

### Handler function patterns

No new event handlers in Phase 2 — the card is fully read-only. The only interactivity is `<Link>` navigation, which Next.js handles internally.

### Component composition

- **`<OvernightResultCard>`** is mounted directly in `page.tsx`. It is its own self-contained component; no extracted sub-components other than the two children below.
- **`<PathTokenChip>`** is colocated inside `overnight-result-card.tsx` (not extracted to a separate file). Its only consumer is the card; cross-file extraction would be premature.
- **`<WinningLinkConvergenceChip>`** is colocated inside `overnight-result-card.tsx`. Same rationale.
- **`<StrategyLine>`** is colocated inside `linked-entities-row.tsx`. Same rationale.

### Information architecture placement

- **Morning result card:** Above `<LinkedEntitiesRow>` on `/studies/{id}`. First "answer" surface the operator sees after the study title block. Discoverable by navigation to any chain member's page.
- **Strategy line:** Inside `<LinkedEntitiesRow>` (the four-FK chip row), as a fifth item. Discoverable wherever the four chips are — i.e., on every study's detail page.

### Tooltips and contextual help

| Element | Tooltip key | Source-of-truth comment | JSX |
|---|---|---|---|
| Card title | `overnight_result` (**Story 1** adds it per cycle-1 C1-1) | Glossary key value-locked at [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | `<InfoTooltip glossaryKey="overnight_result" />` |
| Strategy line | `auto_followup_strategy_line` (**Story 1** adds it per cycle-1 C1-1) | Same lock test | `<InfoTooltip glossaryKey="auto_followup_strategy_line" />` |
| Stop-reason line | `auto_followup_depth` (when `stop_reason === 'depth_exhausted'`) / `auto_followup_budget_skip` (when `'budget'`) — both EXISTING Phase 1 keys per cycle-2 C2-3 | Reuses chain-panel pattern at [`auto-followup-chain-panel.tsx:297-307`](../../../../ui/src/components/studies/auto-followup-chain-panel.tsx#L297-L307) | Conditional `<InfoTooltip glossaryKey="auto_followup_depth"/>` / `<InfoTooltip glossaryKey="auto_followup_budget_skip"/>` |

The glossary entries themselves carry the source-of-truth comment block per the file's policy at [`glossary.ts:6-15`](../../../../ui/src/lib/glossary.ts#L6-L15). The Story 1 entries fit under the existing `feat_overnight_autopilot Story 3.1` block (same logical group as Phase 1's `overnight_strategy` entry).

### Visual consistency

| Element | CSS pattern source |
|---|---|
| `<Card>` + `<CardHeader>` + `<CardTitle>` + `<CardContent>` | `@/components/ui/card` (shadcn primitive; same as chain panel) |
| `flex items-center gap-2 text-base` (card title) | `auto-followup-chain-panel.tsx:182` |
| `space-y-2 text-sm` (card content) | Adjacent to chain panel's `space-y-3 text-sm` — slightly tighter |
| `text-muted-foreground` (label prefix on strategy line) | `linked-entities-row.tsx:40` |
| `text-blue-600 underline-offset-4 hover:underline` (best-config link, "View full digest" link) | `linked-entities-row.tsx:41`; `auto-followup-chain-panel.tsx:283` |
| `ml-2 inline-flex items-center rounded bg-secondary px-2 py-0.5 text-xs` (convergence chip) | New variant on the `<Badge>` pattern — adapt from `auto-followup-chain-panel.tsx:110-114` which uses `bg-muted px-1.5 py-0.5 text-xs text-muted-foreground` (the chip uses `bg-secondary` instead since it's a status, not an annotation) |

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** The closest delete is the inline `CHAIN_STOP_REASON_PHRASE` declaration in `<AutoFollowupChainPanel>` (Story 1 / FR-8), which is ~10 LOC of constant data and triggers no user-observable behavior change (the existing chain-panel tests pass unchanged — the lock for behavioral parity).

### Client-side persistence

None. Per spec D-8, the card carries no dismiss state; there is no `localStorage` or `sessionStorage` usage in Phase 2.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `ui/src/__tests__/lib/` (for standalone modules) + colocated direct-import unit tests inside `overnight-result-card.test.tsx` for helpers that live with the component.
- Scope: pure helpers (`pathTokenForLink`, `truncateNarrative`, `formatSignedLift`, `CHAIN_STOP_REASON_PHRASE` shape, `shouldShowOvernightResultCard`).
- Tasks:
  - [ ] `chain-stop-reason.test.ts` (Story 1)
  - [ ] `format-lift.test.ts` (Story 1)
  - [ ] `chain-path-tokens.test.ts` (Story 2)
  - [ ] Direct unit tests for `shouldShowOvernightResultCard` (Story 3 — pure boolean per FR-7, tested without React render per cycle-2 finding C2-6).
  - [ ] Direct unit tests for `truncateNarrative` (Story 3 — pure helper per FR-5).
- DoD:
  - [ ] All five mapping cases for `pathTokenForLink` covered.
  - [ ] `formatSignedLift` covers null/undefined, positive, negative, zero cases.
  - [ ] `CHAIN_STOP_REASON_PHRASE` six-key shape covered + source-of-truth comment present.
  - [ ] `shouldShowOvernightResultCard` covers undefined / in_flight / single-link / terminal-multi-link cases (no React).
  - [ ] `truncateNarrative` covers ≤240 / sentence-boundary / whitespace-fallback / hard-fallback cases.

### 3.2 Integration tests

- Location: N/A — Phase 2 is frontend-only; no backend integration test layer applicable.
- Tasks: none.
- DoD: N/A.

### 3.3 Contract tests

- Location: N/A — no new endpoints in Phase 2.
- Tasks: none.
- DoD: N/A — existing contract tests for `/chain`, `/studies/{id}`, `/studies/{id}/digest`, `/query-templates/{id}` remain green.

### 3.4 Vitest component tests (frontend equivalent of "integration")

- Location: `ui/src/__tests__/components/studies/`
- Scope: rendered component behavior with TanStack Query test provider; mocked API client; assertion on DOM via `@testing-library/react`.
- Tasks:
  - [ ] `overnight-result-card.test.tsx` (Stories 3 + 4 — AC-1 through AC-6, AC-10, AC-11, three best-config cases, mixed-token-chain, stop-reason tooltip, direct unit tests for `shouldShowOvernightResultCard` + `truncateNarrative`).
  - [ ] `linked-entities-row.test.tsx` extension (Story 5 — AC-7, AC-8, AC-9, defensive unknown-value).
  - [ ] `glossary.test.ts` extension (**Story 1** per cycle-1 finding C1-1 — two new keys lock; moved here from Story 6 because `<InfoTooltip glossaryKey>` is type-locked).
- DoD:
  - [ ] All AC-1 through AC-11 covered by vitest.
  - [ ] Existing `auto-followup-chain-panel.test.tsx` passes UNCHANGED (proves Story 1 refactor is mechanical-only).
  - [ ] Existing `linked-entities-row.test.tsx` original assertions still pass (Story 5 is additive).
  - [ ] Existing `digest-panel.test.tsx` (if it exists) still passes (Story 4's `id="digest"` addition is markup-only, no behavior change).

### 3.5 E2E tests

- Location: `ui/tests/e2e/`
- Scope: real-backend Playwright spec covering AC-12 (best-effort) + negative predicate assertion.
- **Rule:** Per CLAUDE.md "E2E Testing Rules", no `page.route()` mocking. Real backend at `localhost:8000`; real database. Tests must exercise the `page` object for browser-visible behavior; `request` is allowed for setup only.
- Tasks:
  - [ ] `ui/tests/e2e/overnight-result-card.spec.ts`:
    - **Required (negative case):** Navigate to a seeded non-chain study (any study from `make seed-demo` that has `chain.links.length < 2` or no chain). Assert `data-testid="overnight-result-card"` is NOT in the page.
    - **Best-effort (AC-12 click-through):** At impl-time, check whether `make seed-demo` produces ANY study whose `/api/v1/studies/{id}/chain` response has `stop_reason !== 'in_flight'` AND `links.length >= 2` AND `best_link_id !== null` AND `proposal_id_for_best_link !== null`. If yes, add the click-through assertion to the spec. If no, document the gap in the PR description and skip the click-through (spec D-17 sanctions the downgrade).
- DoD:
  - [ ] Negative predicate assertion lands and passes.
  - [ ] Click-through assertion lands IF the seed produces the precondition; otherwise documented downgrade with PR description note.
  - [ ] Spec uses `page.goto` / `page.locator` (NO `page.route()`).

### 3.6 Existing test impact audit

For files touched by this plan, the impact is bounded:

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` | (existing chain-panel tests) | existing | **No change.** Story 1 refactor is mechanical; the panel's external behavior is identical. Verifying these still pass is the lock for Story 1 correctness. |
| `ui/src/__tests__/components/studies/linked-entities-row.test.tsx` | (existing four-chip tests) | existing | **Extend, do not modify existing assertions.** Story 5 adds new test cases for the strategy line; existing four-chip render tests must still pass. |
| `ui/src/__tests__/components/studies/digest-panel.test.tsx` (if it exists) | (existing digest tests) | (verify at impl time) | **No change required.** Story 4 adds `id="digest"` to the outer wrapper but doesn't change behavior. Confirm existing tests pass. |
| `ui/src/__tests__/lib/glossary*.test.ts` (existing lock test) | Phase 1's `overnight_strategy` lock | existing | **Extend, do not modify existing assertions.** **Story 1** adds two new keys (`overnight_result`, `auto_followup_strategy_line`) per cycle-1 C1-1; the existing `overnight_strategy` assertion must still pass. |
| `ui/src/app/studies/[id]/page.test.tsx` (or wherever page-level tests live) | Page render structure | (verify at impl time) | **No change OR additive only.** Story 3 inserts `<OvernightResultCard>` above `<LinkedEntitiesRow>`; if a page-level test asserts the exact order of children, extend it. |
| `ui/tests/e2e/auto-followup.spec.ts` | (existing chain E2E) | existing | **No change.** The chain panel + page structure outside the card are untouched. |

### 3.7 Migration verification

N/A — no schema change in Phase 2.

### 3.8 CI gates

- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm test:e2e` (with caveat per Story 6 — full coverage when demo seed produces the precondition; negative-only otherwise)
- [ ] `cd ui && pnpm build`
- [ ] Backend `make test-unit && make test-integration && make test-contract` — must remain green (no backend code change, so this is a non-regression check).

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — UPDATE after PR merges (Story 6's task):
- [ ] Move from "queued" to "Last 5 merges (newest first)" with merge SHA + date + one-liner summary.
- [ ] Set "In flight" to `_None._` (or the next planned feature).
- [ ] Alembic head unchanged (`0022_solr_engine_auth_check`).

**`architecture.md`** — UPDATE in Story 6:
- [ ] Add a paragraph under "Study detail page" describing the morning card mount, the shared `CHAIN_STOP_REASON_PHRASE` + `formatSignedLift` modules, and the strategy line. Cross-reference `docs/01_architecture/ui-architecture.md` for details.

**`CLAUDE.md`** — NO update required (no new convention introduced; the existing form-select-discipline + Enumerated Value Contract Discipline rules already cover Story 5's source-of-truth comment).

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `docs/01_architecture/ui-architecture.md` — paragraph under "Study detail page" describing the morning card + shared modules + strategy line (Story 6).

### 4.2 Product docs (`docs/02_product`)

- [ ] No update — Phase 2 doesn't change the user-story landscape; it polishes an existing flow.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] No update — no new operator-actionable signal.

### 4.4 Security docs (`docs/04_security`)

- [ ] No update — no new attack surface, no new data flow, no new secrets.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No update — existing test-layer conventions cover Phase 2.

### 4.6 Tutorial guide

- [ ] `docs/08_guides/tutorial-first-study.md` Step 12 — add sub-section *"In the morning — read the overnight result card"* with prose + screenshot (Story 6 / FR-9).

**Documentation DoD**

- [ ] `state.md`, `architecture.md` updated.
- [ ] `docs/01_architecture/ui-architecture.md` carries the morning-card description.
- [ ] `docs/08_guides/tutorial-first-study.md` Step 12 updated.
- [ ] `ui/public/docs/tutorial-first-study.md` regenerated via `pnpm prebuild` (or the freshness gate would catch the drift).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Extract two helpers (`CHAIN_STOP_REASON_PHRASE`, `formatSignedLift`) into shared modules so the chain panel + the morning card consume from a single source of truth. Eliminates the drift risk of two copies of the same constant on the same page.

### 5.2 Planned refactor tasks

- [ ] **Backend refactor:** None — no backend code touched.
- [ ] **Frontend refactor:** Story 1 — extract `CHAIN_STOP_REASON_PHRASE` + `formatSignedLift` into `ui/src/lib/chain-stop-reason.ts` + `ui/src/lib/format-lift.ts`. Chain panel imports the shared modules. Behavior identical.
- [ ] **Remove dead/legacy branches after cutover:** None — Phase 2 is purely additive.

### 5.3 Refactor guardrails

- [ ] **Behavioral parity proven by tests:** existing `auto-followup-chain-panel.test.tsx` passes UNCHANGED after Story 1 (no test edits to the existing file; the refactor is internal).
- [ ] **Lint/typecheck remain green:** ESLint + TypeScript pass after every story.
- [ ] **No expansion of product scope:** Stories adhere to the spec's in-scope list (FR-1 through FR-9). Cap 2 stays delegated to the sibling.
- [ ] **Discovered debt tracked:** None expected for a small frontend-only feature; if Stories surface unexpected debt (e.g., the demo seed doesn't produce a terminated chain at all), file a `chore_*` idea file per CLAUDE.md's tangential-discovery rule.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_overnight_final_solution` Phase 1 — `StudyChainLink.selected_followup_kind` + `StudyConfigSpec.auto_followup_strategy` + `OVERNIGHT_STRATEGY_VALUES` + `SELECTED_FOLLOWUP_KIND_VALUES` enum constants | All stories | Implemented (PR #440, 2026-06-04) | N/A — shipped. |
| `feat_overnight_autopilot` — `/chain` endpoint + `useStudyChain` hook + `<AutoFollowupChainPanel>` + `CHAIN_STOP_REASON_PHRASE` map | All stories | Implemented (PR #343, 2026-05-31) | N/A — shipped. |
| `feat_study_convergence_indicator` — `StudyDetail.convergence.verdict` field | Story 4 (FR-4) | Implemented (PR #352, 2026-06-01) | Low — without it, the convergence chip silently hides per FR-4 graceful-degrade. The rest of the card still functions. |
| `feat_digest_executable_followups` — `DigestResponse.narrative` + `suggested_followups` | Story 4 (FR-5) | Implemented (PR #225, 2026-05-24) | N/A — shipped. |
| Sibling `feat_overnight_studies_summary_card` (index-page surface) | None (coordinate-only) | Idea-stage | N/A — coordination is the shared module; Phase 2's correctness does not depend on the sibling shipping first. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Demo seed doesn't produce a terminated multi-link chain → E2E click-through coverage downgraded | Medium | Low | Spec D-17 sanctions the downgrade. Vitest covers the click-through with mocked hook results. Document the gap in PR description; capture screenshot regen limitation in Story 6 DoD. |
| `<DigestPanel>` outer wrapper structure changes between plan time and impl time, breaking the `id="digest"` addition site | Low | Low | Story 4 includes a "verify before edit" task — re-read the file at impl-time to confirm the outer wrapper. The change is one line. |
| Rules-of-Hooks violation slips through because the lint rule doesn't catch every case | Low | High | Spec D-11 / D-18 / D-19 codify the patterns. Story 3 + 4 DoD include `pnpm lint` (catches `react-hooks/rules-of-hooks`). Cross-model GPT-5.5 review during impl-execute Step 6 will re-flag any drift. |
| `useStudyDigest`'s 404 `DIGEST_NOT_READY` behavior changes (e.g., suppression is removed) → narrative section renders an error | Low | Low | Story 4 DoD asserts the hide-on-isError behavior. If the hook contract changes upstream, the test catches it. |
| `formatSignedLift` extraction breaks the chain panel's existing snapshot or assertion | Low | Medium | Story 1 DoD: existing `auto-followup-chain-panel.test.tsx` passes UNCHANGED. Mechanical refactor — if the test breaks, the refactor isn't mechanical. |
| Phase 2 ships before the sibling `feat_overnight_studies_summary_card` and the two surfaces don't visually coordinate | Low | Low | Both surfaces consume the same `CHAIN_STOP_REASON_PHRASE` (Phase 2's shared module is the foundation). Visual coordination is a sibling-spec concern; Phase 2 ships standalone. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `useStudyChain` returns 404 (study doesn't exist) | Operator navigates to a stale URL | Card hidden (predicate fails when `chain === undefined`); page-level 404 handler renders | Manual — operator navigates away |
| `useStudyDigest` returns 404 `DIGEST_NOT_READY` | Winning link's study is still running | Narrative section hidden; card still renders headline + path + best config + stop reason + convergence chip | Auto — TanStack Query refetches as appropriate |
| `useStudy(best_link_id)` cross-fetch returns 404 | Winning link's study was hard-deleted (unlikely — soft delete is the default) | Convergence chip hidden | Manual — operator investigates the deletion |
| `useTemplate(link.template_id)` returns 404 for a swap_template link | The swap target template was deleted post-chain | Path token falls back to `swap to {first 6 of template_id}` per FR-3 | Auto — graceful-degrade |
| `chain.cumulative_lift === null` | All chain links failed to produce a metric | Headline renders without lift fragment (`"Overnight exploration complete — N studies"`); other sections still render | Auto |
| All `link.selected_followup_kind === null` (legacy narrow chain) | Operator opted into depth but not `follow_suggestions` strategy | Path line hidden per D-7; other sections render | Auto |
| ESLint `react-hooks/rules-of-hooks` rule catches a hook violation | Implementer ignores D-11 / D-18 / D-19 patterns | Build fails at `pnpm lint`; PR can't merge | Manual — implementer restructures per the pattern |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1** — Foundation: extract shared helpers (FR-8) + add glossary keys + extend lock test (FR-6 — landed early per cycle-1 C1-1 so Stories 3 + 5 typecheck against the type-locked `<InfoTooltip glossaryKey>`).
2. **Story 2** — Pure-domain helper `pathTokenForLink` (FR-3; no UI; no React; can be tested in isolation).
3. **Story 3** — `<OvernightResultCard>` shell + headline + path + best config + stop reason + **narrative excerpt** + `truncateNarrative` (FR-1 + FR-3 + FR-5 + FR-7 + FR-8 consumption; mounted on page; vitest for AC subset that doesn't need chip).
4. **Story 4** — Convergence chip + `<DigestPanel>` `id="digest"` anchor (FR-4; AC-1 chip portion + AC-6 + AC-10 tests; depends on Story 3's component file).
5. **Story 5** — `<StrategyLine>` inside `<LinkedEntitiesRow>` (FR-2; independent of card stories; could ship in parallel but lands after 4 for clean review ordering).
6. **Story 6** — Tutorial guide + ui-architecture doc + populated-stack screenshot + E2E spec (FR-9; depends on Stories 1-5 to know the final shape; lands last; triggers state.md/architecture.md updates).

### Parallelization opportunities

- Story 1 + Story 2 + Story 5 are mutually independent (no overlapping file touches). They can be implemented in parallel by separate agents/sessions if desired.
- Story 6 depends on Stories 1-5; cannot be parallelized.
- Story 3 + Story 4 share `overnight-result-card.tsx` ownership; sequential is the only safe path (Story 4 modifies what Story 3 writes).

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — single-PR ship.
- **Feature flag strategy:** None. The card's visibility is gated by the runtime predicate (`shouldShowOvernightResultCard`). Legacy chains / in-flight chains / single-link chains see no change.
- **Migration/cutover steps:** None — no schema change.
- **Reconciliation/repair strategy:** None — read-only feature; no state mutation; no backfill or repair surface.

## 9) Execution tracker

### Current sprint

- [ ] Story 1 — Extract shared helpers
- [ ] Story 2 — Pure-domain helpers
- [ ] Story 3 — `<OvernightResultCard>` shell
- [ ] Story 4 — Convergence chip + narrative excerpt
- [ ] Story 5 — `<StrategyLine>` inside `<LinkedEntitiesRow>`
- [ ] Story 6 — Glossary keys + tutorial guide + doc update

### Blocked items

- None.

### Done this sprint

- (none yet)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] No backend code change (Phase 2 invariant) — verify with `git diff --stat backend/`.
- [ ] Key interfaces implemented with compatible signatures (the TypeScript snippets in each story).
- [ ] Required tests added/updated for the touched layers (unit + vitest component, plus E2E for Story 6's cumulative coverage).
- [ ] Commands executed and passed:
  - [ ] `cd ui && pnpm lint`
  - [ ] `cd ui && pnpm typecheck`
  - [ ] `cd ui && pnpm test`
  - [ ] `cd ui && pnpm build`
  - [ ] `cd ui && pnpm test:e2e` (Story 6 — gated on demo-seed precondition per D-17)
- [ ] No backend migration (no migration round-trip needed).
- [ ] Related docs updated in same PR when behavior/contract changed (Story 6).

## 11) Plan consistency review

### 1. Spec ↔ plan endpoint count

- **Spec §8.1:** 0 NEW endpoints (4 EXISTING consumed). ✓
- **Plan:** 0 new endpoint tables across all stories. ✓ Match.

### 2. Spec ↔ plan error code coverage

- **Spec §8.5:** N/A — no new error codes in Phase 2.
- **Plan:** No new contract test tasks for new error codes (none to cover). ✓ Match.

### 3. Spec ↔ plan FR coverage

| Spec FR | Plan story | Covered |
|---|---|---|
| FR-1 | Story 3 + Story 4 | ✓ |
| FR-2 | Story 5 | ✓ |
| FR-3 | Story 2 (pure helper) + Story 3 (parent stitcher + child component) | ✓ |
| FR-4 | Story 4 | ✓ |
| FR-5 | **Story 3** (narrative section + `truncateNarrative` helper) + **Story 4** (`id="digest"` on `<DigestPanel>` + AC-5 hide-on-error test) | ✓ — moved primary scope from Story 4 to Story 3 per cycle-2 finding C2-4 (Story 3 must consume `digestQ` to avoid an unused-variable lint failure after declaring the hook for invariant-order compliance). |
| FR-6 | **Story 1** (moved from Story 6 per cycle-1 C1-1 — `<InfoTooltip glossaryKey>` is type-locked, so the keys must land before Stories 3+5 consume them) | ✓ |
| FR-7 | **Story 3** (`shouldShowOvernightResultCard` colocated with the card component — clarified per cycle-1 C1-6) | ✓ |
| FR-8 | Story 1 | ✓ |
| FR-9 | Story 6 (screenshot is a hard DoD per cycle-1 C1-9; not waived by spec D-17 E2E downgrade) | ✓ |

All 9 FRs covered. ✓

### 4. Story internal consistency

- Endpoint tables: each story's endpoint section is "None" (Phase 2 is frontend-only). ✓
- DoD ↔ tasks: every task in each story has a corresponding DoD assertion. ✓
- New files: no file is owned by two stories. ✓
- Modified files: each modified file is touched by exactly one story (except `overnight-result-card.tsx`, which Story 3 creates and Story 4 modifies — that's sequential, not concurrent ownership). ✓

### 5. Test file count and assignment

| Test file | Story | Notes |
|---|---|---|
| `ui/src/__tests__/lib/chain-stop-reason.test.ts` | Story 1 | New |
| `ui/src/__tests__/lib/format-lift.test.ts` | Story 1 | New |
| `ui/src/__tests__/lib/glossary*.test.ts` | **Story 1** (extends — moved from Story 6 per cycle-1 C1-1) | Extended |
| `ui/src/__tests__/lib/chain-path-tokens.test.ts` | Story 2 | New |
| `ui/src/__tests__/components/studies/overnight-result-card.test.tsx` | Story 3 (creates) + Story 4 (extends) | New / Extended |
| `ui/src/__tests__/components/studies/linked-entities-row.test.tsx` | Story 5 (extends) | Extended |
| `ui/tests/e2e/overnight-result-card.spec.ts` | Story 6 (creates per cycle-2 C2-2) | New |

7 test files, each assigned to exactly one story (sequential extensions for Story 3 → Story 4 count as one ownership). ✓

### 6. Gate arithmetic

Phase 2 is single-epic, single-PR. No "all N endpoints live" gate to verify. ✓

### 7. Open questions resolved

Spec §19 carries 22 decision-log entries (D-1 through D-22) and zero open questions. ✓

### 8. Frontend UI Guidance completeness

Plan's "UI Guidance" section above covers:
- [x] Insertion point (per modified component)
- [x] Analogous markup patterns (4 patterns with actual JSX)
- [x] Layout and structure (card position, spacing rhythm)
- [x] Confirmation/modal dialog pattern — N/A (no modals in Phase 2)
- [x] Visual consistency table
- [x] Component composition (colocated children rationale)
- [x] Interaction behavior table
- [x] Handler function patterns — N/A (no event handlers)
- [x] Information architecture placement
- [x] Tooltips and contextual help (glossary keys + source-of-truth)
- [x] Legacy behavior parity — explicitly declared N/A (no >100 LOC delete)

### 9. Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| Migration dir is `migrations/versions/` | N/A — no migration | Verified (no migration needed) |
| Alembic head is `0022_solr_engine_auth_check` | `state.md` ("Current branch") | Verified |
| `<LinkedEntitiesRow>` mounted at page.tsx:96 | Read `ui/src/app/studies/[id]/page.tsx` | Verified |
| `<StudyHeaderWithSyntheticChip>` at page.tsx:95 | Read | Verified |
| `CHAIN_STOP_REASON_PHRASE` at auto-followup-chain-panel.tsx:34-41 | Read | Verified |
| `formatSignedLift` at auto-followup-chain-panel.tsx:49-52 | Read | Verified |
| `<ChainLinkStrategyBadge>` at auto-followup-chain-panel.tsx:80 | Read | Verified |
| `useStudy(id: string, options?: { enabled? })` at studies.ts:74-87 | Read | Verified |
| `useStudyDigest(id: string \| undefined, opts?: { enabled? })` at digests.ts:30-50 | Read | Verified |
| `useStudyChain(studyId: string, options)` at studies.ts:212-239 | Read | Verified |
| `useTemplate` at query-templates.ts:49 | Read | Verified |
| `StudyChainLink.selected_followup_kind` at schemas.py:978 | Read | Verified |
| `StudyChainLink.template_id` at schemas.py:972 | Read | Verified |
| `StudyChainLink.name: str` at schemas.py:957 | Read | Verified |
| `StudyChainResponse.best_link_id`, `cumulative_lift`, `proposal_id_for_best_link`, `stop_reason` at schemas.py:996-1008 | Read | Verified |
| `StudyConfigSpec.auto_followup_strategy: str \| None` at schemas.py:724 | Read | Verified |
| `OVERNIGHT_STRATEGY_VALUES` at ui/src/lib/enums.ts:84-92 | Read | Verified |
| `SELECTED_FOLLOWUP_KIND_VALUES` at ui/src/lib/enums.ts:94-110 | Read | Verified |
| `DigestResponse.narrative: str` at schemas.py:1362 | Read | Verified |
| Glossary structure at ui/src/lib/glossary.ts (short/long shape) | Read lines 1-60 | Verified (note: spec says ≤120 chars for `short`; actual lock is ≤140 chars — my entries are well within either) |
| `digest-panel.tsx` has `data-testid="digest-narrative"` but NO `id="digest"` today | grep verification | Verified — Story 4's task to add `id="digest"` is needed |
| Page.tsx layout (vertical stack via `space-y-6` at line 74) | Read | Verified |
| `<LinkedEntitiesRow>` uses `flex flex-wrap gap-x-6 gap-y-1` at line 55 | Read | Verified |

### 10. Infrastructure path verification

- Test file path convention: `ui/src/__tests__/<mirror>` ✓ (mirrors source path)
- E2E spec path: `ui/tests/e2e/<spec>.spec.ts` ✓ (matches existing patterns like `auto-followup.spec.ts`)
- Glossary file: `ui/src/lib/glossary.ts` ✓
- Enum file: `ui/src/lib/enums.ts` ✓

### 11. Frontend data plumbing verification

- Story 3 mounts `<OvernightResultCard study={study} />` from page.tsx — `study` is the `DetailPageShell` callback prop ([page.tsx:81-82](../../../../ui/src/app/studies/[id]/page.tsx#L81-L82)). ✓
- Story 5 mounts `<StrategyLine study={study} />` inside `<LinkedEntitiesRow>` — `study` is the existing prop. ✓
- Story 4's `<WinningLinkConvergenceChip>` takes `linkId: string` (parent-narrowed) + `viewedStudy: StudyDetail` (passed from parent card). ✓
- No new prop drilling needed; all data is reachable from the existing study/chain query state.

### 12. Persistence scope consistency

N/A — no `localStorage` or `sessionStorage` usage in Phase 2 (per spec D-8).

### 13. Enumerated value contract audit

| Field | Backend values | Spec ack | Plan story | Source-of-truth comment |
|---|---|---|---|---|
| `study.config.auto_followup_strategy` | `narrow`, `follow_suggestions` (Phase 1 backend lock) | Spec §8.5 ✓ | Story 5 — imports `OVERNIGHT_STRATEGY_VALUES` from `ui/src/lib/enums.ts` | Source-of-truth comment present above `STRATEGY_DISPLAY` mapping in Story 5's key interface block |
| `StudyChainLink.selected_followup_kind` | `narrow_default`, `narrow`, `widen`, `swap_template` | Spec §8.5 ✓ | Story 2 — `pathTokenForLink` switches on these values | Source-of-truth comment present in Story 2's `chain-path-tokens.ts` |
| `StudyChainResponse.stop_reason` | `in_flight`, `no_lift`, `depth_exhausted`, `budget`, `parent_failed`, `cancelled` | Spec §8.5 ✓ | Story 1 — `CHAIN_STOP_REASON_PHRASE` module | Source-of-truth comment present in Story 1's `chain-stop-reason.ts` |
| `StudyDetail.convergence.verdict` | `converged`, `still_improving`, `too_few_trials` | Spec §8.5 ✓ | Story 4 — `<WinningLinkConvergenceChip>` switches on these values | Inline label mapping — narrow enough; the Literal source is at backend/app/domain/study/convergence.py |

All four enumerations grounded in backend source-of-truth files. No inline string literals reach the wire. ✓

### 14. Audit-event coverage audit

N/A — Phase 2 introduces no state mutation; the card and strategy line are pure read-only views. No audit-event obligation. ✓

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (or "None" justified), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e) are explicitly scoped (vitest unit + vitest component + E2E; backend layers N/A).
- [x] Documentation updates across docs/01-05 are planned (Story 6 covers ui-architecture.md + tutorial-first-study.md).
- [x] Lean refactor scope and guardrails are explicit (Story 1's mechanical extraction).
- [x] Phase/epic gates are measurable (one epic; each story's DoD is the gate).
- [x] Story-by-Story Verification Gate is included (§10).
- [x] Plan consistency review (§11) has been performed with no unresolved findings.
