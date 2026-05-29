# chore_ubi_docs_followup — UBI Stories 5.1 + 5.2 deferred sub-scope

**Date:** 2026-05-29
**Status:** Idea — deferred from `feat_ubi_judgments` Story 5.1 sub-scope
**Origin:** feat_ubi_judgments PR (Story 5.1 shipped the runbook + 3 FAQ entries + data-model patches; the tutorial Step 7 + spec patches + minor architecture-doc one-liners were deferred to keep the PR scope bounded)
**Depends on:** `feat_ubi_judgments` shipped
**Priority:** P2

## Problem

`feat_ubi_judgments` Story 5.1 was scoped to 10 doc artifacts in the
implementation plan. The shipped PR delivered the highest-operator-value
subset:

- ✅ `docs/03_runbooks/ubi-judgment-generation.md` (new runbook)
- ✅ 3 FAQ entries (`do-i-need-ubi`, `trust-ubi-over-llm`, `cluster-no-ubi`)
- ✅ `docs/01_architecture/data-model.md` patches (judgment_lists +
  judgments tables — generation_params column + source CHECK note)

The remaining 7 doc artifacts are deferred:

- `docs/08_guides/tutorial-first-study.md` — Step 7 "Upgrade your
  judgment list to UBI"
- `docs/00_overview/relyloop-spec.md` — §706 / §724 / §14 patches
- `docs/01_architecture/api-conventions.md` — one-line addition for the
  generate-from-ubi endpoint
- `docs/01_architecture/adapters.md` — (already had the UBI-on-Solr
  note from the Solr adapter section; verify completeness)
- `docs/01_architecture/llm-orchestration.md` — "Hybrid UBI + LLM fill"
  subsection
- `docs/04_security/llm-data-flow.md` — "Hybrid UBI + LLM fill"
  subsection
- `docs/05_quality/testing.md` — note the no-cluster-writes integration
  test pattern

## Proposed capabilities

Ship each artifact as a small focused doc-only PR:

1. **Tutorial Step 7** — operator walks through the dialog with method
   = hybrid_ubi_llm on a seeded UBI cluster; surfaces the value-delta
   card.
2. **Umbrella spec patches** — three one-paragraph touches in
   `relyloop-spec.md`.
3. **Architecture-doc one-liners** — each <10 lines, cross-link to the
   shipped feature folder.
4. **Security doc subsection** — what data leaves the cluster on a
   hybrid LLM-fill call (mirrors the existing LLM-judgment subsection).

## Scope signals

- Backend: zero changes.
- Frontend: zero changes.
- Migration: none.
- Config: none.

## Why deferred

Story 5.1 had 10 doc files in scope; the highest-operator-value 3 shipped
in the main UBI PR to keep its size reviewable (~1700 LOC bundled across
all 11 shipped stories). The remaining 7 are independent and can ship as
a follow-up doc-only PR after the main UBI PR merges. None of them
block the UBI feature from working.
