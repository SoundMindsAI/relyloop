# Spec drift — `feat_llm_judgments` §8.5 missing UNKNOWN_MODEL_PRICING + §FR-5 calibration ordering note

**Date:** 2026-05-11
**Status:** Idea — spec drift surfaced during GPT-5.5 cycle 2 review
**Origin:** `docs/02_product/planned_features/feat_llm_judgments/implementation_plan.md` cycle-2-derived follow-up artifacts (§Appendix)
**Depends on:** None

## Problem

Two corrections to the merged `feat_llm_judgments/feature_spec.md` that surfaced during plan review:

1. **§8.5 missing `UNKNOWN_MODEL_PRICING` (503).** GPT-5.5 cycle 2 F4 surfaced that returning `0.0` from `cost_model.compute_call_cost` on an unrecognized model silently defeats the daily budget gate. The plan added `UnknownModelPricingError` to `cost_model.py` and a new 503 `UNKNOWN_MODEL_PRICING` preflight code at `POST /judgments/generate`. The contract test asserts the code is reachable. The spec catalog should reflect it.

2. **§FR-5 missing "run calibration before overrides" guidance.** GPT-5.5 cycle 1 F12 + F13 surfaced that the calibration endpoint filters pairs to `source='llm'` — a list that's been heavily overridden first will likely return `INSUFFICIENT_SAMPLES` after the post-match recheck. The runbook (`docs/03_runbooks/judgment-generation-debugging.md`) documents this; the spec itself doesn't.

## Proposed capabilities

### Spec patch — two edits

a. Add to `feat_llm_judgments/feature_spec.md` §8.5:

```text
| UNKNOWN_MODEL_PRICING | 503 | false | OPENAI_MODEL has no entry in backend/app/llm/cost_model.py; the daily budget gate would be silently defeated. Operator adds pricing or pins a known model |
```

b. Add a paragraph to §FR-5 after the "computes Cohen's kappa..." sentence:

```text
**Run calibration BEFORE any significant volume of human overrides.** The endpoint
filters pairs to `source='llm'` — already-overridden rows are excluded, so a list
that's been heavily overridden may return `INSUFFICIENT_SAMPLES` even if you submit
30+ samples.
```

## Scope signals

- **Backend:** none
- **Frontend:** none
- **Migration:** none
- **Config:** none
- **Audit events:** N/A

## Why deferred

Same rationale as the sibling drifts — patching against a merged feature is churn; infra-sweep PR folds this in.

## Relationship to other work

Pairs with `chore_spec_llm_judgments_endpoint_drift` + `chore_spec_llm_judgments_error_drift`. Three drift ideas can land in one PR.
