# chore_ubi_hybrid_template_render — hybrid LLM-fill should render the template

**Date:** 2026-05-29
**Status:** Idea — deferred from `feat_ubi_judgments` (GPT-5.5 PR #317 final-review finding #6)
**Origin:** feat_ubi_judgments PR #317 — GPT-5.5 cross-model final review flagged that the hybrid worker's LLM-fill path fetches doc bodies via `adapter.get_document(target, doc_id)` rather than rendering `current_template_id` + running `search_batch` to build the LLM context.
**Depends on:** `feat_ubi_judgments` shipped
**Priority:** P2

## Problem

The spec's hybrid contract (FR-2 + FR-3) requires `current_template_id`
for `hybrid_ubi_llm` because the LLM-fill path is meant to retrieve docs
*through the template* (same Jinja-render → `search_batch` path the
LLM-judgment worker uses). The shipped worker
(`backend/workers/judgments_ubi.py` `_make_llm_rate_callback`) instead:

* takes the `(query_id, doc_id)` set already known from UBI,
* fetches each doc body via `adapter.get_document(target, doc_id)`,
* sends `(query_text, doc_body, rubric)` to `rate_query_batch`.

This is **functionally correct** — it rates the same (query, doc) pairs
against the same rubric — but it deviates from the planned contract in
two ways:

1. The `current_template_id` is required + validated but never used by
   the worker (only the dispatcher resolves it for the FK check).
2. UBI engine I/O expands from the spec's stated `search_batch` +
   `get_schema` surface to also include `get_document` (still on the
   `SearchAdapter` Protocol — does NOT violate Absolute Rule #4 — but
   beyond the FR-1 "two-index scan" framing).

## Why deferred (not fixed inline)

* It's functionally correct as shipped — the ratings land on the right
  pairs. This is a contract-fidelity / consistency issue, not a bug.
* The template-render path is a >60-minute re-architecture of the
  LLM-fill callback: render the Jinja template per query, run
  `search_batch`, intersect with the UBI tail pair set, then build the
  doc context from the search hits instead of `get_document`. That's
  cross-cutting enough to warrant its own scoped change.
* The deviation is documented in the worker module docstring
  (`backend/workers/judgments_ubi.py` "Hybrid LLM-fill implementation
  note").

## Proposed capability

Either:

- **(a)** rework `_make_llm_rate_callback` to render `current_template_id`
  + `search_batch` for the tail pairs (aligns with the spec contract +
  keeps UBI I/O on the search surface), OR
- **(b)** formally amend the spec/API to drop the `current_template_id`
  requirement for hybrid mode and document `get_document`-based scoring
  as the intended design.

Decide (a) vs (b) at pickup — (b) is cheaper and the current behavior is
correct, but (a) matches operator expectation that "the template drives
retrieval everywhere."

## Scope signals

- Backend: `backend/workers/judgments_ubi.py` (callback) + possibly the
  request schema (if option b drops the requirement).
- Frontend: none (the dialog already collects template + rubric for hybrid).
- Migration: none.
