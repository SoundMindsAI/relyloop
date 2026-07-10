# Agent confirmation gate binds the tool NAME, not the tool ARGUMENTS

**Date:** 2026-07-10
**Status:** Idea — surfaced during the 2026-07-10 full-codebase security audit (secrets/LLM surface agent, finding B1)
**Priority:** P2
**Origin:** Security audit finding B1 — `backend/app/agent/orchestrator.py:392-410` (`_is_authorized_mutation`). Natural follow-on to `chore_agent_confirmation_per_tool_binding` (PR #582), which hardened the *name* binding but not the *argument* binding.
**Depends on:** None

## Problem

The chat-agent confirmation gate (`_is_authorized_mutation`) verifies that the
assistant proposed exactly one mutating tool **by name** and that the user
affirmed it. It does **not** bind the affirmation to the specific *arguments*
of the mutation. After the user says "yes," the LLM supplies the
`proposal_id` / `cluster_id` / `config_diff` in `tool_call.arguments`, which are
validated only for Pydantic *shape* (`args_model.model_validate_json`). Nothing
ties the confirmed operation's target to the resource the human actually
discussed and approved.

So a prompt-injection in tool output (e.g. a hostile indexed document surfaced
by `run_query`) or a plain model hallucination could cause `open_pr` /
`create_study` to fire against a **different resource ID** than the one the
assistant described and the user approved. Blast radius is bounded in MVP1
(single-tenant, no auth, args are UUIDs referencing existing rows with existence
checks), which is why the audit rated this Low/Medium rather than High — but it
is the sharper residual edge left after the name-binding hardening.

## Proposed capabilities

### Argument-bound confirmation

- When the assistant proposes a mutating tool, have it echo the **key
  argument(s)** (the target `proposal_id` / `cluster_id`, the human-readable
  resource name) in the proposal text that the human sees before the second
  "yes."
- At dispatch time, require the dispatched `tool_call.arguments` to match the
  echoed target (compare the confirmed ID against the arguments actually sent);
  fail safe with the existing `confirmation_required` error code on mismatch,
  forcing re-proposal.
- Surface the concrete target in the `confirmation_required` round-trip so the
  operator sees the exact ID/name, not just the tool name.

## Scope signals

- **Backend:** `backend/app/agent/orchestrator.py` (`_is_authorized_mutation`,
  the dispatch loop, the proposal/confirmation round-trip); `confirmation.py`.
  Likely a new structured "pending mutation" record carrying the confirmed
  target so the second turn can compare.
- **Frontend:** none required, though the confirmation prompt copy improves.
- **Migration:** none expected (in-conversation state).
- **Config:** none.
- **Audit events:** N/A pre-MVP3.

## Why deferred

Requires a product/UX decision on exactly how the assistant echoes the target
and how strictly dispatch must match it (exact-ID match vs. name match vs.
fuzzy) — that design fork can't be resolved unilaterally inside a security
sweep. Per the CLAUDE.md inline-vs-idea rubric, "requires a product/UX
decision" routes to an idea file. The name-binding gate already blocks the
blanket-multi-tool bypass, and the single-tenant/no-auth posture bounds the
blast radius, so this is hardening rather than an active incident.

## Relationship to other work

Extends `chore_agent_confirmation_per_tool_binding` (PR #582,
`implemented_features/`). Same subsystem, same `_is_authorized_mutation`
function — the two together give name + argument binding.
