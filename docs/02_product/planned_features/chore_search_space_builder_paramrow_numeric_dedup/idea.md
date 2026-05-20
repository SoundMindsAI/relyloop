# De-duplicate `ParamRow`'s float-vs-int onChange branches

**Date:** 2026-05-20
**Status:** Idea — surfaced during `feat_create_study_search_space_builder` Story 2.1 implementation (post-impl tangential-observations sweep, 2026-05-20).
**Origin:** [`ui/src/components/studies/search-space-builder/param-row.tsx`](../../../../ui/src/components/studies/search-space-builder/param-row.tsx) — the `<RowNumeric>` onChange wrapper renders two structurally identical branches (one for `spec.type === 'float'`, one for `'int'`), differing only in the discriminator. The branches were kept apart for TypeScript narrowing safety during the original implementation.
**Depends on:** [`feat_create_study_search_space_builder`](../feat_create_study_search_space_builder/) — wait until the feature merges before refactoring.

## Problem

The two branches inside `<ParamRow>`'s `<RowNumeric onChange>` callback look like this:

```ts
onChange={(next) => {
  if (spec.type === 'float') {
    onSpecChange(paramName, {
      ...spec,
      low: next.low ?? spec.low,
      high: next.high ?? spec.high,
    });
  } else {
    onSpecChange(paramName, {
      ...spec,
      low: next.low ?? spec.low,
      high: next.high ?? spec.high,
    });
  }
}}
```

Structurally identical; differ only because TypeScript narrows `spec.type` differently in each branch. Could be collapsed to a single statement using the underlying `FloatParam | IntParam` union type — TS should be able to prove the spread is type-safe with a small helper.

## Proposed capabilities

- Extract a `mergeNumericSpec(spec, next)` helper that narrows on `spec.type` once and returns the merged spec.
- Apply across both float and int rows; remove the if/else.
- Possibly the same pattern applies if `Story 2.2`'s log toggle becomes a third numeric mutation — refactor opportunistically.

## Scope signals

- **Backend:** N/A.
- **Frontend:** ~10-line refactor inside `param-row.tsx`. No new files. No new tests required — the existing `create-study-modal.builder-edits.test.tsx` assertions cover the behavior.
- **Migration:** N/A.

## Why not implemented inline today

The branches were left side-by-side for clarity during the feature implementation — kept the type narrowing obvious for the next reader. Refactoring into a helper is a low-priority code-quality task that has no impact on user-visible behavior. Fits the rubric's "implement later when the surrounding area is touched again" disposition.

## Relationship to other work

- **Builds on** [`feat_create_study_search_space_builder`](../feat_create_study_search_space_builder/) — refactor target.
- **Independent of** all other in-flight work.
