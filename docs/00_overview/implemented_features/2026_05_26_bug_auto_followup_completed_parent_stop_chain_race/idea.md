# Bug — `auto_followup` cascade race with pending followup-enqueue Arq job on completed parents

**Date:** 2026-05-23 (folder renamed `chore_` → `bug_` on 2026-05-26 per `/idea-preflight` audit — operator-visible behavior makes this bug-shaped, not chore-shaped per [feature_templates/README.md](../feature_templates/README.md))
**Status:** Idea — surfaced during the Epic 1+2 phase-gate GPT-5.5 review of `feat_auto_followup_studies` (cumulative-diff review finding F2, accepted in part as a future-work capture)
**Priority:** P2 — small race window, recoverable by manual cancel; not blocking MVP1 ship
**Origin:** [`feat_auto_followup_studies/implementation_plan.md` §9 Execution tracker — Epic 2 phase gate](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/implementation_plan.md), GPT-5.5 phase-gate finding F2

## Problem

The cycle-3 C3-1 cascade-cancel design tolerates terminal parents (cascade traverses through `completed` intermediates to reach in-flight descendants). But the FR-1 digest trigger fires `enqueue_followup_study` via Arq at the moment a study transitions to `completed`. There's a race window between:

1. Parent's digest worker enqueues `enqueue_followup_study(parent_id)` via Arq (deterministic `_job_id`).
2. Operator opens parent's detail page and clicks "Stop chain" (cascade-cancel).
3. Cascade-cancel completes — but the parent is `completed` so the cascade traverses + logs `auto_followup_cancel_terminal_parent`, finds no children (the followup worker hasn't fired yet), and returns.
4. Arq worker picks up `enqueue_followup_study(parent_id)` — loads parent (still `completed`) — gate passes (parent.best_metric set, depth > 0, lift > epsilon) — creates child.

Outcome: operator sees a chain they thought they stopped. Race window: ~Arq poll cycle (typically <2s) up to a few minutes if Arq backlog. The cascade can't see the not-yet-fired enqueue; the worker can't see a not-yet-existing chain-stop marker.

## Why this slipped through Epic 1+2 reviews

The plan's D-11 explicitly deferred the layer-2 idempotency race to MVP2 hardening (per `chore_auto_followup_parent_advisory_lock`). The completed-parent stop-chain race is a different but related race that the plan didn't anticipate — the cycle-3 redesign focused on making the cascade *correct* (traverse through terminal intermediates), not on coordinating with the pending Arq job. The GPT-5.5 phase-gate review caught it post-implementation.

## Proposed capabilities (rough sketch — needs spec-level design)

Three plausible directions, ordered by ship cost:

### Option A — Cascade mutates `parent.config.auto_followup_depth = 0` (smallest)

When `cancel_study_with_chain_cascade(parent)` is called on a `completed` parent, ALSO mutate `parent.config["auto_followup_depth"] = 0` (or remove the key) in the same transaction. The pending Arq worker, on its first action (`repo.get_study(parent)`), reads the mutated config and the gate returns `SKIP_DEPTH_EXHAUSTED`.

Trade-offs:
- Pros: Tiny change (~5 LOC in `cancel_study_with_chain_cascade`). No new schema. No new event.
- Cons: Mutates the parent's `config` JSONB silently — a future "view this study's original config" operator wouldn't see the original `auto_followup_depth`. Could be surprising. Mitigation: log an audit event when the mutation fires (at MVP2 when `audit_log` lands).

### Option B — New `studies.chain_cancelled_at` column

Schema change: add `chain_cancelled_at TIMESTAMPTZ NULL` to the `studies` table. Cascade-cancel stamps it on the parent. Worker re-checks at gate time: if `parent.chain_cancelled_at IS NOT NULL`, skip.

Trade-offs:
- Pros: Doesn't mutate `config` (preserves config audit trail). New column makes the chain-cancellation event observable in DB.
- Cons: New migration (round-trip + downgrade required). New ORM column. UI surfaces need to know about it.

### Option C — Postgres advisory lock on the parent during cascade + worker

`cancel_study_with_chain_cascade` acquires `pg_advisory_xact_lock(hash(parent_id))` and the worker acquires the same lock before its idempotency re-check + child creation. Cascade then either pre-empts the worker (by committing its parent-state mutation first) OR runs after the worker has already created a child (which the cascade then cancels via its existing recurse-into-children path).

Trade-offs:
- Pros: Covers BOTH the cascade race AND the layer-2 idempotency race (`chore_auto_followup_parent_advisory_lock`) with one mechanism.
- Cons: More plumbing. Locks held across multi-second Arq job durations risk deadlock if not carefully scoped. Needs spec-level lock-granularity decision.

**Recommendation:** Option A is the MVP1.5 fix (1 PR, ~30 LOC including a test); Option C is the MVP2 hardening that obsoletes both this idea AND `chore_auto_followup_parent_advisory_lock`. Ship A now if operators report the race; defer to C otherwise.

## Why deferred from this PR

- Race window is small (~Arq poll cycle).
- Impact is recoverable: operator can cancel the spurious child directly from `/studies/[child_id]`.
- No telemetry-loss concern (the child gets its own `auto_followup_enqueued` event with the correct `parent_study_id` for forensics).
- The plan's D-11 already deferred the related layer-2 race to MVP2 hardening with the same trade-off framing; consistent with that decision.
- Implementing Option A right now would also require a unit test that exercises the race (timer-based or thread-coordination test) — non-trivial test infra for a 1-LOC fix.

## Dependencies

- None for Options A or C (both can ship anytime after `feat_auto_followup_studies` lands).
- Option B requires the schema migration to land first, with the downgrade verified per CLAUDE.md Absolute Rule #5.

## Scope signals

- **Backend (Option A):** ~10 LOC in `backend/app/services/study_state.py:cancel_study_with_chain_cascade` + ~30 LOC of test (`test_cascade_mutates_completed_parent_config_to_stop_chain`). One commit.
- **Backend (Option B):** ~30 LOC + Alembic migration + ORM model column + serializer update. 1-2 commits.
- **Backend (Option C):** ~100 LOC + advisory-lock helper module + lock-contention test fixture. Composes with `chore_auto_followup_parent_advisory_lock`.
- **Frontend:** None for Options A or B. Option C might surface lock-wait telemetry on the chain panel — out of scope.
- **Tests:** Option A — 1 new race-coordination test. Option B — schema migration round-trip + 2-3 integration tests. Option C — ~5 integration tests covering lock acquire / release / contention paths.
- **Audit events:** N/A for MVP1 (pre-`audit_log`). At MVP2, all options should emit `auto_followup_cascade_stop_chain_via_config_mutation` (Option A) or equivalent.

## Why not inline today

- The race was caught post-implementation by the phase-gate review (not at spec or plan time).
- Adding the fix mid-PR would mean either (a) shipping it without spec consideration (rushed) or (b) blocking the existing PR on a sub-design decision that needs operator input on the mutation-vs-column trade-off.
- Cleaner to land MVP1 with the documented race, capture this idea, and let operator feedback inform the spec decision.

## Relationship to other work

- **Co-evolves with the D-11-deferred layer-2 advisory-lock approach** (see [`feat_auto_followup_studies/feature_spec.md` D-11](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) and [`implementation_plan.md` §9 finding F2](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/implementation_plan.md), named `chore_auto_followup_parent_advisory_lock` in the deferral note but never captured as a standalone idea file). Option C above is the unified-mechanism fix that obsoletes both. If the operator reports either race, prioritize Option C over A/B.
- **Coordinates with future `feat_chain_audit_view`** (not yet captured) — when MVP2's `audit_log` lands, the cascade-vs-worker race becomes observable in the audit trail; that's the right time to decide whether Options A/B/C are worth shipping or whether the race is rare enough to leave documented-only.
