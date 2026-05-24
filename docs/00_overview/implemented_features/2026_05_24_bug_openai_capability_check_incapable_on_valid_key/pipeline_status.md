# Pipeline Status — bug_openai_capability_check_incapable_on_valid_key

## Idea
- Status: Complete
- File: idea.md
- Origin: surfaced 2026-05-24 during PR #232 smoke-cascade unblock. P1 (blocks smoke pytest).

## Spec
- Status: Approved
- Date: 2026-05-24
- File: feature_spec.md
- Cross-model review: GPT-5.5 — 3 cycles to convergence (8 findings cycle 1, 3 findings cycle 2, 2 findings cycle 3; all accepted except cycle-1 B4 which was rejected with cited counter-evidence)
- Phases: 1 (single-phase observability fix — no deferred phases)
- Key decisions:
  - D-1: cache-miss `models_endpoint` value is `"untested"` (response model only)
  - D-2: cached `CapabilityResult.models_endpoint` schema **NOT** widened — stays `Literal["ok", "fail"]`
  - D-3 + D-8: `models_endpoint_status_code` is required-but-nullable (`int | None = Field(...)`, no default)
  - D-4: `_probe_models_endpoint` exact return contract — `tuple[bool, int | None]`
  - D-5: AC-10 security regression test against 401-body redaction is required
  - D-6 + D-9: CI diagnostic surface is `smoke-logs.txt` artifact ([`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445)), NOT the wait-loop failure curl

## Plan
- Status: Approved
- Date: 2026-05-24
- File: implementation_plan.md
- Cross-model review: GPT-5.5 — 3 cycles (6 findings cycle 1, 8 findings cycle 2, 3 findings cycle 3; all 17 accepted and applied). Cycle cap reached at convergence.
- Stories: 4 (Story 1.1 add CapabilityResult field, Story 1.2 update probe + cache-layer tests, Story 1.3 surface in /healthz + endpoint-layer tests, Story 1.4 docs)
- Test coverage: 15 new/updated cases across 4 test files (7 probe + 5 health + 1 probes-defensive + 2 contract)
- Phases covered: single phase (no deferred phases)

## Implementation
- Status: Complete
- Date: 2026-05-24
- PR: [#234](https://github.com/SoundMindsAI/relyloop/pull/234) (squash-merged as `d69189db`, admin-merged)
- CI in-scope jobs: all green (backend lint+typecheck+tests+coverage, frontend lint+typecheck+tests+build, docker buildx, fast-lane unit)
- CI smoke gate: pre-existing failure from [`bug_demo_clusters_unreachable_in_healthz`](../../planned_features/bug_demo_clusters_unreachable_in_healthz/idea.md) (same failure on `main` at commits `791642e0` + `ad6ff826`; admin-merge precedent set by PR #232 + PR #228). Out of scope for this PR.
- Stories completed: 4/4 (1.1 CapabilityResult field + 1.2 probe refactor + cache-layer tests + 1.3 /healthz response + endpoint tests + contract tests + 1.4 architecture doc)
- Tests: +15 new/updated cases across 4 test files (7 in test_capability_check.py + 5 in test_health.py + 1 in test_probes.py + 2 in test_health_contract.py)
- Phase-gate review: GPT-5.5 — 3 findings (F1 Medium + F3 Low accepted in commit `3a40ec1a`; F2 Low rejected with counter-evidence — dashboard regen is the auto-run pre-commit hook)
- Final cross-model review: GPT-5.5 — 1 Low finding (test-helper type hints) deferred as non-regression follow-up (matches existing file convention; `make typecheck` is green)
- Gemini Code Assist: clean review, zero line-level findings

## Branch
- `bug/openai-capability-check-models-endpoint-observability` (deleted post-merge)
