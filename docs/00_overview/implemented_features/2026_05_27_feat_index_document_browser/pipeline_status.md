# Pipeline Status — Index Document Browser

## Idea
- Status: Complete
- File: [idea.md](idea.md)
- Last patched: 2026-05-27 (Audit & Patch via `/idea-preflight`; 9 decisions locked D-1..D-9; IA section with route hierarchy table added)

## Spec
- Status: Approved
- Date: 2026-05-27
- File: [feature_spec.md](feature_spec.md) (925 lines)
- Cross-model review: GPT-5.5 passed (3 cycles — 13 + 11 + 9 = 33 findings, all 33 accepted; cycle 3 hit max-3 ceiling with no unresolved disagreements)
- Phases: 1 (single-phase per D-10; deferred surfaces tracked in sibling folders)
- FRs: 12 (5 backend + 5 frontend + 1 cursor encoding + 1 convention deviation)
- ACs: 20 (AC-1 through AC-20)
- Decisions logged: 28 (D-1..D-9 from idea + D-10..D-28 from spec)

## Plan
- Status: Approved
- Date: 2026-05-27
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: GPT-5.5 passed (3 cycles — 11 + 10 + 6 = 27 findings, 26 accepted + 1 rejected with cited counter-evidence; cycle 3 hit max-3 ceiling with 0 High findings remaining)
- Stories: 13 (across 3 epics — Adapter Protocol, Backend endpoints, Frontend UI)
  - Epic 1: 3 stories (Protocol additions + 2 ElasticAdapter impls)
  - Epic 2: 4 stories (helpers module + list endpoint + detail endpoint + studies `?target=` filter)
  - Epic 3: 6 stories (Indices card + summary page + list page + detail page + LinkedEntitiesRow/filter-chip + E2E)
- Branch: `feat/index-document-browser`
- Phases covered: 1 (all FRs in this plan)

## Implementation
- Status: **Complete (PR #285, merged 2026-05-27 as squash `7a5bc42`)**
- Branch: `feat/index-document-browser` (deleted post-merge)
- Completed stories: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
- Tests added: backend unit 1537 ✓ (incl. 39 helper-module tests + 24 adapter tests + Story 2.1 helpers); 21 integration tests at `test_documents_endpoints.py` (16 stub-adapter + 5 live-ES); 6 integration at `test_studies_target_filter.py`; 12 contract tests at `test_documents_contract.py`; frontend 904 vitest ✓ (incl. 23 new across 5 component/page tests); 2 E2E specs (top-down + filter chip).
- Adapter sort key flipped from `_id` → `_doc` per spec D-26 fallback after ES 9 returned HTTP 400 with `indices.id_field_data.enabled` disabled; documented in adapter docstring.
- Validation order swapped (parse_fields_csv + decode_documents_cursor before get_cluster) so malformed query strings always return 422 regardless of cluster_id validity.
- Glossary grew by 5 keys (`cluster.indices_card`, `cluster.target_doc_count`, `target.schema`, `target.schema_analyzer`, `document.truncation_sentinel`).
- 4 new frontend routes registered: `/clusters/[id]/indices/[name]`, `.../documents`, `.../documents/[...doc_id]`, plus the existing `/studies` page extended.

## Done
- Status: **Yes** — merged 2026-05-27 (PR #285, squash `7a5bc42`)
- Cross-model review cycles: GPT-5.5 spec (3 cycles, 33 findings) + GPT-5.5 plan (3 cycles, 27 findings) + Gemini PR (1 cycle, 5 findings: 3 accepted + 2 rejected) + GPT-5.5 final (1 cycle, 6 findings: 1 accepted + 1 rejected + 4 deferred as non-regression follow-ups).
