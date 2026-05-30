# Pipeline Status — infra_adapter_solr

## Idea
- Status: Complete (preflighted 2026-05-30 — `/idea-preflight` patched 12 staleness items; UBI-shipped reframe + locked template path + arch-doc drift flags)
- File: [`idea.md`](idea.md)

## Spec
- Status: Approved
- Date: 2026-05-30
- File: [`feature_spec.md`](feature_spec.md)
- Cross-model review: GPT-5.5 converged at cycle 3 (verdict "ready", 0 new High-severity findings)
  - Cycle 1: 14 findings (6 High, 7 Medium, 1 Low). 12 accepted + patched; 2 rejected with cited counter-evidence (PR #320 + feat_contextual_help both shipped per state.md / MVP2_DASHBOARD.md).
  - Cycle 2: 6 findings (1 High self-induced regression from cycle 1, 3 Medium, 2 Low). All accepted + patched.
  - Cycle 3: 5 findings (0 High, 3 Medium, 2 Low). All accepted + patched in the same cycle. Verdict "ready" — convergence.
- Phases: 1 of 1 (single-phase delivery — see §3 "Phase boundaries" for rationale; ten Workstream A stories ship atomically).
- Functional requirements: FR-1 through FR-12 + FR-12a (13 FRs total).
- Acceptance criteria: AC-1 through AC-15 (15 ACs total — 10 original + 5 added at cycle 2 for cycle-1 patch coverage).
- New endpoints: 1 (`POST /api/v1/clusters/{id}/reprobe`).
- New error codes: 1 (`LTR_MODEL_NOT_FOUND` 400).
- Protocol-shape change: 1 additive optional field (`DocumentPage.next_cursor_token: str | None`).
- Migration: 1 (extends `clusters.engine_type` + `clusters.auth_kind` CHECK constraints; sequential after current head `0021_judgment_lists_generation_params`).
- New Compose service: 1 (`solr:10.0` on `127.0.0.1:8983`).

## Plan
- Status: Approved (Ready for Execution)
- Date: 2026-05-30
- File: [`implementation_plan.md`](implementation_plan.md)
- Cross-model review: GPT-5.5 ran 3 cycles (max per CLAUDE.md). Total findings: 25 (12 High overall). 24 accepted + patched. 1 rejected with cited counter-evidence (cycle-2 C2-A4 — `ALLOWED_AUTH_PER_ENGINE["opensearch"]` excluding `opensearch_sigv4` matches existing elastic.py:79-93 reserved-kind pattern).
  - Cycle 1: 11 findings (5 High, 6 Medium). All 11 accepted + patched. Major: /reprobe error code → CREDENTIALS_INVALID; list_documents first page uses cursorMark=*; solr_host defaults to None; LTR_MODEL_NOT_FOUND covers run_query path too; search_batch uses uniqueKey not hardcoded "id".
  - Cycle 2: 9 findings (1 High + 8 lower). 8 accepted + patched. Major: health_check + list_query_parsers FULLY implemented in A1 (were stubbed); probe endpoints concretized; BasicAuth added to seed + smoke; security.json.template removed; /reprobe language "serialize safely" not "coalesce"; bare re-export (no DeprecationWarning).
  - Cycle 3: 5 findings (1 High + 4 lower). All 5 accepted + patched in-cycle (no cycle 4 per max-3 rule). Major: A10 adds checked-in Solr configset (`docker/solr/configsets/relyloop_products` + `relyloop_ubi`) so `make up` brings up Solr with `solr.UBIComponent` + LTR module pre-enabled — closes AC-1/AC-6/AC-7 capability gap.
- Stories: **13 total** in single epic (A1–A13). Workstream A skeleton (A1–A10) + A8 (document-browser) + A9 (/reprobe + /test-connection) + A13 (Solr demo scenario). Expanded 2026-05-30 per operator UX/demo/guide review (see below).
- Phases covered: 1 of 1 (single-phase delivery per spec §3).
- Test layers planned: unit (10 backend + 3 frontend), integration (15 files), contract (6 file extensions/new), E2E (1 new spec + Guide 01 spec extension).

### 2026-05-30 scope expansion (operator-requested)

After a parallel codebase audit of the demo, guide, and cluster-registration-UX systems, the operator directed adding cross-engine improvements the original adapter-focused plan under-scoped:
- **A13 (new):** Solr demo scenario in the home-button reseed (5th scenario; the demo system is already engine-aware — `news` runs on OpenSearch).
- **A12 (expanded):** extend the existing 3-engine Guide 01 walkthrough (not a separate Solr guide).
- **A11 (expanded + 2 plan-accuracy bugs fixed):** per-engine auth filtering, a 3-engine `<EngineBadge>` (none exists today), wire source-of-truth corrected to `schemas.py`. The audit found the form does NOT filter auth by engine today and no badge component exists.
- **A9 (expanded):** new `POST /clusters/test-connection` endpoint (probe without persist) powering A11's pre-submit connection-test button.
- Focused GPT-5.5 delta review: 5 findings (4 Medium + 1 Low), all accepted + patched. Full history in spec §19 decision log.

## Implementation
- Status: Not started

## Notes for downstream skills

- **`/impl-execute` should expect:**
  - 13 stories (A1–A13). A6 (registry relocation) ships first as the foundation; A1 (adapter skeleton + probe + health_check + list_query_parsers) ships next; A2–A8 fill in the per-method adapter implementations; A9–A11 add the endpoints + frontend; A12 (guide/docs/E2E) + A13 (demo) are genuinely last (they exercise the fully-assembled feature).
  - Single-phase delivery; no `phase2_idea.md` to create at finalization.
  - All four test layers required per §3 / §14.
  - E2E spec `ui/tests/e2e/solr-study-end-to-end.spec.ts` runs the full Karpathy loop against the live Compose Solr (real-backend, no `page.route()` mocking per CLAUDE.md E2E Testing Rules).
  - **Verification Ledger items** (NOT separate PRs): three arch-doc patches land with the feature — `mvp2-overview.md` Story A2 + Story A3 row (`templates/solr/` → `samples/templates/solr/`); Story A3 prose (`HTTPX_POOL_LIMITS` → "inline `httpx.AsyncClient` defaults"); plus `adapters.md` §"SolrAdapter (MVP2)" rewrite from forward-reference to past-tense (Story A12 owns).
  - **Mandatory allowlist relocation** lands in A6 (foundational, before any A1 adapter code that imports from `registry.py`).
  - **SolrCloud coverage is cassette + mocked HTTP only** — do NOT add a SolrCloud Compose profile; the maintainer re-records cassettes per the runbook procedure.
