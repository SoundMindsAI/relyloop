# Frontend Stack Refresh — Next 16 / React 19 / Tailwind 4 / Vitest 4

**Date:** 2026-05-09
**Status:** Idea — surfaced during dependency audit on `feature/infra-foundation`
**Origin:** Conversation 2026-05-09: dependency-currency audit comparing `ui/pnpm-lock.yaml` to npm registry latest. Backend (`uv.lock`) is fully current except `redis` (capped by `arq<6` constraint, tracked separately). Frontend is materially behind on every direct dep with a major-version delta.
**Depends on:** [`infra_foundation`](../infra_foundation/feature_spec.md) — must be merged so the placeholder UI shell exists to refresh against.

## Problem

The frontend stack landed during `infra_foundation` is already 1–2 majors behind across the board. Specifically (locked → npm latest as of 2026-05-09):

| Package | Locked | Latest | Delta |
|---|---|---|---|
| `next` | 14.2.35 | 16.2.6 | 2 majors |
| `eslint-config-next` | 14.2.35 | 16.2.6 | tracks Next |
| `react` / `react-dom` | 18.3.1 | 19.2.6 | 1 major |
| `@types/react` / `@types/react-dom` | 18.3.x | 19.2.x | tracks React |
| `tailwindcss` | 3.4.19 | 4.3.0 | 1 major |
| `vitest` | 2.1.9 | 4.1.5 | 2 majors |
| `typescript` | 5.9.3 | 6.0.3 | 1 major |
| `eslint` | 8.57.1 | 10.3.0 | 2 majors |
| `jsdom` | 25.0.1 | 29.1.1 | 4 majors |
| `@vitejs/plugin-react` | 4.7.0 | 6.0.1 | 2 majors |
| `@types/node` | 20.19.40 | 25.6.2 | tracks Node LTS — declared `^20` (Node 20 LTS still active, intentional) |

The Next 14 / React 18 pins were treated as architectural commitments in [CLAUDE.md](../../../../CLAUDE.md) and [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md), but [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) line 57 already says **"Next.js 14+"** — the `+` contemplates forward-compatibility. The architectural commitment is to the Next.js App Router pattern (still how Next 16 works), not to the major version.

The window to do this cheaply is closing fast. `infra_foundation` ships only the placeholder home page ([`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx)) — there is essentially zero React component code, zero Tailwind utility usage, and a single skeleton vitest spec. Once [`feat_studies_ui`](../feat_studies_ui/feature_spec.md) lands (the first feature with real frontend volume), the migration cost compounds across every screen built on top.

## Proposed capabilities

### Coordinated single-PR refresh of the frontend toolchain

- **Next 14 → 16.** Migrate to async `cookies()` / `headers()` / `params` (Next 15 breaking change). Verify App Router conventions still hold.
- **React 18 → 19.** Drop `forwardRef` wrappers (ref-as-prop), remove `defaultProps` from any function components, accept stricter prop validation. The surface today is one placeholder page, so this is mostly a future-proofing pass.
- **Tailwind 3 → 4.** Migrate `tailwind.config.ts` → CSS-first config via `@theme`. New Oxide engine is faster but config format changes are non-trivial — easier to do now (no utility usage) than after the design system materializes.
- **Vitest 2 → 4.** Update test runner. Single skeleton spec means near-zero migration cost.
- **TypeScript 5 → 6.** Update tsconfig as needed for new strictness defaults. Type-check-only impact.
- **eslint 8 → 10 + flat config.** `eslint-config-next` 16 ships flat-config-native; flip [`ui/.eslintrc.json`](../../../../ui/.eslintrc.json) to `eslint.config.mjs`.
- **`@vitejs/plugin-react` 4 → 6, `jsdom` 25 → 29, types refresh.** Mechanical updates that fall out of the React 19 / Vitest 4 bumps.
- **Documentation alignment.** Update [`CLAUDE.md`](../../../../CLAUDE.md) "Stack (MVP1)" line, [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) frontend table, and [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) "Adopted for MVP1" header in the same PR.

### Verification gate

- `pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all green.
- Placeholder page renders under `pnpm dev` at `127.0.0.1:3000` with no console warnings.
- CI workflow [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml) frontend job passes unmodified (already runs lint/tsc/vitest/build).

## Scope signals

- **Backend:** none — pure frontend refresh.
- **Frontend:** all of [`ui/`](../../../../ui/) — `package.json`, lock regeneration, `tailwind.config.ts` → CSS, `eslint` config flip, `tsconfig.json` review, `postcss.config.mjs` review (Tailwind 4 changes the PostCSS plugin shape).
- **Migration:** none.
- **Config:** no env-var changes. `pnpm-lock.yaml` regenerates entirely.
- **Audit events:** N/A (pre-MVP2; no state mutations).

## Why deferred

Not deferred indefinitely — **deferred only past `infra_foundation`'s merge** so the upgrade lands as its own focused PR rather than being entangled with the foundation work currently in flight. The recommended sequencing is:

1. `infra_foundation` merges (current PR).
2. `infra_frontend_stack_refresh` ships next, **before** [`feat_studies_ui`](../feat_studies_ui/feature_spec.md) starts. This is the last moment where frontend code volume is ~0.
3. All subsequent UI features ([`feat_studies_ui`](../feat_studies_ui/feature_spec.md), [`feat_proposals_ui`](../feat_proposals_ui/feature_spec.md), [`feat_chat_agent`](../feat_chat_agent/feature_spec.md), [`feat_llm_judgments`](../feat_llm_judgments/feature_spec.md)) build on the refreshed stack.

If this slips past `feat_studies_ui`, the cost stops being "update one placeholder page" and becomes "audit every component for `forwardRef`, every CSS file for v3 → v4 utility renames, every test for vitest 2 → 4 API drift."

## Relationship to other work

- **Blocks (soft):** [`feat_studies_ui`](../feat_studies_ui/feature_spec.md) — should land before this kicks off significant component work, otherwise the migration tax compounds. Not a hard dependency; `feat_studies_ui` could ship on the current stack and pay the upgrade cost later (worse outcome).
- **Sibling debt item:** `redis` 5.3.1 is capped by `arq 0.28.0`'s `redis[hiredis]<6` pin (verified via PyPI metadata). That's a genuine upstream constraint, not a refresh candidate — track separately as `infra_arq_redis_cap` if/when it becomes load-bearing.
- **No conflict** with any planned MVP1 feature — the App Router pattern, shadcn/ui, TanStack Query, React Hook Form + Zod, and Recharts conventions documented in [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) all carry forward unchanged.
