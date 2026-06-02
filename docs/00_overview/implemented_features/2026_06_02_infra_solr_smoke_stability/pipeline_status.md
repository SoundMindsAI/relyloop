# Pipeline Status — infra_solr_smoke_stability

**Release:** mvp2

## Idea
- Status: Complete
- File: idea.md (preflighted 2026-06-01, 5 patches applied via /idea-preflight before /pipeline)

## Spec
- Status: Approved
- Date: 2026-06-01
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (3 cycles — 15 → 16 → 10 findings, all accepted + resolved).
- Phases: 1 (single-phase; Levers 2 + 3 + memory-pressure documented as runbook escalation paths per D-4).
- Decisions: D-1 through D-7 (D-7 added inline during PR #383 implementation when the Solr filesystem-permissions failure mode surfaced; the spec's lever cascade never anticipated it).

## Plan
- Status: Approved
- Date: 2026-06-01
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (3 cycles — 13 → 10 → 6 findings, all accepted + resolved). Cycle 3 caught Story 2.3 chicken-and-egg → restructured into 2.3a (pre-merge final CI verification + red→green cleanup) + 2.3b (post-merge state.md follow-up PR matching PR #368 pattern).
- Stories: 7 total across 2 epics — 6 in the feature PR + 1 in the state.md follow-up PR (this one).

## Implementation
- Status: Complete (PR #383 squash-merged d32b9714 on 2026-06-02; smoke RED at merge per D-6 fast-lane posture)
- Date: 2026-06-02
- PR: https://github.com/SoundMindsAI/relyloop/pull/383
- Squash SHA: d32b9714
- Commits on feature branch (6 commits + 1 follow-up + 1 timeout-bump):
  1. f49c94b6 — planning artifacts (idea preflight + spec + plan + pipeline_status + dashboards)
  2. 53665637 — Story 1.1: failure-diagnostics fold-in (FR-1 — solr + opensearch + docker inspect)
  3. d2103a31 — Story 1.2: Lever 1 heap-cap (FR-2 — SOLR_HEAP_SIZE step-env + COMPOSE_PROJECT_NAME job-env)
  4. 707f7ea7 — Story 2.1: runbook smoke-solr-stability.md
  5. 3396f0c8 — Story 2.2: CLAUDE.md Key Runbooks row
  6. a5a3c54b — Lever 0 inline fix (filesystem permissions — mkdir + chown before make up; D-7)
  7. 6ee7c288 — beforeAll 30s timeout fix in demo-ubi.spec.ts (Solr unblocking added scenario work)
  8. 2f560455 — job timeout-minutes 15 → 25
  9. 09fd9e30 — follow-up idea: infra_smoke_reseed_runtime_budget (FR-3 / D-6 forcing function)
- CI: backend + frontend + static-checks (both) + docker buildx (both) + backend fast lane + license-headers + license-inventory + DCO + gitleaks + secrets-defense ALL GREEN. Smoke RED at 25m18s — Playwright demo-ubi reseed exceeds the 25-min job cap (captured as follow-up).
- Cross-model: spec GPT-5.5 3 cycles + plan GPT-5.5 3 cycles. No Gemini findings (the docs branch's CLAUDE.md update was a separate PR #384, not part of this feature).
- Tests: N/A (infra-only — no backend/frontend/db/E2E tests in plan). Verification routed through AC-3 (local default unchanged), AC-4 (workflow env interpolation), AC-5 (runbook + CLAUDE.md row).
- Inline tangential fixes during CI iteration (canonical "implement-over-defer" example):
  - Lever 0 (filesystem permissions) — Solr container crashed in 542ms; fixed inline with 3-line YAML edit.
  - beforeAll 30s timeout — Playwright hook timeout (independent of describe-block setTimeout); fixed inline.
  - timeout-minutes 15→25 — job-level cap; fixed inline.
- Follow-up filed BEFORE merge per FR-3 forcing function: infra_smoke_reseed_runtime_budget (linked from PR body).
- Tangential observations sweep: none additional found beyond the three inline fixes above and the captured follow-up.
