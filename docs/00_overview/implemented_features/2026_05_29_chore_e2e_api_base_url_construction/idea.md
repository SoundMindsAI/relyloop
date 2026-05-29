---
name: chore-e2e-api-base-url-construction
description: e2e specs concat API_BASE + path strings; brittle if PLAYWRIGHT_API_BASE_URL is ever set with a trailing slash. Sweep 4 remaining sites to use URL constructor for symmetry with the lone PR #273 fix.
metadata:
  type: chore
---

# Chore — sweep `${API_BASE}/...` string-concat to URL constructor across e2e specs

**Date:** 2026-05-26
**Status:** Idea — surfaced during Gemini Code Assist review on PR #273 (`chore_clone_narrow_bounds_full_roundtrip_e2e`).
**Priority:** P3 — defensive cleanup with no concrete bug. The default value (`'http://127.0.0.1:8000'`) and CI env (`PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8000`) both lack trailing slashes, so the latent footgun hasn't fired. Worth filing for the next infra-sweep agent.
**Depends on:** None.

## Origin

Gemini Code Assist flagged the string-concat pattern at [`ui/tests/e2e/study-clone-narrow-bounds.spec.ts:135`](../../../../../ui/tests/e2e/study-clone-narrow-bounds.spec.ts#L135) (the line PR #273 added) and suggested using the `URL` constructor:

```typescript
// before
await request.get(`${API_BASE}/api/v1/studies/${created.id}`);
// after
await request.get(new URL(`/api/v1/studies/${created.id}`, API_BASE).toString());
```

PR #273 accepted Gemini's finding for the one line it flagged but explicitly chose NOT to expand the fix to the other 4 sibling sites — same loose pattern lives across 3 spec files (`grep -n "API_BASE}" ui/tests/e2e/*.spec.ts`). Tightening just-one-of-four creates inconsistency; tightening only the 2 in this PR's diff (study-clone.spec.ts:40,91) would still leave 2 in followup_run.spec.ts:92,176. A focused sweep PR is the cleaner shape.

## Problem

> **Scope correction (2026-05-29, idea-preflight before implementation):** when this idea was filed (2026-05-26) the pattern lived at 5 sites in 3 specs. Between then and pickup, additional e2e specs landed with the same `${API_BASE}/...` convention. The actual sweep at implementation time was **28 sites across 10 spec files** — not the 4-sites/2-files the table below describes. The originally-cited table is preserved for historical context; the real coverage is in "Resolution" at the bottom. The idea's core rationale ("tightening one-of-N creates inconsistency") only strengthened with the larger N, so the full sweep was the right call.

The e2e specs concatenate `API_BASE` with a path string (original 2026-05-26 census):

| File | Line | Code |
|---|---|---|
| `ui/tests/e2e/study-clone.spec.ts` | 40 | `await request.get(\`${API_BASE}/api/v1/studies/${sourceId}\`)` |
| `ui/tests/e2e/study-clone.spec.ts` | 91 | `await request.get(\`${API_BASE}/api/v1/studies/${created.id}\`)` |
| `ui/tests/e2e/followup_run.spec.ts` | 92 | `await request.get(\`${API_BASE}/api/v1/studies?limit=20\`)` |
| `ui/tests/e2e/followup_run.spec.ts` | 176 | `await request.get(\`${API_BASE}/api/v1/studies?limit=20\`)` |
| `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` | 135 | **Already fixed in PR #273.** |

If a future operator sets `PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8000/` (with trailing slash) in their environment, the concat produces `http://127.0.0.1:8000//api/v1/...` — which most HTTP servers tolerate but Playwright's URL parser might trip on, or an upstream proxy might reject. No CI signal yet because CI sets the var without a trailing slash. The `URL` constructor collapses the double slash regardless of whether `API_BASE` carries a trailing slash, which is the durable fix.

## Proposed fix

Mechanical replace across the 4 remaining sites:

```typescript
// before
await request.get(`${API_BASE}/api/v1/...`);
// after
await request.get(new URL('/api/v1/...', API_BASE).toString());
```

One commit, 4 line changes across 2 files. No test changes needed — the assertions exercise the same endpoint with the same behavior.

## Scope signals

- **Backend:** None.
- **Frontend:** None (e2e spec files only).
- **Migration:** None.
- **Config:** None.
- **Audit events:** None.
- **Tests:** The 4 e2e spec usages are themselves the "tests" being modified; they continue to run unchanged.

## Why deferred

The pattern is established convention across 3 spec files. Fixing one without the others creates inconsistency. PR #273's adjudication of Gemini's finding accepted the specific 1-line flag but deferred the broader sweep so the cleanup could ship as a focused PR without inflating PR #273's diff.

## Relationship to other work

- **Originating PR:** #273 (`chore_clone_narrow_bounds_full_roundtrip_e2e`) — accepted Gemini's finding for the one new line it added; this idea captures the sweep for the other sibling sites.

## Resolution

Swept all 28 `${API_BASE}<path>` concatenations to `new URL(<path>, API_BASE).toString()` across 10 e2e spec files (the 5-site/3-file census above had grown by pickup time):

`auto-followup` (3), `dashboard-reseed` (6), `followup_run` (3), `judgments` (2), `studies-create-builder` (3), `studies-create-target-dropdown` (5), `studies-create-validation` (1), `studies` (1), `study-clone` (2), `trials-data-table` (2).

All variable-path call sites were verified to pass `/`-prefixed paths, so `new URL(path, API_BASE)` is behaviorally identical. Pure single-interpolation cases (`${API_BASE}${path}`) collapse to `new URL(path, API_BASE)`; cases with a query suffix or second interpolation keep a template literal (`new URL(\`${path}?limit=200\`, API_BASE)`). No behavior change — the assertions exercise the same endpoints. `pnpm lint` + `pnpm typecheck` clean.
