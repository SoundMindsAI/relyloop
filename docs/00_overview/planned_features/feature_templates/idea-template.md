# <Feature or Phase Name>

**Date:** <YYYY-MM-DD>
**Status:** Idea — <origin context, e.g., "deferred from Phase 1 implementation" or "identified during Wave X planning">
**Priority:** <P0 | P1 | P2 | Backlog — see priority guidance below>
**Origin:** <Pointer to source — e.g., "Deferred Phase 2 work from `feature_spec.md` (lines N-M)" or "User request during sprint planning">
**Depends on:** <What must be merged/deployed first, or "None">

> **Priority guidance:**
> - **P0** — do next. Actively unblocking a felt incident, paying daily cost, or otherwise the most-leveraged thing to ship right now.
> - **P1** — high-value scoped work, ready to execute when P0 is clear. Most "next batch" items live here.
> - **P2** — important enough to file, not blocking. Default when unsure. Speculative product surface or longer-lived debt.
> - **Backlog** — captured for record but not actively planned. May graduate to P2+ when context changes.
>
> Folders ending `_mvp2` / `_mvp3` are auto-classified to that release; their `Priority` value applies within that release's dashboard. Defaults to **P2** when omitted.

## Problem

<What gap or need does this idea address? 2-4 sentences. If deferred from a prior phase, explain what remains unsolved after the implemented phase ships.>

## Proposed capabilities

<List the capabilities at a level of detail sufficient to generate a feature spec later. For deferred spec phases, include the FR numbers and descriptions from the original spec.>

### <Capability 1 name>

- <Key behavior or requirement>
- <Key behavior or requirement>

### <Capability 2 name>

- <Key behavior or requirement>
- <Key behavior or requirement>

## Scope signals

<Brief notes on which layers/systems are likely affected. Not a full spec — just enough to estimate complexity.>

- **Backend:** <impact hints>
- **Frontend:** <impact hints>
- **Migration:** <expected or not>
- **Config:** <new settings, env vars>
- **Audit events:** <new event_types this idea introduces, OR `N/A` if no state mutations or pre-MVP2>


## Why <deferred / not yet prioritized>

<The rationale for not implementing this now. For deferred phases, copy the reasoning from the spec's phase boundary description. This helps future planners decide when to pick it up.>

## Relationship to other work

<Optional. Note if this idea supersedes, extends, or conflicts with other planned features.>
