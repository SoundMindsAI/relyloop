# Tutorial template `<field>_boost` param names produce wrong-range auto-fill

**Date:** 2026-05-19
**Status:** Idea — surfaced during chore_create_study_wizard_polish implementation
**Origin:** [`samples/templates/product_search.j2`](../../../../samples/templates/product_search.j2) declares params `title_boost`, `description_boost`, `bullet_points_boost`. The new Step-4 auto-fill heuristic at [`ui/src/lib/search-space-defaults.ts`](../../../../ui/src/lib/search-space-defaults.ts) only matches names starting with `field_boost` or `boost_` (prefix) — `<field>_boost` (suffix) falls through to the simple-form `'float'` default which produces `{type: 'float', low: 0.0, high: 1.0}`. The template's own header comment says the params should range `0.5–10` (log-uniform), and that's what the chat-agent path produces.
**Depends on:** [`chore_create_study_wizard_polish`](../chore_create_study_wizard_polish/) (this is the merging chore; the bug is only visible once auto-fill ships)

## Problem

A tutorial user following [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 8 ("Open `/chat` and ask the agent to tune") gets the canonical `0.5–10` log-uniform range — because the chat agent's `propose_search_space` tool emits its own ParamSpec dict that ignores the heuristic. But a user who picks the same template via the **manual wizard** ("Create study" on `/studies`) lands on Step 4 with auto-fill output `{params: {title_boost: {type: 'float', low: 0, high: 1}, ...}}` — the wrong range. The two code paths drift, the tutorial table is inaccurate for the manual path, and users get confusing first-study results.

## Proposed capabilities

### Option A — Extend the heuristic to match `<field>_boost` suffix

- Add a rule to `HEURISTIC_RULES` in `search-space-defaults.ts`:
  `{ match: /^.+_boost$/, spec: { type: 'float', low: 0.5, high: 10.0, log: true } }`
- Order it before `*_weight` so the `_weight` regex doesn't claim names ending in `_boost`.
- Add a unit test in `search-space-defaults.test.ts` asserting the new rule.
- Risk: false positives on names that happen to end in `_boost` but aren't intended as multiplicative boost factors (very unlikely in ES/OpenSearch query DSL conventions).

### Option B — Rename the tutorial template's params

- Rewrite `samples/templates/product_search.j2` to use `boost_title`, `boost_description`, `boost_bullet_points` (prefix instead of suffix).
- Update the same params in [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 7's declared-params table.
- Update the chat-agent's expected propose_search_space output (if it hardcodes the names anywhere).

Option A is preferred — `<field>_boost` is at least as common as `boost_<field>` in real-world ES query templates, and extending the heuristic helps every operator-authored template, not just the tutorial's.

## Scope signals

- **Backend:** none (heuristic is frontend-only).
- **Frontend:** 1 regex addition + 1 unit test case (≈ 5 LOC + 5 LOC test).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (MVP1 — no audit_log yet).

## Why deferred

Surfaced after `chore_create_study_wizard_polish` PR was already drafted; rolling it in would mix the heuristic decision (locked at the spec phase per spec §19) with the tutorial-template fix. Cleaner as a follow-up so the chore PR is reviewable in isolation. The bug only affects users who use the manual wizard with the demo template — the documented happy path is the chat agent, which is unaffected.

## Relationship to other work

- Originating chore: [`chore_create_study_wizard_polish`](../chore_create_study_wizard_polish/)
- Related: [`chore_template_library_expansion`](../chore_template_library_expansion/) (idea) — if the heuristic is broadened, downstream templates in the library should be re-audited against the new rules.
