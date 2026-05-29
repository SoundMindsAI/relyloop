# chore_ubi_hybrid_template_render — resolve the vestigial hybrid template requirement

**Date:** 2026-05-29 (revised after analysis)
**Status:** Idea — contract decision deferred (NOT a worker bug)
**Origin:** GPT-5.5 PR #317 final-review finding #6 flagged that the hybrid
LLM-fill worker uses `adapter.get_document` rather than rendering
`current_template_id` + `search_batch`. On analysis (during the
chore_ubi_e2e_suite work), this is **not** a bug — see below.
**Depends on:** `feat_ubi_judgments` shipped
**Priority:** P3 (cosmetic contract cleanup; current behavior is correct)

## Analysis — the worker is correct as shipped

Spec FR-2 defines the hybrid `llm_rate` callback contract as **per-pair**:
it receives `[(query_id, doc_id, query_text), …]` tuples and returns
`{(query_id, doc_id): rating}`. The callback rates the EXACT sparse
`(query, doc)` pairs UBI surfaced (below `llm_fill_threshold`).

The worker's `_make_llm_rate_callback` fetches each doc body by its known
id (`adapter.get_document(target, doc_id)`) and rates it — the correct
way to satisfy a per-pair contract. A template render + `search_batch`
(spec FR-3 prose) would retrieve whatever the query *ranks*, which is NOT
the sparse pairs (they're sparse precisely because they rank low / have
little signal) — so it would rate the **wrong** docs. Implementing FR-3's
literal "retrieve via template" would be a regression, not a fix.

So GPT-5.5 #6 surfaced a **spec inconsistency**, not a worker defect:
- FR-2 (per-pair callback) is the load-bearing contract the converter,
  dialog, and agent tool are all built around.
- FR-3's "the Jinja template the LLM-fill path uses to retrieve docs per
  query" is the stale half — with the per-pair callback there's nothing
  to "retrieve."

## The only open question (a product/contract decision)

`current_template_id` is REQUIRED for `hybrid_ubi_llm` today but is
**vestigial w.r.t. retrieval** (the worker never uses it; it's kept for
lineage/provenance parity with the LLM path + FK validation). Whether to
**drop the requirement** (make it optional for hybrid; keep `rubric`
required) is a product/UX + wire-contract decision touching:
- `CreateJudgmentListFromUbiRequest` validator + `GenerateJudgmentsFromUbiArgs`
- the generate-judgments dialog (stop forcing a template for hybrid)
- the agent tool + the 3 hybrid-conditional tests + the E2E hybrid spec
- spec §FR-3 prose

Because it (a) needs a product call on the operator flow and (b) churns a
just-shipped, tested wire contract for marginal value, it stays deferred
until an operator signal asks for it. If picked up: drop the template
requirement, keep rubric required, and correct FR-3's prose to describe
per-pair `get_document` scoring.

## Scope signals

- Backend: schema validator + agent-tool validator + dispatcher FK branch.
- Frontend: dialog hybrid-mode template field (required → optional).
- Spec: FR-3 prose correction.
- Migration: none. Product decision required before pickup.
