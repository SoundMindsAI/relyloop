# Spec drift — `feat_llm_judgments` §8.1 missing import endpoint

**Date:** 2026-05-11
**Status:** Idea — spec drift surfaced during plan generation
**Origin:** `docs/02_product/planned_features/feat_llm_judgments/implementation_plan.md` §11.1 + §11.8
**Depends on:** None

## Problem

The implemented_features-archived `feat_llm_judgments/feature_spec.md` enumerates **6 endpoints** in §8.1 but the spec body's FR-3b describes a **7th** endpoint (`POST /api/v1/judgment-lists/import`) used by the tutorial's no-OpenAI first-run flow.

The implementation plan recognized this drift and shipped all 7 endpoints in Stories 3.1–3.5 (the import endpoint is in Story 3.2). The contract test asserts all 7 are registered in the OpenAPI schema. **The shipped code is correct;** the spec is out of date.

## Proposed capabilities

### Spec patch — single edit

Add a row to `feat_llm_judgments/feature_spec.md` §8.1 endpoint table:

```text
| POST /api/v1/judgment-lists/import | 201 JudgmentListDetail | Tutorial path; no OpenAI |
```

And cross-reference FR-3b from §8.1's introductory paragraph.

## Scope signals

- **Backend:** none
- **Frontend:** none
- **Migration:** none
- **Config:** none
- **Audit events:** N/A — MVP1 has no audit_log

## Why deferred

The spec content was authored before the import path was added during plan review. Patching it now would be churn against an already-merged feature; the next infra-sweep PR can fold this in.

## Relationship to other work

Pairs with [`chore_spec_llm_judgments_error_drift`](../chore_spec_llm_judgments_error_drift/idea.md) (the §8.5 catalog drift) and [`chore_spec_llm_judgments_pricing_drift`](../chore_spec_llm_judgments_pricing_drift/idea.md) (UNKNOWN_MODEL_PRICING + calibration "run before overrides" guidance). All three are mechanical edits to the same spec file and could land in one PR.
