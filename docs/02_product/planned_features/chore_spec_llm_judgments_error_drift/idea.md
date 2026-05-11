# Spec drift — `feat_llm_judgments` §8.5 missing error codes

**Date:** 2026-05-11
**Status:** Idea — spec drift surfaced during plan generation
**Origin:** `docs/02_product/planned_features/feat_llm_judgments/implementation_plan.md` §11.2 + §11.8
**Depends on:** None

## Problem

The implemented `feat_llm_judgments/feature_spec.md` §8.5 error-code catalog lists **11 codes** but the spec body references two additional codes that the implementation correctly raises:

* `QUERY_NOT_IN_SET` — referenced in §FR-3b body text; raised by `POST /judgment-lists/import` when an item references a query outside the supplied query set.
* `LIST_NOT_READY` — referenced in §11 edge/error flows; raised by `PATCH /judgment-lists/{id}/judgments/{judgment_id}` when the list is still `status='generating'`.

The contract test (`backend/tests/contract/test_judgments_api_contract.py`) asserts both codes appear as literals in the router source. **The shipped code is correct;** the spec catalog is out of date.

## Proposed capabilities

### Spec patch — add two rows

Add to the `feature_spec.md` §8.5 error-code table:

```text
| QUERY_NOT_IN_SET    | 400 | false | POST /judgment-lists/import: a supplied judgment item references a query not in the supplied query set |
| LIST_NOT_READY      | 409 | true  | PATCH override: the parent judgment list is still status='generating'; the override would race the worker |
```

## Scope signals

- **Backend:** none
- **Frontend:** none
- **Migration:** none
- **Config:** none
- **Audit events:** N/A

## Why deferred

Same as the endpoint drift — patching now is churn against a merged feature; the next infra-sweep PR can fold this in with the sibling drift ideas.

## Relationship to other work

Pairs with `chore_spec_llm_judgments_endpoint_drift` and `chore_spec_llm_judgments_pricing_drift` — all three are edits to the same spec file.
