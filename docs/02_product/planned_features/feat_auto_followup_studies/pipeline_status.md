# Pipeline Status — Auto-Followup Studies

## Idea
- Status: Complete
- File: [`idea.md`](idea.md)
- Preflight audit: 2026-05-23 (49 insertions / 18 deletions; 6 Open questions locked at spec time)

## Spec
- Status: Approved (auto-mode pipeline; no operator review pause per `/pipeline --auto`)
- Date: 2026-05-23
- File: [`feature_spec.md`](feature_spec.md)
- Cross-model review: GPT-5.5 passed (3 cycles — max-cycle convergence)
  - Cycle 1: 1 High finding (depth=0 inconsistency across FR-1 / FR-3 / AC-5) — accepted, patched across FR-1, §8.4, §8.5, AC-2, §14.
  - Cycle 2: 10 findings (2 High, 8 Medium) — all accepted, patched across digest trigger, idempotency design, event catalog, AC-6 lock, repo signature, cost-model citation, cancel-callers inventory, Pydantic coercion. D-10 through D-13 added.
  - Cycle 3: 6 findings (3 High, 3 Medium) — all accepted, patched (dangling references from cycle-2 patches: API convention check still said "no new endpoints"; §2/§4/§8.3/§9 still encoded `1..5` validator; §6 still said "6 events"; FR-3 missing the layer-2 backstop step; §11 edge flow still said failed-parent emits telemetry; §11 primary flow miscounted chain depth).
- Phases: 1 of 1 (single-phase delivery — Tier A + Tier B ship together per §3 Phase boundaries)
- FRs: 12 (FR-1 through FR-12)
- ACs: 13 (AC-1 through AC-13)
- Telemetry events: 8 (FR-9 authoritative catalog)

## Plan
- Status: Not started

## Implementation
- Status: Not started

## Notes
- This feature uses an existing column (`studies.parent_study_id` self-FK from `feat_study_lifecycle` Phase 1 migration 0003) for the first time. **No schema migration is needed.**
- Soft dependency: `feat_study_baseline_trial` (idea-stage). The spec ships with FR-2a (lift-over-first-decile gate) and switches to FR-2b (lift-over-baseline) via a one-line change in `evaluate_chain_gate` when the dependency lands. Tracked in D-3.
- Single-tenant MVP1 — no auth, no audit_log (MVP2 catalog entries pre-shaped per §6).
