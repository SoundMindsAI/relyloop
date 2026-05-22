# chore_e2e_seed_acme_helper_dead

**Date:** 2026-05-21
**Status:** Idea — surfaced during `chore_e2e_test_rows_isolation` Story 1.2 coverage audit
**Priority:** Backlog
**Origin:** Surfaced by [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md) — the §3.4 DoD audit found `seedAcmeProductsChain` at [`ui/tests/e2e/helpers/seed.ts:378`](../../../../ui/tests/e2e/helpers/seed.ts) has zero Playwright spec callers in `ui/tests/e2e/*.spec.ts`.
**Depends on:** None.

## Problem

`seedAcmeProductsChain` is a 140-line helper that constructs a cluster +
query_set + template + judgment_list + study + optional proposal/digest
chain "Acme Products" demo scenario. The function is correctly
instrumented (every resource it creates is appended to the JSONL cleanup
registry), but **no Playwright spec actually calls it**. It is dead code
on the E2E test surface.

The plan's §3.4 DoD treated this as a coverage gap but the helper itself
is structurally correct — the cleanup pipeline isn't at risk. The gap is
that the helper contributes nothing to the test surface today.

## Proposed capabilities

Pick one of two paths:

### Path A — Delete the helper

Drop `seedAcmeProductsChain` + its return type `AcmeProductsChainSeed`
from `ui/tests/e2e/helpers/seed.ts`. Roughly 140 LOC out, no imports to
fix anywhere else.

### Path B — Wire a spec that uses it

If the "complete pre-seeded demo cluster" scenario is genuinely
valuable for some future spec (e.g., a tutorial / first-run E2E spec
that exercises a full chain without each spec re-seeding the parts),
add a single `ui/tests/e2e/acme-demo-chain.spec.ts` that calls the
helper once + asserts the resulting `/studies/[id]` page renders. That
gives the helper a caller and shores up the "full chain" surface.

## Scope signals

- **Backend:** None.
- **Frontend:** `ui/tests/e2e/helpers/seed.ts` only (Path A) OR one new
  spec file (Path B).
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A — test infrastructure.

## Why deferred

The helper is harmless dead code. The cleanup-registry coverage audit
caught it but the right disposition (delete vs. wire) needs a
deliberate product call rather than an inline decision during a
larger feature ship. Captured here so the next infra-sweep agent
can either delete it (probably correct) or wire a spec (if there's
ongoing demand for a turnkey demo chain).

## Relationship to other work

- Surfaced during [`chore_e2e_test_rows_isolation`](../chore_e2e_test_rows_isolation/feature_spec.md) Story 1.2 audit.
- No other planned feature depends on this helper.
