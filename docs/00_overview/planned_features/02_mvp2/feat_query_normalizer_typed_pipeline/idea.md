# feat_query_normalization_tuning — Phase 2 (typed sub-object + JS snippet + smart-quote contractions)

**Date:** 2026-05-31
**Status:** Idea — deferred Phase 2 of [`feat_query_normalization_tuning`](../feat_query_normalization_tuning/feature_spec.md) (§3 Phase boundaries, §19 D-4 / D-6 / D-7). Split into its own planned-features folder 2026-05-31 (was `feat_query_normalization_tuning/phase2_idea.md`).
**Priority:** P2 — picked up if MVP2 adoption shows the four built-in bundles are insufficient OR operators ask for a JS snippet alongside Python OR smart-quote contractions cause measurable miss-rates.
**Origin:** Phase 2 carve-out from `feature_spec.md` §3 "Phase boundaries" + decision-log entries D-4 (search-space shape), D-6 (snippet language), D-7 (smart-quote handling).
**Depends on:** Phase 1 of [`feat_query_normalization_tuning`](../feat_query_normalization_tuning/feature_spec.md) merged.

## Problem

Phase 1 ships four built-in Categorical bundles, an English-only ASCII-apostrophe contraction dictionary, and a Python-only PR-body snippet. Three follow-on capabilities are deferred until operator signal motivates them:

1. **Typed sub-object representing an ordered list of normalization steps.** Lets operators compose arbitrary step sequences (e.g., `[trim, lowercase, expand_contractions, custom_dictionary]`) instead of picking from four hard-coded bundles.
2. **JS/TypeScript reference snippet in the PR body**, in addition to Python — operators with Node/Bun-based query layers translate Python manually today.
3. **Smart-quote contractions** — Phase 1 matches only ASCII `'`; queries with U+2019 (`'`) miss expansion.

## Proposed capabilities

### Capability A — Typed `NormalizerPipelineParam` search-space type

- New discriminated-union member of `ParamSpec` in `backend/app/domain/study/search_space.py`: `NormalizerPipelineParam` with `type: Literal["normalizer_pipeline"]` and `steps: list[NormalizerStep]`.
- New domain enum `NormalizerStep`: `lowercase | trim | expand_contractions_en | expand_contractions_custom | strip_punctuation | collapse_whitespace`.
- The Optuna sampler treats it as a categorical over the powerset of `steps` (subject to the cardinality cap from §FR-1 of Phase 1's spec).
- Migration: NONE if rolled out as additive in `SearchSpace` parsing; the JSONB column shape is forward-compatible.
- The pre-render hook generalizes from "pick a named bundle" to "apply step sequence in order"; the four Phase 1 bundles become aliases the validator desugars into step sequences.

### Capability B — JS/TypeScript snippet in the PR body

- Extend `_PR_BODY_NORMALIZER_SNIPPETS` (or replace it with a per-language structure) so the PR body offers both languages.
- Add a unit test asserting the JS snippet's output matches the Python snippet's output across the same 10-input corpus from Phase 1 AC-12.
- Operator-facing tooltip near the PR body section lets the operator pick which language to copy.

### Capability C — Smart-quote contraction matching

- Extend `_CONTRACTIONS` keys (or the compiled `_PATTERN`) to match BOTH `'` (U+0027) and `'` (U+2019) at the boundary position of every entry.
- Alternative: pre-normalize smart quotes to ASCII inside `normalize` before the contraction regex runs. Either path is acceptable; the second is simpler and additive.
- Regression test: Phase 1 inputs continue to pass; new inputs with U+2019 expand identically.

### Capability D — Operator-supplied contraction dictionaries (optional within Phase 2)

- Allow the operator to attach a custom contraction dictionary at the cluster or template level (JSONB column or template-level metadata). Phase 2 may scope this in or out; recommend scoping out and adding a Phase 2.5 sub-phase if proven needed.

## Scope signals

- **Backend:** medium. New search-space type + sampler integration + Pydantic discriminator. The pre-render hook generalizes.
- **Frontend:** medium. The create-study modal's search-space builder gains a new row type for `normalizer_pipeline`; the digest advisory predicate may need updating to read step-list shape.
- **Migration:** none expected (additive JSONB shapes).
- **Config:** none.
- **Audit events:** N/A (audit_log lands at MVP3).

## Why deferred

The four built-in bundles in Phase 1 cover the operator's headline ask (lowercase + trim + contraction expansion). A typed sub-object expands the design surface significantly: new validator, new sampler integration, frontend row type. Per Phase 1 spec §3, the cost is not justified until adoption shows the bundles are insufficient. JS snippet support is similarly speculative — Phase 1's Python snippet is short enough to translate; supporting two languages doubles the test surface. Smart-quote handling is a known gap but has zero impact on operators who pre-normalize their query strings (most do).

## Relationship to other work

- Extends Phase 1 of `feat_query_normalization_tuning` (sibling folder content).
- Does not block any other planned feature.
