# feat_apply_path_normalizer_declaration — Phase 3 (apply-path-side normalizer declaration)

**Date:** 2026-05-31
**Status:** Idea — deferred Phase 3 of [`feat_query_normalization_tuning`](../feat_query_normalization_tuning/feature_spec.md) (§3 Phase boundaries, §19 D-1). Split into its own planned-features folder 2026-05-31 (was `feat_query_normalization_tuning/phase3_idea.md`).
**Priority:** P2 — picked up only if Phase 1's documentation hand-off (PR body "Operator-side requirement" section) proves frictionful in operator practice (GitHub issues, in-product feedback, adoption survey).
**Origin:** Phase 3 carve-out from `feature_spec.md` §3 "Phase boundaries" + §19 D-1 (prod-reproducibility hand-off). Option (a) of the gating fork — apply-path carries a structured normalizer declaration.
**Depends on:** Phase 1 of [`feat_query_normalization_tuning`](../feat_query_normalization_tuning/feature_spec.md) merged AND a body of evidence that the manual snippet-copy step in the PR-body "Operator-side requirement" section is causing real friction.

## Problem

Phase 1 ships option (b) of the prod-reproducibility fork — the PR body documents the chosen normalizer and embeds a Python snippet, and the operator's merge contract is "you must replicate this normalizer in your query layer for production parity." This is adequate when:

- The operator reads PR descriptions end-to-end (table-stakes for relevance work).
- The operator's query layer is in Python or trivially translatable.
- The operator owns deployment of the query layer.

It's frictionful when:

- The query layer is owned by a different team and the PR-author has no merge rights there.
- The operator's deployment pipeline expects structured config, not prose.
- The "replicate manually" step is forgotten or done wrong, causing the production gain to under-reproduce the loop's measurement.

Phase 3 closes the loop: the winning normalizer ships as a structured field in the config-repo PR (not just prose), so the operator's CI consumes it directly.

## Proposed capabilities

### Capability A — Structured normalizer declaration in the config-repo PR

- Extend the apply-path's config-diff payload to include a `query_normalizer` block (e.g., a top-level YAML key in the rendered config file or a new file alongside the parameters file).
- The block names the normalizer choice AND embeds a language-agnostic spec the operator's query layer can consume (e.g., a YAML manifest listing the steps and parameters, plus pointers to reference implementations).
- The merge contract becomes: "Apply the parameters AND wire the normalizer manifest into your query layer's startup config."

### Capability B — Engineering decisions to lock at Phase 3 spec time

- **Manifest shape.** Inline in the same config file as the existing parameters? Separate `query_normalizer.yaml`? Operator preference signal needed.
- **Language-agnostic step vocabulary.** Phase 2's `NormalizerStep` enum (if shipped) is the natural foundation; otherwise Phase 3 defines its own.
- **Apply-path scope expansion.** Phase 1 keeps `apply-path.md` unchanged. Phase 3 extends it materially — re-audit at spec time.
- **Backward compatibility.** Existing repos consuming the apply-path's current config-diff shape must continue working; new field is additive.

### Capability C — UI surfacing

- The proposal-detail page shows the normalizer manifest preview alongside the existing parameter diff.
- The PR body's "Operator-side requirement" section from Phase 1 transitions from "copy this Python snippet" to "your CI will apply this normalizer manifest automatically — no copy step required."

## Scope signals

- **Backend:** medium-to-large. Apply-path worker (`backend/workers/git_pr.py`) extension; new config-diff payload shape.
- **Frontend:** small-to-medium. Manifest preview in proposal detail.
- **Migration:** likely none for RelyLoop itself; operators may need migrations in their config repo.
- **Config:** possibly a new env var controlling whether the manifest is emitted (for back-compat).
- **Audit events:** N/A (audit_log lands at MVP3; if this ships post-MVP3 it picks up the audit-event matrix discipline).

## Why deferred

Option (b) (documentation hand-off) is genuinely adequate for the operator workflow today. Apply-path extension is a sizable scope expansion — new payload shape, new manifest spec, new operator-side CI contract — and may not be needed at all if operators tolerate the manual snippet copy. The right time to ship Phase 3 is when MVP2 + MVP3 adoption signal proves the friction. Spec time at that point can audit the actual failure mode and pick the right manifest shape, instead of guessing now.

## Relationship to other work

- Extends Phase 1 of `feat_query_normalization_tuning`.
- Composes with Phase 2 (typed `NormalizerPipelineParam`) — Phase 2's step vocabulary makes the Phase 3 manifest more expressive.
- Composes with the broader apply-path roadmap in [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md) — Phase 3 is the first feature to push structured payload through the apply path beyond parameter values.
- Does not block any other planned feature.
