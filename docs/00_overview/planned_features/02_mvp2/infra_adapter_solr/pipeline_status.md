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
- Status: Not started

## Implementation
- Status: Not started

## Notes for downstream skills

- **`/impl-plan-gen` inputs to highlight:**
  - The 5 cycle-3 cleanup patches resolved real consistency issues (cursorMark terminal-condition rule, bootstrap-security.sh flow, uniqueKey-at-probe-time, `unique_key_per_target` required in `engine_config` examples, `/healthz` presence rule). The plan must produce stories that implement these exact contracts.
  - Two arch-doc drift patches must land in this feature's Verification Ledger (NOT a separate PR): `mvp2-overview.md` Story A2 + A3 (`templates/solr/` → `samples/templates/solr/`) and A3 (`HTTPX_POOL_LIMITS` claim → "inline AsyncClient defaults"). Idea-preflight flagged both; this feature owns the patches.
  - Mandatory allowlist relocation: move `SUPPORTED_AUTH_KINDS` + `ALLOWED_AUTH_PER_ENGINE` from `backend/app/adapters/elastic.py` to a new `backend/app/adapters/registry.py` module before adding Solr entries. ES adapter re-exports for one release as deprecated aliases.
  - SolrCloud test coverage is intentionally cassette + mocked HTTP only (NOT live Compose) — see §19 decision log. Plan should explicitly NOT add a SolrCloud Compose profile.
- **`/impl-execute` should expect:**
  - ~10 stories mapping to `mvp2-overview.md` Workstream A1–A10.
  - Single-phase delivery; no `phase2_idea.md` to create at finalization.
  - All four test layers (unit / integration / contract / E2E) required per FR-12 + §14.
  - E2E spec `ui/tests/e2e/solr-study-end-to-end.spec.ts` runs the full Karpathy loop against a live Compose Solr (real-backend, no `page.route()` mocking per CLAUDE.md).
