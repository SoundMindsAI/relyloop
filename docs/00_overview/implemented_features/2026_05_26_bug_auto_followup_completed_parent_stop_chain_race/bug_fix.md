# Bug fix — `bug_auto_followup_completed_parent_stop_chain_race`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/auto-followup-completed-parent-stop-chain-race`
**Type:** bug fix — medium (Option A locked; ~30 LOC + 4 tests)
**Date:** 2026-05-26

## Problem

When the FR-1 digest trigger enqueues `enqueue_followup_study(parent_id)` and the operator then clicks "Stop chain" before the Arq worker picks it up, the existing cascade traverses the (already-`completed`) parent for any in-flight descendants — but it has no way to coordinate with the **pending** worker. The worker fires moments later, loads the parent (still `completed`, with `auto_followup_depth > 0`), passes the chain gate, and creates a child the operator thought they stopped. Race window is small (~Arq poll cycle, typically <2s), recoverable by canceling the spurious child, but operator-visible and surprising.

## Reproduction

The race is timing-sensitive between Arq's poll and the cascade's commit. A deterministic reproducer skips the timer entirely and asserts the two halves separately:

1. The cascade leaves a `completed` parent with `auto_followup_depth > 0` in a state where the chain gate would still ENQUEUE.
2. After the fix, the gate observes the post-cascade parent and short-circuits with SKIP_DEPTH_EXHAUSTED.

```bash
.venv/bin/pytest backend/tests/unit/services/test_study_state.py::test_cascade_zeroes_completed_parent_depth_to_break_pending_enqueue_race -v
```

Pre-fix: assertion `parent.config["auto_followup_depth"] == 0` fails with `assert 2 == 0`. Post-fix: all four new tests pass.

## Root cause

- **Owning layer:** service ([`backend/app/services/study_state.py`](../../../../backend/app/services/study_state.py)).
- **Origin:** [`cancel_study_with_chain_cascade`](../../../../backend/app/services/study_state.py#L216), terminal-parent branch [line 286-292](../../../../backend/app/services/study_state.py#L286-L292). The cascade traverses for children but does nothing to coordinate with the pending worker — it can't see the not-yet-fired Arq job, and the worker can't see a not-yet-existing chain-stop marker.
- **Propagation:** [`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py) calls [`evaluate_chain_gate`](../../../../backend/app/domain/study/auto_followup.py#L113); the gate's `depth is None or depth == 0` check at [auto_followup.py:157](../../../../backend/app/domain/study/auto_followup.py#L157) is the natural choke point — but only if the cascade mutates the depth field that the gate reads.

## Fix design (locked decisions)

Option A from the idea (cascade zeros `parent.config["auto_followup_depth"]` in the same transaction), locked over Options B (new column) and C (advisory lock) per the idea's own §"Recommendation" line.

1. **Mutate `config["auto_followup_depth"] → 0` in the cascade's terminal-parent branch.** Reuses the worker's existing SKIP_DEPTH_EXHAUSTED gate path (no new event, no new column, no new domain function). Cites: idea §"Option A" + worker gate at [`auto_followup.py:156-161`](../../../../backend/app/domain/study/auto_followup.py#L156-L161).
2. **Scope to `parent.status == "completed"` only.** `cancelled` / `failed` parents already short-circuit at the gate's SKIP_PARENT_FAILED branch ([`auto_followup.py:150-154`](../../../../backend/app/domain/study/auto_followup.py#L150-L154)); widening the mutation surface beyond the race window is gratuitous. Cites: CLAUDE.md "Don't add features beyond what the task requires" + idea §"Mutation applies only when the parent is in `completed` state".
3. **Skip mutation when depth is already 0.** Minimal-mutation principle; depth-0 leaves don't have a pending worker that would ENQUEUE anyway. Cites: minimal-fix discipline; preserves config-dict identity so future readers see the cascade left depth-0 parents alone.
4. **No `_authorize_status_mutation` context needed.** The before_flush / orm-execute guards at [`study_state.py:485-548`](../../../../backend/app/services/study_state.py#L485-L548) only fire on `Study.status` mutations; touching `config` is not protected. Cites: guard implementation inspects `attrs["status"].history` only.
5. **Emit a structured `auto_followup_cascade_stop_chain_via_config_mutation` log event when the mutation fires.** Provides forensic trail in logs without depending on the not-yet-shipped `audit_log` table. Cites: idea §"Audit events" + structlog precedent across the auto_followup worker.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| Unit (service) | [`backend/tests/unit/services/test_study_state.py`](../../../../backend/tests/unit/services/test_study_state.py) | 4 new tests cover: depth-zeroed on `completed` parent + post-mutation gate returns SKIP_DEPTH_EXHAUSTED; no mutation when depth already 0 (config dict identity preserved); no mutation on in-flight parents; recursive depth-zeroing across a completed → completed → running chain. |

The main test (`test_cascade_zeroes_completed_parent_depth_to_break_pending_enqueue_race`) exercises the previously-buggy code path under coverage — it calls `cancel_study_with_chain_cascade` and asserts the mutation happens AND the gate predicate observes it. The pre-fix run showed `assert 2 == 0` failure on the depth assertion, proving the test exercises the fix and isn't passing in isolation.

## Rollout

- **Code-only change.** No migration, no new column, no schema mutation, no new env var.
- **No operator action required at deploy.** Live `completed` chains carry their existing `auto_followup_depth` values; the fix only fires on future cascade invocations against `completed` parents.
- **Trigger-lock override (recorded):** the idea's §"Recommendation" ship policy says "Ship A now if operators report the race; defer to C otherwise." Operator has explicitly authorized shipping Option A without an operator-report signal — recorded here so future readers see the gate was bypassed deliberately, not silently violated. The reasoning: the fix is bounded (15 LOC + 4 tests), reversible (revert the commit if Option C lands later), and the race is small but operator-visible — preemptive close on the friction matches "implement-over-defer" from the user's memory.
- **MVP2 obsoletion path:** when the Postgres advisory-lock approach (idea §"Option C") lands, this Option A fix becomes redundant — the lock makes the race impossible. Remove the depth-zeroing block at that time; it's fenced by clear comments so the swap is mechanical.
- **Audit event:** `auto_followup_cascade_stop_chain_via_config_mutation` is emitted via structlog only in MVP1 (no `audit_log` table yet). When MVP2's `audit_log` ships, add an `audit_log` INSERT alongside the structlog call in the same transaction per [`data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md).

## Tangential observations

- The idea (line 83, now patched) referenced [`chore_auto_followup_parent_advisory_lock`](../chore_auto_followup_parent_advisory_lock/idea.md) — a sibling idea that was named in `feat_auto_followup_studies` D-11 + plan F2 but never captured as a standalone file. Six places across the shipped spec/plan + this idea reference the slug. Worth capturing as its own idea file (still MVP2 hardening), but out of scope for this PR.
